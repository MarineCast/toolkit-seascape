from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from seascape.utils.habitat_surface import habitat_topology_for_support


def _inventory(*geometries: Polygon) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "COMPOSITION_ELIGIBLE": [True] * len(geometries),
            "SUPPORTS_AREA": [True] * len(geometries),
            "OBSERVATION_STATUS": ["present"] * len(geometries),
            "COVERAGE_WEIGHT": [1.0] * len(geometries),
            "GEOMETRY_ROLE": ["observation"] * len(geometries),
            "OBSERVED_VS_MODELED": ["observed"] * len(geometries),
            "OBSERVATION_YEAR": [2025] * len(geometries),
            "SOURCE_PRIORITY": [0] * len(geometries),
            "SURVEY_COMPLETENESS": ["unknown"] * len(geometries),
            "SURVEY_EVENT_ID": [None] * len(geometries),
            "RECORD_ID": [f"patch-{i}" for i in range(len(geometries))],
        },
        geometry=list(geometries),
        crs="EPSG:6933",
    )


def _support(*geometries: Polygon) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"H3_INDEX": [f"cell-{index}" for index in range(len(geometries))]},
        geometry=list(geometries),
        crs="EPSG:6933",
    )


def test_continuous_rectangle_topology_is_independent_of_reporting_split() -> None:
    patch = box(0, 0, 200, 100)
    split = _support(box(-10, -10, 100, 110), box(100, -10, 210, 110))
    union = _support(box(-10, -10, 210, 110))
    child = habitat_topology_for_support(split, _inventory(patch), "EPSG:6933")
    parent = habitat_topology_for_support(union, _inventory(patch), "EPSG:6933")
    assert child["HABITAT_AREA_M2"].sum() == pytest.approx(20_000)
    assert child["EDGE_LENGTH_M"].sum() == pytest.approx(600)
    assert child["TOPOLOGY_QC_REASON"].eq("reporting_boundary_truncated").all()
    row = parent.iloc[0]
    assert row["HABITAT_AREA_M2"] == pytest.approx(20_000)
    assert row["PATCH_COUNT"] == 1
    assert row["LARGEST_PATCH_AREA_M2"] == pytest.approx(20_000)
    assert row["EDGE_LENGTH_M"] == pytest.approx(600)
    assert pd.isna(row["TOPOLOGY_QC_REASON"])
    assert 1 - row["LARGEST_PATCH_AREA_M2"] / row["HABITAT_AREA_M2"] == 0


def test_duplicate_polygons_holes_and_contact_rules() -> None:
    support = _support(box(-10, -10, 50, 50))
    outer_with_hole = Polygon(
        box(0, 0, 20, 20).exterior.coords,
        [box(5, 5, 10, 10).exterior.coords],
    )
    duplicate = habitat_topology_for_support(
        support, _inventory(outer_with_hole, outer_with_hole), "EPSG:6933"
    ).iloc[0]
    assert duplicate["HABITAT_AREA_M2"] == pytest.approx(375)
    assert duplicate["PATCH_COUNT"] == 1
    assert duplicate["EDGE_LENGTH_M"] == pytest.approx(100)

    edge_touch = habitat_topology_for_support(
        support, _inventory(box(0, 0, 10, 10), box(10, 0, 20, 10)), "EPSG:6933"
    ).iloc[0]
    point_touch = habitat_topology_for_support(
        support, _inventory(box(0, 0, 10, 10), box(10, 10, 20, 20)), "EPSG:6933"
    ).iloc[0]
    disjoint = habitat_topology_for_support(
        support, _inventory(box(0, 0, 10, 10), box(30, 30, 40, 40)), "EPSG:6933"
    ).iloc[0]
    assert edge_touch["PATCH_COUNT"] == 1
    assert edge_touch["EDGE_LENGTH_M"] == pytest.approx(60)
    assert point_touch["PATCH_COUNT"] == 2
    assert disjoint["PATCH_COUNT"] == 2


def test_empty_or_support_clipped_patch_has_explicit_topology_state() -> None:
    support = _support(box(0, 0, 10, 10))
    empty = habitat_topology_for_support(
        support, _inventory(box(20, 20, 30, 30)), "EPSG:6933"
    ).iloc[0]
    assert empty["PATCH_COUNT"] == 0
    assert empty["TOPOLOGY_QC_REASON"] == "no_mapped_patch"
    clipped = habitat_topology_for_support(
        support, _inventory(box(-5, 2, 5, 8)), "EPSG:6933"
    ).iloc[0]
    assert clipped["HABITAT_AREA_M2"] == pytest.approx(30)
    assert clipped["EDGE_LENGTH_M"] == pytest.approx(16)
    assert clipped["TOPOLOGY_QC_REASON"] == "reporting_boundary_truncated"


def test_actual_neighboring_h3_cells_do_not_count_shared_clip_as_edge() -> None:
    import h3
    from shapely.geometry import Polygon

    origin = h3.latlng_to_cell(48.55, -123.05, 8)
    neighbor = next(cell for cell in h3.grid_ring(origin, 1) if cell != origin)
    geometries = [
        Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(cell)])
        for cell in (origin, neighbor)
    ]
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": [origin, neighbor]}, geometry=geometries, crs="EPSG:4326"
    ).to_crs("EPSG:6933")
    shared = cells.geometry.iloc[0].boundary.intersection(
        cells.geometry.iloc[1].boundary
    )
    assert shared.length > 0
    patch = cells.geometry.iloc[0].union(cells.geometry.iloc[1]).buffer(-5)
    if patch.is_empty:
        pytest.skip("H3 fixture too small after metric buffer")
    inventory = _inventory(patch)
    children = habitat_topology_for_support(cells, inventory, "EPSG:6933")
    parent = habitat_topology_for_support(
        _support(cells.geometry.iloc[0].union(cells.geometry.iloc[1])),
        inventory,
        "EPSG:6933",
    )
    assert children["HABITAT_AREA_M2"].sum() == pytest.approx(
        parent.iloc[0]["HABITAT_AREA_M2"], rel=1e-6
    )
    assert np.isfinite(parent.iloc[0]["EDGE_LENGTH_M"])
