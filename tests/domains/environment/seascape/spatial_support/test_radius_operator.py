from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from seascape.spatial_support.water_network.graph import WaterGraph
from seascape.spatial_support.water_network.radius_operator import (
    RadiusSumOperator,
)


def _graph() -> WaterGraph:
    support = pd.DataFrame(
        {
            "H3_INDEX": ["a", "b", "terminal", "disconnected"],
            "GRAPH_CONNECTION_STATUS": [
                "graph_node",
                "graph_node",
                "terminal_connector",
                "disconnected",
            ],
            "CONNECTOR_TARGET_H3_INDEX": [None, None, "b", None],
            "CONNECTOR_DISTANCE_M": [0.0, 0.0, 200.0, np.nan],
            "GRAPH_QC_REASON": [None, None, "terminal", "land_barrier"],
        }
    )
    return WaterGraph(
        resolution=8,
        cells=np.asarray(["a", "b"], dtype=object),
        offsets=np.asarray([0, 1, 2], dtype=np.int64),
        neighbors=np.asarray([1, 0], dtype=np.int64),
        weights_m=np.asarray([1_000.0, 1_000.0]),
        support=support,
        cell_to_position={"a": 0, "b": 1},
        water_mask_version="water-v1",
        spatial_support_version="support-v1",
    )


def test_radius_operator_matches_graph_connector_and_self_semantics() -> None:
    operator = RadiusSumOperator.build(
        _graph(),
        ["a", "b", "terminal", "disconnected"],
        radius_m=1_100.0,
        graph_checksum="fixture",
    )
    values = np.asarray([1.0, 2.0, 4.0, 8.0])
    observed = operator.apply(values, eligible_sources=np.ones(4, dtype=bool))
    assert observed.tolist() == pytest.approx([3.0, 7.0, 6.0, 8.0])


def test_radius_operator_requires_explicit_finite_eligibility() -> None:
    operator = RadiusSumOperator.build(
        _graph(),
        ["a", "b", "terminal", "disconnected"],
        radius_m=1_100.0,
        graph_checksum="fixture",
    )
    values = np.asarray([1.0, np.nan, 4.0, 8.0])
    with pytest.raises(ValueError, match="must be finite"):
        operator.apply(values, eligible_sources=np.ones(4, dtype=bool))
    observed = operator.apply(
        values,
        eligible_sources=np.asarray([True, False, True, True]),
    )
    assert observed.tolist() == pytest.approx([1.0, 5.0, 4.0, 8.0])


def test_radius_operator_round_trip(tmp_path: Path) -> None:
    operator = RadiusSumOperator.build(
        _graph(),
        ["a", "b", "terminal", "disconnected"],
        radius_m=1_100.0,
        graph_checksum="fixture",
    )
    path = operator.save(tmp_path / "operator.npz")
    loaded = RadiusSumOperator.load(path)
    assert loaded.cells.tolist() == operator.cells.tolist()
    assert loaded.source_cells.tolist() == operator.source_cells.tolist()
    assert loaded.indices.tolist() == operator.indices.tolist()
    assert loaded.connector_semantics == operator.connector_semantics


def test_radius_operator_includes_sources_outside_target_support() -> None:
    operator = RadiusSumOperator.build(
        _graph(),
        ["a"],
        source_cells=["a", "b", "terminal", "disconnected"],
        radius_m=1_100.0,
        graph_checksum="fixture",
    )
    values = np.asarray([0.0, 3.0, 0.0, 0.0])
    observed = operator.apply(values, eligible_sources=values > 0)
    assert observed.tolist() == pytest.approx([3.0])


def test_radius_operator_aligns_target_values_to_rectangular_source_support() -> None:
    operator = RadiusSumOperator.build(
        _graph(),
        ["a", "terminal", "disconnected"],
        source_cells=["a", "b", "terminal", "disconnected"],
        radius_m=1_300.0,
        graph_checksum="fixture",
    )
    values = np.asarray([1.0, 4.0, 8.0])
    observed = operator.apply(values, eligible_sources=np.ones(3, dtype=bool))
    assert observed.tolist() == pytest.approx([5.0, 5.0, 8.0])
