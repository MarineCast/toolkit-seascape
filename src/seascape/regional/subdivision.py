"""Exact Cartesian partition of already qualified projected water geometry."""

import math

import numpy as np
import shapely


def subdivide_water(geometries, guard=lambda: None, side_m=10000):
    if not np.isfinite(side_m) or side_m <= 0:
        raise ValueError("Subdivision side must be positive and finite")
    if any(g.is_empty or not g.is_valid for g in geometries):
        raise ValueError("Subdivision requires valid nonempty qualified geometry")
    output = []
    evidence = []
    for index, g in enumerate(geometries):
        west, south, east, north = g.bounds
        local = []
        for x in range(math.floor(west / side_m), math.floor(east / side_m) + 1):
            for y in range(math.floor(south / side_m), math.floor(north / side_m) + 1):
                piece = g.intersection(
                    shapely.box(
                        x * side_m, y * side_m, (x + 1) * side_m, (y + 1) * side_m
                    )
                )
                if not piece.is_empty:
                    if not piece.is_valid:
                        raise ValueError("Scientific validation failed")
                    local.append(piece)
            guard()
        summed = sum((p.area for p in local))
        delta = abs(summed - g.area)
        if not (delta <= 0.05 and delta / max(g.area, 1) <= 1e-10):
            raise ValueError("Scientific validation failed")
        evidence.append(
            {
                "source_piece": index,
                "subpieces": len(local),
                "sum_area_difference_m2": delta,
            }
        )
        output.extend(local)
        guard()
    return (np.asarray(output, dtype=object), evidence)
