from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import seascape.seafloor_physiography.geomorphometry.build as terrain
from seascape.seafloor_physiography.geomorphic_units.build import (
    _terrain_context,
    load_geomorphic_units_config,
)
from seascape.seafloor_physiography.geomorphometry.build import (
    _circular_aspect_metrics,
    _plane_metrics,
    _quadratic_curvatures,
    _vector_ruggedness,
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


def test_curvature_distinguishes_horizontal_plan_from_surface_tangential() -> None:
    centers = {f"{x},{y}": (float(x), float(y)) for x in (-1, 0, 1) for y in (-1, 0, 1)}
    neighbors = [cell for cell in centers if cell != "0,0"]

    def evaluate(surface):
        depths = {cell: 100.0 - surface(*xy) for cell, xy in centers.items()}
        return _quadratic_curvatures("0,0", neighbors, depths, centers)

    legacy, general, profile, plan, tangential = evaluate(
        lambda x, y: 0.1 * x + 0.01 * y * y
    )
    assert legacy == pytest.approx(0.02)
    assert general == pytest.approx(-0.02)
    assert profile == pytest.approx(0.0, abs=1e-10)
    # Horizontal contour x = -0.1 y² at the origin has curvature -0.2 / m.
    assert plan == pytest.approx(-0.2)
    assert tangential == pytest.approx(-0.02 / math.sqrt(1.01))

    for surface, expected_general in (
        (lambda x, y: 0.1 * x + 0.2 * y, 0.0),
        (lambda x, y: -(x * x + y * y), 4.0),
        (lambda x, y: x * x + y * y, -4.0),
        (lambda x, y: x * x - y * y, 0.0),
    ):
        _legacy, general, _profile, _plan, _tangent = evaluate(surface)
        assert general == pytest.approx(expected_general)
    rank_deficient = {cell: (float(index), 0.0) for index, cell in enumerate(centers)}
    assert all(
        math.isnan(value)
        for value in _quadratic_curvatures(
            "0,0", neighbors, {cell: 100.0 for cell in centers}, rank_deficient
        )
    )


def test_flat_facets_contribute_vertical_normals_to_vrm() -> None:
    assert _vector_ruggedness(
        ["a", "b"], {"a": 0.0, "b": 0.0}, {"a": math.nan, "b": math.nan}
    ) == pytest.approx(0.0)
    mixed = _vector_ruggedness(
        ["flat", "tilted"],
        {"flat": 0.0, "tilted": 60.0},
        {"flat": math.nan, "tilted": 90.0},
    )
    assert mixed == pytest.approx(1.0 - math.sqrt(3) / 2)


def test_nonzero_position_with_zero_neighbor_variance_is_undefined(monkeypatch) -> None:
    cells = ["focal", "east", "west", "north", "south"]
    coords = {
        "focal": (0.0, 0.0),
        "east": (1.0, 0.0),
        "west": (-1.0, 0.0),
        "north": (0.0, 1.0),
        "south": (0.0, -1.0),
    }
    frame = pd.DataFrame(
        {"H3_INDEX": cells, "BATHYMETRY": [50.0, 100.0, 100.0, 100.0, 100.0]}
    )
    neighbors = {"focal": tuple(cells[1:])}
    monkeypatch.setattr(terrain, "_projected_centers", lambda *_args: coords)
    config = replace(terrain.load_geomorphometry_config(), neighborhood_rings=(1,))
    result = terrain._derive_metrics(frame, config, {1: neighbors}).set_index(
        "H3_INDEX"
    )
    assert result.loc["focal", "TERRAIN_POSITION_RING_1_M"] == 50.0
    assert np.isnan(result.loc["focal", "TERRAIN_POSITION_RING_1_Z"])
    assert (
        result.loc["focal", "TERRAIN_POSITION_RING_1_Z_QC_REASON"]
        == "zero_neighbor_variance_nonzero_position"
    )
    geomorphic = frame.assign(SLOPE=2.0, TERRAIN_POSITION=50.0)
    unit_config = load_geomorphic_units_config()
    context = _terrain_context(
        geomorphic,
        np.asarray([coords[cell] for cell in cells]),
        unit_config,
        {unit_config.broad_neighborhood_rings: neighbors, 1: neighbors},
    )
    assert context["BROAD_TPI"][0] == 50.0
    assert np.isnan(context["BROAD_Z"][0])
