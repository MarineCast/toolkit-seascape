"""Selected outlet to marine-cell relationships on the canonical water graph.

Coordinates are in one declared projected metre CRS. Graph connectors are
terminal distances: they contribute to a route but never become graph edges.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from seascape.products import resolve_product
from seascape.spatial_support.water_network.graph import WaterGraph

OUTLET_COLUMNS = (
    "OUTLET_ID",
    "SOURCE_ID",
    "SOURCE_VERSION",
    "SOURCE_FEATURE_ID",
    "RIVER_BASIN_ID",
    "OUTLET_X_M",
    "OUTLET_Y_M",
    "GRAPH_H3_INDEX",
    "SOURCE_CONNECTOR_DISTANCE_M",
    "SELECTION_PROVENANCE",
    "MULTIPLE_MOUTH_GROUP_ID",
)
CELL_COLUMNS = (
    "H3_INDEX",
    "H3_RESOLUTION",
    "REPRESENTATIVE_X_M",
    "REPRESENTATIVE_Y_M",
    "GRAPH_H3_INDEX",
    "TARGET_CONNECTOR_DISTANCE_M",
)


def _unique(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    if frame[columns].isna().any().any() or frame.duplicated(columns).any():
        raise ValueError(f"{name} has null or duplicate identity {columns}")


def validate_inputs(
    cells: pd.DataFrame, outlets: pd.DataFrame, graph: WaterGraph
) -> None:
    """Require explicit stable identities and water-valid canonical attachments."""

    missing_cells = set(CELL_COLUMNS) - set(cells)
    missing_outlets = set(OUTLET_COLUMNS) - set(outlets)
    if missing_cells or missing_outlets:
        raise ValueError(
            f"Missing cell columns {sorted(missing_cells)} or outlet columns {sorted(missing_outlets)}"
        )
    _unique(cells, ["H3_INDEX", "H3_RESOLUTION"], "cells")
    _unique(outlets, ["OUTLET_ID"], "outlets")
    _unique(outlets, ["SOURCE_ID", "SOURCE_VERSION", "SOURCE_FEATURE_ID"], "outlets")
    for column in (
        "SOURCE_ID",
        "SOURCE_VERSION",
        "SOURCE_FEATURE_ID",
        "SELECTION_PROVENANCE",
    ):
        if (
            outlets[column].isna().any()
            or outlets[column].astype(str).str.len().eq(0).any()
        ):
            raise ValueError(f"Outlet {column} must be nonempty")
    if not cells["H3_RESOLUTION"].eq(graph.resolution).all():
        raise ValueError("Cell resolution differs from canonical graph resolution")
    for frame, columns in (
        (
            cells,
            ("REPRESENTATIVE_X_M", "REPRESENTATIVE_Y_M", "TARGET_CONNECTOR_DISTANCE_M"),
        ),
        (outlets, ("OUTLET_X_M", "OUTLET_Y_M", "SOURCE_CONNECTOR_DISTANCE_M")),
    ):
        for column in columns:
            values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
            if not np.isfinite(values).all():
                raise ValueError(f"{column} must be finite")
            if "CONNECTOR" in column and (values < 0).any():
                raise ValueError(f"{column} must be nonnegative")
        if not set(frame["GRAPH_H3_INDEX"].astype(str)) <= set(graph.cell_to_position):
            raise ValueError("Attachment is outside canonical water graph")


def _outlet_distances(
    graph: WaterGraph, node: int, connector_m: float, max_search_m: float | None
) -> np.ndarray:
    """One sparse Dijkstra per outlet; terminal connector is seeded once."""

    distances = np.full(len(graph.cells), np.inf, dtype=float)
    distances[node] = connector_m
    queue = [(connector_m, node)]
    while queue:
        distance, position = heapq.heappop(queue)
        if distance > distances[position] + 1e-9:
            continue
        if max_search_m is not None and distance > max_search_m:
            break
        neighbors, weights = graph.neighbors_of(position)
        for neighbor, weight in zip(neighbors, weights, strict=True):
            target = int(neighbor)
            candidate = distance + float(weight)
            if candidate + 1e-9 < distances[target] and (
                max_search_m is None or candidate <= max_search_m
            ):
                distances[target] = candidate
                heapq.heappush(queue, (candidate, target))
    return distances


def outlet_relationship_chunks(
    cells: pd.DataFrame,
    outlets: pd.DataFrame,
    graph: WaterGraph,
    *,
    max_pairs: int = 2_000_000,
    max_search_m: float | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield one deterministic long-table chunk per outlet.

    Search-limited means the configured bound prevented proof of reachability.
    Disconnected means no path exists in the *available* graph; clipping may
    change that result. Every requested pair receives exactly one row.
    """

    validate_inputs(cells, outlets, graph)
    if max_pairs < 1 or len(cells) * len(outlets) > max_pairs:
        raise ValueError(
            f"Cell/outlet pair budget exceeded: {len(cells) * len(outlets)} > {max_pairs}"
        )
    if max_search_m is not None and (
        not math.isfinite(max_search_m) or max_search_m <= 0
    ):
        raise ValueError("max_search_m must be positive and finite")
    ordered_cells = cells.sort_values(["H3_RESOLUTION", "H3_INDEX"]).reset_index(
        drop=True
    )
    positions = np.array(
        [graph.cell_to_position[str(node)] for node in ordered_cells["GRAPH_H3_INDEX"]],
        dtype=int,
    )
    target_connector = ordered_cells["TARGET_CONNECTOR_DISTANCE_M"].to_numpy(
        dtype=float
    )
    support = graph.support.set_index("H3_INDEX")
    for outlet in outlets.sort_values("OUTLET_ID").itertuples(index=False):
        source_node = graph.cell_to_position[str(outlet.GRAPH_H3_INDEX)]
        source_connector = float(outlet.SOURCE_CONNECTOR_DISTANCE_M)
        distances = _outlet_distances(
            graph, source_node, source_connector, max_search_m
        )
        route = distances[positions] + target_connector
        reached = np.isfinite(route)
        if max_search_m is not None:
            reached &= route <= max_search_m
        source_component = support.loc[str(outlet.GRAPH_H3_INDEX), "WATER_COMPONENT_ID"]
        target_components = support.loc[
            ordered_cells["GRAPH_H3_INDEX"].astype(str), "WATER_COMPONENT_ID"
        ].to_numpy()
        status = np.where(
            reached,
            "reachable",
            np.where(
                target_components != source_component,
                "disconnected_within_available_graph",
                "search_limited"
                if max_search_m is not None
                else "disconnected_within_available_graph",
            ),
        )
        direct = np.hypot(
            ordered_cells["REPRESENTATIVE_X_M"].to_numpy(dtype=float)
            - float(outlet.OUTLET_X_M),
            ordered_cells["REPRESENTATIVE_Y_M"].to_numpy(dtype=float)
            - float(outlet.OUTLET_Y_M),
        )
        direct[~reached] = np.nan
        network = np.where(reached, route, np.nan)
        detour = network - direct
        ratio = np.full(len(ordered_cells), np.nan, dtype=float)
        noncoincident = reached & (direct > 1e-9)
        ratio[noncoincident] = network[noncoincident] / direct[noncoincident]
        coincident = reached & ~noncoincident & (network <= 1e-9)
        ratio[coincident] = 1.0
        inconsistent = reached & (detour < -1e-6)
        status[inconsistent] = "metric_inconsistency"
        yield pd.DataFrame(
            {
                "H3_INDEX": ordered_cells["H3_INDEX"],
                "H3_RESOLUTION": ordered_cells["H3_RESOLUTION"],
                "OUTLET_ID": str(outlet.OUTLET_ID),
                "RIVER_BASIN_ID": outlet.RIVER_BASIN_ID,
                "WATER_NETWORK_DISTANCE_M": network,
                "EUCLIDEAN_DISTANCE_M": direct,
                "DETOUR_DISTANCE_M": detour,
                "DETOUR_RATIO": ratio,
                "REACHABILITY_STATUS": status,
                "SOURCE_CONNECTOR_DISTANCE_M": source_connector,
                "TARGET_CONNECTOR_DISTANCE_M": target_connector,
                "GRAPH_COMPONENT_ID": target_components,
                "QC_REASON": np.where(
                    inconsistent, "network_shorter_than_direct", None
                ),
            }
        )


