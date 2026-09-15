from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer
from shapely.geometry import LineString

from seascape.coastal_configuration.exposure_and_enclosure.build import (
    _open_water_seed_positions,
)
from seascape.coastal_configuration.shoreline_proximity.build import (
    _shoreline_distances,
)
from seascape.coastal_configuration.waterbody_morphometry.build import (
    _bounded_adjacency_positions,
    _constriction_indices,
    _sill_candidates,
    _width_metrics,
)


def test_open_water_seeds_require_a_materialized_open_water_class() -> None:
    openness = np.asarray([0.25, 0.60, 0.61])

    assert _open_water_seed_positions(openness, 0.60).tolist() == [1, 2]
    with pytest.raises(ValueError, match="maximum graph openness was 0.610"):
        _open_water_seed_positions(openness, 0.75)


def test_width_and_constriction_mechanisms_preserve_local_narrows() -> None:
    rays = np.full((3, 16), 1_000.0)
    rays[1, 0] = 100.0
    rays[1, 8] = 100.0
    width = _width_metrics(rays, maximum_search_m=1_000.0)["LOCAL_WATERBODY_WIDTH_M"]
    adjacency = [(1,), (0, 2), (1,)]

    constriction = _constriction_indices(width, adjacency, neighborhood_rings=1)

    assert width.tolist() == [2_000.0, 200.0, 2_000.0]
    assert constriction[1] == pytest.approx(0.9)
    assert constriction[[0, 2]].tolist() == [0.0, 0.0]
    assert _bounded_adjacency_positions(0, adjacency, 1) == [0, 1]


def test_sill_candidates_require_relief_width_and_constriction(tmp_path) -> None:
    bathymetry_path = tmp_path / "bathymetry.parquet"
    pd.DataFrame({"H3_INDEX": ["a", "b", "c"], "BATHYMETRY": [30.0, 10.0, 30.0]}).to_parquet(
        bathymetry_path, index=False
    )
    config = SimpleNamespace(
        bathymetry_path=bathymetry_path,
        sill_neighborhood_rings=1,
        sill_minimum_neighbors=2,
        sill_min_relief_m=15.0,
        sill_max_width_km=1.0,
        sill_min_constriction=0.5,
    )

    candidates = _sill_candidates(
        config,
        ["a", "b", "c"],
        [(1,), (0, 2), (1,)],
        np.asarray([2_000.0, 500.0, 2_000.0]),
        np.asarray([0.0, 0.75, 0.0]),
    )

    assert candidates.tolist() == [1]


def test_shoreline_distance_uses_projected_nearest_geometry() -> None:
    shoreline = LineString([(-123.0, 48.0), (-123.0, 49.0)])
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True)
    x_on, y_on = transformer.transform(-123.0, 48.5)
    x_off, y_off = transformer.transform(-122.9, 48.5)

    distances = _shoreline_distances(
        shoreline,
        np.asarray([x_on, x_off]),
        np.asarray([y_on, y_off]),
        "EPSG:32610",
    )

    assert distances[0] == pytest.approx(0.0, abs=1e-6)
    assert distances[1] > 7_000.0
