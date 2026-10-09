"""Indexed exact native-boundary events on the reviewed 50 km / 100 m rays."""

from types import SimpleNamespace

import numpy as np
import shapely

from .coastal import GEOD, RegisteredGeometryContext


class IndexedFirstExit:
    def __init__(self, water, extent):
        RegisteredGeometryContext(water, extent)
        self.water = water
        self.extent = extent
        shapely.prepare(water)
        self.fragments = []
        for boundary in (water.boundary, extent.boundary):
            for ring in shapely.get_parts(boundary):
                coordinates = shapely.get_coordinates(ring)
                for index in range(0, len(coordinates) - 1, 64):
                    self.fragments.append(
                        shapely.LineString(
                            coordinates[index : min(len(coordinates), index + 65)]
                        )
                    )
        self.tree = shapely.STRtree(self.fragments)

    def calculate(self, longitude, latitude, bearing):
        return self.boundary_exit(
            SimpleNamespace(
                ORIGIN_LONGITUDE=longitude,
                ORIGIN_LATITUDE=latitude,
                BEARING_DEG=bearing,
            )
        )

    def boundary_exit(self, row):
        origin = shapely.Point(row.ORIGIN_LONGITUDE, row.ORIGIN_LATITUDE)
        if not self.extent.covers(origin):
            return (None, "origin_outside_registered_source_extent", 0)
        if not self.water.covers(origin):
            return (None, "origin_not_mapped_water", 0)
        distances = np.linspace(0, 50000, 501)
        xs, ys, _ = GEOD.fwd(
            np.full(501, origin.x),
            np.full(501, origin.y),
            np.full(501, row.BEARING_DEG),
            distances,
        )
        line = shapely.LineString(np.column_stack([xs, ys]))
        members = self.tree.query(line, predicate="intersects")
        events = [0.0, line.length]
        for member in members:
            pending = [line.intersection(self.fragments[member])]
            while pending:
                geometry = pending.pop()
                if geometry.is_empty:
                    continue
                if geometry.geom_type == "Point":
                    events.append(line.project(geometry))
                elif geometry.geom_type == "LineString":
                    events.extend(
                        [
                            line.project(shapely.Point(geometry.coords[0])),
                            line.project(shapely.Point(geometry.coords[-1])),
                        ]
                    )
                elif hasattr(geometry, "geoms"):
                    pending.extend(geometry.geoms)
        events = sorted(set(events))
        for left, right in zip(events[:-1], events[1:]):
            if right - left <= 1e-12:
                continue
            midpoint = line.interpolate((left + right) / 2)
            if not (self.water.covers(midpoint) and self.extent.covers(midpoint)):
                endpoint = line.interpolate(left)
                distance = abs(GEOD.inv(origin.x, origin.y, endpoint.x, endpoint.y)[2])
                return (
                    distance,
                    "source_extent_exit"
                    if endpoint.distance(self.extent.boundary) <= 1e-08
                    else "mapped_geometry_boundary",
                    len(members),
                )
        return (50000.0, "configured_limit_censored", len(members))
