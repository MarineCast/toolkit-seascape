"""Scientific invariants for recovered source-bound producers."""

import numpy as np
import pytest
from shapely import LineString

from seascape.regional.shoreline_union import _physical_line_union_lengths


def test_shoreline_duplicate_evidence_not_double_length():
    line = LineString([(0, 0), (10, 0)])
    total, known, classes, availability, disagreement = _physical_line_union_lengths(
        [
            (line, True, ("ROCKY",)),
            (line, True, ("ROCKY",)),
            (line, True, ("SANDY",)),
            (line, False, ()),
        ]
    )
    assert total == known == 10
    assert classes["ROCKY"] == classes["SANDY"] == 10
    assert availability == disagreement == 10


def test_percent_unknown_renormalizes_without_zero_fill():
    from seascape.regional.substrate import blend

    values, weight, count = blend(
        [[25, 75, -99, -99]], [[0.25, 0.25, 0.25, 0.25]], [[False, False, True, True]]
    )
    assert values[0] == 0.5 and weight[0] == 0.5 and count[0] == 2
    values, _, _ = blend([[0, 0, 0, 0]], [[0.25] * 4], [[True] * 4])
    assert np.isnan(values[0])


def test_source_percent_outside_range_rejected():
    from seascape.regional.substrate import blend

    with pytest.raises(ValueError, match="outside"):
        blend([[101]], [[1]], [[False]])
