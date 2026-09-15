"""Build resolution-8 shoreline-proximity features from canonical water geometry.

The three exported metrics have deliberately different interpretations:

* ``SHORELINE_DISTANCE_M`` is projected Euclidean distance from the H3 center to
  the nearest boundary of the configured land polygons.
* ``WATER_NETWORK_DISTANCE_M`` is the shortest path from the cell to that
  boundary over adjacent non-land H3 centers. It cannot jump across cells whose
  centers are classified as land.
* ``OPEN_OCEAN_INDEX`` is mean directional water fetch, normalized to [0, 1],
  over evenly spaced bearings and a configured maximum fetch radius.
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
from shapely import STRtree, points
from shapely.geometry import LinearRing, LineString, MultiLineString, box

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
from seascape.utils.spatial import project_h3_centers as _cell_centers

LOGGER = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "H3_INDEX",
    "SHORELINE_DISTANCE_M",
    "WATER_NETWORK_DISTANCE_M",
    "OPEN_OCEAN_INDEX",
    "WATER_COMPONENT_ID",
    "NETWORK_CONNECTOR_METHOD",
    "NETWORK_CONNECTOR_DISTANCE_M",
    "NETWORK_DISTANCE_QC_REASON",
]


@dataclass(frozen=True)
class ShorelineProximityConfig:
    """Resolved inputs and parameters for shoreline-proximity processing."""

    bbox: dict[str, float]
    h3_resolution: int
    water_polygon_path: Path
    land_polygon_path: Path
    output_path: Path
    projected_crs: str
    network_context_buffer_km: float
    shoreline_seed_distance_m: float
    open_ocean_radius_km: float
    open_ocean_bearings: int


def load_shoreline_proximity_config(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> ShorelineProximityConfig:
    """Load and validate the shoreline-proximity configuration."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("shoreline_proximity"), "shoreline_proximity")
    processing = _mapping(section.get("processing"), "shoreline_proximity.processing")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("shoreline_proximity.processing.h3_resolution must be 8.")
    network_context_buffer_km = float(processing.get("network_context_buffer_km", 35.0))
    shoreline_seed_distance_m = float(processing.get("shoreline_seed_distance_m", 650.0))
    open_ocean_radius_km = float(processing.get("open_ocean_radius_km", 25.0))
    open_ocean_bearings = int(processing.get("open_ocean_bearings", 16))
    if network_context_buffer_km <= 0.0:
        raise ValueError("network_context_buffer_km must be positive.")
    if shoreline_seed_distance_m <= 0.0:
        raise ValueError("shoreline_seed_distance_m must be positive.")
    if open_ocean_radius_km <= 0.0:
        raise ValueError("open_ocean_radius_km must be positive.")
    if open_ocean_bearings < 4:
        raise ValueError("open_ocean_bearings must be at least 4.")
    return ShorelineProximityConfig(
        bbox=bbox_from_config(section),
        h3_resolution=resolution,
        water_polygon_path=_resolve(processing["water_polygon_path"], base_dir),
        land_polygon_path=_resolve(processing["land_polygon_path"], base_dir),
        output_path=_resolve(processing["processed_path"], base_dir),
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        network_context_buffer_km=network_context_buffer_km,
        shoreline_seed_distance_m=shoreline_seed_distance_m,
        open_ocean_radius_km=open_ocean_radius_km,
        open_ocean_bearings=open_ocean_bearings,
    )


def _spatial_support(config: ShorelineProximityConfig):
    """Return canonical target water plus contextual land and physical shoreline."""

    import geopandas as gpd

    if not config.water_polygon_path.exists():
        raise FileNotFoundError(f"Canonical water geometry not found: {config.water_polygon_path}")
    if not config.land_polygon_path.exists():
        raise FileNotFoundError(f"Land polygons not found: {config.land_polygon_path}")
    water = gpd.read_parquet(config.water_polygon_path)
    if water.crs is None:
        raise ValueError(f"Water geometry has no CRS: {config.water_polygon_path}")
    water = water.to_crs("EPSG:4326")
    if config.land_polygon_path.suffix.lower() in {".parquet", ".geoparquet"}:
        land = gpd.read_parquet(config.land_polygon_path)
    else:
        land = gpd.read_file(config.land_polygon_path)
    if land.crs is None:
        raise ValueError(f"Land polygons have no CRS: {config.land_polygon_path}")
    land = land.to_crs("EPSG:4326")
    context_km = max(
        config.network_context_buffer_km,
        config.open_ocean_radius_km + 2.0,
    )
    target_box = box(
        config.bbox["min_lon"],
        config.bbox["min_lat"],
        config.bbox["max_lon"],
        config.bbox["max_lat"],
    )
    context_box = _expanded_bbox(config.bbox, context_km)
    # The second guard prevents the context-clip edge from becoming shoreline.
    union_guard_box = _expanded_bbox(config.bbox, context_km + 10.0)
    target_water = safe_polygonal_union(water, clip_geometry=target_box)
    context_water = safe_polygonal_union(water, clip_geometry=context_box)
    guarded_land = safe_polygonal_union(land, clip_geometry=union_guard_box)
    context_land = normalize_polygonal_geometry(guarded_land.intersection(context_box))
    shoreline = guarded_land.boundary.intersection(context_box)
    if shoreline.is_empty:
        raise ValueError("No shoreline boundary intersects the configured analysis context.")
    return target_water, context_water, context_box, context_land, shoreline


