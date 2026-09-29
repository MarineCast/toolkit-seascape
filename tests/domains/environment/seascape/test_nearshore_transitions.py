from __future__ import annotations

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from seascape.coastal_configuration.nearshore_transitions import (
    first_water_facing_contour,
    nearshore_depth_areas,
)


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
