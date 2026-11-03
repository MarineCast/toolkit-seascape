"""Versioned continuous first exit on a densified WGS84 geodesic polyline.

This diagnoses mapped geometry only. It never fills unregistered source extent,
repairs native sources, or upgrades coastline/source accuracy.
"""

import math
from dataclasses import dataclass

import numpy as np
import shapely
from pyproj import Geod

GEOD = Geod(ellps="WGS84")
METHOD_VERSION = "continuous_mapped_water_first_exit_geodesic_polyline_v2"


@dataclass(frozen=True)
class RegisteredGeometryContext:
    water_geometry: object
    source_extent: object

    def __post_init__(self):
        if not self.water_geometry.is_valid or not self.source_extent.is_valid:
            raise ValueError("Native geometry must be valid; no silent repair")


def continuous_first_exit(
    longitude,
    latitude,
    bearing,
    maximum_distance_m,
    water_geometry,
    source_extent,
    *,
    maximum_segment_m=100.0,
    validated_context=None,
):
    if maximum_distance_m <= 0 or maximum_segment_m <= 0:
        raise ValueError("Distance and segment bounds must be positive")
    if validated_context is None:
        RegisteredGeometryContext(water_geometry, source_extent)
    elif (
        not isinstance(validated_context, RegisteredGeometryContext)
        or validated_context.water_geometry is not water_geometry
        or validated_context.source_extent is not source_extent
    ):
        raise ValueError(
            "Validated context must bind these exact immutable geometry objects"
        )
    origin = shapely.Point(longitude, latitude)
    common = {
        "method_version": METHOD_VERSION,
        "maximum_search_m": float(maximum_distance_m),
        "geodesic_polyline_max_segment_m": float(maximum_segment_m),
        "physical_source_accuracy": "unqualified;partial_fine/generalized_mapped_geometry",
    }
    if not shapely.covers(source_extent, origin):
        return {
            **common,
            "connected_water_run_bound_m": None,
            "mapped_boundary_distance_m": None,
            "first_exit_status": "origin_outside_registered_source_extent",
            "configured_limit_censored": False,
            "source_context_censored": True,
        }
    if not shapely.covers(water_geometry, origin):
        return {
            **common,
            "connected_water_run_bound_m": None,
            "mapped_boundary_distance_m": None,
            "first_exit_status": "origin_not_mapped_water",
            "configured_limit_censored": False,
            "source_context_censored": False,
        }
    count = max(2, int(math.ceil(maximum_distance_m / maximum_segment_m)) + 1)
    distances = np.linspace(0, maximum_distance_m, count)
    xs, ys, _ = GEOD.fwd(
        np.full(count, float(longitude)),
        np.full(count, float(latitude)),
        np.full(count, float(bearing)),
        distances,
    )
    line = shapely.LineString(np.column_stack([xs, ys]))
    # Clip to registered source as well as mapped water. Unknown exterior is not
    # inferred as navigable water even if a caller supplies wider cartography.
    connected = line.intersection(water_geometry).intersection(source_extent)
    intervals = []
    pending = [connected]
    while pending:
        geometry = pending.pop()
        if geometry.is_empty:
            continue
        if geometry.geom_type == "LineString":
            coordinates = list(geometry.coords)
            a = line.project(shapely.Point(coordinates[0]))
            b = line.project(shapely.Point(coordinates[-1]))
            intervals.append((min(a, b), max(a, b)))
        elif hasattr(geometry, "geoms"):
            pending.extend(geometry.geoms)
    reach = 0.0
    # One-picometre angular tolerance only joins floating arithmetic at identical
    # interval endpoints, not a physical gap-filling or coastline tolerance.
    for start, end in sorted(intervals):
        if start <= reach + 1e-12:
            reach = max(reach, end)
        else:
            break
    endpoint = line.interpolate(reach)
    if reach >= line.length - 1e-12:
        return {
            **common,
            "connected_water_run_bound_m": float(maximum_distance_m),
            "mapped_boundary_distance_m": None,
            "first_exit_status": "configured_limit_censored",
            "configured_limit_censored": True,
            "source_context_censored": False,
        }
    distance = min(
        float(maximum_distance_m),
        abs(float(GEOD.inv(longitude, latitude, endpoint.x, endpoint.y)[2])),
    )
    edge = endpoint.distance(source_extent.boundary) <= 1e-8
    return {
        **common,
        "connected_water_run_bound_m": distance,
        "mapped_boundary_distance_m": None if edge else distance,
        "first_exit_status": "source_extent_exit"
        if edge
        else "mapped_geometry_boundary",
        "configured_limit_censored": False,
        "source_context_censored": bool(edge),
    }