def _line_parts(geometry: Any) -> list[LineString | LinearRing]:
    if isinstance(geometry, (LineString, LinearRing)):
        return [geometry] if not geometry.is_empty else []
    if isinstance(geometry, MultiLineString) or hasattr(geometry, "geoms"):
        return [part for value in geometry.geoms for part in _line_parts(value)]
    return []


def _shoreline_distances(
    shoreline: Any,
    x_values: np.ndarray,
    y_values: np.ndarray,
    projected_crs: str,
) -> np.ndarray:
    import geopandas as gpd

    projected = gpd.GeoSeries([shoreline], crs="EPSG:4326").to_crs(projected_crs).iloc[0]
    parts = _line_parts(projected)
    if not parts:
        raise ValueError("Projected shoreline contains no line geometry.")
    tree = STRtree(parts)
    query_points = points(x_values, y_values)
    indices, distances = tree.query_nearest(
        query_points,
        all_matches=False,
        return_distance=True,
    )
    output = np.full(len(query_points), np.nan, dtype="float64")
    output[np.asarray(indices[0], dtype=int)] = np.asarray(distances, dtype="float64")
    if not np.isfinite(output).all():
        raise ValueError("Nearest-shoreline search did not return every H3 center.")
    return output


def _open_ocean_indices(
    cells: list[str],
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    water_geometry: Any,
    *,
    radius_km: float,
    bearing_count: int,
) -> np.ndarray:
    """Return mean normalized uninterrupted water fetch over radial bearings."""

    bearings = np.linspace(0.0, 360.0, bearing_count, endpoint=False)
    radius_m = float(radius_km) * 1_000.0
    output = np.empty(len(cells), dtype="float64")
    for index, (cell, latitude, longitude) in enumerate(
        zip(cells, latitudes, longitudes, strict=True)
    ):
        fractions = [
            directional_water_fraction(
                float(longitude),
                float(latitude),
                float(bearing),
                radius_m,
                water_geometry,
            )
            for bearing in bearings
        ]
        output[index] = float(np.mean(fractions))
        if (index + 1) % 5_000 == 0:
            LOGGER.info("Calculated open-ocean index for %d/%d cells", index + 1, len(cells))
    return np.clip(output, 0.0, 1.0)


