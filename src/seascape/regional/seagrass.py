"""Native positive pixel footprints on full R6 support."""

import math

import h3
import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform

TO_AREA = Transformer.from_crs(4326, 6933, always_xy=True)
SEGMENT_DEGREES = 0.001


def cell_geometries(keys, segment_degrees=SEGMENT_DEGREES):
    geographic = [
        Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(k)]) for k in keys
    ]
    projected = [
        transform(TO_AREA.transform, shapely.segmentize(g, segment_degrees))
        for g in geographic
    ]
    return geographic, projected


def select_blocks(headers, geographic):
    """Full source block intersection with full cells; no bbox/water clipping."""
    tree = shapely.STRtree(geographic)
    extent = shapely.total_bounds(geographic)
    rows = []
    for tile, head in enumerate(headers):
        left, bottom, right, top = head["bounds_wgs84"]
        dx, dy = head["resolution"]
        bh, bw = head["block_shapes"][0]
        height, width = head["shape"]
        west, south, east, north = extent
        c0 = max(0, math.floor((max(west, left) - left) / dx / bw))
        c1 = min(math.ceil(width / bw), math.ceil((min(east, right) - left) / dx / bw))
        r0 = max(0, math.floor((top - min(north, top)) / dy / bh))
        r1 = min(
            math.ceil(height / bh), math.ceil((top - max(south, bottom)) / dy / bh)
        )
        if c0 >= c1 or r0 >= r1:
            continue
        for r in range(r0, r1):
            cols = np.arange(c0, c1)
            xmin = left + cols * bw * dx
            ymax = top - r * bh * dy
            shapes = shapely.box(
                xmin,
                np.full(len(cols), ymax - bh * dy),
                xmin + bw * dx,
                np.full(len(cols), ymax),
            )
            hits = tree.query(shapes, predicate="intersects")
            for local in np.unique(hits[0]):
                candidates = sorted(int(v) for v in hits[1, hits[0] == local])
                rows.append([tile, r, int(cols[local]), *candidates])
    return rows


def positive_metrics(raw, affine, row_off, col_off, candidates, keys, projected):
    """Counts via H3 centres; areas via all pixel-footprint overlaps, kept separate."""
    if np.any((raw != 0) & (raw != 1)):
        raise ValueError("Unexpected raster class")
    rr, cc = np.nonzero(raw == 1)
    if not len(rr):
        return {}, {
            "positive_pixels": 0,
            "source_positive_area_m2": 0.0,
            "retained_overlap_area_m2": 0.0,
        }
    west = affine.c + (col_off + cc) * affine.a
    east = west + affine.a
    north = affine.f + (row_off + rr) * affine.e
    south = north + affine.e
    xmin, ymin = TO_AREA.transform(west, south)
    xmax, ymax = TO_AREA.transform(east, north)
    pixels = shapely.box(xmin, ymin, xmax, ymax)
    source_area = float(np.sum((xmax - xmin) * (ymax - ymin)))
    count = {}
    indexes = {keys[i]: i for i in candidates}
    for lon, lat in zip((west + east) / 2, (south + north) / 2):
        key = h3.latlng_to_cell(float(lat), float(lon), 6)
        if key in indexes:
            i = indexes[key]
            count[i] = count.get(i, 0) + 1
    result = {}
    retained = 0.0
    for i in candidates:
        hit = shapely.intersects(pixels, projected[i])
        area = (
            float(np.sum(shapely.area(shapely.intersection(pixels[hit], projected[i]))))
            if np.any(hit)
            else 0.0
        )
        retained += area
        if area or count.get(i):
            result[i] = {
                "positive_pixel_center_count": count.get(i, 0),
                "modeled_positive_footprint_overlap_m2": area,
            }
    if retained > source_area * (1 + 1e-8) + 0.001:
        raise ValueError("Footprint partition exceeds source pixel area")
    return result, {
        "positive_pixels": int(len(rr)),
        "source_positive_area_m2": source_area,
        "retained_overlap_area_m2": retained,
    }
