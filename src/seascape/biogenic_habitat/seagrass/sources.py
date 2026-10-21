"""Positive polygon evidence, retaining source methods and temporal precision."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Mapping

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from shapely.geometry import box, shape

from seascape.utils.habitat_raster import discover_geotiffs


def mapped_inventory(
    frame: gpd.GeoDataFrame,
    *,
    source: str,
    year: int | None,
    method: str,
    species_column: str | None = None,
    map_date_column: str | None = None,
) -> gpd.GeoDataFrame:
    """Mapped eelgrass footprints, never site boundaries or buffered points/lines."""
    if frame.crs is None or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Mapped seagrass requires source polygon geometry and CRS")
    frame = frame.to_crs(4326).copy()
    ids = frame["EELGRASS_ID"] if "EELGRASS_ID" in frame else frame["OBJECTID"]
    if ids.isna().any() or ids.duplicated().any():
        raise ValueError("Source mapped polygon identities must be unique")
    frame["SOURCE_ATTRIBUTES_JSON"] = [
        __import__("json").dumps(
            {k: v for k, v in row.items() if k != "geometry"},
            sort_keys=True,
            default=str,
        )
        for row in frame.to_dict("records")
    ]
    frame["RECORD_ID"] = [f"{source}:{v}" for v in ids]
    frame["SOURCE_DATASET"] = source
    frame["HABITAT_TYPE"] = "eelgrass"
    frame["OBSERVATION_STATUS"] = "present"
    frame["OBSERVATION_YEAR"] = year
    frame["OBSERVED_VS_MODELED"] = "observed"
    frame["SURVEY_METHOD"] = method
    frame["SPECIES"] = (
        frame[species_column].fillna("eelgrass; species unspecified")
        if species_column
        else "eelgrass; species unspecified"
    )
    frame["SOURCE_PERIOD"] = (
        str(year) if year else "legacy compilation; observation dates unknown"
    )
    frame["SOURCE_MAP_DATE"] = frame[map_date_column] if map_date_column else None
    return frame[
        [
            "RECORD_ID",
            "SOURCE_DATASET",
            "HABITAT_TYPE",
            "OBSERVATION_STATUS",
            "OBSERVATION_YEAR",
            "OBSERVED_VS_MODELED",
            "SURVEY_METHOD",
            "SPECIES",
            "SOURCE_PERIOD",
            "SOURCE_MAP_DATE",
            "SOURCE_ATTRIBUTES_JSON",
            "geometry",
        ]
    ]


def raster_inventory(
    archive: str | Path,
    *,
    source: str,
    period: tuple[int, int],
    bbox: Mapping[str, float],
    expected_sha256: str | None = None,
    max_blocks: int = 100000,
    max_records: int = 200000,
    max_seconds: float = 600,
) -> gpd.GeoDataFrame:
    """Polygonize class 1 in bounded blocks directly from compressed source tiles.

    Pixel footprints retain their actual source affine. Background/nodata 0 never
    becomes observed absence. Two-year composites carry no annual observation year.
    """
    started = time.monotonic()
    archive = Path(archive).resolve()
    with archive.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("Seagrass archive differs from pinned identity")
    if (
        min(max_blocks, max_records, max_seconds) <= 0
        or not 1 <= period[0] <= period[1] < 9999
    ):
        raise ValueError("Invalid raster budgets or composite period")
    extent = box(bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"])
    paths = discover_geotiffs(archive)
    if len(paths) > 2048:
        raise ValueError("Raster member budget exceeded")
    geometries = []
    rectangles = []
    blocks = 0
    with rasterio.Env(GDAL_CACHEMAX=32 * 1024**2):
        for path in paths:
            with rasterio.open(path) as src:
                if src.crs is None or src.crs.to_epsg() != 4326:
                    raise ValueError("Seagrass requires original EPSG:4326 tiles")
                rectangle = box(*src.bounds)
                if not rectangle.intersects(extent):
                    continue
                affine = src.transform
                if (
                    src.count != 1
                    or src.dtypes[0] != "uint8"
                    or src.nodata != 0
                    or affine.b
                    or affine.d
                    or affine.a <= 0
                    or affine.e >= 0
                ):
                    raise ValueError("Unsupported source raster contract")
                if any(
                    rectangle.intersection(other).area > 1e-10 for other in rectangles
                ):
                    raise ValueError(
                        "Overlapping source tiles require explicit reconciliation"
                    )
                rectangles.append(rectangle)
                for _, window in src.block_windows(1):
                    if time.monotonic() - started > max_seconds:
                        raise ValueError("Seagrass raster time budget exceeded")
                    bounds = rasterio.windows.bounds(window, affine)
                    if not box(*bounds).intersects(extent):
                        continue
                    blocks += 1
                    if blocks > max_blocks or window.width * window.height > 16000000:
                        raise ValueError("Seagrass source block budget exceeded")
                    raw = src.read(1, window=window)
                    if np.any((raw != 0) & (raw != 1)):
                        raise ValueError("Unexpected source class; expected binary 0/1")
                    positive = raw == 1
                    if not positive.any():
                        continue
                    for geom, value in shapes(
                        raw,
                        mask=positive,
                        transform=src.window_transform(window),
                        connectivity=4,
                    ):
                        if int(value) == 1:
                            geometries.append(shape(geom))
                    if len(geometries) > max_records:
                        raise ValueError("Seagrass positive polygon budget exceeded")
    n = len(geometries)
    frame = gpd.GeoDataFrame(
        {
            "RECORD_ID": [f"{source}:{i}" for i in range(n)],
            "SOURCE_DATASET": source,
            "HABITAT_TYPE": "seagrass",
            "OBSERVATION_STATUS": "present",
            "OBSERVATION_YEAR": pd.array([None] * n, dtype="Int16"),
            "OBSERVED_VS_MODELED": "modeled",
            "SURVEY_METHOD": "Sentinel-2 deep-learning shallow-water binary classification; positive 10 m raster footprints",
            "SPECIES": "generic seagrass; no species resolution",
            "SOURCE_PERIOD": f"{period[0]}-{period[1]} composite",
            "SOURCE_MAP_DATE": None,
            "SOURCE_ATTRIBUTES_JSON": __import__("json").dumps(
                {
                    "archive_sha256": checksum,
                    "positive_class": 1,
                    "background_is_absence": False,
                }
            ),
        },
        geometry=geometries,
        crs=4326,
    )
    frame.attrs["raster_report"] = {
        "archive_sha256": checksum,
        "positive_block_polygons": n,
        "blocks_read": blocks,
        "elapsed_seconds": time.monotonic() - started,
        "period": list(period),
    }
    return frame
