import math

import h3
import numpy as np
import pandas as pd
import rasterio
import shapely

from seascape.seafloor_physiography.geomorphometry.build import (
    _native_raster_slope_summary,
)


def equal(a, b, tol=1e-08):
    if not (math.isnan(a) and math.isnan(b) or abs(a - b) <= tol):
        raise ValueError((a, b))


def native_slope_batch(selected, depths, raster_path, guard):
    native_rows = []
    with rasterio.Env(GDAL_CACHEMAX=16 * 1024**2), rasterio.open(raster_path) as raster:
        for cell in selected:
            boundary = shapely.Polygon(
                [(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]
            )
            window = rasterio.windows.from_bounds(*boundary.bounds, raster.transform)
            col = max(0, math.floor(window.col_off) - 2)
            first = max(0, math.floor(window.row_off) - 2)
            endcol = min(raster.width, math.ceil(window.col_off + window.width) + 2)
            endrow = min(raster.height, math.ceil(window.row_off + window.height) + 2)
            window = rasterio.windows.Window(col, first, endcol - col, endrow - first)
            array = raster.read(1, window=window)
            transform = raster.window_transform(window)
            profile = raster.profile.copy()
            profile.update(
                height=array.shape[0],
                width=array.shape[1],
                transform=transform,
                driver="GTiff",
            )
            with rasterio.io.MemoryFile() as memory:
                with memory.open(**profile) as local:
                    local.write(array, 1)
                try:
                    native = (
                        _native_raster_slope_summary(memory.read(), {cell}, 8, 0.9)
                        .set_index("H3_INDEX")
                        .loc[cell]
                    )
                    producer_mean = float(native.SLOPE_MEAN_NATIVE_RASTER)
                    producer_q90 = float(native.SLOPE_Q90_NATIVE_RASTER)
                except ValueError as error:
                    if (
                        not str(error)
                        == "No native-raster slope pixels overlap the H3 bathymetry universe."
                    ):
                        raise ValueError("Scientific validation failed")
                    producer_mean = producer_q90 = math.nan
            slopes = []
            marine_count = expected_count = 0
            excluded_land = excluded_nodata = source_edge = 0
            for rr in range(1, array.shape[0] - 1):
                for cc in range(1, array.shape[1] - 1):
                    lon, lat = rasterio.transform.xy(transform, rr, cc, offset="center")
                    if h3.latlng_to_cell(lat, lon, 8) != cell:
                        continue
                    expected_count += 1
                    central = int(array[rr, cc])
                    if central == raster.nodata or central >= 0:
                        continue
                    marine_count += 1
                    cross = [
                        int(array[rr - 1, cc]),
                        int(array[rr + 1, cc]),
                        int(array[rr, cc - 1]),
                        int(array[rr, cc + 1]),
                    ]
                    if any((v == raster.nodata for v in cross)):
                        excluded_nodata += 1
                        continue
                    if any((v >= 0 for v in cross)):
                        excluded_land += 1
                        continue
                    dy = (cross[1] - cross[0]) / (2 * abs(transform.e) * 110574.0)
                    dx = (cross[3] - cross[2]) / (
                        2
                        * abs(transform.a)
                        * 111320.0
                        * max(math.cos(math.radians(lat)), 0.1)
                    )
                    slopes.append(math.degrees(math.atan(math.hypot(dx, dy))))
            if not expected_count == depths[cell]["NATIVE_EXPECTED_PIXEL_COUNT"]:
                raise ValueError("Scientific validation failed")
            if not marine_count == depths[cell]["NATIVE_VALID_MARINE_SAMPLE_COUNT"]:
                raise ValueError("Scientific validation failed")
            equal(producer_mean, float(np.mean(slopes)) if slopes else math.nan)
            equal(producer_q90, float(np.quantile(slopes, 0.9)) if slopes else math.nan)
            if not len(slopes) + excluded_land + excluded_nodata == marine_count:
                raise ValueError("Scientific validation failed")
            native_rows.append(
                {
                    "H3_INDEX": cell,
                    "SLOPE_MEAN_NATIVE_RASTER": producer_mean,
                    "SLOPE_Q90_NATIVE_RASTER": producer_q90,
                    "NATIVE_FULL_H3_PIXEL_COUNT": expected_count,
                    "NATIVE_MARINE_FOCAL_PIXEL_COUNT": marine_count,
                    "NATIVE_VALID_SLOPE_STENCIL_COUNT": len(slopes),
                    "NATIVE_STENCIL_LAND_EXCLUDED_COUNT": excluded_land,
                    "NATIVE_STENCIL_NODATA_EXCLUDED_COUNT": excluded_nodata,
                    "NATIVE_SOURCE_EDGE_STENCIL_COUNT": source_edge,
                    "NATIVE_SLOPE_STATUS": "valid_marine_stencil_subset"
                    if slopes
                    else "no_valid_marine_stencils"
                    if marine_count
                    else "no_native_marine_focal_samples",
                }
            )
            guard()
    return pd.DataFrame(native_rows).set_index("H3_INDEX")
