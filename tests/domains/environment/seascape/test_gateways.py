from __future__ import annotations

import numpy as np
import pandas as pd
from shapely.geometry import Point, box

from seascape.coastal_configuration.gateways import (
    alternate_route_after_gateway_removal,
    basin_membership,
    corridor_coordinates,
    gateway_relationships,
)
from seascape.spatial_support.water_network.graph import WaterGraph


def _graph() -> WaterGraph:
    # Two basin-crossing channels: a-b-d primary and a-c-d alternate.
    names = np.array(["a", "b", "c", "d", "island"])
    return WaterGraph(
        8,
        names,
        np.array([0, 2, 4, 6, 8, 8]),
        np.array([1, 2, 0, 3, 0, 3, 1, 2]),
        np.array([1, 3, 1, 1, 3, 3, 1, 3], dtype=float),
        pd.DataFrame(
            {"H3_INDEX": names, "WATER_COMPONENT_ID": ["main"] * 4 + ["separate"]}
        ),
        {str(name): i for i, name in enumerate(names)},
        "fixture",
        "fixture",
    )


def test_gateway_interior_distance_and_alternate_route() -> None:
    graph = _graph()
    cells = pd.DataFrame(
        {
            "H3_INDEX": ["a", "b", "c", "d", "island"],
            "H3_RESOLUTION": [8] * 5,
            "GRAPH_H3_INDEX": ["a", "b", "c", "d", "island"],
            "TARGET_CONNECTOR_DISTANCE_M": [0.0] * 5,
        }
    )
    attachments = pd.DataFrame(
        {
            "GATEWAY_ID": ["gate", "gate", "other"],
            "GRAPH_H3_INDEX": ["b", "d", "c"],
            "GATEWAY_CONNECTOR_DISTANCE_M": [0.0] * 3,
        }
    )
    result = gateway_relationships(cells, attachments, graph)
    assert len(result) == 10
    lookup = result.set_index(["H3_INDEX", "GATEWAY_ID"])
    assert lookup.loc[("d", "gate"), "WATER_NETWORK_DISTANCE_M"] == 0
    assert (
        lookup.loc[("island", "gate"), "REACHABILITY_STATUS"]
        == "disconnected_within_available_graph"
    )
    before = graph.neighbors.copy()
    route = alternate_route_after_gateway_removal(graph, "a", "d", [("b", "d")])
    assert route["PRIMARY_ROUTE_LENGTH_M"] == 2
    assert route["ALTERNATE_ROUTE_LENGTH_AFTER_GATEWAY_REMOVAL_M"] == 6
    np.testing.assert_array_equal(graph.neighbors, before)
    assert (
        alternate_route_after_gateway_removal(
            graph, "a", "d", [("b", "d"), ("c", "d")]
        )["ALTERNATE_ROUTE_STATUS"]
        == "disconnected_within_available_graph"
    )


def test_basin_ambiguity_and_corridor_support() -> None:
    basins = {"west": box(0, 0, 2, 2), "east": box(2, 0, 4, 2)}
    assert basin_membership(Point(2, 1), basins) == (None, "ambiguous_membership")
    assert basin_membership(Point(1, 1), basins) == ("west", "assigned")
    from shapely.geometry import LineString

    assert corridor_coordinates(
        Point(3, 1), LineString([(0, 0), (5, 0)]), max_lateral_offset_m=2
    ) == (3, 1, "assigned")