def build_outlet_relationships(
    cells: pd.DataFrame,
    outlets: pd.DataFrame,
    graph: WaterGraph,
    **kwargs: object,
) -> pd.DataFrame:
    """Materialize bounded relationships in memory for small requests/tests."""

    chunks = list(outlet_relationship_chunks(cells, outlets, graph, **kwargs))
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def read_released_outlets(
    outlet_ids: Iterable[str],
    *,
    workspace: str | Path | None = None,
    release_id: str | None = None,
    resolution: int = 8,
) -> pd.DataFrame:
    """Read exact selected IDs from an immutable release, never nearest-N."""

    selected = tuple(dict.fromkeys(str(item) for item in outlet_ids))
    if not selected:
        raise ValueError("At least one explicit outlet ID is required")
    artifact = resolve_product(
        workspace=workspace,
        release_id=release_id,
        product="outlet_relationships",
        resolution=resolution,
    )
    frame = pd.read_parquet(artifact.path)
    _unique(frame, ["H3_INDEX", "H3_RESOLUTION", "OUTLET_ID"], "released outlets")
    missing = set(selected) - set(frame["OUTLET_ID"].astype(str))
    if missing:
        raise KeyError(f"Outlet IDs absent from release: {sorted(missing)}")
    return frame.loc[frame["OUTLET_ID"].isin(selected)].copy()


def pivot_selected_outlets(
    frame: pd.DataFrame, outlet_ids: Iterable[str]
) -> pd.DataFrame:
    """Wide network-distance view for explicitly chosen IDs only."""

    selected = tuple(dict.fromkeys(str(item) for item in outlet_ids))
    if not selected:
        raise ValueError("Select outlet IDs explicitly")
    _unique(frame, ["H3_INDEX", "H3_RESOLUTION", "OUTLET_ID"], "outlet relationships")
    if set(selected) - set(frame["OUTLET_ID"].astype(str)):
        raise KeyError("Selected outlet missing from relationship table")
    wide = frame.loc[frame["OUTLET_ID"].isin(selected)].pivot(
        index=["H3_INDEX", "H3_RESOLUTION"],
        columns="OUTLET_ID",
        values="WATER_NETWORK_DISTANCE_M",
    )
    wide.columns = [
        f"WATER_NETWORK_DISTANCE_M__OUTLET_{len(str(value))}_{value}"
        for value in wide.columns
    ]
    return wide.reset_index()
