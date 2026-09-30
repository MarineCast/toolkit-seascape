from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Polygon, box

from seascape.coastal_configuration.coast_complexity import (
    headland_candidates,
    shoreline_sinuosity,
    summarize_coast,
)


def test_sinuosity_and_axial_wraparound() -> None:
    assert shoreline_sinuosity(LineString([(0, 0), (100, 0)])) == 1
    semicircle = LineString(
        [
            (100 * math.cos(t), 100 * math.sin(t))
            for t in [math.pi * k / 100 for k in range(101)]
        ]
    )
    assert shoreline_sinuosity(semicircle) == pytest.approx(math.pi / 2, rel=1e-4)
    lines = [
        LineString([(0, 0), (100, 1)]),
        LineString([(100, 20), (0, 21)]),
    ]
    support = box(-10, -10, 110, 40)
    water = box(-10, -10, 110, 10)
    island = box(20, 0, 40, 5)
    result = summarize_coast(
        lines,
        support,
        water,
        {"source:island": island},
        box(-100, -100, 200, 200).boundary,
        minimum_island_area_m2=10,
        normal_probe_m=1,
    )
    assert result.axial_orientation_deg is not None
    assert min(result.axial_orientation_deg, 180 - result.axial_orientation_deg) < 1
    assert result.orientation_concentration == pytest.approx(1, rel=1e-3)
    assert result.island_count == 1
    assert result.island_ids == ("source:island",)
    assert result.island_area_within_support_m2 == 100
    clipped = summarize_coast(
        lines,
        support,
        water,
        {"mainland?": box(100, 0, 250, 10)},
        box(-100, -100, 200, 200).boundary,
        minimum_island_area_m2=10,
        normal_probe_m=1,
    )
    assert clipped.island_count == 0
    assert clipped.boundary_censored_island_ids == ("mainland?",)


def test_land_sided_headland_excludes_bay() -> None:
    headland = LineString([(0, 0), (1, 1), (0, 2)])
    headland_land = Polygon([(-5, -5), (0, 0), (1, 1), (0, 2), (-5, 5)])
    candidates = headland_candidates(
        "coast-1",
        headland,
        headland_land,
        smoothing_distance_m=1,
        station_spacing_m=0.1,
        minimum_turn_degrees=30,
        side_probe_m=0.1,
    )
    assert candidates
    bay = LineString([(0, 0), (-1, 1), (0, 2)])
    bay_land = Polygon([(-5, -5), (0, 0), (-1, 1), (0, 2), (-5, 5)])
    assert not headland_candidates(
        "coast-2",
        bay,
        bay_land,
        smoothing_distance_m=1,
        station_spacing_m=0.1,
        minimum_turn_degrees=30,
        side_probe_m=0.1,
    )
