"""Mapped geographic gateways and bounded canonical-graph route diagnostics."""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from seascape.products import resolve_product
from seascape.spatial_support.water_network.graph import WaterGraph


def gateway_relationships(
    cells: pd.DataFrame,
    attachments: pd.DataFrame,
    graph: WaterGraph,
    *,
    max_pairs: int = 2_000_000,
    max_distance_m: float | None = None,
) -> pd.DataFrame:
    """One search per gateway from all validated geometry attachments.

    Attachments are graph nodes touched by reviewed gateway geometry or by a
    water-valid terminal connector. The caller retains that geometry registry.
    """

    required_cells = {"H3_INDEX", "H3_RESOLUTION", "GRAPH_H3_INDEX", "TARGET_CONNECTOR_DISTANCE_M"}
    required_attachments = {"GATEWAY_ID", "GRAPH_H3_INDEX", "GATEWAY_CONNECTOR_DISTANCE_M"}
    if required_cells - set(cells) or required_attachments - set(attachments):
        raise ValueError("Missing gateway cell or attachment fields")
    if cells.duplicated(["H3_INDEX", "H3_RESOLUTION"]).any():
        raise ValueError("Duplicate cell identity")
    if attachments.duplicated(["GATEWAY_ID", "GRAPH_H3_INDEX"]).any():
        raise ValueError("Duplicate gateway attachment")
    if not cells.H3_RESOLUTION.eq(graph.resolution).all():
        raise ValueError("Gateway cell resolution differs from graph")
    if not set(cells.GRAPH_H3_INDEX.astype(str)) <= set(graph.cell_to_position) or not set(attachments.GRAPH_H3_INDEX.astype(str)) <= set(graph.cell_to_position):
        raise ValueError("Gateway attachment outside canonical graph")
    for column, frame in (("TARGET_CONNECTOR_DISTANCE_M", cells), ("GATEWAY_CONNECTOR_DISTANCE_M", attachments)):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f"Invalid {column}")
    if max_distance_m is not None and (not math.isfinite(max_distance_m) or max_distance_m <= 0):
        raise ValueError("max_distance_m must be positive and finite")
    gateway_ids = sorted(attachments.GATEWAY_ID.astype(str).unique())
    if not gateway_ids or len(cells) * len(gateway_ids) > max_pairs:
        raise ValueError("Gateway pair budget exceeded or no gateways selected")
    ordered = cells.sort_values(["H3_RESOLUTION", "H3_INDEX"]).reset_index(drop=True)
    positions = [graph.cell_to_position[str(node)] for node in ordered.GRAPH_H3_INDEX]
    components = graph.support.set_index("H3_INDEX")["WATER_COMPONENT_ID"]
    frames = []
    for gateway_id in gateway_ids:
        sources = attachments.loc[attachments.GATEWAY_ID.eq(gateway_id)]
        source_components = set(components.loc[sources.GRAPH_H3_INDEX.astype(str)].astype(str))
        distances = np.full(len(graph.cells), np.inf)
        queue = []
        for row in sources.itertuples(index=False):
            node = graph.cell_to_position[str(row.GRAPH_H3_INDEX)]
            distance = float(row.GATEWAY_CONNECTOR_DISTANCE_M)
            if distance < distances[node]:
                distances[node] = distance
                heapq.heappush(queue, (distance, node))
        while queue:
            distance, node = heapq.heappop(queue)
            if distance > distances[node] + 1e-9:
                continue
            if max_distance_m is not None and distance > max_distance_m:
                break
            neighbors, weights = graph.neighbors_of(node)
            for target, weight in zip(neighbors, weights, strict=True):
                target = int(target)
                candidate = distance + float(weight)
                if candidate + 1e-9 < distances[target] and (max_distance_m is None or candidate <= max_distance_m):
                    distances[target] = candidate
                    heapq.heappush(queue, (candidate, target))
        measured = distances[positions] + ordered.TARGET_CONNECTOR_DISTANCE_M.to_numpy(dtype=float)
        reached = np.isfinite(measured)
        if max_distance_m is not None:
            reached &= measured <= max_distance_m
        target_components = components.loc[ordered.GRAPH_H3_INDEX.astype(str)].astype(str).to_numpy()
        frames.append(pd.DataFrame({
            "H3_INDEX": ordered.H3_INDEX,
            "H3_RESOLUTION": ordered.H3_RESOLUTION,
            "GATEWAY_ID": gateway_id,
            "WATER_NETWORK_DISTANCE_M": np.where(reached, measured, np.nan),
            "REACHABILITY_STATUS": np.where(reached, "reachable", np.where(
                np.isin(target_components, list(source_components)) & (max_distance_m is not None),
                "search_limited", "disconnected_within_available_graph")),
            "TARGET_CONNECTOR_DISTANCE_M": ordered.TARGET_CONNECTOR_DISTANCE_M,
            "GRAPH_COMPONENT_ID": target_components,
        }))
    return pd.concat(frames, ignore_index=True)


