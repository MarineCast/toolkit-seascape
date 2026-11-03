"""Window edges preserve whole-raster marine slope and exact aggregation."""

import h3
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

from seascape.seafloor_physiography.geomorphometry.build import (
    _native_raster_slope_summary,
    validate_native_raster_header,
)


def original(raster_path, target_cells, resolution, quantile):
    with rasterio.open(raster_path) as raster:
        validate_native_raster_header(raster)
        elevation = raster.read(1, masked=True).astype("float64").filled(np.nan)
        transform = raster.transform

    rows, columns = np.indices(elevation.shape)
    longitudes, latitudes = rasterio.transform.xy(
        transform, rows, columns, offset="center"
    )
    latitudes = np.asarray(latitudes, dtype="float64").reshape(elevation.shape)
    longitudes = np.asarray(longitudes, dtype="float64").reshape(elevation.shape)
    marine = np.isfinite(elevation) & (elevation < 0.0)
    latitude_step_m = abs(float(transform.e)) * 110_574.0
    longitude_step_m = (
        abs(float(transform.a))
        * 111_320.0
        * np.maximum(np.cos(np.deg2rad(latitudes)), 0.1)
    )
    # Central differences require marine support on both sides. Raster edges
    # retain numpy's one-sided stencil; land and nodata never contribute.
    marine_elevation = np.where(marine, elevation, np.nan)
    gradient_row = np.gradient(marine_elevation, axis=0) / latitude_step_m
    gradient_column = np.gradient(marine_elevation, axis=1) / longitude_step_m
    slope = np.degrees(np.arctan(np.hypot(gradient_column, gradient_row)))
    valid = marine & np.isfinite(slope)
    valid_latitudes = latitudes[valid]
    valid_longitudes = longitudes[valid]
    pixel_cells = np.fromiter(
        (
            h3.latlng_to_cell(float(latitude), float(longitude), resolution)
            for latitude, longitude in zip(
                valid_latitudes, valid_longitudes, strict=True
            )
        ),
        dtype=object,
        count=len(valid_latitudes),
    )
    in_target = np.fromiter(
        (cell in target_cells for cell in pixel_cells),
        dtype=bool,
        count=len(pixel_cells),
    )
    samples = pd.DataFrame(
        {
            "H3_INDEX": pixel_cells[in_target],
            "NATIVE_SLOPE": slope[valid][in_target],
        }
    )
    return (
        samples.groupby("H3_INDEX", observed=True)["NATIVE_SLOPE"]
        .agg(
            SLOPE_MEAN_NATIVE_RASTER="mean",
            SLOPE_Q90_NATIVE_RASTER=lambda values: values.quantile(quantile),
        )
        .reset_index()
    )


def test_windowed_native_raster_exact_reference(tmp_path):
    rows, cols = np.indices((258, 30))
    z = -100.0 - rows * 0.3 - cols * 0.8 - np.sin(rows) * 5
    z[127, 12] = 2.0
    z[128, 13] = -9999.0
    z[255, 5] = 0.0
    z[0, 1] = -9999.0
    transform = from_origin(-123, 49, 0.004166666666666667, 0.004166666666666667)
    path = tmp_path / "realistic.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=258,
        width=30,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as raster:
        raster.write(z, 1)
    lon, lat = rasterio.transform.xy(transform, rows, cols, offset="center")
    keys = {
        h3.latlng_to_cell(float(y), float(x), 8)
        for x, y in zip(np.asarray(lon).ravel(), np.asarray(lat).ravel(), strict=True)
    }
    expected = original(path, keys, 8, 0.9)
    actual = _native_raster_slope_summary(path, keys, 8, 0.9)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
