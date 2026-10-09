"""Qualify floating-point ring collapse after projection, never repair sources."""

import numpy as np
import shapely


def qualify_projected_geometries(native, projected):
    if not all((g.is_valid for g in native)):
        raise ValueError("Invalid native source: stop")
    output = list(projected)
    evidence = []
    for i, g in enumerate(projected):
        if g.is_valid:
            continue
        fixed = shapely.make_valid(g)
        delta = abs(fixed.area - g.area)
        before = np.ascontiguousarray(shapely.get_coordinates(g))
        after = np.ascontiguousarray(shapely.get_coordinates(fixed))
        typ = np.dtype([("x", np.float64), ("y", np.float64)])
        original = np.unique(before.view(typ).ravel())
        repaired = np.unique(after.view(typ).ravel())
        removed = np.setdiff1d(original, repaired)
        if not len(removed) == 0:
            raise ValueError("Projection repair removed original vertices: stop")
        added = np.setdiff1d(repaired, original)
        new_coords = added.view(np.float64).reshape(-1, 2)
        displacement = max(
            (float(shapely.Point(x, y).distance(g.boundary)) for x, y in new_coords),
            default=0.0,
        )
        if not (delta <= 0.01 and delta / max(abs(g.area), 1) <= 1e-10):
            raise ValueError("Projection repair area exceeds precision guard")
        if not displacement <= 1e-06:
            raise ValueError(
                "Projection repair new vertex is outside one micrometre boundary guard"
            )
        if not fixed.is_valid:
            raise ValueError("Scientific validation failed")
        evidence.append(
            {
                "index": i,
                "native_valid": True,
                "projected_reason": shapely.is_valid_reason(g),
                "absolute_area_change_m2": delta,
                "added_vertex_boundary_distance_m": displacement,
                "result_type": fixed.geom_type,
            }
        )
        output[i] = fixed
    return (output, evidence)