def build_shoreline_proximity(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> Path:
    """Build and save the configured resolution-8 shoreline-proximity product."""

    import h3

    config = load_shoreline_proximity_config(config_path)
    target_water, context_water, context_box, context_land, shoreline = _spatial_support(config)
    target_support = load_model_area_support(config.h3_resolution, config_path)
    target_cells = target_support["H3_INDEX"].astype(str).tolist()
    if not target_cells:
        raise ValueError("No water-supported H3 cells overlap the configured model area.")
    if any(h3.get_resolution(cell) != config.h3_resolution for cell in target_cells):
        raise ValueError("Target water support contains an unexpected H3 resolution.")
    target_lat, target_lon, target_x, target_y = _cell_centers(target_cells, config.projected_crs)
    target_shoreline_distance = _shoreline_distances(
        shoreline,
        target_x,
        target_y,
        config.projected_crs,
    )
    graph = load_water_graph(
        config.h3_resolution,
        config_path,
        bbox=tuple(context_box.bounds),
    )
    context_cells = graph.cells.astype(str).tolist()
    graph_support = graph.support.set_index("H3_INDEX").loc[context_cells]
    context_lon = graph_support["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(dtype="float64")
    context_lat = graph_support["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(dtype="float64")
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", config.projected_crs, always_xy=True)
    context_x, context_y = transformer.transform(context_lon, context_lat)
    context_x = np.asarray(context_x, dtype="float64")
    context_y = np.asarray(context_y, dtype="float64")
    LOGGER.info(
        "Shoreline proximity support: %d target cells, %d non-land context cells",
        len(target_cells),
        len(context_cells),
    )
    context_shoreline_distance = _shoreline_distances(
        shoreline,
        context_x,
        context_y,
        config.projected_crs,
    )
    seed_positions = np.flatnonzero(context_shoreline_distance <= config.shoreline_seed_distance_m)
    context_network_distance, _owners = multi_source_shortest_paths(
        graph,
        [
            (context_cells[index], float(context_shoreline_distance[index]), int(index))
            for index in seed_positions
        ],
    )
    mapped, connector_distance, mapping_reasons = target_graph_mapping(graph, target_cells)
    target_network_distance = np.full(len(target_cells), np.nan, dtype="float64")
    mapped_to_graph = mapped >= 0
    reachable = np.zeros(len(target_cells), dtype=bool)
    reachable[mapped_to_graph] = np.isfinite(
        context_network_distance[mapped[mapped_to_graph]]
    ) & np.isfinite(connector_distance[mapped_to_graph])
    target_network_distance[reachable] = (
        context_network_distance[mapped[reachable]] + connector_distance[reachable]
    )
    target_network_distance[reachable] = np.maximum(
        target_network_distance[reachable], target_shoreline_distance[reachable]
    )
    missing_reason = ~reachable & pd.isna(mapping_reasons)
    mapping_reasons[missing_reason & mapped_to_graph] = "no_reachable_shoreline_seed_in_component"
    mapping_reasons[missing_reason & ~mapped_to_graph] = "unreachable_from_shoreline_seed"
    target_open_ocean = _open_ocean_indices(
        target_cells,
        target_lat,
        target_lon,
        context_water,
        radius_km=config.open_ocean_radius_km,
        bearing_count=config.open_ocean_bearings,
    )

    target_lineage = target_support.set_index("H3_INDEX").loc[target_cells]
    output = (
        pl.DataFrame(
            {
                "H3_INDEX": target_cells,
                "SHORELINE_DISTANCE_M": target_shoreline_distance,
                "WATER_NETWORK_DISTANCE_M": target_network_distance,
                "OPEN_OCEAN_INDEX": target_open_ocean,
                "WATER_COMPONENT_ID": nullable_string_values(target_lineage["WATER_COMPONENT_ID"]),
                "NETWORK_CONNECTOR_METHOD": nullable_string_values(
                    target_lineage["CONNECTOR_METHOD"]
                ),
                "NETWORK_CONNECTOR_DISTANCE_M": target_lineage["CONNECTOR_DISTANCE_M"].tolist(),
                "NETWORK_DISTANCE_QC_REASON": nullable_string_values(mapping_reasons),
            }
        )
        .with_columns(
            pl.col("H3_INDEX").cast(pl.String),
            pl.col("SHORELINE_DISTANCE_M").cast(pl.Float64),
            pl.col("WATER_NETWORK_DISTANCE_M").cast(pl.Float64),
            pl.col("OPEN_OCEAN_INDEX").cast(pl.Float64),
            pl.col("WATER_COMPONENT_ID").cast(pl.String),
            pl.col("NETWORK_CONNECTOR_METHOD").cast(pl.String),
            pl.col("NETWORK_CONNECTOR_DISTANCE_M").cast(pl.Float64),
            pl.col("NETWORK_DISTANCE_QC_REASON").cast(pl.String),
        )
        .select(OUTPUT_COLUMNS)
        .sort("H3_INDEX")
    )
    if output["H3_INDEX"].n_unique() != output.height:
        raise ValueError("Shoreline-proximity output contains duplicate H3_INDEX values.")
    numeric = output.select(pl.selectors.numeric()).to_numpy()
    if np.isinf(numeric).any():
        raise ValueError("Shoreline-proximity output contains infinite values.")
    publisher = stage_parquet_family(
        config.output_path.parent,
        ((output, config.output_path),),
    )
    network = load_water_network_config(config_path)
    manifest = build_manifest(
        dataset_family="environment.seascape.shoreline_proximity",
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
                "text": "Natural Earth; derived shoreline metrics by Seascape Toolkit",
                "license": "Public domain",
            }
        ],
        source_completeness="complete",
        metadata={
            "distance_semantics": (
                "Straight shoreline distance is geometric; network distance follows the "
                "canonical water-passable graph; openness retains directional ray casting."
            )
        },
    )
    publisher.publish_manifest(
        config.output_path.parent / "shoreline_proximity_manifest.json",
        manifest,
    )
    LOGGER.info("Saved resolution-8 shoreline proximity: %s", config.output_path)
    return config.output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(build_shoreline_proximity(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
