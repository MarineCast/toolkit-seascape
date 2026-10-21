"""Optional bounded coast and island summaries from source vector geometry."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString
from shapely.ops import unary_union

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent
from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.spatial_support.water_network.load import load_model_area_geometry
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)

from .coast_complexity import (
    headland_candidates,
    sample_line_positions,
    shoreline_sinuosity,
    summarize_coast,
)
from .shoreline_characterization.build import load_shoreline_config

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoastComplexityConfig:
    shoreline_path: Path
    land_components_path: Path
    source_context_path: Path
    water_path: Path
    clipped_r8_path: Path
    output_dir: Path
    projected_crs: str
    sinuosity_scales_m: tuple[float, ...]
    minimum_island_area_m2: float
    orientation_probe_m: float
    headland_smoothing_m: float
    headland_station_spacing_m: float
    headland_minimum_turn_degrees: float
    max_cells: int
    max_coast_segments: int
    max_headland_candidates: int
    selected_h3_indices: tuple[str, ...]


def load_coast_complexity_config(config_path: str | Path) -> CoastComplexityConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("coast_complexity")
    if (
        not isinstance(section, dict)
        or not section.get("land_components_path")
        or not section.get("source_context_path")
    ):
        raise ValueError(
            "Set coast_complexity land_components_path and source_context_path"
        )
    shoreline = load_shoreline_config(config_path)
    network = load_water_network_config(config_path)
    root = project_root()
    output = root / str(
        section.get(
            "output_dir",
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/coast_complexity",
        )
    )
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Coast complexity output escapes workspace")
    scales = tuple(
        float(value) for value in section.get("sinuosity_scales_m", (500, 2000))
    )
    if (
        not scales
        or len(scales) != len(set(scales))
        or any(value <= 0 for value in scales)
    ):
        raise ValueError("Sinuosity scales must be distinct and positive")
    numbers = {
        key: float(section[key])
        for key in (
            "minimum_island_area_m2",
            "orientation_probe_m",
            "headland_smoothing_m",
            "headland_station_spacing_m",
            "headland_minimum_turn_degrees",
        )
    }
    if numbers["minimum_island_area_m2"] < 0 or any(
        value <= 0 for key, value in numbers.items() if key != "minimum_island_area_m2"
    ):
        raise ValueError("Coast physical scales must be nonnegative/positive")
    bounds = {
        key: int(section.get(key, default))
        for key, default in (
            ("max_cells", 200),
            ("max_coast_segments", 200),
            ("max_headland_candidates", 200),
        )
    }
    if min(bounds.values()) < 1:
        raise ValueError("Coast resource bounds must be positive")
    return CoastComplexityConfig(
        root / str(section["shoreline_path"])
        if section.get("shoreline_path")
        else shoreline.inventory_path,
        root / str(section["land_components_path"]),
        root / str(section["source_context_path"]),
        network.water_polygon_path,
        network.clipped_geometry_path(8),
        output,
        shoreline.projected_crs,
        scales,
        **numbers,
        **bounds,
        selected_h3_indices=tuple(
            str(value) for value in section.get("selected_h3_indices", ())
        ),
    )


def _local_sinuosity(line, scale_m: float) -> float | None:
    if line.length < scale_m:
        return shoreline_sinuosity(line)
    distances = np.arange(int(line.length // scale_m) + 1) * scale_m
    points = sample_line_positions(line, distances)
    chords = np.array(
        [a.distance(b) for a, b in zip(points[:-1], points[1:], strict=True)]
    )
    values = (scale_m / chords[chords > max(1e-9, scale_m * 1e-9)]).tolist()
    return sum(values) / len(values) if values else None


def _coast_chunks(shore):
    """Index short source-line pieces while retaining their original scale identity."""
    rows = []
    for index, line in shore.geometry.items():
        coordinates = np.asarray(line.coords)
        for start in range(0, len(coordinates) - 1, 64):
            piece = LineString(coordinates[start : start + 65])
            if piece.length > 0:
                rows.append({"SOURCE_COAST_INDEX": index, "geometry": piece})
            if len(rows) > 200000:
                raise ValueError("Coast source-chunk budget exceeded")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=shore.crs)


def build_coast_complexity(config_path: str | Path) -> tuple[Path, ...]:
    config = load_coast_complexity_config(config_path)
    shore = gpd.read_parquet(config.shoreline_path).to_crs(config.projected_crs)
    if (
        "SEGMENT_ID" not in shore
        or shore.SEGMENT_ID.isna().any()
        or shore.SEGMENT_ID.duplicated().any()
    ):
        raise ValueError("Source coastline requires unique SEGMENT_ID")
    cells = load_model_area_geometry(8, config_path).to_crs(config.projected_crs)
    if config.selected_h3_indices:
        missing = set(config.selected_h3_indices) - set(cells.H3_INDEX.astype(str))
        if missing:
            raise KeyError(
                f"Selected coast cells missing from canonical R8: {sorted(missing)}"
            )
        cells = cells.loc[cells.H3_INDEX.isin(config.selected_h3_indices)]
    if cells.empty or len(cells) > config.max_cells:
        raise ValueError("Coast cell bound exceeded or no source-coast support")
    source_land = gpd.read_parquet(config.land_components_path)
    land = source_land.to_crs(config.projected_crs)
    required_land = {
        "LAND_COMPONENT_ID",
        "IS_ISLAND_CANDIDATE",
        "SOURCE_ID",
        "SOURCE_VERSION",
    }
    if (
        required_land - set(land)
        or land.LAND_COMPONENT_ID.isna().any()
        or land.LAND_COMPONENT_ID.duplicated().any()
    ):
        raise ValueError(
            "Land component registry needs stable unique source-backed IDs"
        )
    context = (
        gpd.read_parquet(config.source_context_path)
        .to_crs(config.projected_crs)
        .geometry.union_all()
    )
    if context.is_empty:
        raise ValueError("Source context polygon is empty")
    water = (
        gpd.read_parquet(config.water_path)
        .to_crs(config.projected_crs)
        .geometry.union_all()
    )
    cells = cells.sort_values("H3_INDEX")
    # Headland candidates retain full source context. Reporting-cell clipping
    # below selects local coast summaries without truncating nearest candidates.
    if len(shore) > config.max_coast_segments:
        raise ValueError("Coast segment bound exceeded")
    if not shore.geometry.geom_type.eq("LineString").all():
        raise ValueError("Source coastline segments must be individual lines")
    LOGGER.info(
        "Coast context: %d source segments, %d reporting cells", len(shore), len(cells)
    )
    islands = {
        str(row.LAND_COMPONENT_ID): row.geometry
        for row in land.itertuples(index=False)
        if bool(row.IS_ISLAND_CANDIDATE)
    }
    headland_rows = []
    # Clip only the working land-side test, before projection. Complete source
    # components remain retained for identity, size and censoring diagnostics.
    source_context = (
        gpd.read_parquet(config.source_context_path)
        .to_crs(source_land.crs)
        .geometry.union_all()
    )
    working_land = source_land.copy()
    working_land.geometry = working_land.geometry.intersection(source_context)
    land_union = working_land.to_crs(config.projected_crs).geometry.union_all()
    shapely.prepare(land_union)
    shapely.prepare(water)
    for segment in shore.itertuples(index=False):
        headland_rows.extend(
            headland_candidates(
                str(segment.SEGMENT_ID),
                segment.geometry,
                land_union,
                smoothing_distance_m=config.headland_smoothing_m,
                station_spacing_m=config.headland_station_spacing_m,
                minimum_turn_degrees=config.headland_minimum_turn_degrees,
                side_probe_m=config.orientation_probe_m,
            )
        )
        if len(headland_rows) > config.max_headland_candidates:
            raise ValueError("Headland candidate bound exceeded")
    if headland_rows:
        headlands = gpd.GeoDataFrame(
            headland_rows, geometry="GEOMETRY", crs=config.projected_crs
        )
    else:
        headlands = gpd.GeoDataFrame(
            {
                "HEADLAND_CANDIDATE_ID": pd.Series(dtype="string"),
                "SOURCE_COAST_ID": pd.Series(dtype="string"),
                "ALONG_COAST_M": pd.Series(dtype="float64"),
                "TURN_DEGREES": pd.Series(dtype="float64"),
                "SMOOTHING_DISTANCE_M": pd.Series(dtype="float64"),
                "METHOD": pd.Series(dtype="string"),
                "GEOMETRY": gpd.GeoSeries([], crs=config.projected_crs),
            },
            geometry="GEOMETRY",
            crs=config.projected_crs,
        )
    LOGGER.info("Derived %d source-context headland candidates", len(headland_rows))
    supports = {8: cells}
    supports[6] = gpd.GeoDataFrame(
        [
            {"H3_INDEX": parent, "geometry": unary_union(list(group.geometry))}
            for parent, group in cells.assign(
                PARENT=cells.H3_INDEX.map(lambda value: cell_to_parent(str(value), 6))
            ).groupby("PARENT")
        ],
        geometry="geometry",
        crs=cells.crs,
    )
    source_land["SOURCE_CONTEXT_CENSORED"] = ~source_land.geometry.within(
        source_context
    )
    outputs = [
        (source_land, config.output_dir / "LAND_COMPONENT_INVENTORY.parquet"),
        (headlands, config.output_dir / "HEADLAND_CANDIDATES.parquet"),
    ]
    sinuosity = {
        (index, scale): _local_sinuosity(line, scale)
        for index, line in shore.geometry.items()
        for scale in config.sinuosity_scales_m
    }
    chunks = _coast_chunks(shore)
    shore_index = chunks.sindex
    island_frame = gpd.GeoDataFrame(
        {"LAND_COMPONENT_ID": list(islands)},
        geometry=list(islands.values()),
        crs=land.crs,
    )
    island_index = island_frame.sindex
    for resolution, frame in supports.items():
        rows = []
        for cell_number, cell in enumerate(frame.itertuples(index=False), start=1):
            local = chunks.iloc[
                shore_index.query(cell.geometry, predicate="intersects")
            ]
            fragments = []
            for geometry in local.geometry.intersection(cell.geometry):
                fragments.extend(
                    [
                        part
                        for part in shapely.get_parts(geometry)
                        if part.geom_type == "LineString"
                    ]
                )
            local_islands = island_frame.iloc[
                island_index.query(cell.geometry, predicate="intersects")
            ]
            summary = summarize_coast(
                fragments,
                cell.geometry,
                water,
                dict(
                    zip(
                        local_islands.LAND_COMPONENT_ID,
                        local_islands.geometry,
                        strict=True,
                    )
                ),
                context.boundary,
                minimum_island_area_m2=config.minimum_island_area_m2,
                normal_probe_m=config.orientation_probe_m,
            )
            nearest = None
            nearest_distance = None
            if not headlands.empty:
                position = int(
                    headlands.sindex.nearest(cell.geometry, return_all=False)[1, 0]
                )
                index = headlands.index[position]
                nearest = str(headlands.loc[index, "HEADLAND_CANDIDATE_ID"])
                nearest_distance = float(
                    headlands.geometry.loc[index].distance(cell.geometry)
                )
            row = {
                "H3_INDEX": str(cell.H3_INDEX),
                "H3_RESOLUTION": resolution,
                "SHORELINE_LENGTH_M": summary.shoreline_length_m,
                "SHORELINE_LENGTH_DENSITY_M_PER_KM2": summary.shoreline_length_density_m_per_km2,
                "SHORELINE_AXIAL_ORIENTATION_DEG": summary.axial_orientation_deg,
                "SHORELINE_AXIAL_SIN_2THETA": summary.axial_sin_2theta,
                "SHORELINE_AXIAL_COS_2THETA": summary.axial_cos_2theta,
                "SHORELINE_ORIENTATION_CONCENTRATION": summary.orientation_concentration,
                "WATER_FACING_NORMAL_BEARING_DEG": summary.water_normal_bearing_deg,
                "ISLAND_COUNT": summary.island_count,
                "ISLAND_AREA_WITHIN_SUPPORT_M2": summary.island_area_within_support_m2,
                "ISLAND_FRACTION_OF_SUPPORT": summary.island_fraction_of_support,
                "ISLAND_IDS": "|".join(summary.island_ids),
                "BOUNDARY_CENSORED_ISLAND_IDS": "|".join(
                    summary.boundary_censored_island_ids
                ),
                "NEAREST_HEADLAND_CANDIDATE_ID": nearest,
                "DISTANCE_TO_HEADLAND_CANDIDATE_M": nearest_distance,
                "SPATIAL_SUPPORT": "water_clipped_r8"
                if resolution == 8
                else "hierarchical_r8_child_union",
            }
            for scale in config.sinuosity_scales_m:
                values = [
                    (
                        line.intersection(cell.geometry).length,
                        sinuosity[(local.loc[index, "SOURCE_COAST_INDEX"], scale)],
                    )
                    for index, line in local.geometry.items()
                ]
                usable = [
                    (weight, value)
                    for weight, value in values
                    if weight > 0 and value is not None
                ]
                token = (
                    str(int(scale))
                    if scale.is_integer()
                    else str(scale).replace(".", "P")
                )
                row[f"SHORELINE_SINUOSITY_{token}M"] = (
                    sum(weight * value for weight, value in usable)
                    / sum(weight for weight, _ in usable)
                    if usable
                    else None
                )
            rows.append(row)
            if cell_number % 10000 == 0:
                LOGGER.info(
                    "Summarized coast R%d cells: %d/%d",
                    resolution,
                    cell_number,
                    len(frame),
                )
        outputs.append(
            (
                pd.DataFrame(rows),
                config.output_dir / f"COAST_COMPLEXITY_RES_{resolution}.parquet",
            )
        )
    publisher = stage_parquet_family(config.output_dir, outputs)
    source_paths = (
        config.shoreline_path,
        config.land_components_path,
        config.source_context_path,
    )
    manifest = build_manifest(
        dataset_family="environment.seascape.coast_complexity",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": path.name,
                "path": str(path),
                "checksum": checksum_artifact(path),
                "license": "Per-source inventory rights",
            }
            for path in source_paths
        ],
        upstream_artifacts=[
            {"path": str(path), "checksum": checksum_artifact(path)}
            for path in (config.water_path, config.clipped_r8_path)
        ],
        attribution=[
            {"text": f"{source_id}, version {version}", "license": str(rights)}
            for source_id, version, rights in shore[
                ["SOURCE_ID", "SOURCE_VERSION", "RIGHTS"]
            ]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        ],
        source_completeness="partial",
        metadata={
            "scientific_method_version": "source_coast_complexity_v1",
            "sample_support": "source vector coastline, complete source land components, water-clipped R8 and R8-child-union R6",
        },
    )
    publisher.publish_manifest(
        config.output_dir / "coast_complexity_manifest.json", manifest
    )
    return tuple(path for _frame, path in outputs)
