"""Build H3 depth, within-cell summaries, and selected isobath distances."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .pipeline import BathymetryConfig

LOGGER = logging.getLogger(__name__)

BASE_OUTPUT_COLUMNS = [
    "H3_INDEX",
    "BATHYMETRY",
    "BATHYMETRY_MEDIAN",
    "BATHYMETRY_MIN",
    "BATHYMETRY_MAX",
    "BATHYMETRY_STD",
    "BATHYMETRY_RANGE",
    "BATHYMETRY_LOCAL_ANOMALY",
    "BATHYMETRY_PIXEL_COUNT",
]

DEPTH_BANDS_M: tuple[tuple[str, float, float | None], ...] = (
    ("0_10", 0.0, 10.0),
    ("10_30", 10.0, 30.0),
    ("30_50", 30.0, 50.0),
    ("50_100", 50.0, 100.0),
    ("100_200", 100.0, 200.0),
    ("OVER_200", 200.0, None),
)


def _depth_band_membership(depth_positive_m: np.ndarray) -> dict[str, np.ndarray]:
    """Return half-open positive-depth band membership arrays."""

    depth = np.asarray(depth_positive_m, dtype="float64")
    output = {}
    for token, lower, upper in DEPTH_BANDS_M:
        in_band = np.isfinite(depth) & (depth >= lower)
        if upper is not None:
            in_band &= depth < upper
        output[token] = in_band
    return output


def _number_token(value: float) -> str:
    return format(float(value), ".10g").replace(".", "_")


def _quantile_column(quantile: float) -> str:
    return f"BATHYMETRY_Q{_number_token(quantile * 100.0)}"


def _isobath_distance_column(level_m: float) -> str:
    return f"DISTANCE_TO_ISOBATH_{_number_token(level_m)}_M"


def _output_columns(
    depth_quantiles: tuple[float, ...],
    isobath_levels_m: tuple[float, ...],
) -> list[str]:
    quantile_columns = [_quantile_column(value) for value in depth_quantiles]
    isobath_columns = [_isobath_distance_column(value) for value in isobath_levels_m]
    band_columns = [
        column
        for token, _lower, _upper in DEPTH_BANDS_M
        for column in (
            f"BATHYMETRY_PIXEL_COUNT_{token}_M",
            f"BATHYMETRY_FRAC_{token}_M",
        )
    ]
    return (
        BASE_OUTPUT_COLUMNS[:-1]
        + quantile_columns
        + isobath_columns
        + band_columns
        + [BASE_OUTPUT_COLUMNS[-1]]
    )


def _cells_from_existing_grid(config: BathymetryConfig) -> list[str]:
    grid = pd.read_parquet(config.h3_grid_path)
    if "H3_INDEX" not in grid.columns:
        raise ValueError(f"H3 grid must contain H3_INDEX: {config.h3_grid_path}")
    return sorted(grid["H3_INDEX"].dropna().astype(str).unique().tolist())


def load_h3_cells(config: BathymetryConfig) -> list[str]:
    """Load the required canonical model-area support for this resolution."""

    if not config.h3_grid_path.exists():
        raise FileNotFoundError(
            "Canonical model-area support is required before bathymetry: " f"{config.h3_grid_path}"
        )
    cells = _cells_from_existing_grid(config)
    source = config.h3_grid_path
    if not cells:
        raise ValueError(f"No H3 cells found in the configured model area using {source}.")
    import h3

    unexpected = sorted(
        {int(h3.get_resolution(cell)) for cell in cells}.difference({config.h3_resolution})
    )
    if unexpected:
        raise ValueError(
            f"Canonical support contains resolutions {unexpected}; expected {config.h3_resolution}."
        )
    LOGGER.info(
        "Using %d water H3 cells at resolution %d from %s",
        len(cells),
        config.h3_resolution,
        source,
    )
    return cells


def _pixel_centers(transform: Any, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    rows, columns = np.indices(shape, dtype=float)
    longitudes = transform.c + (columns + 0.5) * transform.a + (rows + 0.5) * transform.b
    latitudes = transform.f + (columns + 0.5) * transform.d + (rows + 0.5) * transform.e
    return latitudes, longitudes


def _latlngs_to_h3(latitudes: np.ndarray, longitudes: np.ndarray, resolution: int) -> list[str]:
    import h3

    return [
        str(h3.latlng_to_cell(float(latitude), float(longitude), int(resolution)))
        for latitude, longitude in zip(latitudes, longitudes, strict=True)
    ]


def _local_depth_anomaly(
    cells: list[str],
    depth_values: pd.Series,
    neighborhood_rings: int,
    neighborhoods: pd.DataFrame,
) -> np.ndarray:
    """Return focal depth minus the mean over bounded water-graph neighbors."""

    depth_by_cell = {
        cell: float(value)
        for cell, value in zip(cells, depth_values, strict=True)
        if pd.notna(value) and np.isfinite(float(value))
    }
    anomaly = np.full(len(cells), np.nan, dtype="float64")
    required = {
        "SOURCE_H3_INDEX",
        "TARGET_H3_INDEX",
        "MINIMUM_HOP_COUNT",
        "NETWORK_DISTANCE_M",
    }
    missing = sorted(required.difference(neighborhoods.columns))
    if missing:
        raise ValueError(f"Water-neighborhood table is missing columns: {missing}")
    selected = neighborhoods.loc[neighborhoods["MINIMUM_HOP_COUNT"].between(1, neighborhood_rings)]
    targets_by_source = selected.groupby("SOURCE_H3_INDEX", sort=False)["TARGET_H3_INDEX"].agg(list)
    for index, cell in enumerate(cells):
        focal_depth = depth_by_cell.get(cell)
        if focal_depth is None:
            continue
        nearby_depths = [
            depth_by_cell[neighbor]
            for neighbor in targets_by_source.get(cell, [])
            if neighbor in depth_by_cell
        ]
        if nearby_depths:
            anomaly[index] = focal_depth - float(np.mean(nearby_depths))
    return anomaly


def _isobath_crossings(
    contour_depth: np.ndarray,
    marine_mask: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    level_m: float,
) -> np.ndarray:
    """Interpolate raster-edge crossing points for one positive-down contour."""

    crossing_parts: list[np.ndarray] = []
    edge_pairs = (
        (
            contour_depth[:, :-1],
            contour_depth[:, 1:],
            marine_mask[:, :-1],
            marine_mask[:, 1:],
            latitudes[:, :-1],
            latitudes[:, 1:],
            longitudes[:, :-1],
            longitudes[:, 1:],
        ),
        (
            contour_depth[:-1, :],
            contour_depth[1:, :],
            marine_mask[:-1, :],
            marine_mask[1:, :],
            latitudes[:-1, :],
            latitudes[1:, :],
            longitudes[:-1, :],
            longitudes[1:, :],
        ),
    )
    for (
        first,
        second,
        first_marine,
        second_marine,
        first_lat,
        second_lat,
        first_lon,
        second_lon,
    ) in edge_pairs:
        valid = np.isfinite(first) & np.isfinite(second) & first_marine & second_marine
        crossing = valid & ((first - level_m) * (second - level_m) <= 0.0)
        if not crossing.any():
            continue
        first_values = first[crossing]
        second_values = second[crossing]
        denominator = second_values - first_values
        fraction = np.full(first_values.shape, 0.5, dtype="float64")
        np.divide(
            level_m - first_values,
            denominator,
            out=fraction,
            where=np.abs(denominator) > np.finfo("float64").eps,
        )
        crossing_lat = first_lat[crossing] + fraction * (second_lat[crossing] - first_lat[crossing])
        crossing_lon = first_lon[crossing] + fraction * (second_lon[crossing] - first_lon[crossing])
        crossing_parts.append(np.column_stack((crossing_lon, crossing_lat)))
    if not crossing_parts:
        raise ValueError(f"GEBCO raster does not cross the configured {level_m:g} m isobath.")
    return np.concatenate(crossing_parts, axis=0)


def _distance_to_isobaths(
    cells: list[str],
    contour_depth: np.ndarray,
    marine_mask: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    isobath_levels_m: tuple[float, ...],
    projected_crs: str,
) -> dict[str, np.ndarray]:
    """Measure H3-center distance to native-raster isobath crossings."""

    import h3
    from pyproj import CRS, Transformer
    from scipy.spatial import cKDTree

    target_crs = CRS.from_user_input(projected_crs)
    if not target_crs.is_projected:
        raise ValueError("Bathymetry isobath distance CRS must be projected.")
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    cell_latlngs = [h3.cell_to_latlng(cell) for cell in cells]
    cell_x, cell_y = transformer.transform(
        [longitude for _latitude, longitude in cell_latlngs],
        [latitude for latitude, _longitude in cell_latlngs],
    )
    cell_points = np.column_stack((cell_x, cell_y))

    distances: dict[str, np.ndarray] = {}
    for level_m in isobath_levels_m:
        crossings = _isobath_crossings(
            contour_depth,
            marine_mask,
            latitudes,
            longitudes,
            level_m,
        )
        crossing_x, crossing_y = transformer.transform(crossings[:, 0], crossings[:, 1])
        crossing_points = np.column_stack((crossing_x, crossing_y))
        crossing_points = crossing_points[np.isfinite(crossing_points).all(axis=1)]
        if crossing_points.size == 0:
            raise ValueError(f"No projectable crossings found for the {level_m:g} m isobath.")
        nearest_distance, _nearest_index = cKDTree(crossing_points).query(
            cell_points,
            workers=-1,
        )
        column = _isobath_distance_column(level_m)
        distances[column] = nearest_distance.astype("float64", copy=False)
        LOGGER.info(
            "Measured %s from %d native-raster contour crossings",
            column,
            len(crossing_points),
        )
    return distances


def _aggregate_raster(
    raster_path: Path,
    cells: list[str],
    resolution: int,
    bathymetry_sign: str,
    depth_quantiles: tuple[float, ...],
    local_depth_anomaly_neighborhood_rings: int,
    isobath_levels_m: tuple[float, ...],
    isobath_distance_projected_crs: str,
    neighborhoods: pd.DataFrame,
) -> pd.DataFrame:
    import rasterio

    with rasterio.open(raster_path) as raster:
        if raster.count != 1:
            raise ValueError(f"Expected a single-band GEBCO raster: {raster_path}")
        if raster.crs is None or raster.crs.to_epsg() != 4326:
            raise ValueError("GEBCO GeoTIFF must use EPSG:4326 for H3 aggregation.")
        elevation = raster.read(1, masked=True).astype("float64").filled(np.nan)
        transform = raster.transform

    latitudes, longitudes = _pixel_centers(transform, elevation.shape)
    marine = np.isfinite(elevation) & (elevation < 0.0)
    marine_depth = np.where(marine, -elevation, np.nan)
    contour_depth = marine_depth
    pixel_cells = _latlngs_to_h3(latitudes[marine], longitudes[marine], resolution)
    cell_set = set(cells)
    in_grid = np.fromiter((cell in cell_set for cell in pixel_cells), dtype=bool)
    selected_cells = np.asarray(pixel_cells, dtype=object)[in_grid]
    if selected_cells.size == 0:
        raise ValueError("No marine GEBCO pixels overlap the configured water H3 cells.")

    depth = marine_depth[marine][in_grid]
    if bathymetry_sign == "negative_elevation":
        depth = -depth
    samples = pd.DataFrame(
        {
            "H3_INDEX": selected_cells,
            "BATHYMETRY": depth,
            "DEPTH_POSITIVE_M": marine_depth[marine][in_grid],
        }
    )
    band_membership = _depth_band_membership(samples["DEPTH_POSITIVE_M"].to_numpy())
    for token, in_band in band_membership.items():
        samples[f"BATHYMETRY_PIXEL_COUNT_{token}_M"] = in_band.astype("int64")
    aggregations: dict[str, Any] = {
        "BATHYMETRY": "mean",
        "BATHYMETRY_MEDIAN": "median",
        "BATHYMETRY_MIN": "min",
        "BATHYMETRY_MAX": "max",
        "BATHYMETRY_STD": lambda values: values.std(ddof=0),
        "BATHYMETRY_PIXEL_COUNT": "size",
    }
    for quantile in depth_quantiles:
        aggregations[_quantile_column(quantile)] = (
            lambda values, selected_quantile=quantile: values.quantile(selected_quantile)
        )
    grouped = samples.groupby("H3_INDEX", sort=False, observed=True)["BATHYMETRY"].agg(
        **aggregations
    )
    band_counts = samples.groupby("H3_INDEX", sort=False, observed=True)[
        [f"BATHYMETRY_PIXEL_COUNT_{token}_M" for token, _lower, _upper in DEPTH_BANDS_M]
    ].sum()
    grouped = grouped.join(band_counts, how="left")
    for token, _lower, _upper in DEPTH_BANDS_M:
        grouped[f"BATHYMETRY_FRAC_{token}_M"] = (
            grouped[f"BATHYMETRY_PIXEL_COUNT_{token}_M"] / grouped["BATHYMETRY_PIXEL_COUNT"]
        )
    grouped["BATHYMETRY_RANGE"] = grouped["BATHYMETRY_MAX"] - grouped["BATHYMETRY_MIN"]
    result = pd.DataFrame({"H3_INDEX": cells}).merge(
        grouped.reset_index(), on="H3_INDEX", how="left", validate="one_to_one"
    )
    result["BATHYMETRY_LOCAL_ANOMALY"] = _local_depth_anomaly(
        cells,
        result["BATHYMETRY"],
        local_depth_anomaly_neighborhood_rings,
        neighborhoods,
    )
    for column, values in _distance_to_isobaths(
        cells,
        contour_depth,
        marine,
        latitudes,
        longitudes,
        isobath_levels_m,
        isobath_distance_projected_crs,
    ).items():
        result[column] = values
    return result[_output_columns(depth_quantiles, isobath_levels_m)]


def build_bathymetry_parquet(
    config: BathymetryConfig,
    *,
    raster_path: str | Path | None = None,
) -> Path:
    """Aggregate GEBCO depth and direct depth summaries into configured H3 cells."""

    source = Path(raster_path).expanduser().resolve() if raster_path else config.raw_path
    if not source.exists():
        raise FileNotFoundError(f"GEBCO GeoTIFF not found: {source}")
    cells = load_h3_cells(config)
    neighborhood_path = Path(
        config.water_neighborhood_path_template.format(res=config.h3_resolution)
    )
    if not neighborhood_path.exists():
        raise FileNotFoundError(
            "Canonical water-neighborhood artifact is required for bathymetry anomaly: "
            f"{neighborhood_path}"
        )
    neighborhoods = pd.read_parquet(neighborhood_path)
    output = _aggregate_raster(
        source,
        cells,
        config.h3_resolution,
        config.bathymetry_sign,
        config.depth_quantiles,
        config.local_depth_anomaly_neighborhood_rings,
        config.isobath_levels_m,
        config.isobath_distance_projected_crs,
        neighborhoods,
    )
    config.processed_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(config.processed_path, index=False)
    LOGGER.info("Saved bathymetry Parquet: %s", config.processed_path)
    return config.processed_path
