"""Raster ingestion helpers shared by benthic habitat pipelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry import box, shape


def discover_geotiffs(root: Path) -> list[str | Path]:
    """Return every GeoTIFF beneath *root* in stable order."""

    if not root.exists():
        raise FileNotFoundError(f"Raster source does not exist: {root}")
    if root.is_file() and root.suffix.lower() == ".zip":
        import zipfile

        with zipfile.ZipFile(root) as archive:
            members = sorted(
                member
                for member in archive.namelist()
                if member.lower().endswith((".tif", ".tiff"))
            )
        if not members:
            raise FileNotFoundError(f"No GeoTIFF files were found in {root}")
        absolute = root.resolve()
        return [f"/vsizip/{absolute}/{member}" for member in members]
    if not root.is_dir():
        raise ValueError(f"Raster source must be a directory or ZIP archive: {root}")
    paths = sorted({*root.rglob("*.tif"), *root.rglob("*.tiff")})
    if not paths:
        raise FileNotFoundError(f"No GeoTIFF files were found beneath {root}")
    return paths


def _bbox_in_crs(
    bbox: Mapping[str, float],
    destination_crs: Any,
) -> tuple[float, float, float, float]:
    from rasterio.warp import transform_bounds

    return transform_bounds(
        "EPSG:4326",
        destination_crs,
        float(bbox["min_lon"]),
        float(bbox["min_lat"]),
        float(bbox["max_lon"]),
        float(bbox["max_lat"]),
        densify_pts=21,
    )


def positive_raster_polygons(
    paths: Iterable[str | Path],
    *,
    bbox: Mapping[str, float],
    positive_values: Sequence[int | float],
) -> tuple[list[Any], Any]:
    """Polygonize configured positive raster classes inside a WGS84 bbox.

    The returned geometries retain the first intersecting raster CRS. Callers
    should construct a GeoDataFrame with the returned CRS before reprojecting.
    """

    import rasterio
    from rasterio.features import shapes
    from rasterio.windows import Window, from_bounds
    from rasterio.windows import transform as window_transform

    accepted = np.asarray(list(positive_values))
    if accepted.size == 0:
        raise ValueError("At least one positive raster value must be configured.")
    from pyproj import Transformer
    from shapely.ops import transform as transform_geometry

    output: list[Any] = []
    for path in paths:
        with rasterio.open(path) as source:
            if source.crs is None:
                raise ValueError(f"Raster has no CRS: {path}")
            bounds = _bbox_in_crs(bbox, source.crs)
            overlap = box(*bounds).intersection(box(*source.bounds))
            if overlap.is_empty:
                continue
            raw_window = from_bounds(*overlap.bounds, transform=source.transform)
            window = (
                raw_window.round_offsets()
                .round_lengths()
                .intersection(Window(0, 0, source.width, source.height))
            )
            values = source.read(1, window=window, masked=True)
            present = np.isin(values.data, accepted) & ~np.ma.getmaskarray(values)
            if not present.any():
                continue
            transform = window_transform(window, source.transform)
            to_wgs84 = Transformer.from_crs(source.crs, "EPSG:4326", always_xy=True)
            output.extend(
                transform_geometry(to_wgs84.transform, shape(geometry))
                for geometry, value in shapes(
                    present.astype("uint8"), mask=present, transform=transform
                )
                if int(value) == 1
            )
    if not output:
        raise ValueError("No configured positive raster pixels intersect the model area.")
    return output, "EPSG:4326"


def sample_raster_bilinear(
    path: Path,
    longitudes: Sequence[float],
    latitudes: Sequence[float],
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinearly sample one raster at WGS84 point coordinates.

    Returns sampled values plus an explicit validity mask. Only a bounded
    window around the requested points is read, so global/coarse deliveries do
    not need to be loaded into memory.
    """

    import rasterio
    from pyproj import Transformer
    from rasterio.windows import Window

    lon = np.asarray(longitudes, dtype="float64")
    lat = np.asarray(latitudes, dtype="float64")
    if lon.shape != lat.shape:
        raise ValueError("Raster sample longitude and latitude arrays must have equal shape.")
    result = np.full(lon.shape, np.nan, dtype="float64")
    valid_result = np.zeros(lon.shape, dtype=bool)
    with rasterio.open(path) as source:
        if source.crs is None:
            raise ValueError(f"Raster has no CRS: {path}")
        transformer = Transformer.from_crs("EPSG:4326", source.crs, always_xy=True)
        x, y = transformer.transform(lon, lat)
        x = np.asarray(x, dtype="float64")
        y = np.asarray(y, dtype="float64")
        inside = (
            np.isfinite(x)
            & np.isfinite(y)
            & (x >= source.bounds.left)
            & (x <= source.bounds.right)
            & (y >= source.bounds.bottom)
            & (y <= source.bounds.top)
        )
        if not inside.any():
            return result, valid_result
        inverse = ~source.transform
        cols, rows = inverse * (x[inside], y[inside])
        cols = np.asarray(cols, dtype="float64") - 0.5
        rows = np.asarray(rows, dtype="float64") - 0.5
        col0 = np.floor(cols).astype(int)
        row0 = np.floor(rows).astype(int)
        col1 = col0 + 1
        row1 = row0 + 1
        min_col = max(0, int(col0.min()))
        min_row = max(0, int(row0.min()))
        max_col = min(source.width - 1, int(col1.max()))
        max_row = min(source.height - 1, int(row1.max()))
        window = Window(
            min_col,
            min_row,
            max_col - min_col + 1,
            max_row - min_row + 1,
        )
        raster = source.read(1, window=window, masked=True)
        local_col0 = np.clip(col0 - min_col, 0, raster.shape[1] - 1)
        local_col1 = np.clip(col1 - min_col, 0, raster.shape[1] - 1)
        local_row0 = np.clip(row0 - min_row, 0, raster.shape[0] - 1)
        local_row1 = np.clip(row1 - min_row, 0, raster.shape[0] - 1)
        raster_float = raster.astype("float64")
        neighbors = np.column_stack(
            [
                raster_float[local_row0, local_col0].filled(np.nan),
                raster_float[local_row0, local_col1].filled(np.nan),
                raster_float[local_row1, local_col0].filled(np.nan),
                raster_float[local_row1, local_col1].filled(np.nan),
            ]
        )
        dc = cols - col0
        dr = rows - row0
        weights = np.column_stack(
            [
                (1.0 - dc) * (1.0 - dr),
                dc * (1.0 - dr),
                (1.0 - dc) * dr,
                dc * dr,
            ]
        )
        neighbor_valid = np.isfinite(neighbors)
        weight_sum = np.where(neighbor_valid, weights, 0.0).sum(axis=1)
        sampled = np.divide(
            np.where(neighbor_valid, neighbors * weights, 0.0).sum(axis=1),
            weight_sum,
            out=np.full(len(cols), np.nan, dtype="float64"),
            where=weight_sum > 0,
        )
        positions = np.flatnonzero(inside)
        result[positions] = sampled
        valid_result[positions] = np.isfinite(sampled)
    return result, valid_result


def validate_percentage(values: np.ndarray, variable: str) -> np.ndarray:
    """Convert a percent raster to a bounded fraction and reject bad units."""

    finite = values[np.isfinite(values)]
    if finite.size and (finite.min() < -1e-6 or finite.max() > 100.0 + 1e-6):
        raise ValueError(
            f"dbSEABED {variable} raster must use percent values in [0, 100]; "
            f"observed [{finite.min()}, {finite.max()}]."
        )
    return np.clip(values / 100.0, 0.0, 1.0)
