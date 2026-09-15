"""Private graph-construction primitives for canonical marine support."""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Geod, Transformer
from scipy.spatial import cKDTree
from shapely import from_wkb
from shapely.prepared import prep

from seascape.core.geo.h3 import cell_to_parent, grid_disk_set

from .config import WaterNetworkConfig
from .geometry import water_path_metrics

LOGGER = logging.getLogger(__name__)
GEOD = Geod(ellps="WGS84")
PASSABILITY_METHOD = "geodesic_representative_point_segment_v1"
CONNECTOR_METHOD = "water_valid_terminal_connector_v1"


@dataclass(frozen=True)
class WaterGraph:
    """Deterministic CSR representation of valid canonical water edges."""

    resolution: int
    cells: np.ndarray
    offsets: np.ndarray
    neighbors: np.ndarray
    weights_m: np.ndarray
    support: pd.DataFrame
    cell_to_position: dict[str, int]
    water_mask_version: str
    spatial_support_version: str

    def neighbors_of(self, position: int) -> tuple[np.ndarray, np.ndarray]:
        start = int(self.offsets[position])
        end = int(self.offsets[position + 1])
        return self.neighbors[start:end], self.weights_m[start:end]


def target_graph_mapping(
    graph: WaterGraph,
    target_cells: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map support cells to graph nodes using only canonical terminal connectors."""

    support = graph.support.set_index("H3_INDEX")
    positions = np.full(len(target_cells), -1, dtype=np.int64)
    connectors = np.full(len(target_cells), np.nan, dtype=np.float64)
    reasons = np.empty(len(target_cells), dtype=object)
    reasons[:] = None
    for index, cell in enumerate(target_cells):
        direct = graph.cell_to_position.get(str(cell))
        if direct is not None:
            positions[index] = direct
            connectors[index] = 0.0
            continue
        if str(cell) not in support.index:
            reasons[index] = "cell_outside_loaded_canonical_support"
            continue
        row = support.loc[str(cell)]
        if row["GRAPH_CONNECTION_STATUS"] == "terminal_connector":
            target = str(row["CONNECTOR_TARGET_H3_INDEX"])
            mapped = graph.cell_to_position.get(target)
            if mapped is not None:
                positions[index] = mapped
                connectors[index] = float(row["CONNECTOR_DISTANCE_M"])
                reasons[index] = row["GRAPH_QC_REASON"]
                continue
            reasons[index] = "terminal_connector_target_outside_loaded_graph"
        else:
            reasons[index] = row["GRAPH_QC_REASON"]
    return positions, connectors, reasons


class _UnionFind:
    def __init__(self, size: int):
        self.parent = np.arange(size, dtype=np.int64)
        self.rank = np.zeros(size, dtype=np.int8)

    def find(self, value: int) -> int:
        parent = int(self.parent[value])
        while parent != int(self.parent[parent]):
            self.parent[parent] = self.parent[int(self.parent[parent])]
            parent = int(self.parent[parent])
        while value != parent:
            next_value = int(self.parent[value])
            self.parent[value] = parent
            value = next_value
        return parent

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _candidate_pairs(eligible_cells: set[str]):
    for source in sorted(eligible_cells):
        for target in sorted(grid_disk_set(source, 1)):
            if source < target and target in eligible_cells:
                yield source, target


def _build_edges(
    support: pd.DataFrame,
    water_geometry: Any,
    resolution: int,
    config: WaterNetworkConfig,
) -> pd.DataFrame:
    eligible = support.loc[support["GRAPH_NODE_ELIGIBLE"], "H3_INDEX"].astype(str)
    coordinates = {
        str(row.H3_INDEX): (
            float(row.REPRESENTATIVE_POINT_LONGITUDE),
            float(row.REPRESENTATIVE_POINT_LATITUDE),
        )
        for row in support[
            [
                "H3_INDEX",
                "REPRESENTATIVE_POINT_LONGITUDE",
                "REPRESENTATIVE_POINT_LATITUDE",
            ]
        ].itertuples(index=False)
    }
    frames: list[pd.DataFrame] = []
    buffer: dict[str, list[Any]] = {
        "SOURCE_H3_INDEX": [],
        "TARGET_H3_INDEX": [],
        "H3_RESOLUTION": [],
        "EDGE_DISTANCE_M": [],
        "EDGE_IS_WATER_PASSABLE": [],
        "PASSABILITY_METHOD": [],
        "WATER_PATH_FRACTION": [],
        "SOURCE_WATER_COMPONENT_ID": [],
        "TARGET_WATER_COMPONENT_ID": [],
        "WATER_MASK_VERSION": [],
        "SPATIAL_SUPPORT_VERSION": [],
    }
    prepared_water = prep(from_wkb(water_geometry.wkb))
    processed = 0
    for source, target in _candidate_pairs(set(eligible)):
        source_lon, source_lat = coordinates[source]
        target_lon, target_lat = coordinates[target]
        distance, fraction, passable = water_path_metrics(
            source_lon,
            source_lat,
            target_lon,
            target_lat,
            water_geometry,
            maximum_segment_m=config.geodesic_segment_max_m,
            outside_tolerance_m=config.passability_tolerance_m,
            prepared_water=prepared_water,
        )
        values = (
            source,
            target,
            resolution,
            distance,
            passable,
            PASSABILITY_METHOD,
            fraction,
            None,
            None,
            config.water_mask_version,
            config.spatial_support_version,
        )
        for column, value in zip(buffer, values):
            buffer[column].append(value)
        processed += 1
        if processed % config.edge_chunk_size == 0:
            frames.append(pd.DataFrame(buffer))
            buffer = {column: [] for column in buffer}
            LOGGER.info("Evaluated H3 r%d water edges: %d", resolution, processed)
    if buffer["SOURCE_H3_INDEX"]:
        frames.append(pd.DataFrame(buffer))
    if not frames:
        raise ValueError(f"Canonical H3 r{resolution} graph has no neighbor candidates.")
    LOGGER.info("Evaluated H3 r%d water edges: %d", resolution, processed)
    return pd.concat(frames, ignore_index=True)


def _assign_components(support: pd.DataFrame, edges: pd.DataFrame) -> None:
    stage_started = time.perf_counter()
    cells = support["H3_INDEX"].astype(str).tolist()
    positions = {cell: index for index, cell in enumerate(cells)}
    union_find = _UnionFind(len(cells))
    degree = np.zeros(len(cells), dtype=np.int32)
    valid = edges["EDGE_IS_WATER_PASSABLE"].astype(bool)
    for source, target in edges.loc[valid, ["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]].itertuples(
        index=False
    ):
        source_index = positions[str(source)]
        target_index = positions[str(target)]
        union_find.union(source_index, target_index)
        degree[source_index] += 1
        degree[target_index] += 1
    LOGGER.info("Unioned valid water edges in %.1fs", time.perf_counter() - stage_started)
    stage_started = time.perf_counter()
    node_indices = np.flatnonzero(degree > 0)
    roots = np.fromiter(
        (union_find.find(int(index)) for index in node_indices),
        dtype=np.int64,
        count=len(node_indices),
    )
    component_minimum: dict[int, str] = {}
    for index, root in zip(node_indices, roots):
        cell = cells[int(index)]
        current = component_minimum.get(int(root))
        if current is None or cell < current:
            component_minimum[int(root)] = cell
    component_values = np.empty(len(cells), dtype=object)
    component_values[:] = None
    for index, root in zip(node_indices, roots):
        component_values[int(index)] = component_minimum[int(root)]
    support["GRAPH_DEGREE"] = degree
    graph_nodes = degree > 0
    support.loc[graph_nodes, "GRAPH_CONNECTION_STATUS"] = "graph_node"
    support["WATER_COMPONENT_ID"] = pd.Categorical(component_values)
    LOGGER.info(
        "Derived deterministic water components in %.1fs", time.perf_counter() - stage_started
    )
    stage_started = time.perf_counter()
    component_series = pd.Series(component_values, index=cells, dtype="string")
    edges["SOURCE_WATER_COMPONENT_ID"] = pd.Categorical(
        edges["SOURCE_H3_INDEX"].map(component_series)
    )
    edges["TARGET_WATER_COMPONENT_ID"] = pd.Categorical(
        edges["TARGET_H3_INDEX"].map(component_series)
    )
    LOGGER.info("Mapped edge component lineage in %.1fs", time.perf_counter() - stage_started)


def _build_connectors(
    support: pd.DataFrame,
    water_geometry: Any,
    resolution: int,
    config: WaterNetworkConfig,
) -> pd.DataFrame:
    graph_nodes = support["GRAPH_DEGREE"].to_numpy(dtype="int64") > 0
    hierarchy_only = support["IS_HIERARCHY_ONLY_PARENT"].astype(bool).to_numpy()
    terminal_positions = np.flatnonzero(~graph_nodes & ~hierarchy_only)
    if not len(terminal_positions):
        return pd.DataFrame(
            columns=[
                "H3_INDEX",
                "TARGET_H3_INDEX",
                "H3_RESOLUTION",
                "CONNECTOR_DISTANCE_M",
                "CONNECTOR_IS_WATER_PASSABLE",
                "CONNECTOR_METHOD",
                "WATER_PATH_FRACTION",
                "WATER_COMPONENT_ID",
                "QC_REASON",
                "WATER_MASK_VERSION",
                "SPATIAL_SUPPORT_VERSION",
            ]
        )
    node_positions = np.flatnonzero(graph_nodes)
    if not len(node_positions):
        support["GRAPH_QC_REASON"] = "canonical_graph_has_no_valid_edges"
        return pd.DataFrame()
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    longitudes = support["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(dtype="float64")
    latitudes = support["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(dtype="float64")
    x_values, y_values = transformer.transform(longitudes, latitudes)
    xy = np.column_stack((x_values, y_values))
    tree = cKDTree(xy[node_positions])
    k = min(config.connector_candidate_limit, len(node_positions))
    _distances, nearest = tree.query(xy[terminal_positions], k=k)
    nearest = np.asarray(nearest)
    if nearest.ndim == 1:
        nearest = nearest[:, None]
    cells = support["H3_INDEX"].astype(str).tolist()
    components = support["WATER_COMPONENT_ID"].astype("string")
    maximum_distance = config.connector_max_distance_m[resolution]
    rows: list[dict[str, Any]] = []
    prepared_water = prep(from_wkb(water_geometry.wkb))
    for query_offset, source_position in enumerate(terminal_positions):
        source_position = int(source_position)
        source_cell = cells[source_position]
        candidates: list[tuple[float, str, int]] = []
        for tree_offset in np.atleast_1d(nearest[query_offset]):
            target_position = int(node_positions[int(tree_offset)])
            target_cell = cells[target_position]
            _azimuth, _back_azimuth, distance = GEOD.inv(
                longitudes[source_position],
                latitudes[source_position],
                longitudes[target_position],
                latitudes[target_position],
            )
            candidates.append((float(distance), target_cell, target_position))
        candidates.sort(key=lambda value: (value[0], value[1]))
        within = [candidate for candidate in candidates if candidate[0] <= maximum_distance]
        evaluated: list[tuple[float, str, int, float, bool]] = []
        accepted: tuple[float, str, int, float, bool] | None = None
        for distance, target_cell, target_position in within:
            _distance, fraction, passable = water_path_metrics(
                longitudes[source_position],
                latitudes[source_position],
                longitudes[target_position],
                latitudes[target_position],
                water_geometry,
                maximum_segment_m=config.geodesic_segment_max_m,
                outside_tolerance_m=config.passability_tolerance_m,
                prepared_water=prepared_water,
            )
            evaluated_candidate = (
                distance,
                target_cell,
                target_position,
                fraction,
                passable,
            )
            evaluated.append(evaluated_candidate)
            if passable:
                accepted = evaluated_candidate
                break
        base_reason = (
            "below_minimum_water_support"
            if not bool(support.at[source_position, "GRAPH_NODE_ELIGIBLE"])
            else "no_water_passable_neighbor"
        )
        if accepted is not None:
            distance, target_cell, target_position, fraction, _passable = accepted
            component = str(components.iloc[target_position])
            support.at[source_position, "WATER_COMPONENT_ID"] = component
            support.at[source_position, "GRAPH_CONNECTION_STATUS"] = "terminal_connector"
            support.at[source_position, "CONNECTOR_TARGET_H3_INDEX"] = target_cell
            support.at[source_position, "CONNECTOR_METHOD"] = CONNECTOR_METHOD
            support.at[source_position, "CONNECTOR_DISTANCE_M"] = distance
            support.at[source_position, "CONNECTOR_WATER_PATH_FRACTION"] = fraction
            support.at[source_position, "GRAPH_QC_REASON"] = base_reason
            row_target = target_cell
            row_distance = distance
            row_fraction = fraction
            row_component = component
            row_reason = base_reason
            row_passable = True
        else:
            closest = evaluated[0] if evaluated else None
            row_target = closest[1] if closest else (candidates[0][1] if candidates else None)
            row_distance = closest[0] if closest else (candidates[0][0] if candidates else np.nan)
            row_fraction = closest[3] if closest else np.nan
            row_component = None
            row_passable = False
            row_reason = (
                "connector_crosses_land" if within else "no_graph_node_within_connector_limit"
            )
            support.at[source_position, "GRAPH_QC_REASON"] = row_reason
        rows.append(
            {
                "H3_INDEX": source_cell,
                "TARGET_H3_INDEX": row_target,
                "H3_RESOLUTION": resolution,
                "CONNECTOR_DISTANCE_M": row_distance,
                "CONNECTOR_IS_WATER_PASSABLE": row_passable,
                "CONNECTOR_METHOD": CONNECTOR_METHOD,
                "WATER_PATH_FRACTION": row_fraction,
                "WATER_COMPONENT_ID": row_component,
                "QC_REASON": row_reason,
                "WATER_MASK_VERSION": config.water_mask_version,
                "SPATIAL_SUPPORT_VERSION": config.spatial_support_version,
            }
        )
        if (query_offset + 1) % 5_000 == 0:
            LOGGER.info(
                "Evaluated H3 r%d terminal connectors: %d/%d",
                resolution,
                query_offset + 1,
                len(terminal_positions),
            )
    return pd.DataFrame(rows)


def _crosswalk(support_by_resolution: dict[int, pd.DataFrame], config: WaterNetworkConfig):
    if 6 not in support_by_resolution or 8 not in support_by_resolution:
        return None
    parent = support_by_resolution[6].set_index("H3_INDEX")
    child = support_by_resolution[8]
    parent_indices = pd.Series(
        [cell_to_parent(str(cell), 6) for cell in child["H3_INDEX"]],
        index=child.index,
        dtype="string",
    )
    parent_is_marine = parent_indices.isin(parent.index.astype(str))
    frame = pd.DataFrame(
        {
            "CHILD_H3_INDEX": child["H3_INDEX"].astype(str),
            "CHILD_H3_RESOLUTION": 8,
            "PARENT_H3_INDEX": parent_indices,
            "PARENT_H3_RESOLUTION": 6,
            "PARENT_IN_MARINE_SUPPORT": parent_is_marine,
            "CHILD_WATER_AREA_M2": child["WATER_AREA_M2"].to_numpy(),
            "CHILD_WATER_FRACTION": child["WATER_FRACTION"].to_numpy(),
            "CHILD_WATER_COMPONENT_ID": child["WATER_COMPONENT_ID"].astype("string"),
            "WATER_MASK_VERSION": config.water_mask_version,
            "SPATIAL_SUPPORT_VERSION": config.spatial_support_version,
        }
    )
    frame["PARENT_WATER_AREA_M2"] = (
        frame["PARENT_H3_INDEX"].map(parent["WATER_AREA_M2"]).fillna(0.0)
    )
    frame["PARENT_WATER_FRACTION"] = (
        frame["PARENT_H3_INDEX"].map(parent["WATER_FRACTION"]).fillna(0.0)
    )
    frame["PARENT_WATER_COMPONENT_ID"] = frame["PARENT_H3_INDEX"].map(parent["WATER_COMPONENT_ID"])
    return frame.sort_values("CHILD_H3_INDEX").reset_index(drop=True)


def _build_neighborhoods(
    support: pd.DataFrame,
    edges: pd.DataFrame,
    connectors: pd.DataFrame,
    resolution: int,
    config: WaterNetworkConfig,
) -> pd.DataFrame:
    """Materialize deterministic bounded neighborhoods from water-passable links."""

    cells = support["H3_INDEX"].astype(str).tolist()
    positions = {cell: index for index, cell in enumerate(cells)}
    adjacency: list[list[tuple[int, float]]] = [[] for _ in cells]
    passable_edges = edges.loc[edges["EDGE_IS_WATER_PASSABLE"].astype(bool)]
    for source, target, distance in passable_edges[
        ["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "EDGE_DISTANCE_M"]
    ].itertuples(index=False):
        left = positions.get(str(source))
        right = positions.get(str(target))
        if left is None or right is None:
            continue
        weight = float(distance)
        adjacency[left].append((right, weight))
        adjacency[right].append((left, weight))
    if not connectors.empty:
        accepted = connectors.loc[connectors["CONNECTOR_IS_WATER_PASSABLE"].astype(bool)]
        for source, target, distance in accepted[
            ["H3_INDEX", "TARGET_H3_INDEX", "CONNECTOR_DISTANCE_M"]
        ].itertuples(index=False):
            left = positions.get(str(source))
            right = positions.get(str(target))
            if left is None or right is None:
                continue
            weight = float(distance)
            adjacency[left].append((right, weight))
            adjacency[right].append((left, weight))
    for values in adjacency:
        values.sort(key=lambda item: cells[item[0]])

    support_by_cell = support.set_index("H3_INDEX")
    rows: list[dict[str, Any]] = []
    maximum_hops = config.maximum_neighborhood_hops
    for source_position, source_cell in enumerate(cells):
        best_hops = {source_position: 0}
        best_distance = {source_position: 0.0}
        queue: deque[int] = deque([source_position])
        while queue:
            current = queue.popleft()
            current_hops = best_hops[current]
            if current_hops >= maximum_hops:
                continue
            for neighbor, weight in adjacency[current]:
                candidate_hops = current_hops + 1
                candidate_distance = best_distance[current] + weight
                known_hops = best_hops.get(neighbor)
                known_distance = best_distance.get(neighbor, math.inf)
                replace = known_hops is None or candidate_hops < known_hops
                tie = candidate_hops == known_hops and candidate_distance < known_distance - 1e-9
                if replace or tie:
                    best_hops[neighbor] = candidate_hops
                    best_distance[neighbor] = candidate_distance
                    queue.append(neighbor)
        source_status = str(support_by_cell.at[source_cell, "GRAPH_CONNECTION_STATUS"])
        source_qc = support_by_cell.at[source_cell, "GRAPH_QC_REASON"]
        for target_position in sorted(best_hops, key=lambda position: cells[position]):
            hops = best_hops[target_position]
            rows.append(
                {
                    "SOURCE_H3_INDEX": source_cell,
                    "TARGET_H3_INDEX": cells[target_position],
                    "H3_RESOLUTION": resolution,
                    "MINIMUM_HOP_COUNT": hops,
                    "NETWORK_DISTANCE_M": best_distance[target_position],
                    "CONNECTIVITY_STATUS": (
                        "self_only" if hops == 0 and len(best_hops) == 1 else "reachable"
                    ),
                    "QC_REASON": (
                        None
                        if hops > 0 or source_status != "disconnected"
                        else source_qc or "disconnected_support_cell"
                    ),
                    "WATER_MASK_VERSION": config.water_mask_version,
                    "SPATIAL_SUPPORT_VERSION": config.spatial_support_version,
                }
            )
    return (
        pd.DataFrame(rows)
        .sort_values(["SOURCE_H3_INDEX", "MINIMUM_HOP_COUNT", "TARGET_H3_INDEX"])
        .reset_index(drop=True)
    )
