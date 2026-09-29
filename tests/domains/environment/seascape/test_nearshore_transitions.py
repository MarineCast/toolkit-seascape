from __future__ import annotations

import numpy as np
import pandas as pd
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from seascape.coastal_configuration.nearshore_build import _deep_network_distance
from seascape.coastal_configuration.nearshore_transitions import (
    bounded_deep_target_components,
    first_water_facing_contour,
    nearshore_depth_areas,
)
from seascape.spatial_support.water_network.graph import WaterGraph


def test_pixel_footprint_denominators_and_analytic_slope() -> None:
    values = np.tile(np.arange(5, 105, 10, dtype="float32"), (10, 1))
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=10,
            height=10,
            count=1,
            dtype="float32",
            crs="EPSG:32610",
            transform=from_origin(0, 100, 10, 10),
            nodata=-9999,
        ) as raster:
            raster.write(values, 1)
            water = box(0, 0, 100, 100)
            coast = LineString([(0, 0), (0, 100)])
            result = nearshore_depth_areas(
                box(0, 0, 100, 100), water, coast, raster,
                depth_threshold_m=25, band_width_m=50,
            )
            assert result.eligible_area_m2 == 5000
            assert result.valid_area_m2 == 5000
            assert result.deep_area_m2 == 3000
            assert result.deep_fraction_of_valid == 0.6
            crossing = first_water_facing_contour(
                Point(0, 50), (0, 1), water, raster,
                depth_threshold_m=25, step_m=10, max_distance_m=90,
            )
            assert crossing.status == "crossed"
            assert crossing.width_m == 20
            assert crossing.gradient_m_per_m == 1
            values[:, 1] = -9999
            raster.write(values, 1)
            partial = nearshore_depth_areas(
                box(0, 0, 100, 100), water, coast, raster,
                depth_threshold_m=25, band_width_m=50,
            )
            assert partial.valid_area_m2 == 4000
            assert partial.deep_fraction_of_valid == 0.75
            assert partial.bathymetry_coverage_fraction == 0.8
            assert first_water_facing_contour(
                Point(0, 50), (0, 1), water, raster,
                depth_threshold_m=25, step_m=10, max_distance_m=90,
            ).status == "nodata_censored"


def test_island_blocks_transect_before_deep_water() -> None:
    values = np.tile(np.arange(5, 105, 10, dtype="float32"), (10, 1))
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=10, height=10, count=1,
            dtype="float32", crs="EPSG:32610",
            transform=from_origin(0, 100, 10, 10),
        ) as raster:
            raster.write(values, 1)
            water = box(0, 0, 100, 100).difference(box(15, 40, 25, 60))
            result = first_water_facing_contour(
                Point(0, 50), (0, 1), water, raster,
                depth_threshold_m=55, step_m=5, max_distance_m=90,
            )
            assert result.status == "land_censored"


def test_subpixel_support_reads_both_intersecting_footprints() -> None:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=2, height=1, count=1,
            dtype="float32", crs="EPSG:32610",
            transform=from_origin(0, 10, 10, 10),
        ) as raster:
            raster.write(np.array([[5, 50]], dtype="float32"), 1)
            result = nearshore_depth_areas(
                box(9.9, 0, 10.1, 10), box(0, 0, 20, 10),
                LineString([(0, 0), (0, 10)]), raster,
                depth_threshold_m=25, band_width_m=20,
            )
            assert np.isclose(result.eligible_area_m2, 2)
            assert np.isclose(result.valid_area_m2, 2)
            assert np.isclose(result.deep_area_m2, 1)


def test_bounded_native_raster_deep_components_remain_distinct() -> None:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=5, height=2, count=1,
            dtype="float32", crs="EPSG:32610",
            transform=from_origin(0, 20, 10, 10),
        ) as raster:
            raster.write(np.array([[50, 50, 5, 50, 50]] * 2, dtype="float32"), 1)
            cells = [("left", box(0, 0, 20, 20)), ("right", box(30, 0, 50, 20))]
            components, by_cell = bounded_deep_target_components(
                cells, box(0, 0, 50, 20), LineString([(0, 0), (50, 0)]),
                raster, depth_threshold_m=25, band_width_m=20, max_pixels=10,
            )
            assert len(components) == 2
            assert all(str(row["DEEP_COMPONENT_ID"]).startswith("deep:synthetic-raster:25m:") for row in components)
            assert components[0]["PIXEL_COUNT"] == 4
            assert len(by_cell["left"]) == len(by_cell["right"]) == 1
            assert by_cell["left"] != by_cell["right"]
            with np.testing.assert_raises_regex(ValueError, "pixel budget"):
                bounded_deep_target_components(
                    cells, box(0, 0, 50, 20), LineString([(0, 0), (50, 0)]),
                    raster, depth_threshold_m=25, band_width_m=20, max_pixels=9,
                )


def test_network_distance_identifies_the_reached_deep_component() -> None:
    graph = WaterGraph(
        8, np.array(["a", "b", "c"]), np.array([0, 1, 3, 4]),
        np.array([1, 0, 2, 1]), np.array([100, 100, 300, 300], dtype=float),
        pd.DataFrame({"H3_INDEX": ["a", "b", "c"]}),
        {"a": 0, "b": 1, "c": 2}, "fixture", "fixture",
    )
    table = pd.DataFrame({
        "H3_INDEX": ["a", "b", "c"],
        "DEEP_TARGET_COMPONENT_IDS": ["left", "", "right"],
    })
    distances, qc, nearest = _deep_network_distance(table, graph, resolution=8)
    assert distances.tolist() == [0, 100, 0]
    assert qc == ["mapped_deep_h3_target_graph_v1"] * 3
    assert nearest == ["left", "left", "right"]
