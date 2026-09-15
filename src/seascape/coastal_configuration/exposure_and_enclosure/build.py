"""Build static resolution-8 coastal exposure and enclosure features.

Land polygons are the only obstruction source. Territorial water selects the
canonical output H3 universe but does not define fetch limits or barriers.
Dynamic wind, wave, tide, and weather inputs are intentionally excluded.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
from shapely.geometry import box

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.geo.geometry import normalize_polygonal_geometry, safe_polygonal_union
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.spatial_support.water_network.geometry import (
    directional_water_fraction,
)
from seascape.spatial_support.water_network.graph import (
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    load_model_area_support,
    load_water_graph,
    load_water_support,
    multi_source_shortest_paths,
    nullable_string_values,
)
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.spatial import (
    expanded_bbox_polygon as _expanded_bbox,
)
from seascape.utils.spatial import (
    load_polygon_layer as _read_polygon_layer,
)
from seascape.utils.spatial import project_h3_centers as _cell_centers

LOGGER = logging.getLogger(__name__)

BEARING_LABELS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)
OUTPUT_COLUMNS = [
    "H3_INDEX",
    "OPENNESS_TO_OCEAN_INDEX",
    "ENCLOSURE_INDEX",
    "EMBAYMENT_INDEX",
    "DISTANCE_TO_OPEN_WATER_M",
    "OPEN_WATER_ANGULAR_APERTURE_DEG",
    "WATER_COMPONENT_ID",
    "NETWORK_CONNECTOR_METHOD",
    "NETWORK_CONNECTOR_DISTANCE_M",
    "NETWORK_DISTANCE_QC_REASON",
]


@dataclass(frozen=True)
class ExposureEnclosureConfig:
    """Resolved static exposure and enclosure configuration."""

    bbox: dict[str, float]
    h3_resolution: int
    water_polygon_path: Path
    land_polygon_path: Path
    output_path: Path
    projected_crs: str
    maximum_fetch_km: float
    bearing_count: int
    network_context_buffer_km: float
    open_water_openness_threshold: float
    open_bearing_fetch_fraction: float


def load_exposure_enclosure_config(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> ExposureEnclosureConfig:
    """Load and validate exposure-and-enclosure settings."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(
        raw.get("exposure_and_enclosure"),
        "exposure_and_enclosure",
    )
    processing = _mapping(
        section.get("processing"),
        "exposure_and_enclosure.processing",
    )
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("exposure_and_enclosure.processing.h3_resolution must be 8.")
    maximum_fetch_km = float(processing.get("maximum_fetch_km", 50.0))
    bearing_count = int(processing.get("bearing_count", len(BEARING_LABELS)))
    network_context_buffer_km = float(processing.get("network_context_buffer_km", 60.0))
    openness_threshold = float(processing.get("open_water_openness_threshold", 0.75))
    bearing_threshold = float(processing.get("open_bearing_fetch_fraction", 0.90))
    if maximum_fetch_km <= 0.0:
        raise ValueError("maximum_fetch_km must be positive.")
    if bearing_count != len(BEARING_LABELS):
        raise ValueError(
            f"bearing_count must be {len(BEARING_LABELS)} for the named bearing schema."
        )
    if network_context_buffer_km <= 0.0:
        raise ValueError("network_context_buffer_km must be positive.")
    if not 0.0 < openness_threshold <= 1.0:
        raise ValueError("open_water_openness_threshold must be in (0, 1].")
    if not 0.0 < bearing_threshold <= 1.0:
        raise ValueError("open_bearing_fetch_fraction must be in (0, 1].")
    return ExposureEnclosureConfig(
        bbox=bbox_from_config(section),
        h3_resolution=resolution,
        water_polygon_path=_resolve(processing["water_polygon_path"], base_dir),
        land_polygon_path=_resolve(processing["land_polygon_path"], base_dir),
        output_path=_resolve(processing["processed_path"], base_dir),
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        maximum_fetch_km=maximum_fetch_km,
        bearing_count=bearing_count,
        network_context_buffer_km=network_context_buffer_km,
        open_water_openness_threshold=openness_threshold,
        open_bearing_fetch_fraction=bearing_threshold,
    )


