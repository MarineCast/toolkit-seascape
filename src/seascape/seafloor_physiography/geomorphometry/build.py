"""Build resolution-8 H3 seafloor geomorphometry from GEBCO bathymetry.

The stable legacy columns remain available.  Additional columns name their
native-raster or H3-neighborhood scale explicitly.  Surface-area ratio is a
deterministic transformation of slope and must not be treated as independent
terrain evidence.
"""

from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.geo.h3 import cell_to_polygon
from seascape.spatial_support.water_network import (
    load_water_neighborhoods,
)
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.spatial import water_neighborhood_lookup

LOGGER = logging.getLogger(__name__)

LEGACY_OUTPUT_COLUMNS = [
    "SLOPE",
    "ASPECT",
    "TERRAIN_POSITION",
    "CURVATURE",
    "RELIEF",
    "RUGGEDNESS",
]
NATIVE_OUTPUT_COLUMNS = [
    "SLOPE_MEAN_NATIVE_RASTER",
    "SLOPE_Q90_NATIVE_RASTER",
    "NATIVE_RASTER_RESOLUTION_ARC_SECONDS",
    "EASTNESS",
    "NORTHNESS",
    "PROFILE_CURVATURE",
    "PLAN_CURVATURE",
    "GENERAL_CURVATURE",
    "SURFACE_AREA_RATIO_FROM_SLOPE",
]
PER_RING_TEMPLATES = (
    "SLOPE_MEAN_RING_{ring}",
    "SLOPE_Q90_RING_{ring}",
    "ASPECT_CIRCULAR_MEAN_RING_{ring}",
    "ASPECT_RESULTANT_LENGTH_RING_{ring}",
    "TERRAIN_POSITION_RING_{ring}_M",
    "TERRAIN_POSITION_RING_{ring}_Z",
    "LOCAL_RELIEF_RING_{ring}_M",
    "DEPTH_RANGE_RING_{ring}_M",
    "DEPTH_STD_RING_{ring}_M",
    "DEPTH_MAD_RING_{ring}_M",
    "VECTOR_RUGGEDNESS_RING_{ring}",
    "NEIGHBORHOOD_ROUGHNESS_RING_{ring}_M",
)
SHAPE_INDEX_COLUMNS = [
    "POSITIVE_OPENNESS_DEG",
    "NEGATIVE_OPENNESS_DEG",
    "OPENNESS_SECTOR_COVERAGE",
    "RIDGE_INDEX",
    "VALLEY_INDEX",
    "CONVEXITY_INDEX",
    "CONCAVITY_INDEX",
]


def ring_output_columns(rings: tuple[int, ...]) -> list[str]:
    """Return deterministic scale-qualified output columns."""

    return [template.format(ring=ring) for ring in rings for template in PER_RING_TEMPLATES]


def output_columns(rings: tuple[int, ...]) -> list[str]:
    """Return the complete configured schema."""

    return [
        "H3_INDEX",
        *LEGACY_OUTPUT_COLUMNS,
        *NATIVE_OUTPUT_COLUMNS,
        *ring_output_columns(rings),
        *SHAPE_INDEX_COLUMNS,
    ]


# The repository's configured radii are stable defaults. Inspectors use the
# loaded configuration rather than relying on this convenience export.
OUTPUT_COLUMNS = output_columns((1, 2, 4))


@dataclass(frozen=True)
class GeomorphometryConfig:
    """Resolved inputs and parameters for H3 geomorphometry."""

    h3_resolution: int
    bathymetry_path: Path
    native_raster_path: Path
    native_resolution_arc_seconds: float
    output_path: Path
    projected_crs: str
    neighbor_ring: int
    neighborhood_rings: tuple[int, ...]
    minimum_neighbors: int
    ruggedness_algorithm: str
    slope_upper_quantile: float
    openness_radius_rings: int
    openness_bearing_sectors: int
    curvature_index_scale_per_m: float


