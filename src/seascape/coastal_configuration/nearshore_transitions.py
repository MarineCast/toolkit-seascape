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
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from scipy.ndimage import label
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


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


def bounded_deep_target_components(
    cells: list[tuple[str, BaseGeometry]],
    water: BaseGeometry,
    shoreline: BaseGeometry,
    raster: rasterio.io.DatasetReader,
    *,
    depth_threshold_m: float,
    band_width_m: float,
    max_pixels: int,
    source_identity: str = "synthetic-raster",
    raster_depth_convention: str = "positive_down",
) -> tuple[list[dict[str, object]], dict[str, tuple[str, ...]]]:
    """Four-neighbor deep pixel components in the selected nearshore support.

    Components are bounded by the selected water/shore band. Pixel topology is
    an analysis-scale candidate and is censored at the selected-context edge.
    """

    _require_metric_raster(raster)
    if max_pixels < 1 or band_width_m <= 0 or depth_threshold_m < 0 or not source_identity:
        raise ValueError("Invalid bounded deep-component settings")
    band = shoreline.buffer(band_width_m)
    eligible = {
        cell_id: geometry.intersection(water).intersection(band)
        for cell_id, geometry in cells
    }
    support = unary_union([geometry for geometry in eligible.values() if not geometry.is_empty])
    if support.is_empty:
        return [], {cell_id: () for cell_id, _ in cells}
    floating = from_bounds(*support.bounds, transform=raster.transform)
    left, top = math.floor(floating.col_off), math.floor(floating.row_off)
    window = rasterio.windows.Window(
        left, top,
        math.ceil(floating.col_off + floating.width) - left,
        math.ceil(floating.row_off + floating.height) - top,
    )
    try:
        window = window.intersection(rasterio.windows.Window(0, 0, raster.width, raster.height))
    except rasterio.errors.WindowError:
        return [], {cell_id: () for cell_id, _ in cells}
    if window.width * window.height > max_pixels:
        raise ValueError("Deep-component raster pixel budget exceeded")
    source = raster.read(1, window=window, masked=True)
    values = np.ma.asarray(source, dtype=float).filled(np.nan)
    if raster_depth_convention == "negative_elevation":
        deep = np.isfinite(values) & (values < 0) & (-values >= depth_threshold_m)
    elif raster_depth_convention == "positive_down":
        if np.any(np.isfinite(values) & (values < 0)):
            raise ValueError("Depth raster contradicts positive-down convention")
        deep = np.isfinite(values) & (values >= depth_threshold_m)
    else:
        raise ValueError("Depth convention must be positive_down or negative_elevation")
    transform = raster.window_transform(window)
    in_support = geometry_mask(
        [support], out_shape=values.shape, transform=transform,
        invert=True, all_touched=False,
    )
    labels, count = label(deep & in_support, structure=np.array([
        [0, 1, 0], [1, 1, 1], [0, 1, 0],
    ]))
    component_ids: dict[int, str] = {}
    components: list[dict[str, object]] = []
    pixel_area = abs(transform.a * transform.e)
    for number in range(1, count + 1):
        rows, cols = np.where(labels == number)
        if not len(rows):
            continue
        component_id = (
            f"deep:{source_identity}:{depth_threshold_m:g}m:"
            f"r{int(window.row_off) + int(rows.min())}:"
            f"c{int(window.col_off) + int(cols.min())}"
        )
        component_ids[number] = component_id
        components.append({
            "DEEP_COMPONENT_ID": component_id,
            "DEPTH_THRESHOLD_M": depth_threshold_m,
            "PIXEL_COUNT": len(rows),
            "RASTER_COMPONENT_PIXEL_AREA_M2": len(rows) * pixel_area,
            "COMPONENT_CONTEXT_STATUS": "selected_support_boundary_censored",
            "METHOD": "virtual_projected_source_scale_four_neighbor_v1",
        })
    by_cell: dict[str, tuple[str, ...]] = {}
    for cell_id, geometry in eligible.items():
        if geometry.is_empty:
            by_cell[cell_id] = ()
            continue
        cell_mask = geometry_mask(
            [geometry], out_shape=values.shape, transform=transform,
            invert=True, all_touched=False,
        )
        by_cell[cell_id] = tuple(sorted({
            component_ids[int(number)] for number in np.unique(labels[cell_mask])
            if int(number) in component_ids
        }))
    return components, by_cell


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