def _spatial_support(config: ExposureEnclosureConfig):
    """Prepare target support, graph context, and a larger fetch mask context."""

    water = _read_polygon_layer(config.water_polygon_path)
    land = _read_polygon_layer(config.land_polygon_path)
    target_box = box(
        config.bbox["min_lon"],
        config.bbox["min_lat"],
        config.bbox["max_lon"],
        config.bbox["max_lat"],
    )
    graph_box = _expanded_bbox(config.bbox, config.network_context_buffer_km)
    fetch_mask_km = config.network_context_buffer_km + config.maximum_fetch_km + 2.0
    fetch_mask_box = _expanded_bbox(config.bbox, fetch_mask_km)
    land_guard_box = _expanded_bbox(config.bbox, fetch_mask_km + 10.0)
    target_water = safe_polygonal_union(water, clip_geometry=target_box)
    fetch_mask_water = safe_polygonal_union(water, clip_geometry=fetch_mask_box)
    guarded_land = safe_polygonal_union(land, clip_geometry=land_guard_box)
    fetch_mask_land = normalize_polygonal_geometry(guarded_land.intersection(fetch_mask_box))
    return target_water, graph_box, fetch_mask_box, fetch_mask_land, fetch_mask_water


def _directional_fetch_matrix(
    cells: list[str],
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    water_geometry: Any,
    maximum_fetch_km: float,
) -> np.ndarray:
    """Calculate uninterrupted non-land fetch along 16 compass bearings."""

    bearings = np.linspace(0.0, 360.0, len(BEARING_LABELS), endpoint=False)
    maximum_fetch_m = float(maximum_fetch_km) * 1_000.0
    output = np.empty((len(cells), len(BEARING_LABELS)), dtype="float64")
    for index, (_cell, latitude, longitude) in enumerate(
        zip(cells, latitudes, longitudes, strict=True)
    ):
        for bearing_index, bearing in enumerate(bearings):
            output[index, bearing_index] = maximum_fetch_m * directional_water_fraction(
                float(longitude),
                float(latitude),
                float(bearing),
                maximum_fetch_m,
                water_geometry,
            )
        if (index + 1) % 10_000 == 0:
            LOGGER.info("Calculated directional fetch for %d/%d cells", index + 1, len(cells))
    return np.clip(output, 0.0, maximum_fetch_m)


def _open_water_seed_positions(openness: np.ndarray, threshold: float) -> np.ndarray:
    """Return graph seeds for open water and fail before publishing an empty metric."""

    seeds = np.flatnonzero(openness >= threshold)
    if len(seeds):
        return seeds
    maximum = float(np.nanmax(openness)) if len(openness) else float("nan")
    raise ValueError(
        "No graph cell met the configured open-water openness threshold "
        f"{threshold:.3f}; maximum graph openness was {maximum:.3f}. "
        "Adjust the scale-explicit threshold before publishing DISTANCE_TO_OPEN_WATER_M."
    )


