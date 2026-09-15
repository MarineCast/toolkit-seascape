from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from seascape.seafloor_physiography.bathymetry.build import (
    DEPTH_BANDS_M,
    _depth_band_membership,
    _isobath_crossings,
    _local_depth_anomaly,
)
from seascape.seafloor_physiography.bathymetry.pipeline import (
    recompute_parent_depth_bands,
)


def test_isobath_crossing_requires_both_edge_endpoints_to_be_marine() -> None:
    depth = np.array([[5.0, 0.0]])
    marine = np.array([[True, False]])
    latitude = np.array([[48.0, 48.0]])
    longitude = np.array([[-123.0, -122.9]])
    with pytest.raises(ValueError, match="does not cross"):
        _isobath_crossings(depth, marine, latitude, longitude, 2.5)

    crossings = _isobath_crossings(
        np.array([[1.0, 5.0]]),
        np.array([[True, True]]),
        latitude,
        longitude,
        2.5,
    )
    assert crossings.shape == (1, 2)
    assert -123.0 < crossings[0, 0] < -122.9


def test_depth_bands_are_half_open_and_exhaustive_for_valid_depths() -> None:
    depth = np.array([0.0, 9.999, 10.0, 29.999, 30.0, 50.0, 100.0, 199.999, 200.0])
    membership = _depth_band_membership(depth)
    stacked = np.column_stack(list(membership.values()))
    assert (stacked.sum(axis=1) == 1).all()
    assert membership["0_10"].tolist()[:3] == [True, True, False]
    assert membership["10_30"][2]
    assert membership["OVER_200"][-1]


def test_local_anomaly_uses_only_water_connected_neighbors() -> None:
    cells = ["a", "b", "c"]
    depth = pd.Series([10.0, 20.0, 1000.0])
    neighborhoods = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": ["a", "a", "b", "b", "c"],
            "TARGET_H3_INDEX": ["a", "b", "b", "a", "c"],
            "MINIMUM_HOP_COUNT": [0, 1, 0, 1, 0],
            "NETWORK_DISTANCE_M": [0.0, 500.0, 0.0, 500.0, 0.0],
        }
    )
    anomaly = _local_depth_anomaly(cells, depth, 2, neighborhoods)
    assert anomaly[0] == pytest.approx(-10.0)
    assert anomaly[1] == pytest.approx(10.0)
    assert np.isnan(anomaly[2])


def test_parent_depth_fractions_are_recomputed_from_summed_child_counts(tmp_path) -> None:
    import h3

    parent = h3.latlng_to_cell(48.5, -123.2, 6)
    children = sorted(h3.cell_to_children(parent, 8))[:2]
    count_columns = [f"BATHYMETRY_PIXEL_COUNT_{token}_M" for token, _lower, _upper in DEPTH_BANDS_M]
    child = pd.DataFrame({"H3_INDEX": children})
    for index, column in enumerate(count_columns, start=1):
        child[column] = [index, index + 1]
    parent_frame = pd.DataFrame({"H3_INDEX": [parent], "BATHYMETRY_PIXEL_COUNT": [999]})
    for column in count_columns:
        parent_frame[column] = 999
    for token, _lower, _upper in DEPTH_BANDS_M:
        parent_frame[f"BATHYMETRY_FRAC_{token}_M"] = -1.0
    child_path = tmp_path / "r8.parquet"
    parent_path = tmp_path / "r6.parquet"
    child.to_parquet(child_path, index=False)
    parent_frame.to_parquet(parent_path, index=False)

    recompute_parent_depth_bands(child_path, parent_path, parent_resolution=6)
    rebuilt = pd.read_parquet(parent_path).iloc[0]
    expected_total = sum((index + index + 1) for index in range(1, len(count_columns) + 1))
    assert rebuilt["BATHYMETRY_PIXEL_COUNT"] == expected_total
    assert sum(
        rebuilt[f"BATHYMETRY_FRAC_{token}_M"] for token, _, _ in DEPTH_BANDS_M
    ) == pytest.approx(1.0)
