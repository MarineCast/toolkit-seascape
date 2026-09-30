from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from seascape.hydrologic_connectivity.fluvial_connectivity.multiple_outlets import (
    build_outlet_relationships,
    pivot_selected_outlets,
)
from seascape.spatial_support.water_network.graph import WaterGraph


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame, WaterGraph]:
    # a--b--c and d are separated by an island/land barrier; e is isolated.
    names = ["a", "b", "c", "d", "e"]
    support = pd.DataFrame(
        {"H3_INDEX": names, "WATER_COMPONENT_ID": ["main"] * 3 + ["island", "isolated"]}
    )
    graph = WaterGraph(
        resolution=8,
        cells=np.array(names),
        offsets=np.array([0, 1, 3, 4, 4, 4]),
        neighbors=np.array([1, 0, 2, 1]),
        weights_m=np.array([100.0, 100.0, 100.0, 100.0]),
        support=support,
        cell_to_position={name: index for index, name in enumerate(names)},
        water_mask_version="fixture",
        spatial_support_version="fixture",
    )
    cells = pd.DataFrame(
        {
            "H3_INDEX": names,
            "H3_RESOLUTION": [8] * 5,
            "REPRESENTATIVE_X_M": [0, 100, 200, 100, 500],
            "REPRESENTATIVE_Y_M": [0, 0, 0, 25, 0],
            "GRAPH_H3_INDEX": names,
            "TARGET_CONNECTOR_DISTANCE_M": [0.0] * 5,
        }
    )
    outlets = pd.DataFrame(
        {
            "OUTLET_ID": ["one", "two", "far", "island"],
            "SOURCE_ID": ["source"] * 4,
            "SOURCE_VERSION": ["v1"] * 4,
            "SOURCE_FEATURE_ID": ["1", "2", "3", "4"],
            "RIVER_BASIN_ID": ["shared", "shared", "other", "island"],
            "OUTLET_X_M": [0, 100, 200, 100],
            "OUTLET_Y_M": [0, 0, 0, 25],
            "GRAPH_H3_INDEX": ["a", "b", "c", "d"],
            "SOURCE_CONNECTOR_DISTANCE_M": [0.0] * 4,
            "SELECTION_PROVENANCE": ["explicit"] * 4,
            "MULTIPLE_MOUTH_GROUP_ID": ["delta", "delta", None, None],
        }
    )
    return cells, outlets, graph


def test_all_explicit_outlets_and_island_barrier() -> None:
    cells, outlets, graph = _fixture()
    result = build_outlet_relationships(cells, outlets, graph)
    assert len(result) == 20
    assert result.set_index(["H3_INDEX", "OUTLET_ID"]).index.is_unique
    lookup = result.set_index(["H3_INDEX", "OUTLET_ID"])
    assert lookup.loc[("a", "far"), "WATER_NETWORK_DISTANCE_M"] == 200
    assert lookup.loc[("c", "one"), "WATER_NETWORK_DISTANCE_M"] == 200
    assert (
        lookup.loc[("b", "island"), "REACHABILITY_STATUS"]
        == "disconnected_within_available_graph"
    )
    assert pd.isna(lookup.loc[("e", "far"), "WATER_NETWORK_DISTANCE_M"])
    assert set(
        result.loc[
            result.H3_INDEX.eq("a") & result.RIVER_BASIN_ID.eq("shared"), "OUTLET_ID"
        ]
    ) == {"one", "two"}
    pd.testing.assert_frame_equal(
        result,
        build_outlet_relationships(
            cells.sample(frac=1, random_state=9), outlets.iloc[::-1], graph
        ),
    )
    wide = pivot_selected_outlets(result, ["one", "far"])
    assert len(wide) == 5
    assert len(wide.columns) == 4


def test_bound_and_identity_validation() -> None:
    cells, outlets, graph = _fixture()
    result = build_outlet_relationships(cells, outlets, graph, max_search_m=150)
    lookup = result.set_index(["H3_INDEX", "OUTLET_ID"])
    assert lookup.loc[("a", "far"), "REACHABILITY_STATUS"] == "search_limited"
    assert (
        lookup.loc[("a", "island"), "REACHABILITY_STATUS"]
        == "disconnected_within_available_graph"
    )
    with pytest.raises(ValueError, match="budget"):
        build_outlet_relationships(cells, outlets, graph, max_pairs=19)
    with pytest.raises(ValueError, match="duplicate"):
        build_outlet_relationships(cells, pd.concat([outlets, outlets.iloc[:1]]), graph)
