"""Native one-degree source seams distinguished from mapped shoreline edges."""

import numpy as np
import shapely

from seascape.coastal_configuration.shoreline_proximity.build import _line_parts


def mapped_shoreline_parts(land_frame, water_frame, study, guard=lambda: None):
    if (
        land_frame.crs.to_epsg() != 4326
        or water_frame.crs.to_epsg() != 4326
        or not land_frame.geometry.is_valid.all()
        or not water_frame.geometry.is_valid.all()
        or "tile" not in land_frame
    ):
        raise ValueError(
            "Qualified native one-degree tiled land/water geometry required"
        )
    waters = water_frame.geometry.to_numpy()
    water_tree = shapely.STRtree(waters)
    parts = []
    removed_cut_segments = 0
    retained_edge_coast_segments = 0
    for row in land_frame.itertuples():
        tile_west, tile_south = [int(v) for v in row.tile.split(",")]
        west = max(tile_west, study.bounds[0])
        east = min(tile_west + 1, study.bounds[2])
        north = min(tile_south + 1, study.bounds[3])
        south = max(tile_south, study.bounds[1])
        for boundary in _line_parts(row.geometry.boundary):
            coords = shapely.get_coordinates(boundary)
            first = coords[:-1]
            second = coords[1:]
            edge_segments = np.zeros(len(first), dtype=bool)
            outer_segments = np.zeros(len(first), dtype=bool)
            for axis, limits in ((0, (west, east)), (1, (south, north))):
                for limit in limits:
                    edge_segments |= (first[:, axis] == limit) & (
                        second[:, axis] == limit
                    )
                for limit in (study.bounds[axis], study.bounds[axis + 2]):
                    outer_segments |= (first[:, axis] == limit) & (
                        second[:, axis] == limit
                    )
            keep = ~edge_segments
            ambiguous = np.flatnonzero(edge_segments & ~outer_segments)
            if len(ambiguous):
                midpoints = shapely.points((first[ambiguous] + second[ambiguous]) / 2)
                nearest = water_tree.nearest(midpoints)
                adjacent = shapely.distance(midpoints, waters[nearest]) <= 1e-10
                keep[ambiguous] = adjacent
                retained_edge_coast_segments += int(adjacent.sum())
            removed_cut_segments += int((~keep).sum())
            # Maximal contiguous runs, then <=1000vertex chunks without changing vertices.
            starts = np.flatnonzero(keep & ~np.r_[False, keep[:-1]])
            ends = np.flatnonzero(keep & ~np.r_[keep[1:], False]) + 1
            for begin, end in zip(starts, ends, strict=True):
                for offset in range(int(begin), int(end), 999):
                    parts.append(
                        shapely.LineString(
                            coords[offset : min(offset + 1000, int(end) + 1)]
                        )
                    )
        guard()

    if not parts:
        raise ValueError("No retained mapped shoreline segments")
    return parts, {
        "removed_cut_segments": removed_cut_segments,
        "retained_edge_coast_segments": retained_edge_coast_segments,
    }
