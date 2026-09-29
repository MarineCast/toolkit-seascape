from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from seascape.seafloor_physiography.bathymetry.build import (
    DEPTH_BANDS_M,
    _aggregate_raster,
    _depth_band_membership,
    _isobath_crossings,
    _local_depth_anomaly,
)
from seascape.seafloor_physiography.bathymetry.download import _retrying_session


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


def test_r6_direct_pixel_support_does_not_inherit_neighboring_r8_child(
    tmp_path,
) -> None:
    import h3
    import rasterio
    from rasterio.transform import from_origin

    # Controlled point in child 8828d10425fffff, whose hierarchical R6
    # parent differs from the cell found by direct R6 coordinate assignment.
    latitude, longitude = 48.563551186379655, -123.05173211437292
    child = "8828d10425fffff"
    hierarchical_parent = "8628d1047ffffff"
    direct_parent = "8628d1057ffffff"
    assert h3.latlng_to_cell(latitude, longitude, 8) == child
    assert h3.cell_to_parent(child, 6) == hierarchical_parent
    assert h3.latlng_to_cell(latitude, longitude, 6) == direct_parent
    raster = tmp_path / "one-valid-one-nodata.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=2,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(longitude - 0.0001, latitude + 0.0001, 0.0002, 0.0002),
        nodata=-32767,
    ) as dst:
        dst.write(np.array([[-25.0, -32767.0]], dtype="float32"), 1)
    neighborhoods = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": [],
            "TARGET_H3_INDEX": [],
            "MINIMUM_HOP_COUNT": [],
            "NETWORK_DISTANCE_M": [],
        }
    )

    def aggregate(cells: list[str], resolution: int) -> pd.DataFrame:
        return _aggregate_raster(
            raster,
            cells,
            resolution,
            "positive_down",
            (0.25, 0.75),
            1,
            (),
            "EPSG:32610",
            neighborhoods,
        ).set_index("H3_INDEX")

    r8 = aggregate([child], 8)
    r6 = aggregate([hierarchical_parent, direct_parent], 6)
    assert r8.loc[child, "BATHYMETRY_PIXEL_COUNT"] == 1
    assert r6.loc[direct_parent, "BATHYMETRY"] == 25.0
    assert r6.loc[direct_parent, "BATHYMETRY_PIXEL_COUNT"] == 1
    assert r6.loc[direct_parent, "BATHYMETRY_MEDIAN"] == 25.0
    assert r6.loc[direct_parent, "BATHYMETRY_Q25"] == 25.0
    assert pd.isna(r6.loc[hierarchical_parent, "BATHYMETRY"])
    assert pd.isna(r6.loc[hierarchical_parent, "BATHYMETRY_PIXEL_COUNT"])
    assert pd.isna(r6.loc[hierarchical_parent, "BATHYMETRY_FRAC_10_30_M"])
    for cell in (child, direct_parent):
        row = r8.loc[cell] if cell == child else r6.loc[cell]
        counts = [
            row[f"BATHYMETRY_PIXEL_COUNT_{token}_M"] for token, _, _ in DEPTH_BANDS_M
        ]
        fractions = [row[f"BATHYMETRY_FRAC_{token}_M"] for token, _, _ in DEPTH_BANDS_M]
        assert sum(counts) == row["BATHYMETRY_PIXEL_COUNT"]
        assert sum(fractions) == pytest.approx(1.0)


def test_missing_bathymetry_source_fails_before_publication(tmp_path) -> None:
    from types import SimpleNamespace

    from seascape.seafloor_physiography.bathymetry.build import (
        build_bathymetry_parquet,
    )

    missing = tmp_path / "absent-gebco.tif"
    config = SimpleNamespace(raw_path=missing)
    with pytest.raises(FileNotFoundError, match="GEBCO GeoTIFF not found"):
        build_bathymetry_parquet(config)


def test_gebco_session_retries_transient_status_reads_but_not_queue_posts() -> None:
    session = _retrying_session()
    policy = session.get_adapter("https://").max_retries

    assert policy.total == 5
    assert policy.read == 5
    assert 503 in policy.status_forcelist
    assert "GET" in policy.allowed_methods
    assert "POST" not in policy.allowed_methods
