from __future__ import annotations

import math

import pytest

from seascape.seafloor_physiography.geomorphometry.build import (
    _circular_aspect_metrics,
    _plane_metrics,
)


def test_plane_slope_and_flat_aspect_contract() -> None:
    centers = {
        "center": (0.0, 0.0),
        "east": (1.0, 0.0),
        "west": (-1.0, 0.0),
        "north": (0.0, 1.0),
        "south": (0.0, -1.0),
    }
    neighbors = ["east", "west", "north", "south"]
    planar_depths = {cell: 10.0 + centers[cell][0] for cell in centers}
    slope, aspect = _plane_metrics("center", neighbors, planar_depths, centers)
    assert slope == pytest.approx(45.0)
    assert aspect == pytest.approx(90.0)

    flat_depths = {cell: 10.0 for cell in centers}
    flat_slope, flat_aspect = _plane_metrics("center", neighbors, flat_depths, centers)
    assert flat_slope == pytest.approx(0.0)
    assert math.isnan(flat_aspect)


def test_aspect_aggregation_is_circular_across_north() -> None:
    _slope, aspect, resultant = _circular_aspect_metrics(
        ["left", "right"],
        {"left": 5.0, "right": 5.0},
        {"left": 359.0, "right": 1.0},
    )
    assert aspect == pytest.approx(0.0, abs=1e-10)
    assert resultant > 0.99
