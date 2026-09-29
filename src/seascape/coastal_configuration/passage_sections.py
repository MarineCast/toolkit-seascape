"""Bounded, source-identified passage cross sections and shoal candidates."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

DepthSampler = Callable[[float, float], float | None]


@dataclass(frozen=True)
class PassageSection:
    passage_id: str
    along_axis_m: float
    wet_width_m: float
    cross_section_area_m2: float | None
    valid_integral_area_m2: float
    max_depth_m: float | None
    width_at_depth_threshold_m: float | None
    max_contiguous_width_at_depth_threshold_m: float | None
    bank_status: str
    bathymetry_status: str
    wet_intervals: int
    section: LineString


def _line_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > 0 else []
    if not hasattr(geometry, "geoms"):
        return []
    return [part for child in geometry.geoms for part in _line_parts(child)]


def _threshold_width(a: float, b: float, step: float, threshold: float) -> float:
    if a >= threshold and b >= threshold:
        return step
    if a < threshold and b < threshold:
        return 0.0
    fraction = (threshold - a) / (b - a)
    return step * (1 - fraction if a < threshold else fraction)


def measure_passage_section(
    passage_id: str,
    passage_polygon: BaseGeometry,
    centerline: LineString,
    water: BaseGeometry,
    depth_at: DepthSampler,
    *,
    along_axis_m: float,
    half_length_m: float,
    sample_step_m: float,
    depth_threshold_m: float,
    tangent_scale_m: float,
) -> PassageSection:
    """Integrate positive-down depth over separately clipped wet intervals.

    A complete area is emitted only when both banks and all wet samples are
    observed. The valid-span integral is separately named for partial data.
    """

    if not passage_id or centerline.length <= 0 or passage_polygon.is_empty:
        raise ValueError("Passage identity and geometry are required")
    if min(half_length_m, sample_step_m, tangent_scale_m) <= 0 or depth_threshold_m < 0:
        raise ValueError("Invalid passage analysis scale")
    if not 0 <= along_axis_m <= centerline.length:
        raise ValueError("Section position is outside the centerline")
    start = centerline.interpolate(max(0, along_axis_m - tangent_scale_m / 2))
    end = centerline.interpolate(min(centerline.length, along_axis_m + tangent_scale_m / 2))
    dx, dy = end.x - start.x, end.y - start.y
    norm = math.hypot(dx, dy)
    if norm <= 0:
        raise ValueError("Centerline tangent is unresolved")
    center = centerline.interpolate(along_axis_m)
    nx, ny = -dy / norm, dx / norm
    section = LineString(
        [
            (center.x - nx * half_length_m, center.y - ny * half_length_m),
            (center.x + nx * half_length_m, center.y + ny * half_length_m),
        ]
    )
    wet = _line_parts(section.intersection(passage_polygon).intersection(water))
    wet.sort(key=lambda line: section.project(line.interpolate(0.5, normalized=True)))
    bank_status = (
        "complete"
        if wet
        and not passage_polygon.covers(section.boundary.geoms[0])
        and not passage_polygon.covers(section.boundary.geoms[1])
        else "bank_censored"
    )
    wet_width = sum(part.length for part in wet)
    area = 0.0
    total_width = 0.0
    contiguous_max = 0.0
    max_depth: float | None = None
    missing = False
    for part in wet:
        count = max(1, math.ceil(part.length / sample_step_m))
        distances = [part.length * index / count for index in range(count + 1)]
        values = [depth_at(*part.interpolate(distance).coords[0]) for distance in distances]
        run = 0.0
        for index in range(count):
            a, b = values[index : index + 2]
            step = distances[index + 1] - distances[index]
            if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
                missing = True
                run = 0.0
                continue
            if a < 0 or b < 0:
                raise ValueError("Passage depth contradicts positive-down convention")
            max_depth = max(a, b) if max_depth is None else max(max_depth, a, b)
            area += step * (max(a, 0) + max(b, 0)) / 2
            width = _threshold_width(a, b, step, depth_threshold_m)
            total_width += width
            if width > 0:
                run += width
                contiguous_max = max(contiguous_max, run)
            else:
                run = 0.0
    complete = bool(wet) and bank_status == "complete" and not missing
    return PassageSection(
        passage_id,
        along_axis_m,
        wet_width,
        area if complete else None,
        area,
        max_depth,
        total_width if not missing else None,
        contiguous_max if not missing else None,
        bank_status,
        "complete" if not missing and wet else "partial_or_unavailable",
        len(wet),
        section,
    )


def sill_candidates(
    sections: pd.DataFrame, *, min_relief_m: float, min_width_m: float = 1.0
) -> pd.DataFrame:
    """Find interior along-axis shoals with deeper full sections on both sides.

    Section maximum depth is a cross-channel proxy, not a validated controlling
    depth. Candidates require separate review before any named-sill assertion.
    """

    required = {"PASSAGE_ID", "ALONG_AXIS_M", "MAX_DEPTH_M", "WET_WIDTH_M", "BANK_STATUS", "BATHYMETRY_STATUS"}
    if required - set(sections):
        raise ValueError(f"Missing section fields: {sorted(required - set(sections))}")
    if min_relief_m <= 0 or min_width_m <= 0:
        raise ValueError("Relief and width thresholds must be positive")
    if sections.duplicated(["PASSAGE_ID", "ALONG_AXIS_M"]).any():
        raise ValueError("Duplicate passage section identity")
    rows = []
    for passage_id, group in sections.groupby("PASSAGE_ID", sort=True):
        ordered = group.sort_values("ALONG_AXIS_M").reset_index(drop=True)
        for index in range(1, len(ordered) - 1):
            left, middle, right = (ordered.iloc[index + offset] for offset in (-1, 0, 1))
            trio = (left, middle, right)
            if any(
                row.BANK_STATUS != "complete"
                or row.BATHYMETRY_STATUS != "complete"
                or pd.isna(row.MAX_DEPTH_M)
                or row.WET_WIDTH_M < min_width_m
                for row in trio
            ):
                continue
            relief_left = float(left.MAX_DEPTH_M - middle.MAX_DEPTH_M)
            relief_right = float(right.MAX_DEPTH_M - middle.MAX_DEPTH_M)
            if min(relief_left, relief_right) < min_relief_m:
                continue
            position = float(middle.ALONG_AXIS_M)
            rows.append(
                {
                    "SILL_CANDIDATE_ID": f"{passage_id}:section:{position:.3f}m",
                    "PASSAGE_ID": passage_id,
                    "ALONG_AXIS_M": position,
                    "SILL_CANDIDATE_DEPTH_M": float(middle.MAX_DEPTH_M),
                    "RELIEF_LEFT_M": relief_left,
                    "RELIEF_RIGHT_M": relief_right,
                    "SUPPORTING_SECTION_POSITIONS_M": [float(row.ALONG_AXIS_M) for row in trio],
                    "METHOD": "along_axis_section_max_proxy_v1",
                    "QC": "candidate_requires_bathymetric_saddle_review",
                }
            )
    return pd.DataFrame(rows)
