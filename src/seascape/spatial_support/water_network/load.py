"""Strict loaders and array-backed algorithms for canonical water graphs."""

from __future__ import annotations

import heapq
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Geod, Transformer
from scipy.spatial import cKDTree
from shapely import covers, points
from shapely.geometry import Point, box
from shapely.ops import nearest_points
from shapely.ops import transform as transform_geometry
from shapely.prepared import prep

from seascape.core.config.paths import project_root
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.h3 import cell_to_parent

from .config import DEFAULT_CONFIG_PATH, WaterNetworkConfig, load_water_network_config
from .graph import WaterGraph
from .validation import (
    validate_edges,
    validate_manifest_payload,
    validate_neighborhoods,
    validate_support,
)


def nullable_string_values(values: Any) -> list[str | None]:
    """Normalize pandas/object string values for strict Arrow/Polars construction."""

    return [None if value is None or pd.isna(value) else str(value) for value in values]


def _manifest(config: WaterNetworkConfig) -> dict[str, Any]:
    if not config.manifest_path.exists():
        raise FileNotFoundError(
            f"Canonical water-network manifest not found: {config.manifest_path}"
        )
    payload = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    metadata = payload["metadata"]
    if metadata["water_mask_version"] != config.water_mask_version:
        raise ValueError("Configured and manifested water-mask versions disagree.")
    if metadata["spatial_support_version"] != config.spatial_support_version:
        raise ValueError("Configured and manifested spatial-support versions disagree.")
    return payload


def _verify_artifact(path: Path, payload: dict[str, Any]) -> None:
    resolved = path.resolve()
    artifact_root = Path(os.environ.get("SEASCAPE_CANDIDATE_ROOT", project_root())).resolve()
    matches = [
        artifact
        for artifact in payload["artifacts"]
        if (
            Path(str(artifact["path"])).resolve()
            if Path(str(artifact["path"])).is_absolute()
            else (artifact_root / str(artifact["path"])).resolve()
        )
        == resolved
    ]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not identify exactly one artifact for {path}.")
    expected = str(matches[0]["checksum"])
    observed = checksum_path(path)
    if observed != expected:
        raise ValueError(
            f"Artifact checksum does not match canonical manifest: {path}; "
            f"expected {expected}, observed {observed}."
        )