def basin_membership(point: Point, basins: Mapping[str, BaseGeometry]) -> tuple[str | None, str]:
    """Preserve overlap/boundary ambiguity rather than arbitrary first match."""

    matches = sorted(name for name, geometry in basins.items() if geometry.covers(point))
    if len(matches) == 1:
        return matches[0], "assigned"
    return None, "outside_mapped_basins" if not matches else "ambiguous_membership"


def corridor_coordinates(
    point: Point, axis: BaseGeometry, *, max_lateral_offset_m: float
) -> tuple[float | None, float | None, str]:
    if axis.geom_type != "LineString" or axis.length <= 0 or max_lateral_offset_m <= 0:
        raise ValueError("Corridor requires one ordered line and a positive lateral bound")
    along = float(axis.project(point))
    offset = float(point.distance(axis))
    if offset > max_lateral_offset_m:
        return None, None, "outside_corridor_support"
    return along, offset, "assigned"


def alternate_route_after_gateway_removal(
    graph: WaterGraph,
    source_node: str,
    target_node: str,
    gateway_edges: Iterable[tuple[str, str]],
    *,
    max_search_m: float | None = None,
) -> dict[str, float | str | None]:
    """Return primary and edge-removal route lengths without mutating graph."""

    if source_node not in graph.cell_to_position or target_node not in graph.cell_to_position:
        raise ValueError("Route endpoints must be canonical graph nodes")
    removed = {frozenset((str(a), str(b))) for a, b in gateway_edges}
    if not removed:
        raise ValueError("Gateway crossing edge set must be explicit")
    for edge in removed:
        if len(edge) != 2 or not edge <= set(graph.cell_to_position):
            raise ValueError("Invalid gateway crossing edge")

    def search(remove: bool) -> float | None:
        start = graph.cell_to_position[source_node]
        goal = graph.cell_to_position[target_node]
        queue = [(0.0, start)]
        best = {start: 0.0}
        while queue:
            distance, node = heapq.heappop(queue)
            if distance > best[node] + 1e-9:
                continue
            if node == goal:
                return distance
            if max_search_m is not None and distance > max_search_m:
                break
            neighbors, weights = graph.neighbors_of(node)
            for target, weight in zip(neighbors, weights, strict=True):
                target = int(target)
                edge = frozenset((str(graph.cells[node]), str(graph.cells[target])))
                if remove and edge in removed:
                    continue
                candidate = distance + float(weight)
                if candidate < best.get(target, math.inf) and (max_search_m is None or candidate <= max_search_m):
                    best[target] = candidate
                    heapq.heappush(queue, (candidate, target))
        return None

    primary = search(False)
    alternate = search(True)
    return {
        "PRIMARY_ROUTE_LENGTH_M": primary,
        "ALTERNATE_ROUTE_LENGTH_AFTER_GATEWAY_REMOVAL_M": alternate,
        "ALTERNATE_ROUTE_STATUS": (
            "reachable" if alternate is not None else
            "search_limited" if max_search_m is not None else
            "disconnected_within_available_graph"
        ),
    }


def read_released_gateways(
    gateway_ids: Iterable[str], *, workspace: str | Path | None = None,
    release_id: str | None = None, resolution: int = 8,
) -> pd.DataFrame:
    selected = tuple(dict.fromkeys(str(value) for value in gateway_ids))
    if not selected:
        raise ValueError("Select exact gateway IDs")
    artifact = resolve_product(
        product="gateway_relationships", resolution=resolution,
        workspace=workspace, release_id=release_id,
    )
    frame = pd.read_parquet(artifact.path)
    if frame.duplicated(["H3_INDEX", "H3_RESOLUTION", "GATEWAY_ID"]).any():
        raise ValueError("Released gateway relationship identity is ambiguous")
    if set(selected) - set(frame.GATEWAY_ID.astype(str)):
        raise KeyError("Selected gateway absent from release")
    return frame.loc[frame.GATEWAY_ID.isin(selected)].copy()


def pivot_selected_gateways(frame: pd.DataFrame, gateway_ids: Iterable[str]) -> pd.DataFrame:
    selected = tuple(dict.fromkeys(str(value) for value in gateway_ids))
    if not selected or set(selected) - set(frame.GATEWAY_ID.astype(str)):
        raise ValueError("Select available gateway IDs explicitly")
    if frame.duplicated(["H3_INDEX", "H3_RESOLUTION", "GATEWAY_ID"]).any():
        raise ValueError("Gateway relationship identity is ambiguous")
    wide = frame.loc[frame.GATEWAY_ID.isin(selected)].pivot(
        index=["H3_INDEX", "H3_RESOLUTION"], columns="GATEWAY_ID",
        values="WATER_NETWORK_DISTANCE_M",
    )
    wide.columns = [f"WATER_NETWORK_DISTANCE_M__GATEWAY_{len(str(value))}_{value}" for value in wide.columns]
    return wide.reset_index()