def _build_output(
    target_cells: list[str],
    target_fetch: np.ndarray,
    target_distance_to_open_water: np.ndarray,
    config: ExposureEnclosureConfig,
    lineage: pd.DataFrame,
    qc_reasons: np.ndarray,
) -> pl.DataFrame:
    maximum_fetch_m = config.maximum_fetch_km * 1_000.0
    fetch_mean = target_fetch.mean(axis=1)
    fetch_max = target_fetch.max(axis=1)
    openness = np.clip(fetch_mean / maximum_fetch_m, 0.0, 1.0)
    enclosure = 1.0 - openness
    # High values identify cells with one relatively open outlet but low mean
    # exposure, a scale-explicit geometric signature of embayment.
    embayment = np.clip(fetch_max / maximum_fetch_m - openness, 0.0, 1.0)
    aperture = (target_fetch >= maximum_fetch_m * config.open_bearing_fetch_fraction).sum(
        axis=1
    ) * (360.0 / len(BEARING_LABELS))
    data: dict[str, Any] = {
        "H3_INDEX": target_cells,
        "OPENNESS_TO_OCEAN_INDEX": openness,
        "ENCLOSURE_INDEX": enclosure,
        "EMBAYMENT_INDEX": embayment,
        "DISTANCE_TO_OPEN_WATER_M": target_distance_to_open_water,
        "OPEN_WATER_ANGULAR_APERTURE_DEG": aperture,
        "WATER_COMPONENT_ID": nullable_string_values(lineage["WATER_COMPONENT_ID"]),
        "NETWORK_CONNECTOR_METHOD": nullable_string_values(lineage["CONNECTOR_METHOD"]),
        "NETWORK_CONNECTOR_DISTANCE_M": lineage["CONNECTOR_DISTANCE_M"].tolist(),
        "NETWORK_DISTANCE_QC_REASON": nullable_string_values(qc_reasons),
    }
    return (
        pl.DataFrame(data)
        .with_columns(
            pl.col("H3_INDEX").cast(pl.String),
            pl.exclude(
                "H3_INDEX",
                "WATER_COMPONENT_ID",
                "NETWORK_CONNECTOR_METHOD",
                "NETWORK_DISTANCE_QC_REASON",
            ).cast(pl.Float64),
            pl.col("WATER_COMPONENT_ID").cast(pl.String),
            pl.col("NETWORK_CONNECTOR_METHOD").cast(pl.String),
            pl.col("NETWORK_DISTANCE_QC_REASON").cast(pl.String),
        )
        .select(OUTPUT_COLUMNS)
        .sort("H3_INDEX")
    )


