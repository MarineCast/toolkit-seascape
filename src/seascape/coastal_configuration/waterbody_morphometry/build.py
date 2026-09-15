"""Build resolution-8 waterbody morphometry from land, water, and bathymetry.

Land polygons define barriers. The territorial-water polygon selects the
canonical output universe. Whole-component area and perimeter are deliberately
not exported because the Pacific/Salish Sea component intersects the analysis
boundary; instead, area, perimeter, compactness, and branching are measured on
a config-defined local water-network neighborhood.
"""

from __future__ import annotations

import argparse
import logging
import math
from collections import deque
from collections.abc import Mapping
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
    "LOCAL_WATERBODY_WIDTH_M",
    "WATERBODY_WIDTH_MEAN_M",
    "WATERBODY_WIDTH_MEDIAN_M",
    "WATERBODY_WIDTH_STD_M",
    "WATERBODY_WIDTH_CENSORED_FRACTION",
    "DISTANCE_TO_OPPOSITE_SHORE_M",
    "OPPOSITE_SHORE_CENSORED",
    "CONSTRICTION_INDEX",
    "LOCAL_WATERSPACE_AREA_KM2",
    "LOCAL_WATERSPACE_PERIMETER_KM",
    "LOCAL_WATERSPACE_COMPACTNESS",
    "LOCAL_WATERSPACE_BRANCH_COUNT",
    "DISTANCE_TO_CONSTRICTED_PASSAGE_M",
    "DISTANCE_TO_SILL_CANDIDATE_M",
    "WATER_COMPONENT_ID",
    "NETWORK_CONNECTOR_METHOD",
    "NETWORK_CONNECTOR_DISTANCE_M",
    "NETWORK_DISTANCE_QC_REASON",
]


@dataclass(frozen=True)
class WaterbodyMorphometryConfig:
    """Resolved configuration for static waterbody morphometry."""

    bbox: dict[str, float]
    h3_resolution: int
    water_polygon_path: Path
    land_polygon_path: Path
    bathymetry_path: Path
    output_path: Path
    projected_crs: str
    maximum_shore_search_km: float
    bearing_count: int
    network_context_buffer_km: float
    constriction_neighborhood_rings: int
    narrows_max_width_km: float
    narrows_constriction_threshold: float
    local_water_space_radius_rings: int
    sill_neighborhood_rings: int
    sill_minimum_neighbors: int
    sill_min_relief_m: float
    sill_max_width_km: float
    sill_min_constriction: float