def load_water_support(
    resolution: int,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    bbox_buffer_m: float = 0.0,
    component_id: str | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Load validated support, optionally filtered by representative-point bbox/component."""

    config = load_water_network_config(config_path)
    if resolution not in config.resolutions:
        raise ValueError(f"H3 r{resolution} is not a configured canonical water graph.")
    payload = _manifest(config)
    path = config.support_path(resolution)
    if not path.exists():
        raise FileNotFoundError(f"Canonical marine support not found: {path}")
    if verify_checksum:
        _verify_artifact(path, payload)
    frame = pd.read_parquet(path)
    validate_support(
        frame,
        resolution,
        water_mask_version=config.water_mask_version,
        spatial_support_version=config.spatial_support_version,
        area_tolerance_m2=config.area_tolerance_m2,
    )
    if bbox_buffer_m < 0.0:
        raise ValueError("bbox_buffer_m must be nonnegative.")
    if bbox is None and bbox_buffer_m:
        raise ValueError("bbox_buffer_m requires bbox.")
    if bbox is not None and bbox_buffer_m:
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
        buffered_aoi = transform_geometry(transformer.transform, box(*map(float, bbox))).buffer(
            float(bbox_buffer_m)
        )
        x_values, y_values = transformer.transform(
            frame["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(),
            frame["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(),
        )
        frame = frame.loc[np.asarray(covers(buffered_aoi, points(x_values, y_values)))]
    elif bbox is not None:
        min_lon, min_lat, max_lon, max_lat = map(float, bbox)
        frame = frame.loc[
            frame["REPRESENTATIVE_POINT_LONGITUDE"].between(min_lon, max_lon)
            & frame["REPRESENTATIVE_POINT_LATITUDE"].between(min_lat, max_lat)
        ]
    if component_id is not None:
        frame = frame.loc[frame["WATER_COMPONENT_ID"] == str(component_id)]
    return frame.sort_values("H3_INDEX").reset_index(drop=True)


def load_model_area_support(
    resolution: int,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Load the unfiltered canonical model support and verify R8-to-R6 hierarchy."""

    config = load_water_network_config(config_path)
    if resolution not in config.resolutions:
        raise ValueError(f"H3 r{resolution} is not configured for model support.")
    payload = _manifest(config)
    path = config.model_support_path(resolution)
    if not path.exists():
        raise FileNotFoundError(f"Canonical model-area support not found: {path}")
    if verify_checksum:
        _verify_artifact(path, payload)
    support = pd.read_parquet(path)
    validate_support(
        support,
        resolution,
        water_mask_version=config.water_mask_version,
        spatial_support_version=config.spatial_support_version,
        area_tolerance_m2=config.area_tolerance_m2,
    )
    if resolution == 6 and {6, 8}.issubset(config.resolutions):
        child_path = config.model_support_path(8)
        if not child_path.exists():
            raise FileNotFoundError(f"Canonical R8 model-area support not found: {child_path}")
        if verify_checksum:
            _verify_artifact(child_path, payload)
        children = pd.read_parquet(child_path, columns=["H3_INDEX"])
        expected = {cell_to_parent(str(cell), 6) for cell in children["H3_INDEX"].astype(str)}
        observed = set(support["H3_INDEX"].astype(str))
        if observed != expected:
            missing = sorted(expected.difference(observed))[:5]
            extra = sorted(observed.difference(expected))[:5]
            raise ValueError(
                "Canonical R6 support must be the exact parent union of canonical R8; "
                f"missing={missing}, extra={extra}."
            )
    return support.sort_values("H3_INDEX").reset_index(drop=True)


def load_water_neighborhoods(
    resolution: int,
    maximum_hops: int,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    source_cells: list[str] | tuple[str, ...] | None = None,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Load bounded water-passable neighborhoods through ``maximum_hops``."""

    config = load_water_network_config(config_path)
    if maximum_hops < 0 or maximum_hops > config.maximum_neighborhood_hops:
        raise ValueError(
            "maximum_hops must be between zero and the configured materialized bound "
            f"({config.maximum_neighborhood_hops})."
        )
    payload = _manifest(config)
    path = config.neighborhood_path(resolution)
    if not path.exists():
        raise FileNotFoundError(f"Canonical water neighborhoods not found: {path}")
    if verify_checksum:
        _verify_artifact(path, payload)
    frame = pd.read_parquet(path)
    support = load_model_area_support(
        resolution,
        config_path,
        verify_checksum=verify_checksum,
    )
    validate_neighborhoods(
        frame,
        support,
        resolution,
        maximum_hops=config.maximum_neighborhood_hops,
    )
    frame = frame.loc[frame["MINIMUM_HOP_COUNT"] <= maximum_hops]
    if source_cells is not None:
        selected = {str(cell) for cell in source_cells}
        unknown = selected.difference(support["H3_INDEX"].astype(str))
        if unknown:
            raise ValueError(
                f"Requested neighborhood sources are outside support: {sorted(unknown)[:5]}"
            )
        frame = frame.loc[frame["SOURCE_H3_INDEX"].astype(str).isin(selected)]
    return frame.sort_values(
        ["SOURCE_H3_INDEX", "MINIMUM_HOP_COUNT", "TARGET_H3_INDEX"]
    ).reset_index(drop=True)


def _csr(support: pd.DataFrame, edges: pd.DataFrame, resolution: int) -> WaterGraph:
    node_cells = sorted(
        set(edges["SOURCE_H3_INDEX"].astype(str)).union(edges["TARGET_H3_INDEX"].astype(str))
    )
    positions = {cell: index for index, cell in enumerate(node_cells)}
    adjacency: list[list[tuple[int, float]]] = [[] for _ in node_cells]
    for source, target, distance in edges[
        ["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "EDGE_DISTANCE_M"]
    ].itertuples(index=False):
        left = positions[str(source)]
        right = positions[str(target)]
        weight = float(distance)
        adjacency[left].append((right, weight))
        adjacency[right].append((left, weight))
    offsets = np.zeros(len(node_cells) + 1, dtype=np.int64)
    neighbor_values: list[int] = []
    weight_values: list[float] = []
    for index, values in enumerate(adjacency):
        values.sort(key=lambda item: node_cells[item[0]])
        neighbor_values.extend(item[0] for item in values)
        weight_values.extend(item[1] for item in values)
        offsets[index + 1] = len(neighbor_values)
    return WaterGraph(
        resolution=resolution,
        cells=np.asarray(node_cells, dtype=object),
        offsets=offsets,
        neighbors=np.asarray(neighbor_values, dtype=np.int64),
        weights_m=np.asarray(weight_values, dtype=np.float64),
        support=support,
        cell_to_position=positions,
        water_mask_version=str(support["WATER_MASK_VERSION"].iloc[0]),
        spatial_support_version=str(support["SPATIAL_SUPPORT_VERSION"].iloc[0]),
    )


def load_water_graph(
    resolution: int,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    bbox_buffer_m: float = 0.0,
    component_id: str | None = None,
    verify_checksum: bool = True,
) -> WaterGraph:
    """Load valid canonical edges and return deterministic symmetric CSR adjacency."""

    config = load_water_network_config(config_path)
    payload = _manifest(config)
    support = load_water_support(
        resolution,
        config_path,
        bbox=bbox,
        bbox_buffer_m=bbox_buffer_m,
        component_id=component_id,
        verify_checksum=verify_checksum,
    )
    path = config.edge_path(resolution)
    if not path.exists():
        raise FileNotFoundError(f"Canonical water edge table not found: {path}")
    if verify_checksum:
        _verify_artifact(path, payload)
    edges = pd.read_parquet(path)
    full_support = (
        support
        if bbox is None and component_id is None
        else load_water_support(resolution, config_path, verify_checksum=verify_checksum)
    )
    validate_edges(edges, full_support, resolution)
    selected = set(support["H3_INDEX"].astype(str))
    edges = edges.loc[
        edges["EDGE_IS_WATER_PASSABLE"].astype(bool)
        & edges["SOURCE_H3_INDEX"].isin(selected)
        & edges["TARGET_H3_INDEX"].isin(selected)
    ].copy()
    if edges.empty:
        raise ValueError(f"Selected canonical H3 r{resolution} graph has no valid edges.")
    return _csr(support, edges, resolution)


def load_radius_sum_operator(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    verify_checksum: bool = True,
):
    """Load the canonical R8 radius operator and verify its graph/support lineage."""

    from .radius_operator import RadiusSumOperator

    config = load_water_network_config(config_path)
    payload = _manifest(config)
    path = config.radius_sum_operator_path
    if not path.exists():
        raise FileNotFoundError(f"Canonical radius-sum operator not found: {path}")
    if verify_checksum:
        _verify_artifact(path, payload)
    operator = RadiusSumOperator.load(path)
    support = load_model_area_support(8, config_path, verify_checksum=verify_checksum)
    source_support = load_water_support(8, config_path, verify_checksum=verify_checksum)
    operator.validate_lineage(
        graph_path=config.edge_path(8),
        support_cells=support["H3_INDEX"].astype(str).tolist(),
        source_support_cells=source_support["H3_INDEX"].astype(str).tolist(),
    )
    if operator.radius_m != config.canonical_radius_m:
        raise ValueError("Configured and materialized radius-operator distances disagree.")
    return operator


def load_reachable_water_area(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    verify_checksum: bool = True,
) -> pd.DataFrame:
    """Load the materialized reachable-water-area graph derivative."""

    config = load_water_network_config(config_path)
    payload = _manifest(config)
    path = config.reachable_water_area_path
    if not path.exists():
        raise FileNotFoundError(f"Canonical reachable-water-area derivative not found: {path}")
    if verify_checksum:
        _verify_artifact(path, payload)
    frame = pd.read_parquet(path)
    support = load_model_area_support(8, config_path, verify_checksum=verify_checksum)
    if frame["H3_INDEX"].astype(str).tolist() != support["H3_INDEX"].astype(str).tolist():
        raise ValueError("Reachable-water-area support order is noncanonical.")
    values = frame["REACHABLE_WATER_AREA_WITHIN_5KM_M2"].to_numpy(dtype="float64")
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Reachable-water-area values must be finite and nonnegative.")
    return frame


def multi_source_shortest_paths(
    graph: WaterGraph,
    sources: list[tuple[str, float, int]],
) -> tuple[np.ndarray, np.ndarray]:
    """Run deterministic weighted Dijkstra from `(cell, distance, owner)` sources."""

    distances = np.full(len(graph.cells), np.inf, dtype=np.float64)
    owners = np.full(len(graph.cells), -1, dtype=np.int64)
    queue: list[tuple[float, int, int]] = []
    for cell, initial_distance, owner in sorted(
        sources, key=lambda value: (float(value[1]), int(value[2]), str(value[0]))
    ):
        position = graph.cell_to_position.get(str(cell))
        if position is None:
            continue
        initial = float(initial_distance)
        replace = initial < distances[position] - 1e-9
        tie = math.isclose(initial, distances[position], abs_tol=1e-9) and (
            owners[position] < 0 or int(owner) < owners[position]
        )
        if replace or tie:
            distances[position] = initial
            owners[position] = int(owner)
            heapq.heappush(queue, (initial, int(owner), position))
    if not queue:
        raise ValueError("No shortest-path source belongs to the selected canonical graph.")
    while queue:
        current, owner, position = heapq.heappop(queue)
        if current > distances[position] + 1e-9 or owner != owners[position]:
            continue
        neighbors, weights = graph.neighbors_of(position)
        for neighbor, weight in zip(neighbors, weights, strict=True):
            neighbor = int(neighbor)
            candidate = current + float(weight)
            replace = candidate < distances[neighbor] - 1e-9
            tie = math.isclose(candidate, distances[neighbor], abs_tol=1e-9) and (
                owners[neighbor] < 0 or owner < owners[neighbor]
            )
            if replace or tie:
                distances[neighbor] = candidate
                owners[neighbor] = owner
                heapq.heappush(queue, (candidate, owner, neighbor))
    return distances, owners


def attach_points_to_graph(
    graph: WaterGraph,
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    water_geometry: Any,
    *,
    source_water_max_distance_m: float,
    graph_connector_max_distance_m: float,
    candidate_limit: int = 16,
    geodesic_segment_max_m: float = 100.0,
    passability_tolerance_m: float = 1.0,
) -> pd.DataFrame:
    """Attach external points through a water entry point and water-valid connector."""

    from .geometry import water_path_metrics

    geod = Geod(ellps="WGS84")
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    support = graph.support.set_index("H3_INDEX").loc[graph.cells.astype(str)]
    node_lon = support["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(dtype="float64")
    node_lat = support["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(dtype="float64")
    node_x, node_y = transformer.transform(node_lon, node_lat)
    tree = cKDTree(np.column_stack((node_x, node_y)))
    prepared_water = prep(water_geometry)
    rows: list[dict[str, Any]] = []
    k = min(max(1, int(candidate_limit)), len(graph.cells))
    for source_position, (longitude, latitude) in enumerate(
        zip(longitudes, latitudes, strict=True)
    ):
        point = Point(float(longitude), float(latitude))
        entry = point if water_geometry.covers(point) else nearest_points(point, water_geometry)[1]
        _azimuth, _back_azimuth, source_distance = geod.inv(
            float(longitude), float(latitude), float(entry.x), float(entry.y)
        )
        if float(source_distance) > source_water_max_distance_m:
            rows.append(
                {
                    "SOURCE_POSITION": source_position,
                    "WATER_ENTRY_LONGITUDE": float(entry.x),
                    "WATER_ENTRY_LATITUDE": float(entry.y),
                    "SOURCE_TO_WATER_DISTANCE_M": float(source_distance),
                    "GRAPH_H3_INDEX": None,
                    "GRAPH_CONNECTOR_DISTANCE_M": np.nan,
                    "WATER_PATH_FRACTION": np.nan,
                    "IS_CONNECTED": False,
                    "QC_REASON": "source_exceeds_water_entry_tolerance",
                }
            )
            continue
        entry_x, entry_y = transformer.transform(float(entry.x), float(entry.y))
        _approximate, candidates = tree.query((entry_x, entry_y), k=k)
        candidates = np.atleast_1d(candidates)
        evaluated: list[tuple[float, str, float, bool]] = []
        for graph_position in candidates:
            graph_position = int(graph_position)
            distance, fraction, passable = water_path_metrics(
                float(entry.x),
                float(entry.y),
                node_lon[graph_position],
                node_lat[graph_position],
                water_geometry,
                maximum_segment_m=geodesic_segment_max_m,
                outside_tolerance_m=passability_tolerance_m,
                prepared_water=prepared_water,
            )
            evaluated.append((distance, str(graph.cells[graph_position]), fraction, passable))
        evaluated.sort(key=lambda value: (value[0], value[1]))
        within = [value for value in evaluated if value[0] <= graph_connector_max_distance_m]
        accepted = next((value for value in within if value[3]), None)
        if accepted is None:
            closest = within[0] if within else (evaluated[0] if evaluated else None)
            rows.append(
                {
                    "SOURCE_POSITION": source_position,
                    "WATER_ENTRY_LONGITUDE": float(entry.x),
                    "WATER_ENTRY_LATITUDE": float(entry.y),
                    "SOURCE_TO_WATER_DISTANCE_M": float(source_distance),
                    "GRAPH_H3_INDEX": closest[1] if closest else None,
                    "GRAPH_CONNECTOR_DISTANCE_M": closest[0] if closest else np.nan,
                    "WATER_PATH_FRACTION": closest[2] if closest else np.nan,
                    "IS_CONNECTED": False,
                    "QC_REASON": (
                        "source_connector_crosses_land"
                        if within
                        else "source_has_no_graph_node_within_connector_limit"
                    ),
                }
            )
            continue
        distance, cell, fraction, _passable = accepted
        rows.append(
            {
                "SOURCE_POSITION": source_position,
                "WATER_ENTRY_LONGITUDE": float(entry.x),
                "WATER_ENTRY_LATITUDE": float(entry.y),
                "SOURCE_TO_WATER_DISTANCE_M": float(source_distance),
                "GRAPH_H3_INDEX": cell,
                "GRAPH_CONNECTOR_DISTANCE_M": distance,
                "WATER_PATH_FRACTION": fraction,
                "IS_CONNECTED": True,
                "QC_REASON": None,
            }
        )
    return pd.DataFrame(rows)
