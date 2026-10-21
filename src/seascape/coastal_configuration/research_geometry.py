"""Bounded source-water paths and bank sections for explicit research registries."""

from __future__ import annotations

import heapq
import math

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.prepared import prep


def source_water_path(
    water,
    anchors,
    *,
    grid_m=50.0,
    margin_m=3000.0,
    max_cells=1_000_000,
    max_anchor_distance_m=2500.0,
):
    """Find a deterministic axis through ordered research anchors in source water.

    Every edge is checked against physical source geometry. The clearance cost
    chooses an interior research path; it supplies no depth/navigation inference.
    """
    if len(anchors) < 2 or min(grid_m, margin_m) <= 0 or not water.is_valid:
        raise ValueError("Valid water, two route anchors and positive scales required")
    xy = np.asarray(anchors, dtype=float)
    if xy.shape != (len(anchors), 2) or not np.isfinite(xy).all():
        raise ValueError("Route anchors must be finite metric coordinate pairs")
    xmin, ymin = np.floor((xy.min(axis=0) - margin_m) / grid_m) * grid_m
    xmax, ymax = np.ceil((xy.max(axis=0) + margin_m) / grid_m) * grid_m
    width, height = (
        int(round((xmax - xmin) / grid_m)),
        int(round((ymax - ymin) / grid_m)),
    )
    if width * height > max_cells:
        raise ValueError("Research path grid budget exceeded")
    local = water.intersection(box(xmin, ymin, xmax, ymax))
    wet = rasterize(
        [(local, 1)],
        out_shape=(height, width),
        transform=from_origin(xmin, ymax, grid_m, grid_m),
        dtype="uint8",
    )
    iy, ix = np.nonzero(wet)
    if not len(ix):
        raise ValueError("No source water in research path extent")
    coords = np.column_stack((xmin + (ix + 0.5) * grid_m, ymax - (iy + 0.5) * grid_m))
    distance, nearest = cKDTree(coords).query(xy)
    if np.any(distance > max_anchor_distance_m):
        raise ValueError("Research anchor too far from physical source water")
    nodes = [(int(iy[i]), int(ix[i])) for i in nearest]
    clearance = distance_transform_edt(wet) * grid_m
    prepared = prep(local)

    def coordinate(node):
        row, col = node
        return xmin + (col + 0.5) * grid_m, ymax - (row + 0.5) * grid_m

    def segment(start, end):
        queue = [(0.0, 0.0, start)]
        costs, parents = {start: 0.0}, {}
        while queue:
            _, cost, node = heapq.heappop(queue)
            if cost != costs.get(node):
                continue
            if node == end:
                result = [node]
                while result[-1] != start:
                    result.append(parents[result[-1]])
                return result[::-1]
            row, col = node
            for dy, dx in (
                (-1, 0),
                (0, -1),
                (0, 1),
                (1, 0),
                (-1, -1),
                (-1, 1),
                (1, -1),
                (1, 1),
            ):
                other = row + dy, col + dx
                y, x = other
                if not (0 <= y < height and 0 <= x < width and wet[y, x]):
                    continue
                length = grid_m * math.hypot(dy, dx)
                candidate = cost + length * (1 + grid_m / max(clearance[y, x], grid_m))
                if candidate >= costs.get(other, math.inf):
                    continue
                if not prepared.covers(
                    LineString([coordinate(node), coordinate(other)])
                ):
                    continue
                costs[other], parents[other] = candidate, node
                heuristic = grid_m * math.hypot(y - end[0], x - end[1])
                heapq.heappush(queue, (candidate + heuristic, candidate, other))
        raise ValueError(
            "No source-water path between ordered route anchors at this grid"
        )

    path = []
    for start, end in zip(nodes[:-1], nodes[1:], strict=True):
        part = segment(start, end)
        path.extend(part if not path else part[1:])
    if len(set(path)) != len(path):
        raise ValueError("Research axis repeats a grid node; review route anchors")
    line = LineString([coordinate(node) for node in path])
    simplified = line.simplify(grid_m / 2)
    if prepared.covers(simplified):
        line = simplified
    if not prepared.covers(line) or not line.is_simple or line.length == 0:
        raise ValueError("Research axis is not a simple, source-water-covered line")
    return line, {
        "grid_m": grid_m,
        "processing_bounds": [xmin, ymin, xmax, ymax],
        "grid_cells": width * height,
        "anchor_displacement_m": distance.tolist(),
        "water_path_valid": True,
        "method": "source_water_grid_astar_clearance_v1",
    }


def bank_section(
    water, axis, *, position_m=None, half_length_m=50000.0, tangent_m=1000.0
):
    """Return the single source-bank interval containing the selected axis station."""
    position = axis.length / 2 if position_m is None else position_m
    center = axis.interpolate(position)
    a, b = (
        axis.interpolate(max(0, position - tangent_m / 2)),
        axis.interpolate(min(axis.length, position + tangent_m / 2)),
    )
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy)
    if norm == 0 or half_length_m <= 0:
        raise ValueError("Unresolved axis tangent or invalid section extent")
    nx, ny = -dy / norm, dx / norm
    section = LineString(
        [
            (center.x - nx * half_length_m, center.y - ny * half_length_m),
            (center.x + nx * half_length_m, center.y + ny * half_length_m),
        ]
    )
    from .passage_sections import _line_parts

    parts = [
        g for g in _line_parts(section.intersection(water)) if g.distance(center) < 1e-6
    ]
    if len(parts) != 1:
        raise ValueError("Gateway station has no unique contiguous water interval")
    part = parts[0]
    if any(
        water.boundary.distance(Point(c)) > 1e-6
        or section.boundary.distance(Point(c)) < 1e-6
        for c in (part.coords[0], part.coords[-1])
    ):
        raise ValueError("Gateway section is bank-censored at its analysis extent")
    return part


def bounded_passage(water, axis, *, cross_channel_extent_m=60000.0):
    """Select physical water between declared research endcaps, retaining islands."""
    length = max(axis.length * 4, cross_channel_extent_m * 4)
    result = water.intersection(box(*axis.bounds).buffer(cross_channel_extent_m))
    coords = list(axis.coords)
    for a, b in ((coords[0], coords[1]), (coords[-1], coords[-2])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy)
        dx, dy = dx / norm, dy / norm
        nx, ny = -dy, dx
        # Extend computational endcaps by 1 cm; physical water is unchanged.
        a = (a[0] - dx * 0.01, a[1] - dy * 0.01)
        halfplane = Polygon(
            [
                (a[0] + nx * length, a[1] + ny * length),
                (a[0] - nx * length, a[1] - ny * length),
                (a[0] - nx * length + dx * length, a[1] - ny * length + dy * length),
                (a[0] + nx * length + dx * length, a[1] + ny * length + dy * length),
            ]
        )
        result = result.intersection(halfplane)
    if not result.is_valid or not result.buffer(1e-7).covers(axis):
        raise ValueError("Research endcaps exclude the axis; review its endpoints")
    return result
