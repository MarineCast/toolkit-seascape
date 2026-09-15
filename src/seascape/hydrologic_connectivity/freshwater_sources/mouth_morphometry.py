"""Mapped polygon cross-section morphometry for freshwater mouths."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import unary_union

from seascape.utils.values import (
    clean_optional_text,
    iter_frame_records,
)

from .source_geometry import polygon_parts


def line_components(geometry: Any) -> list[Any]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [component for part in geometry.geoms for component in line_components(part)]
    return []


def cross_section(line: Any, mouth_at_end: bool, distance_m: float, length_m: float):
    if line.is_empty or line.length <= 0:
        return None, None
    inward_distance = min(distance_m, line.length * 0.9)
    along = line.length - inward_distance if mouth_at_end else inward_distance
    center = line.interpolate(along)
    delta = min(20.0, max(line.length * 0.05, 0.5))
    before = line.interpolate(max(0.0, along - delta))
    after = line.interpolate(min(line.length, along + delta))
    dx, dy = after.x - before.x, after.y - before.y
    norm = math.hypot(dx, dy)
    if norm <= 0:
        return None, None
    half = length_m / 2.0
    normal_x, normal_y = -dy / norm, dx / norm
    return center, LineString(
        [
            (center.x - normal_x * half, center.y - normal_y * half),
            (center.x + normal_x * half, center.y + normal_y * half),
        ]
    )


def width_from_polygons(
    row: Mapping[str, Any],
    polygons: Any,
    bc_polygon_indices: Mapping[str, list[int]],
    config: Any,
) -> tuple[float | None, str | None, int]:
    dataset = str(row["SOURCE_DATASET"])
    key = clean_optional_text(row.get("_WIDTH_KEY"))
    candidate_indices = (
        list(bc_polygon_indices.get(key, [])) if dataset == "BC_FWA_STREAM_NETWORK" and key else []
    )
    search_geometry = row["_TERMINAL_LINE"].buffer(config.mouth_width_polygon_match_distance_m)
    allowed_source = {
        "BC_FWA_STREAM_NETWORK": "BC_FWA_RIVER_POLYGONS",
        "US_NHD_SMALL_SCALE": "US_NHDPLUS_HR_NHDAREA",
    }.get(dataset)
    for index in polygons.sindex.query(search_geometry, predicate="intersects"):
        if allowed_source is None or polygons.iloc[index]["WIDTH_SOURCE_DATASET"] == allowed_source:
            candidate_indices.append(int(index))
    candidate_indices = sorted(set(candidate_indices))
    if not candidate_indices:
        return None, None, 0
    candidates = polygons.iloc[candidate_indices]
    river_polygon = unary_union(candidates.geometry.tolist())
    widths = []
    for distance_m in config.mouth_width_sample_distances_m:
        center, section = cross_section(
            row["_TERMINAL_LINE"],
            bool(row["_MOUTH_AT_END"]),
            distance_m,
            config.mouth_width_cross_section_length_m,
        )
        if center is None or section is None:
            continue
        components = line_components(section.intersection(river_polygon))
        if not components:
            continue
        nearest = min(components, key=lambda component: component.distance(center))
        if nearest.distance(center) <= config.mouth_width_polygon_match_distance_m:
            width = float(nearest.length)
            if 0 < width <= config.mouth_width_cross_section_length_m:
                widths.append(width)
    if not widths:
        return None, None, 0
    sources = sorted(set(candidates["WIDTH_SOURCE_DATASET"].astype(str)))
    return float(np.median(widths)), "+".join(sources), len(widths)


def apply_mouth_widths(mouths: Any, bc_polygons: Any, us_polygons: Any, config: Any):
    """Attach measured mouth widths while retaining configured-default provenance."""

    import geopandas as gpd

    frames = []
    for frame, source in (
        (bc_polygons, "BC_FWA_RIVER_POLYGONS"),
        (us_polygons, "US_NHDPLUS_HR_NHDAREA"),
    ):
        polygons = polygon_parts(frame).to_crs(config.projected_crs)
        polygons["WIDTH_SOURCE_DATASET"] = source
        frames.append(polygons)
    polygons = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=config.projected_crs,
    )
    if polygons.empty:
        return mouths
    bc_indices: dict[str, list[int]] = {}
    for index, value in polygons.get("BLUE_LINE_KEY", pd.Series(dtype="string")).items():
        key = clean_optional_text(value)
        if key:
            bc_indices.setdefault(key, []).append(int(index))
    output = mouths.copy()
    for index, row in iter_frame_records(output):
        width, source, sample_count = width_from_polygons(row, polygons, bc_indices, config)
        if width is not None:
            output.at[index, "MOUTH_WIDTH_M"] = width
            output.at[index, "MOUTH_WIDTH_SOURCE_DATASET"] = source
            output.at[index, "MOUTH_WIDTH_METHOD"] = (
                f"median_of_{sample_count}_mapped_polygon_cross_sections"
            )
    return output


__all__ = ["apply_mouth_widths", "cross_section", "line_components", "width_from_polygons"]
