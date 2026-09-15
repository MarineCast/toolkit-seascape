"""Geospatial distance helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    *,
    radius_m: float = EARTH_RADIUS_M,
) -> float:
    """Return great-circle distance between two WGS84 coordinates in meters."""
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return float(radius_m) * c


def geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return WGS84 ellipsoidal distance between two coordinates in meters."""
    try:
        from pyproj import Geod
    except Exception as e:
        raise ImportError("Install pyproj to use geodesic_distance_m.") from e

    _, _, dist_m = Geod(ellps="WGS84").inv(float(lon1), float(lat1), float(lon2), float(lat2))
    return float(dist_m)


haversine_distance = haversine_distance_m
geodesic_distance = geodesic_distance_m