def load_geomorphometry_config(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> GeomorphometryConfig:
    """Load the geomorphometry configuration and bathymetry dependencies."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    bathymetry = _mapping(raw.get("bathymetry"), "bathymetry")
    bathymetry_source = _mapping(bathymetry.get("source"), "bathymetry.source")
    bathymetry_processing = _mapping(bathymetry.get("processing"), "bathymetry.processing")
    section = _mapping(raw.get("geomorphometry"), "geomorphometry")
    processing = _mapping(section.get("processing"), "geomorphometry.processing")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()

    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("geomorphometry.processing.h3_resolution must be 8.")
    ruggedness_algorithm = str(processing.get("ruggedness_algorithm", "wilson")).lower()
    if ruggedness_algorithm != "wilson":
        raise ValueError(
            "geomorphometry.processing.ruggedness_algorithm must be 'wilson' "
            "for the bathymetric product."
        )
    rings = tuple(sorted({int(value) for value in processing.get("neighborhood_rings", [1, 2, 4])}))
    neighbor_ring = int(processing.get("neighbor_ring", 1))
    if not rings or min(rings) < 1 or neighbor_ring not in rings:
        raise ValueError(
            "geomorphometry.processing.neighborhood_rings must be positive and "
            "include neighbor_ring."
        )
    quantile = float(processing.get("slope_upper_quantile", 0.90))
    if not 0.5 < quantile < 1.0:
        raise ValueError("geomorphometry.processing.slope_upper_quantile must be in (0.5, 1).")
    openness_radius = int(processing.get("openness_radius_rings", max(rings)))
    openness_sectors = int(processing.get("openness_bearing_sectors", 12))
    if openness_radius < 1 or openness_sectors < 4:
        raise ValueError("Openness radius must be positive and use at least four sectors.")
    curvature_scale = float(processing.get("curvature_index_scale_per_m", 0.0002))
    if curvature_scale <= 0.0:
        raise ValueError("curvature_index_scale_per_m must be positive.")

    raw_dir = Path(str(bathymetry_source["raw_dir"]))
    raw_filename = str(bathymetry_source["raw_filename"])
    default_raster = raw_dir / raw_filename
    return GeomorphometryConfig(
        h3_resolution=resolution,
        bathymetry_path=_resolve(
            processing.get("bathymetry_path", bathymetry_processing["processed_path"]),
            base_dir,
        ),
        native_raster_path=_resolve(processing.get("native_raster_path", default_raster), base_dir),
        native_resolution_arc_seconds=float(
            processing.get(
                "native_resolution_arc_seconds",
                bathymetry_source.get("native_resolution_arc_seconds", 15.0),
            )
        ),
        output_path=_resolve(processing["processed_path"], base_dir),
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        neighbor_ring=neighbor_ring,
        neighborhood_rings=rings,
        minimum_neighbors=int(processing.get("minimum_neighbors", 3)),
        ruggedness_algorithm=ruggedness_algorithm,
        slope_upper_quantile=quantile,
        openness_radius_rings=openness_radius,
        openness_bearing_sectors=openness_sectors,
        curvature_index_scale_per_m=curvature_scale,
    )


def _projected_centers(cells: pd.Series, crs: str) -> dict[str, tuple[float, float]]:
    import geopandas as gpd

    geometry = cells.astype(str).map(cell_to_polygon)
    frame = gpd.GeoDataFrame(
        {"H3_INDEX": cells.astype(str)}, geometry=geometry, crs="EPSG:4326"
    ).to_crs(crs)
    centers = frame.geometry.centroid
    return dict(zip(frame["H3_INDEX"], zip(centers.x, centers.y, strict=True), strict=True))


def _plane_coefficients(
    cells: list[str],
    depths: Mapping[str, float],
    centers: Mapping[str, tuple[float, float]],
) -> np.ndarray:
    center_x = float(np.mean([centers[cell][0] for cell in cells]))
    center_y = float(np.mean([centers[cell][1] for cell in cells]))
    design = np.asarray(
        [[centers[cell][0] - center_x, centers[cell][1] - center_y, 1.0] for cell in cells]
    )
    values = np.asarray([depths[cell] for cell in cells])
    return np.linalg.lstsq(design, values, rcond=None)[0]


def _plane_metrics(
    center: str,
    neighbors: list[str],
    depths: Mapping[str, float],
    centers: Mapping[str, tuple[float, float]],
) -> tuple[float, float]:
    gradient_x, gradient_y, _intercept = _plane_coefficients([center, *neighbors], depths, centers)
    magnitude = math.hypot(float(gradient_x), float(gradient_y))
    slope = math.degrees(math.atan(magnitude))
    aspect = (
        math.degrees(math.atan2(float(gradient_x), float(gradient_y))) % 360.0
        if magnitude > 1e-12
        else math.nan
    )
    return slope, aspect


def _quadratic_curvatures(
    center: str,
    neighbors: list[str],
    depths: Mapping[str, float],
    centers: Mapping[str, tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Return legacy Laplacian and positive-convex general/profile/plan curvature."""

    center_x, center_y = centers[center]
    cells = [center, *neighbors]
    distances = [
        math.hypot(centers[cell][0] - center_x, centers[cell][1] - center_y) for cell in neighbors
    ]
    scale = float(np.mean(distances))
    if not math.isfinite(scale) or scale <= 0.0:
        return (math.nan,) * 4
    design: list[list[float]] = []
    elevations: list[float] = []
    for cell in cells:
        x = (centers[cell][0] - center_x) / scale
        y = (centers[cell][1] - center_y) / scale
        design.append([x * x, x * y, y * y, x, y, 1.0])
        elevations.append(-depths[cell])
    coefficients, _residuals, rank, _singular = np.linalg.lstsq(
        np.asarray(design), np.asarray(elevations), rcond=None
    )
    if rank < 6:
        return (math.nan,) * 4
    a, b, c, d, e, _intercept = coefficients
    p = float(d / scale)
    q = float(e / scale)
    r = float(2.0 * a / (scale * scale))
    s = float(b / (scale * scale))
    t = float(2.0 * c / (scale * scale))
    legacy_laplacian = r + t
    general = -legacy_laplacian
    gradient_squared = p * p + q * q
    if gradient_squared <= 1e-18:
        return legacy_laplacian, general, math.nan, math.nan
    profile = -(r * p * p + 2.0 * s * p * q + t * q * q) / (
        gradient_squared * (1.0 + gradient_squared) ** 1.5
    )
    plan = -(r * q * q - 2.0 * s * p * q + t * p * p) / (
        gradient_squared * math.sqrt(1.0 + gradient_squared)
    )
    return legacy_laplacian, general, float(profile), float(plan)


def _native_raster_slope_summary(
    raster_path: Path,
    target_cells: set[str],
    resolution: int,
    quantile: float,
) -> pd.DataFrame:
    """Aggregate 15-arc-second GEBCO pixel slopes into the H3 universe."""

    import h3
    import rasterio

    if not raster_path.exists():
        raise FileNotFoundError(f"Native GEBCO raster not found: {raster_path}")
    with rasterio.open(raster_path) as raster:
        if raster.count != 1 or raster.crs is None or raster.crs.to_epsg() != 4326:
            raise ValueError("Native GEBCO slope input must be a one-band EPSG:4326 raster.")
        elevation = raster.read(1, masked=True).astype("float64").filled(np.nan)
        transform = raster.transform

    rows, columns = np.indices(elevation.shape)
    longitudes, latitudes = rasterio.transform.xy(transform, rows, columns, offset="center")
    latitudes = np.asarray(latitudes, dtype="float64").reshape(elevation.shape)
    longitudes = np.asarray(longitudes, dtype="float64").reshape(elevation.shape)
    marine = np.isfinite(elevation) & (elevation < 0.0)
    latitude_step_m = abs(float(transform.e)) * 110_574.0
    longitude_step_m = (
        abs(float(transform.a)) * 111_320.0 * np.maximum(np.cos(np.deg2rad(latitudes)), 0.1)
    )
    gradient_row = np.gradient(elevation, axis=0) / latitude_step_m
    gradient_column = np.gradient(elevation, axis=1) / longitude_step_m
    slope = np.degrees(np.arctan(np.hypot(gradient_column, gradient_row)))
    valid = marine & np.isfinite(slope)
    valid_latitudes = latitudes[valid]
    valid_longitudes = longitudes[valid]
    pixel_cells = np.fromiter(
        (
            h3.latlng_to_cell(float(latitude), float(longitude), resolution)
            for latitude, longitude in zip(valid_latitudes, valid_longitudes, strict=True)
        ),
        dtype=object,
        count=len(valid_latitudes),
    )
    in_target = np.fromiter(
        (cell in target_cells for cell in pixel_cells), dtype=bool, count=len(pixel_cells)
    )
    samples = pd.DataFrame(
        {
            "H3_INDEX": pixel_cells[in_target],
            "NATIVE_SLOPE": slope[valid][in_target],
        }
    )
    if samples.empty:
        raise ValueError("No native-raster slope pixels overlap the H3 bathymetry universe.")
    return (
        samples.groupby("H3_INDEX", observed=True)["NATIVE_SLOPE"]
        .agg(
            SLOPE_MEAN_NATIVE_RASTER="mean",
            SLOPE_Q90_NATIVE_RASTER=lambda values: values.quantile(quantile),
        )
        .reset_index()
    )


def _neighbors(
    cell: str,
    ring: int,
    depths: Mapping[str, float],
    neighborhood_lookups: Mapping[int, Mapping[str, tuple[str, ...]]],
) -> list[str]:
    return [
        str(neighbor)
        for neighbor in neighborhood_lookups.get(ring, {}).get(cell, ())
        if str(neighbor) != cell and str(neighbor) in depths
    ]


def _detrended_roughness(
    cells: list[str],
    depths: Mapping[str, float],
    centers: Mapping[str, tuple[float, float]],
) -> float:
    if len(cells) < 3:
        return math.nan
    center_x = float(np.mean([centers[cell][0] for cell in cells]))
    center_y = float(np.mean([centers[cell][1] for cell in cells]))
    design = np.asarray(
        [[centers[cell][0] - center_x, centers[cell][1] - center_y, 1.0] for cell in cells]
    )
    values = np.asarray([depths[cell] for cell in cells])
    coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
    residuals = values - design @ coefficients
    return float(np.mean(np.abs(residuals)))


def _circular_aspect_metrics(
    cells: list[str],
    slopes: Mapping[str, float],
    aspects: Mapping[str, float],
) -> tuple[float, float, float]:
    valid = [
        cell
        for cell in cells
        if math.isfinite(slopes.get(cell, math.nan)) and math.isfinite(aspects.get(cell, math.nan))
    ]
    if not valid:
        return math.nan, math.nan, math.nan
    slope_values = np.asarray([slopes[cell] for cell in valid])
    radians = np.deg2rad([aspects[cell] for cell in valid])
    east = float(np.mean(np.sin(radians)))
    north = float(np.mean(np.cos(radians)))
    mean_aspect = math.degrees(math.atan2(east, north)) % 360.0
    if math.isclose(mean_aspect, 360.0, abs_tol=1e-12):
        mean_aspect = 0.0
    resultant = math.hypot(east, north)
    return float(np.mean(slope_values)), mean_aspect, resultant


def _vector_ruggedness(
    cells: list[str],
    slopes: Mapping[str, float],
    aspects: Mapping[str, float],
) -> float:
    valid = [
        cell
        for cell in cells
        if math.isfinite(slopes.get(cell, math.nan)) and math.isfinite(aspects.get(cell, math.nan))
    ]
    if not valid:
        return math.nan
    slope_radians = np.deg2rad([slopes[cell] for cell in valid])
    aspect_radians = np.deg2rad([aspects[cell] for cell in valid])
    x = np.sin(slope_radians) * np.sin(aspect_radians)
    y = np.sin(slope_radians) * np.cos(aspect_radians)
    z = np.cos(slope_radians)
    resultant = math.sqrt(float(np.mean(x)) ** 2 + float(np.mean(y)) ** 2 + float(np.mean(z)) ** 2)
    return float(np.clip(1.0 - resultant, 0.0, 1.0))


def _openness(
    center: str,
    neighbors: list[str],
    depths: Mapping[str, float],
    centers: Mapping[str, tuple[float, float]],
    sectors: int,
) -> tuple[float, float, float]:
    center_x, center_y = centers[center]
    center_elevation = -depths[center]
    positive_horizon = np.full(sectors, np.nan)
    negative_horizon = np.full(sectors, np.nan)
    for neighbor in neighbors:
        delta_x = centers[neighbor][0] - center_x
        delta_y = centers[neighbor][1] - center_y
        distance = math.hypot(delta_x, delta_y)
        if distance <= 0.0:
            continue
        bearing = math.atan2(delta_x, delta_y) % (2.0 * math.pi)
        sector = min(sectors - 1, int(bearing / (2.0 * math.pi) * sectors))
        angle = math.degrees(math.atan2(-depths[neighbor] - center_elevation, distance))
        positive_horizon[sector] = (
            angle
            if not math.isfinite(positive_horizon[sector])
            else max(positive_horizon[sector], angle)
        )
        negative_horizon[sector] = (
            -angle
            if not math.isfinite(negative_horizon[sector])
            else max(negative_horizon[sector], -angle)
        )
    valid = np.isfinite(positive_horizon)
    if not valid.any():
        return math.nan, math.nan, 0.0
    positive = float(90.0 - np.mean(positive_horizon[valid]))
    negative = float(90.0 - np.mean(negative_horizon[valid]))
    return positive, negative, float(valid.mean())


def _derive_metrics(
    frame: pd.DataFrame,
    config: GeomorphometryConfig,
    neighborhood_lookups: Mapping[int, Mapping[str, tuple[str, ...]]],
) -> pd.DataFrame:
    cells = frame["H3_INDEX"].astype(str).tolist()
    numeric_depth = pd.to_numeric(frame["BATHYMETRY"], errors="coerce")
    depths = {
        cell: float(depth)
        for cell, depth in zip(cells, numeric_depth, strict=True)
        if math.isfinite(float(depth))
    }
    centers = _projected_centers(pd.Series(cells), config.projected_crs)
    columns = output_columns(config.neighborhood_rings)
    rows: dict[str, dict[str, float | str]] = {
        cell: {column: math.nan for column in columns} for cell in cells
    }
    slopes: dict[str, float] = {}
    aspects: dict[str, float] = {}

    for cell in cells:
        row = rows[cell]
        row["H3_INDEX"] = cell
        row["NATIVE_RASTER_RESOLUTION_ARC_SECONDS"] = config.native_resolution_arc_seconds
        if cell not in depths:
            continue
        neighbors = _neighbors(cell, config.neighbor_ring, depths, neighborhood_lookups)
        if neighbors:
            values = np.asarray([depths[neighbor] for neighbor in neighbors])
            differences = np.abs(values - depths[cell])
            row["TERRAIN_POSITION"] = float(values.mean() - depths[cell])
            row["RELIEF"] = float(np.ptp(np.concatenate(([depths[cell]], values))))
            # Wilson TRI is the mean absolute focal-to-neighbor difference and
            # is retained as the bathymetry-specific ruggedness measure.
            row["RUGGEDNESS"] = float(differences.mean())
        if len(neighbors) >= config.minimum_neighbors:
            slope, aspect = _plane_metrics(cell, neighbors, depths, centers)
            row["SLOPE"] = slope
            row["ASPECT"] = aspect
            slopes[cell] = slope
            aspects[cell] = aspect
            if math.isfinite(aspect):
                row["EASTNESS"] = math.sin(math.radians(aspect))
                row["NORTHNESS"] = math.cos(math.radians(aspect))
            row["SURFACE_AREA_RATIO_FROM_SLOPE"] = 1.0 / math.cos(math.radians(slope))
        if len(neighbors) >= 5:
            legacy, general, profile, plan = _quadratic_curvatures(cell, neighbors, depths, centers)
            row["CURVATURE"] = legacy
            row["GENERAL_CURVATURE"] = general
            row["PROFILE_CURVATURE"] = profile
            row["PLAN_CURVATURE"] = plan

    for cell in cells:
        if cell not in depths:
            continue
        row = rows[cell]
        tpi_z_values: list[float] = []
        for ring in config.neighborhood_rings:
            neighbors = _neighbors(cell, ring, depths, neighborhood_lookups)
            if not neighbors:
                continue
            neighborhood = [cell, *neighbors]
            neighbor_depths = np.asarray([depths[item] for item in neighbors])
            all_depths = np.asarray([depths[item] for item in neighborhood])
            terrain_position = float(neighbor_depths.mean() - depths[cell])
            neighbor_standard_deviation = float(np.std(neighbor_depths))
            terrain_position_z = (
                terrain_position / neighbor_standard_deviation
                if neighbor_standard_deviation > 1e-9
                else 0.0
            )
            tpi_z_values.append(terrain_position_z)
            deviations = np.abs(all_depths - depths[cell])
            median_depth = float(np.median(all_depths))
            row[f"TERRAIN_POSITION_RING_{ring}_M"] = terrain_position
            row[f"TERRAIN_POSITION_RING_{ring}_Z"] = terrain_position_z
            row[f"LOCAL_RELIEF_RING_{ring}_M"] = float(np.max(deviations))
            row[f"DEPTH_RANGE_RING_{ring}_M"] = float(np.ptp(all_depths))
            row[f"DEPTH_STD_RING_{ring}_M"] = float(np.std(all_depths))
            row[f"DEPTH_MAD_RING_{ring}_M"] = float(np.median(np.abs(all_depths - median_depth)))
            row[f"NEIGHBORHOOD_ROUGHNESS_RING_{ring}_M"] = _detrended_roughness(
                neighborhood, depths, centers
            )
            valid_slopes = np.asarray([slopes[item] for item in neighborhood if item in slopes])
            if len(valid_slopes):
                row[f"SLOPE_MEAN_RING_{ring}"] = float(np.mean(valid_slopes))
                row[f"SLOPE_Q90_RING_{ring}"] = float(
                    np.quantile(valid_slopes, config.slope_upper_quantile)
                )
            _mean_slope, circular_aspect, resultant = _circular_aspect_metrics(
                neighborhood, slopes, aspects
            )
            row[f"ASPECT_CIRCULAR_MEAN_RING_{ring}"] = circular_aspect
            row[f"ASPECT_RESULTANT_LENGTH_RING_{ring}"] = resultant
            row[f"VECTOR_RUGGEDNESS_RING_{ring}"] = _vector_ruggedness(
                neighborhood, slopes, aspects
            )

        openness_neighbors = _neighbors(
            cell,
            config.openness_radius_rings,
            depths,
            neighborhood_lookups,
        )
        positive, negative, coverage = _openness(
            cell,
            openness_neighbors,
            depths,
            centers,
            config.openness_bearing_sectors,
        )
        row["POSITIVE_OPENNESS_DEG"] = positive
        row["NEGATIVE_OPENNESS_DEG"] = negative
        row["OPENNESS_SECTOR_COVERAGE"] = coverage
        if tpi_z_values:
            row["RIDGE_INDEX"] = float(np.clip(max(max(tpi_z_values), 0.0), 0.0, 3.0) / 3.0)
            row["VALLEY_INDEX"] = float(
                np.clip(max(max(-value for value in tpi_z_values), 0.0), 0.0, 3.0) / 3.0
            )
        general_curvature = float(row["GENERAL_CURVATURE"])
        if math.isfinite(general_curvature):
            row["CONVEXITY_INDEX"] = float(
                np.clip(
                    max(general_curvature, 0.0) / config.curvature_index_scale_per_m,
                    0.0,
                    1.0,
                )
            )
            row["CONCAVITY_INDEX"] = float(
                np.clip(
                    max(-general_curvature, 0.0) / config.curvature_index_scale_per_m,
                    0.0,
                    1.0,
                )
            )

    return pd.DataFrame([rows[cell] for cell in cells], columns=columns)


def build_geomorphometry(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> Path:
    """Build the configured resolution-8 multi-scale geomorphometry Parquet."""

    config = load_geomorphometry_config(config_path)
    if not config.bathymetry_path.exists():
        raise FileNotFoundError(f"Bathymetry Parquet not found: {config.bathymetry_path}")
    bathymetry = pd.read_parquet(config.bathymetry_path)
    missing = sorted({"H3_INDEX", "BATHYMETRY"}.difference(bathymetry.columns))
    if missing:
        raise ValueError(f"Bathymetry Parquet is missing columns: {missing}")
    if bathymetry["H3_INDEX"].isna().any() or not bathymetry["H3_INDEX"].is_unique:
        raise ValueError("Bathymetry must contain one non-null row per H3_INDEX.")
    source = bathymetry[["H3_INDEX", "BATHYMETRY"]].copy()
    source["H3_INDEX"] = source["H3_INDEX"].astype(str)
    required_hops = sorted(
        {
            config.neighbor_ring,
            config.openness_radius_rings,
            *config.neighborhood_rings,
        }
    )
    neighborhoods = load_water_neighborhoods(
        config.h3_resolution,
        max(required_hops),
        config_path,
    )
    neighborhood_lookups = {
        hops: water_neighborhood_lookup(neighborhoods, maximum_hops=hops) for hops in required_hops
    }
    result = _derive_metrics(source, config, neighborhood_lookups)
    native_slope = _native_raster_slope_summary(
        config.native_raster_path,
        set(source["H3_INDEX"]),
        config.h3_resolution,
        config.slope_upper_quantile,
    )
    result = result.drop(columns=["SLOPE_MEAN_NATIVE_RASTER", "SLOPE_Q90_NATIVE_RASTER"]).merge(
        native_slope, on="H3_INDEX", how="left", validate="one_to_one"
    )
    columns = output_columns(config.neighborhood_rings)
    result = result[columns]
    if result["H3_INDEX"].nunique() != len(result):
        raise ValueError("Geomorphometry output contains duplicate H3_INDEX values.")
    numeric = result.drop(columns="H3_INDEX").to_numpy(dtype="float64")
    if np.isinf(numeric).any():
        raise ValueError("Geomorphometry output contains infinite values.")
    publisher = stage_parquet_family(
        config.output_path.parent,
        ((result, config.output_path),),
    )
    network = load_water_network_config(config_path)
    neighborhood_path = network.neighborhood_path(config.h3_resolution)
    manifest = build_manifest(
        dataset_family="environment.seascape.geomorphometry",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "GEBCO bathymetric compilation grid",
                "path": str(config.native_raster_path),
                "checksum": checksum_artifact(config.native_raster_path),
                "license": "GEBCO terms of use",
                "observation_period": "compiled source observations; see GEBCO release metadata",
            }
        ],
        upstream_artifacts=[
            {"path": str(path), "checksum": checksum_artifact(path)}
            for path in (config.bathymetry_path, neighborhood_path)
        ],
        attribution=[
            {
                "text": "GEBCO Compilation Group; derived H3 geomorphometry by Seascape Toolkit",
                "license": "GEBCO terms of use",
            }
        ],
        source_completeness="complete",
        metadata={
            "neighborhood_semantics": "water-passable graph neighborhoods",
            "surface_area_ratio_warning": (
                "SURFACE_AREA_RATIO_FROM_SLOPE is deterministic from slope and excluded from "
                "the default model matrix."
            ),
        },
    )
    publisher.publish_manifest(
        config.output_path.parent / "geomorphometry_manifest.json",
        manifest,
    )
    LOGGER.info(
        "Saved resolution-8 geomorphometry with %d metrics: %s",
        len(columns) - 1,
        config.output_path,
    )
    return config.output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(build_geomorphometry(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
