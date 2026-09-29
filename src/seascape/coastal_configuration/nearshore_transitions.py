"""Positive-down nearshore depth geometry on water-clipped support.

Callers supply source shoreline/water geometry in the raster's projected metre
CRS. Raster footprints, rather than pixel counts, define area denominators.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.windows import from_bounds
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class NearshoreArea:
    eligible_area_m2: float
    valid_area_m2: float
    deep_area_m2: float | None
    deep_fraction_of_valid: float | None
    bathymetry_coverage_fraction: float | None
    status: str


@dataclass(frozen=True)
class TransectCrossing:
    width_m: float | None
    gradient_m_per_m: float | None
    status: str
    samples: tuple[tuple[float, float], ...]


def _require_metric_raster(raster: rasterio.io.DatasetReader) -> None:
    if raster.crs is None or raster.crs.is_geographic:
        raise ValueError("Nearshore geometry requires a projected raster CRS")
    if not all(abs(axis.unit_conversion_factor - 1) < 1e-6 for axis in CRS.from_user_input(raster.crs).axis_info[:2]):
        raise ValueError("Raster horizontal axes must use metres")
    if raster.count != 1:
        raise ValueError("Expected one positive-down depth band")


def _positive_depth(value: float, convention: str) -> float | None:
    if convention == "negative_elevation":
        return -value if value < 0 else None
    if convention == "positive_down":
        if value < 0:
            raise ValueError("Depth raster contradicts positive-down convention")
        return value
    raise ValueError("Depth convention must be positive_down or negative_elevation")


def nearshore_depth_areas(
    support: BaseGeometry,
    water: BaseGeometry,
    shoreline: BaseGeometry,
    raster: rasterio.io.DatasetReader,
    *,
    depth_threshold_m: float,
    band_width_m: float,
    raster_depth_convention: str = "positive_down",
) -> NearshoreArea:
    """E=C∩water∩shore band, V=E∩valid raster, B=V∩depth>=h."""

    _require_metric_raster(raster)
    if depth_threshold_m < 0 or band_width_m <= 0:
        raise ValueError("Threshold must be nonnegative and band width positive")
    eligible = support.intersection(water).intersection(shoreline.buffer(band_width_m))
    eligible_area = float(eligible.area)
    if eligible_area <= 1e-9:
        return NearshoreArea(0.0, 0.0, None, None, None, "empty_nearshore_support")
    window = from_bounds(*eligible.bounds, transform=raster.transform)
    # Read every source pixel whose footprint can intersect the eligible area.
    # Rounding the length to nearest can omit a narrow strip at the far edge.
    left = math.floor(window.col_off)
    top = math.floor(window.row_off)
    window = rasterio.windows.Window(
        left, top,
        math.ceil(window.col_off + window.width) - left,
        math.ceil(window.row_off + window.height) - top,
    )
    try:
        window = window.intersection(rasterio.windows.Window(0, 0, raster.width, raster.height))
    except rasterio.errors.WindowError:
        return NearshoreArea(eligible_area, 0.0, None, None, 0.0, "bathymetry_unavailable")
    depths = raster.read(1, window=window, masked=True)
    transform = raster.window_transform(window)
    valid_area = 0.0
    deep_area = 0.0
    for row in range(depths.shape[0]):
        for col in range(depths.shape[1]):
            value = depths[row, col]
            if np.ma.is_masked(value) or not math.isfinite(float(value)):
                continue
            depth = _positive_depth(float(value), raster_depth_convention)
            if depth is None:
                continue
            x0, y0 = transform * (col, row)
            x1, y1 = transform * (col + 1, row + 1)
            overlap = eligible.intersection(box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
            area = overlap.area
            valid_area += area
            if depth >= depth_threshold_m:
                deep_area += area
    if valid_area <= 1e-9:
        return NearshoreArea(eligible_area, 0.0, None, None, 0.0, "bathymetry_unavailable")
    return NearshoreArea(
        eligible_area,
        valid_area,
        deep_area,
        deep_area / valid_area,
        min(1.0, valid_area / eligible_area),
        "complete" if eligible_area - valid_area <= 1e-6 else "partial_bathymetry",
    )


def first_water_facing_contour(
    station: Point,
    tangent: tuple[float, float],
    water: BaseGeometry,
    raster: rasterio.io.DatasetReader,
    *,
    depth_threshold_m: float,
    step_m: float,
    max_distance_m: float,
    orientation_probe_m: float | None = None,
    raster_depth_convention: str = "positive_down",
) -> TransectCrossing:
    """First interpolated crossing along the contiguous seaward transect.

    Samples preserve nonmonotonic profiles. A station with ambiguous water side
    is unresolved; the routine never silently chooses one normal.
    """

    _require_metric_raster(raster)
    if depth_threshold_m < 0 or step_m <= 0 or max_distance_m <= 0:
        raise ValueError("Invalid transect scale or threshold")
    tx, ty = tangent
    norm = math.hypot(tx, ty)
    if norm <= 0:
        raise ValueError("Tangent must be nonzero")
    normals = ((-ty / norm, tx / norm), (ty / norm, -tx / norm))
    probe = orientation_probe_m or step_m / 2
    sides = [water.covers(Point(station.x + nx * probe, station.y + ny * probe)) for nx, ny in normals]
    if sides.count(True) != 1:
        return TransectCrossing(None, None, "ambiguous_water_side", ())
    nx, ny = normals[sides.index(True)]
    samples: list[tuple[float, float]] = []
    previous_point = station
    distance = 0.0
    while distance <= max_distance_m + 1e-9:
        point = Point(station.x + nx * distance, station.y + ny * distance)
        if distance > 0 and not water.buffer(1e-7).covers(LineString([previous_point, point])):
            return TransectCrossing(None, None, "land_censored", tuple(samples))
        value = next(raster.sample([(point.x, point.y)], masked=True))[0]
        if np.ma.is_masked(value) or not math.isfinite(float(value)) or (
            raster.nodata is not None and float(value) == raster.nodata
        ):
            return TransectCrossing(None, None, "nodata_censored", tuple(samples))
        depth = _positive_depth(float(value), raster_depth_convention)
        if depth is None:
            return TransectCrossing(None, None, "land_or_nonmarine_raster", tuple(samples))
        samples.append((distance, depth))
        if depth >= depth_threshold_m:
            if len(samples) == 1:
                return TransectCrossing(0.0, None, "already_deep", tuple(samples))
            old_distance, old_depth = samples[-2]
            fraction = (depth_threshold_m - old_depth) / (depth - old_depth)
            crossing = old_distance + fraction * (distance - old_distance)
            return TransectCrossing(
                crossing,
                (depth - old_depth) / (distance - old_distance),
                "crossed",
                tuple(samples),
            )
        previous_point = point
        distance += step_m
    return TransectCrossing(None, None, "search_limited", tuple(samples))
