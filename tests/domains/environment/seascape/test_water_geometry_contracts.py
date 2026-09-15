from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from seascape.spatial_support.water_geometry.geometry_operations import (
    polygonize_boundary_cycle,
)


def test_boundary_polygonization_is_order_independent_and_drops_spurs() -> None:
    square = [
        LineString([(0, 0), (10, 0)]),
        LineString([(10, 0), (10, 10)]),
        LineString([(10, 10), (0, 10)]),
        LineString([(0, 10), (0, 0)]),
        LineString([(10, 10), (20, 20)]),
    ]
    frame = gpd.GeoDataFrame(geometry=square, crs="EPSG:3857")
    expected = polygonize_boundary_cycle(
        frame,
        snap_tolerance_m=0.1,
        projected_crs="EPSG:3857",
    )
    shuffled = polygonize_boundary_cycle(
        frame.sample(frac=1.0, random_state=4),
        snap_tolerance_m=0.1,
        projected_crs="EPSG:3857",
    )
    assert expected.area == pytest.approx(100.0)
    assert expected.equals_exact(shuffled, tolerance=1e-9)


def test_boundary_polygonization_rejects_open_linework() -> None:
    frame = gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])],
        crs="EPSG:3857",
    )
    with pytest.raises(ValueError, match="no closed cycle"):
        polygonize_boundary_cycle(
            frame,
            snap_tolerance_m=0.1,
            projected_crs="EPSG:3857",
        )


def test_boundary_polygonization_rejects_empty_and_ambiguous_cycles() -> None:
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:3857")
    with pytest.raises(ValueError, match="nonempty"):
        polygonize_boundary_cycle(empty, snap_tolerance_m=0.1, projected_crs="EPSG:3857")

    first = [
        LineString([(0, 0), (10, 0)]),
        LineString([(10, 0), (10, 10)]),
        LineString([(10, 10), (0, 10)]),
        LineString([(0, 10), (0, 0)]),
    ]
    second = [
        LineString([(20, 0), (30, 0)]),
        LineString([(30, 0), (30, 10)]),
        LineString([(30, 10), (20, 10)]),
        LineString([(20, 10), (20, 0)]),
    ]
    ambiguous = gpd.GeoDataFrame(geometry=[*first, *second], crs="EPSG:3857")
    with pytest.raises(ValueError, match="multiple comparable"):
        polygonize_boundary_cycle(
            ambiguous,
            snap_tolerance_m=0.1,
            projected_crs="EPSG:3857",
        )