def build_exposure_and_enclosure(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> Path:
    """Build and save the configured static exposure-and-enclosure product."""

    import h3

    config = load_exposure_enclosure_config(config_path)
    target_water, graph_box, fetch_mask_box, fetch_mask_land, fetch_mask_water = _spatial_support(
        config
    )
    target_support = load_model_area_support(config.h3_resolution, config_path)
    target_cells = target_support["H3_INDEX"].astype(str).tolist()
    if not target_cells:
        raise ValueError("No target H3 cells overlap the configured water support.")
    if any(h3.get_resolution(cell) != config.h3_resolution for cell in target_cells):
        raise ValueError("Target support contains an unexpected H3 resolution.")
    target_lat, target_lon, target_x, target_y = _cell_centers(
        target_cells,
        config.projected_crs,
    )
    graph = load_water_graph(
        config.h3_resolution,
        config_path,
        bbox=tuple(graph_box.bounds),
    )
    graph_cells = graph.cells.astype(str).tolist()
    graph_lineage = graph.support.set_index("H3_INDEX").loc[graph_cells]
    graph_lon = graph_lineage["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(dtype="float64")
    graph_lat = graph_lineage["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(dtype="float64")
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", config.projected_crs, always_xy=True)
    graph_x, graph_y = transformer.transform(graph_lon, graph_lat)
    graph_x = np.asarray(graph_x, dtype="float64")
    graph_y = np.asarray(graph_y, dtype="float64")
    fetch_support = load_water_support(
        config.h3_resolution,
        config_path,
        bbox=tuple(fetch_mask_box.bounds),
    )
    fetch_mask_set = set(
        fetch_support.loc[fetch_support["WATER_COMPONENT_ID"].notna(), "H3_INDEX"].astype(str)
    )
    LOGGER.info(
        "Exposure support: %d target cells, %d graph cells, %d fetch-mask cells",
        len(target_cells),
        len(graph_cells),
        len(fetch_mask_set),
    )
    graph_fetch = _directional_fetch_matrix(
        graph_cells,
        graph_lat,
        graph_lon,
        fetch_mask_water,
        config.maximum_fetch_km,
    )
    maximum_fetch_m = config.maximum_fetch_km * 1_000.0
    graph_openness = np.clip(graph_fetch.mean(axis=1) / maximum_fetch_m, 0.0, 1.0)
    open_seeds = _open_water_seed_positions(
        graph_openness,
        config.open_water_openness_threshold,
    )
    graph_distance_to_open, _owners = multi_source_shortest_paths(
        graph,
        [(graph_cells[index], 0.0, int(index)) for index in open_seeds],
    )
    graph_index = {cell: index for index, cell in enumerate(graph_cells)}
    target_fetch = np.empty((len(target_cells), len(BEARING_LABELS)), dtype="float64")
    missing_target_indices = [
        index for index, cell in enumerate(target_cells) if cell not in graph_index
    ]
    for index, cell in enumerate(target_cells):
        graph_position = graph_index.get(cell)
        if graph_position is not None:
            target_fetch[index] = graph_fetch[graph_position]
    if missing_target_indices:
        missing_cells = [target_cells[index] for index in missing_target_indices]
        missing_fetch = _directional_fetch_matrix(
            missing_cells,
            target_lat[missing_target_indices],
            target_lon[missing_target_indices],
            fetch_mask_water,
            config.maximum_fetch_km,
        )
        target_fetch[np.asarray(missing_target_indices, dtype=int)] = missing_fetch
    mapped, connectors, qc_reasons = target_graph_mapping(graph, target_cells)
    target_distance_to_open = np.full(len(target_cells), np.nan, dtype="float64")
    graph_mapped = mapped >= 0
    reachable = graph_mapped & np.isfinite(graph_distance_to_open[np.maximum(mapped, 0)])
    target_distance_to_open[reachable] = (
        graph_distance_to_open[mapped[reachable]] + connectors[reachable]
    )
    qc_reasons[graph_mapped & ~reachable & pd.isna(qc_reasons)] = "no_open_water_seed"
    qc_reasons[~graph_mapped & pd.isna(qc_reasons)] = "unreachable_from_open_water_seed"
    lineage = target_support.set_index("H3_INDEX").loc[target_cells]
    output = _build_output(
        target_cells,
        target_fetch,
        target_distance_to_open,
        config,
        lineage,
        qc_reasons,
    )
    if output["H3_INDEX"].n_unique() != output.height:
        raise ValueError("Exposure output contains duplicate H3_INDEX values.")
    publisher = stage_parquet_family(
        config.output_path.parent,
        ((output, config.output_path),),
    )
    network = load_water_network_config(config_path)
    manifest = build_manifest(
        dataset_family="environment.seascape.exposure_and_enclosure",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "Natural Earth land and marine polygons",
                "license": "Public domain",
                "observation_period": "generalized cartographic source; not observational",
            }
        ],
        upstream_artifacts=[
            {"path": str(path), "checksum": checksum_artifact(path)}
            for path in (
                config.water_polygon_path,
                config.land_polygon_path,
                network.manifest_path,
            )
        ],
        attribution=[
            {
                "text": "Natural Earth; derived exposure metrics by Seascape Toolkit",
                "license": "Public domain",
            }
        ],
        source_completeness="complete",
        metadata={
            "algorithm_semantics": (
                "Directional exposure and line-of-sight use geometric ray casting; distance "
                "to open water follows the canonical water-passable graph."
            ),
            "open_water_openness_threshold": config.open_water_openness_threshold,
            "open_water_seed_definition": (
                "Graph OPENNESS_TO_OCEAN_INDEX is at least the configured threshold; the "
                "index is mean directional fetch divided by maximum fetch across 16 bearings."
            ),
            "open_water_seed_count": int(len(open_seeds)),
            "graph_openness_max": float(np.max(graph_openness)),
            "source_warning": (
                "Null distance means no cell in the connected graph component met the configured "
                "open-water threshold; it is not encoded as zero or infinity."
            ),
        },
    )
    publisher.publish_manifest(
        config.output_path.parent / "exposure_and_enclosure_manifest.json",
        manifest,
    )
    LOGGER.info("Saved resolution-8 exposure and enclosure: %s", config.output_path)
    return config.output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(build_exposure_and_enclosure(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