def load_waterbody_morphometry_config(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> WaterbodyMorphometryConfig:
    """Load and validate waterbody-morphometry settings."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("waterbody_morphometry"), "waterbody_morphometry")
    processing = _mapping(
        section.get("processing"),
        "waterbody_morphometry.processing",
    )
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("waterbody_morphometry.processing.h3_resolution must be 8.")
    maximum_search_km = float(processing.get("maximum_shore_search_km", 50.0))
    bearing_count = int(processing.get("bearing_count", len(BEARING_LABELS)))
    context_buffer_km = float(processing.get("network_context_buffer_km", 60.0))
    constriction_rings = int(processing.get("constriction_neighborhood_rings", 5))
    narrows_width_km = float(processing.get("narrows_max_width_km", 5.0))
    narrows_threshold = float(processing.get("narrows_constriction_threshold", 0.25))
    local_radius = int(processing.get("local_water_space_radius_rings", 8))
    sill_rings = int(processing.get("sill_neighborhood_rings", 4))
    sill_minimum_neighbors = int(processing.get("sill_minimum_neighbors", 6))
    sill_min_relief_m = float(processing.get("sill_min_relief_m", 10.0))
    sill_max_width_km = float(processing.get("sill_max_width_km", 15.0))
    sill_min_constriction = float(processing.get("sill_min_constriction", 0.05))
    if maximum_search_km <= 0.0:
        raise ValueError("maximum_shore_search_km must be positive.")
    if bearing_count != len(BEARING_LABELS):
        raise ValueError(
            f"bearing_count must be {len(BEARING_LABELS)} for the named bearing schema."
        )
    if context_buffer_km <= maximum_search_km:
        raise ValueError("network_context_buffer_km must exceed maximum_shore_search_km.")
    if constriction_rings < 1 or local_radius < 1 or sill_rings < 1:
        raise ValueError("All H3 neighborhood ring settings must be positive.")
    if narrows_width_km <= 0.0 or sill_max_width_km <= 0.0:
        raise ValueError("Narrows and sill maximum widths must be positive.")
    if not 0.0 <= narrows_threshold <= 1.0:
        raise ValueError("narrows_constriction_threshold must be in [0, 1].")
    if not 0.0 <= sill_min_constriction <= 1.0:
        raise ValueError("sill_min_constriction must be in [0, 1].")
    if sill_minimum_neighbors < 1 or sill_min_relief_m <= 0.0:
        raise ValueError("Sill neighbor and relief settings must be positive.")
    return WaterbodyMorphometryConfig(
        bbox=bbox_from_config(section),
        h3_resolution=resolution,
        water_polygon_path=_resolve(processing["water_polygon_path"], base_dir),
        land_polygon_path=_resolve(processing["land_polygon_path"], base_dir),
        bathymetry_path=_resolve(processing["bathymetry_path"], base_dir),
        output_path=_resolve(processing["processed_path"], base_dir),
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        maximum_shore_search_km=maximum_search_km,
        bearing_count=bearing_count,
        network_context_buffer_km=context_buffer_km,
        constriction_neighborhood_rings=constriction_rings,
        narrows_max_width_km=narrows_width_km,
        narrows_constriction_threshold=narrows_threshold,
        local_water_space_radius_rings=local_radius,
        sill_neighborhood_rings=sill_rings,
        sill_minimum_neighbors=sill_minimum_neighbors,
        sill_min_relief_m=sill_min_relief_m,
        sill_max_width_km=sill_max_width_km,
        sill_min_constriction=sill_min_constriction,
    )


def _spatial_support(config: WaterbodyMorphometryConfig):
    water = _read_polygon_layer(config.water_polygon_path)
    land = _read_polygon_layer(config.land_polygon_path)
    target_box = box(
        config.bbox["min_lon"],
        config.bbox["min_lat"],
        config.bbox["max_lon"],
        config.bbox["max_lat"],
    )
    graph_box = _expanded_bbox(config.bbox, config.network_context_buffer_km)
    fetch_mask_km = config.network_context_buffer_km + config.maximum_shore_search_km + 2.0
    fetch_mask_box = _expanded_bbox(config.bbox, fetch_mask_km)
    land_guard_box = _expanded_bbox(config.bbox, fetch_mask_km + 10.0)
    target_water = safe_polygonal_union(water, clip_geometry=target_box)
    fetch_mask_water = safe_polygonal_union(water, clip_geometry=fetch_mask_box)
    guarded_land = safe_polygonal_union(land, clip_geometry=land_guard_box)
    fetch_mask_land = normalize_polygonal_geometry(guarded_land.intersection(fetch_mask_box))
    return target_water, graph_box, fetch_mask_box, fetch_mask_land, fetch_mask_water


def _directional_shore_distances(
    cells: list[str],
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    water_geometry: Any,
    maximum_search_km: float,
) -> np.ndarray:
    """Measure uninterrupted center-to-shore distance on 16 bearings."""

    bearings = np.linspace(0.0, 360.0, len(BEARING_LABELS), endpoint=False)
    maximum_search_m = float(maximum_search_km) * 1_000.0
    output = np.empty((len(cells), len(BEARING_LABELS)), dtype="float64")
    for index, (_cell, latitude, longitude) in enumerate(
        zip(cells, latitudes, longitudes, strict=True)
    ):
        for bearing_index, bearing in enumerate(bearings):
            output[index, bearing_index] = maximum_search_m * directional_water_fraction(
                float(longitude),
                float(latitude),
                float(bearing),
                maximum_search_m,
                water_geometry,
            )
        if (index + 1) % 10_000 == 0:
            LOGGER.info(
                "Calculated directional shore distances for %d/%d cells",
                index + 1,
                len(cells),
            )
    return np.clip(output, 0.0, maximum_search_m)


def _width_metrics(
    rays: np.ndarray,
    maximum_search_m: float,
) -> dict[str, np.ndarray]:
    axis_widths = rays[:, :8] + rays[:, 8:]
    axis_censored = (rays[:, :8] >= maximum_search_m) | (rays[:, 8:] >= maximum_search_m)
    nearest_bearing = np.argmin(rays, axis=1)
    opposite_bearing = (nearest_bearing + 8) % len(BEARING_LABELS)
    rows = np.arange(len(rays))
    narrowest_axis = np.argmin(axis_widths, axis=1)
    opposite_distance = rays[rows, opposite_bearing]
    return {
        "LOCAL_WATERBODY_WIDTH_M": axis_widths.min(axis=1),
        "_LOCAL_WATERBODY_WIDTH_CENSORED": axis_censored[
            rows,
            narrowest_axis,
        ].astype("float64"),
        "WATERBODY_WIDTH_MEAN_M": axis_widths.mean(axis=1),
        "WATERBODY_WIDTH_MEDIAN_M": np.median(axis_widths, axis=1),
        "WATERBODY_WIDTH_STD_M": axis_widths.std(axis=1),
        "WATERBODY_WIDTH_CENSORED_FRACTION": axis_censored.mean(axis=1),
        "DISTANCE_TO_OPPOSITE_SHORE_M": opposite_distance,
        "OPPOSITE_SHORE_CENSORED": (opposite_distance >= maximum_search_m).astype("float64"),
    }


def _constriction_indices(
    widths: np.ndarray,
    adjacency: list[tuple[int, ...]],
    neighborhood_rings: int,
) -> np.ndarray:
    output = np.zeros(len(adjacency), dtype="float64")
    for index in range(len(adjacency)):
        neighborhood = _bounded_adjacency_positions(index, adjacency, neighborhood_rings)
        reference = float(np.median(widths[neighborhood]))
        if reference > 0.0:
            output[index] = max(0.0, 1.0 - float(widths[index]) / reference)
    return np.clip(output, 0.0, 1.0)


def _bounded_adjacency_positions(
    source: int,
    adjacency: list[tuple[int, ...]],
    maximum_hops: int,
) -> list[int]:
    """Return canonical water-graph positions through an inclusive hop bound."""

    distances = {int(source): 0}
    queue = deque([int(source)])
    while queue:
        current = queue.popleft()
        hops = distances[current]
        if hops >= maximum_hops:
            continue
        for neighbor in adjacency[current]:
            if neighbor not in distances:
                distances[neighbor] = hops + 1
                queue.append(neighbor)
    return sorted(distances)


def _local_water_space_metrics(
    source_indices: np.ndarray,
    adjacency: list[tuple[int, ...]],
    cell_areas_km2: np.ndarray,
    edge_length_km: float,
    radius_rings: int,
) -> dict[str, np.ndarray]:
    unique_sources = np.unique(source_indices[source_indices >= 0])
    graph_area = np.full(len(adjacency), np.nan, dtype="float64")
    graph_perimeter = np.full(len(adjacency), np.nan, dtype="float64")
    graph_compactness = np.full(len(adjacency), np.nan, dtype="float64")
    graph_branches = np.full(len(adjacency), np.nan, dtype="float64")
    for count, source in enumerate(unique_sources, start=1):
        distances = {int(source): 0}
        queue = deque([int(source)])
        while queue:
            index = queue.popleft()
            step = distances[index]
            if step >= radius_rings:
                continue
            for neighbor in adjacency[index]:
                if neighbor not in distances:
                    distances[neighbor] = step + 1
                    queue.append(neighbor)
        reachable = set(distances)
        boundary_edges = sum(
            6 - sum(neighbor in reachable for neighbor in adjacency[index]) for index in reachable
        )
        area = float(cell_areas_km2[list(reachable)].sum())
        perimeter = float(boundary_edges) * edge_length_km
        compactness = (
            min(1.0, 4.0 * math.pi * area / (perimeter * perimeter)) if perimeter > 0.0 else 0.0
        )
        outer = {index for index, step in distances.items() if step == radius_rings}
        branches = 0
        remaining = set(outer)
        while remaining:
            branches += 1
            branch_queue = [remaining.pop()]
            while branch_queue:
                index = branch_queue.pop()
                connected = [neighbor for neighbor in adjacency[index] if neighbor in remaining]
                for neighbor in connected:
                    remaining.remove(neighbor)
                    branch_queue.append(neighbor)
        graph_area[source] = area
        graph_perimeter[source] = perimeter
        graph_compactness[source] = compactness
        graph_branches[source] = float(branches)
        if count % 5_000 == 0:
            LOGGER.info(
                "Calculated local water-space morphometry for %d/%d source cells",
                count,
                len(unique_sources),
            )
    valid = source_indices >= 0
    output: dict[str, np.ndarray] = {}
    for name, values in (
        ("LOCAL_WATERSPACE_AREA_KM2", graph_area),
        ("LOCAL_WATERSPACE_PERIMETER_KM", graph_perimeter),
        ("LOCAL_WATERSPACE_COMPACTNESS", graph_compactness),
        ("LOCAL_WATERSPACE_BRANCH_COUNT", graph_branches),
    ):
        target = np.full(len(source_indices), np.nan, dtype="float64")
        target[valid] = values[source_indices[valid]]
        output[name] = target
    return output


def _sill_candidates(
    config: WaterbodyMorphometryConfig,
    graph_cells: list[str],
    adjacency: list[tuple[int, ...]],
    local_width: np.ndarray,
    constriction: np.ndarray,
) -> np.ndarray:
    if not config.bathymetry_path.exists():
        raise FileNotFoundError(f"Bathymetry source not found: {config.bathymetry_path}")
    bathymetry = pl.read_parquet(
        config.bathymetry_path,
        columns=["H3_INDEX", "BATHYMETRY"],
    ).drop_nulls()
    depths = np.full(len(graph_cells), np.nan, dtype="float64")
    cell_index = {cell: index for index, cell in enumerate(graph_cells)}
    for cell, depth in bathymetry.iter_rows():
        index = cell_index.get(str(cell))
        if index is not None and math.isfinite(float(depth)):
            depths[index] = float(depth)
    candidates: list[int] = []
    for index in np.flatnonzero(np.isfinite(depths)):
        neighbors = [
            neighbor
            for neighbor in _bounded_adjacency_positions(
                int(index), adjacency, config.sill_neighborhood_rings
            )
            if neighbor != index and math.isfinite(depths[neighbor])
        ]
        if len(neighbors) < config.sill_minimum_neighbors:
            continue
        shallower_by = float(np.median(depths[neighbors]) - depths[index])
        if (
            shallower_by >= config.sill_min_relief_m
            and local_width[index] <= config.sill_max_width_km * 1_000.0
            and constriction[index] >= config.sill_min_constriction
        ):
            candidates.append(int(index))
    return np.asarray(candidates, dtype=int)


def _build_output(
    target_cells: list[str],
    width_metrics: Mapping[str, np.ndarray],
    constriction: np.ndarray,
    local_metrics: Mapping[str, np.ndarray],
    distance_to_narrows: np.ndarray,
    distance_to_sill: np.ndarray,
    lineage: pd.DataFrame,
    qc_reasons: np.ndarray,
) -> pl.DataFrame:
    data: dict[str, Any] = {"H3_INDEX": target_cells}
    data.update(width_metrics)
    data["CONSTRICTION_INDEX"] = constriction
    data.update(local_metrics)
    data["DISTANCE_TO_CONSTRICTED_PASSAGE_M"] = distance_to_narrows
    data["DISTANCE_TO_SILL_CANDIDATE_M"] = distance_to_sill
    data["WATER_COMPONENT_ID"] = nullable_string_values(lineage["WATER_COMPONENT_ID"])
    data["NETWORK_CONNECTOR_METHOD"] = nullable_string_values(lineage["CONNECTOR_METHOD"])
    data["NETWORK_CONNECTOR_DISTANCE_M"] = lineage["CONNECTOR_DISTANCE_M"].tolist()
    data["NETWORK_DISTANCE_QC_REASON"] = nullable_string_values(qc_reasons)
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


def build_waterbody_morphometry(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> Path:
    """Build and save the configured resolution-8 morphometry product."""

    import h3

    config = load_waterbody_morphometry_config(config_path)
    target_water, graph_box, fetch_mask_box, fetch_mask_land, fetch_mask_water = _spatial_support(
        config
    )
    target_support = load_model_area_support(config.h3_resolution, config_path)
    target_cells = target_support["H3_INDEX"].astype(str).tolist()
    if not target_cells:
        raise ValueError("No target H3 cells overlap the configured water support.")
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
    fetch_mask_cells = (
        fetch_support.loc[fetch_support["WATER_COMPONENT_ID"].notna(), "H3_INDEX"]
        .astype(str)
        .tolist()
    )
    LOGGER.info(
        "Waterbody support: %d target cells, %d graph cells, %d fetch-mask cells",
        len(target_cells),
        len(graph_cells),
        len(fetch_mask_cells),
    )
    rays = _directional_shore_distances(
        graph_cells,
        graph_lat,
        graph_lon,
        fetch_mask_water,
        config.maximum_shore_search_km,
    )
    graph_width_metrics = _width_metrics(
        rays,
        config.maximum_shore_search_km * 1_000.0,
    )
    adjacency = [
        tuple(int(value) for value in graph.neighbors_of(index)[0])
        for index in range(len(graph_cells))
    ]
    graph_constriction = _constriction_indices(
        graph_width_metrics["LOCAL_WATERBODY_WIDTH_M"],
        adjacency,
        config.constriction_neighborhood_rings,
    )
    graph_constriction[graph_width_metrics["_LOCAL_WATERBODY_WIDTH_CENSORED"] > 0.5] = 0.0
    narrows_candidates = np.flatnonzero(
        (graph_width_metrics["LOCAL_WATERBODY_WIDTH_M"] <= config.narrows_max_width_km * 1_000.0)
        & (graph_constriction >= config.narrows_constriction_threshold)
        & (graph_width_metrics["_LOCAL_WATERBODY_WIDTH_CENSORED"] < 0.5)
    )
    sill_candidates = _sill_candidates(
        config,
        graph_cells,
        adjacency,
        graph_width_metrics["LOCAL_WATERBODY_WIDTH_M"],
        graph_constriction,
    )
    LOGGER.info(
        "Identified %d narrows candidates and %d bathymetric sill candidates",
        len(narrows_candidates),
        len(sill_candidates),
    )
    graph_distance_to_narrows = np.full(len(graph_cells), np.inf, dtype="float64")
    if len(narrows_candidates):
        graph_distance_to_narrows, _narrows_owner = multi_source_shortest_paths(
            graph,
            [(graph_cells[index], 0.0, int(index)) for index in narrows_candidates],
        )
    graph_distance_to_sill = np.full(len(graph_cells), np.inf, dtype="float64")
    if len(sill_candidates):
        graph_distance_to_sill, _sill_owner = multi_source_shortest_paths(
            graph,
            [(graph_cells[index], 0.0, int(index)) for index in sill_candidates],
        )
    source_indices, connector_distances, qc_reasons = target_graph_mapping(graph, target_cells)
    cell_areas_km2 = graph_lineage["CELL_AREA_M2"].to_numpy(dtype="float64") / 1_000_000.0
    local_metrics = _local_water_space_metrics(
        source_indices,
        adjacency,
        cell_areas_km2,
        float(h3.average_hexagon_edge_length(config.h3_resolution, unit="km")),
        config.local_water_space_radius_rings,
    )
    valid = source_indices >= 0
    target_width_metrics: dict[str, np.ndarray] = {}
    for column, values in graph_width_metrics.items():
        if column.startswith("_"):
            continue
        target = np.full(len(target_cells), np.nan, dtype="float64")
        target[valid] = values[source_indices[valid]]
        target_width_metrics[column] = target
    target_constriction = np.full(len(target_cells), np.nan, dtype="float64")
    target_constriction[valid] = graph_constriction[source_indices[valid]]
    distance_to_narrows = np.full(len(target_cells), np.nan, dtype="float64")
    distance_to_sill = np.full(len(target_cells), np.nan, dtype="float64")
    narrows_reachable = valid & np.isfinite(
        graph_distance_to_narrows[np.maximum(source_indices, 0)]
    )
    sill_reachable = valid & np.isfinite(graph_distance_to_sill[np.maximum(source_indices, 0)])
    distance_to_narrows[narrows_reachable] = (
        graph_distance_to_narrows[source_indices[narrows_reachable]]
        + connector_distances[narrows_reachable]
    )
    distance_to_sill[sill_reachable] = (
        graph_distance_to_sill[source_indices[sill_reachable]] + connector_distances[sill_reachable]
    )
    qc_reasons[~valid & pd.isna(qc_reasons)] = "unreachable_in_canonical_water_graph"
    lineage = target_support.set_index("H3_INDEX").loc[target_cells]
    output = _build_output(
        target_cells,
        target_width_metrics,
        target_constriction,
        local_metrics,
        distance_to_narrows,
        distance_to_sill,
        lineage,
        qc_reasons,
    )
    if output["H3_INDEX"].n_unique() != output.height:
        raise ValueError("Waterbody-morphometry output contains duplicate H3_INDEX values.")
    numeric = output.select(pl.selectors.numeric()).to_numpy()
    if np.isinf(numeric).any():
        raise ValueError("Waterbody-morphometry output contains infinite values.")
    publisher = stage_parquet_family(
        config.output_path.parent,
        ((output, config.output_path),),
    )
    network = load_water_network_config(config_path)
    manifest = build_manifest(
        dataset_family="environment.seascape.waterbody_morphometry",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "Natural Earth water geometry and GEBCO bathymetry",
                "license": "Natural Earth public domain; GEBCO terms of use",
                "observation_period": "compiled and generalized sources; see upstream manifests",
            }
        ],
        upstream_artifacts=[
            {"path": str(path), "checksum": checksum_artifact(path)}
            for path in (
                config.water_polygon_path,
                config.land_polygon_path,
                config.bathymetry_path,
                network.manifest_path,
            )
        ],
        attribution=[
            {
                "text": "Natural Earth and GEBCO Compilation Group; derived metrics by Seascape Toolkit",
                "license": "Natural Earth public domain; GEBCO terms of use",
            }
        ],
        source_completeness="complete",
        metadata={
            "neighborhood_semantics": "canonical water-passable graph neighborhoods",
            "censoring_contract": (
                "Directional width censoring and unavailable graph distances remain explicit."
            ),
        },
    )
    publisher.publish_manifest(
        config.output_path.parent / "waterbody_morphometry_manifest.json",
        manifest,
    )
    LOGGER.info("Saved resolution-8 waterbody morphometry: %s", config.output_path)
    return config.output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(build_waterbody_morphometry(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
