"""Source-coastline orientation, sinuosity, headland candidates and islands."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class CoastSummary:
    shoreline_length_m: float
    shoreline_length_density_m_per_km2: float
    axial_orientation_deg: float | None
    axial_sin_2theta: float | None
    axial_cos_2theta: float | None
    orientation_concentration: float | None
    water_normal_bearing_deg: float | None
    island_count: int
    island_area_within_support_m2: float
    island_fraction_of_support: float
    island_ids: tuple[str, ...]
    boundary_censored_island_ids: tuple[str, ...]


def shoreline_sinuosity(line: LineString) -> float | None:
    """Arc/chord on one connected source segment; closed/short chords unresolved."""

    if line.is_empty or line.length <= 0:
        return None
    chord = Point(line.coords[0]).distance(Point(line.coords[-1]))
    if chord <= max(1e-9, line.length * 1e-9):
        return None
    return float(line.length / chord)


def _segments(
    line: LineString, support: BaseGeometry
) -> list[tuple[float, float, float, Point]]:
    """Clip source segments to support without introducing H3 boundary angles."""

    output = []
    for a, b in zip(line.coords[:-1], line.coords[1:], strict=True):
        piece = LineString([a, b]).intersection(support)
        if piece.is_empty or piece.length <= 0:
            continue
        dx, dy = b[0] - a[0], b[1] - a[1]
        angle = math.atan2(dy, dx)
        output.append(
            (piece.length, math.sin(2 * angle), math.cos(2 * angle), piece.centroid)
        )
    return output


def summarize_coast(
    coastlines: Sequence[LineString],
    support: BaseGeometry,
    water: BaseGeometry,
    islands: Mapping[str, BaseGeometry],
    source_context_boundary: BaseGeometry,
    *,
    minimum_island_area_m2: float,
    normal_probe_m: float,
    minimum_direction_concentration: float = 0.1,
) -> CoastSummary:
    """Summarize on explicit metric support; use complete source island IDs."""

    if support.area <= 0 or minimum_island_area_m2 < 0 or normal_probe_m <= 0:
        raise ValueError("Invalid coastline support or analysis scale")
    segments = [segment for line in coastlines for segment in _segments(line, support)]
    length = sum(segment[0] for segment in segments)
    sin_sum = sum(segment[0] * segment[1] for segment in segments)
    cos_sum = sum(segment[0] * segment[2] for segment in segments)
    concentration = math.hypot(sin_sum, cos_sum) / length if length > 0 else None
    resolved = (
        concentration is not None and concentration >= minimum_direction_concentration
    )
    axial = math.degrees(math.atan2(sin_sum, cos_sum) / 2) % 180 if resolved else None
    normal_x = normal_y = 0.0
    normal_weight = 0.0
    for line in coastlines:
        for a, b in zip(line.coords[:-1], line.coords[1:], strict=True):
            piece = LineString([a, b]).intersection(support)
            if piece.is_empty or piece.length <= 0:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            scale = math.hypot(dx, dy)
            nx, ny = -dy / scale, dx / scale
            midpoint = piece.centroid
            left = water.covers(
                Point(
                    midpoint.x + nx * normal_probe_m, midpoint.y + ny * normal_probe_m
                )
            )
            right = water.covers(
                Point(
                    midpoint.x - nx * normal_probe_m, midpoint.y - ny * normal_probe_m
                )
            )
            if left == right:
                continue
            sign = 1 if left else -1
            normal_x += sign * nx * piece.length
            normal_y += sign * ny * piece.length
            normal_weight += piece.length
    normal_bearing = None
    if (
        normal_weight
        and math.hypot(normal_x, normal_y) / normal_weight
        >= minimum_direction_concentration
    ):
        normal_bearing = math.degrees(math.atan2(normal_x, normal_y)) % 360
    selected = {}
    censored = []
    for island_id, geometry in islands.items():
        if geometry.area < minimum_island_area_m2 or not geometry.intersects(support):
            continue
        if geometry.intersects(source_context_boundary):
            censored.append(island_id)
        else:
            selected[island_id] = geometry.intersection(support).area
    return CoastSummary(
        length,
        length / (support.area / 1_000_000),
        axial,
        sin_sum / length if resolved else None,
        cos_sum / length if resolved else None,
        concentration,
        normal_bearing,
        len(selected),
        sum(selected.values()),
        sum(selected.values()) / support.area,
        tuple(sorted(selected)),
        tuple(sorted(censored)),
    )


def headland_candidates(
    source_id: str,
    coast: LineString,
    land: BaseGeometry,
    *,
    smoothing_distance_m: float,
    station_spacing_m: float,
    minimum_turn_degrees: float,
    side_probe_m: float,
) -> list[dict[str, object]]:
    """Find land-convex turns at declared scale; bays get no candidate ID."""

    if not source_id or min(smoothing_distance_m, station_spacing_m, side_probe_m) <= 0:
        raise ValueError("Source ID and positive physical scales are required")
    if not 0 < minimum_turn_degrees < 180:
        raise ValueError("Turn threshold must be between zero and 180 degrees")
    output = []
    position = smoothing_distance_m
    while position + smoothing_distance_m < coast.length:
        before = coast.interpolate(position - smoothing_distance_m)
        center = coast.interpolate(position)
        after = coast.interpolate(position + smoothing_distance_m)
        ax, ay = center.x - before.x, center.y - before.y
        bx, by = after.x - center.x, after.y - center.y
        turn = math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
        scale = math.hypot(ax + bx, ay + by)
        if scale > 1e-9:
            nx, ny = -(ay + by) / scale, (ax + bx) / scale
            left_land = land.covers(
                Point(center.x + nx * side_probe_m, center.y + ny * side_probe_m)
            )
            right_land = land.covers(
                Point(center.x - nx * side_probe_m, center.y - ny * side_probe_m)
            )
            side = (
                1
                if left_land and not right_land
                else -1
                if right_land and not left_land
                else 0
            )
            if side * turn >= minimum_turn_degrees:
                output.append(
                    {
                        "HEADLAND_CANDIDATE_ID": f"{source_id}:{position:.3f}m:{smoothing_distance_m:.3f}m",
                        "SOURCE_COAST_ID": source_id,
                        "ALONG_COAST_M": position,
                        "TURN_DEGREES": turn,
                        "SMOOTHING_DISTANCE_M": smoothing_distance_m,
                        "GEOMETRY": center,
                        "METHOD": "land_sided_curvature_candidate_v1",
                    }
                )
        position += station_spacing_m
    return output
