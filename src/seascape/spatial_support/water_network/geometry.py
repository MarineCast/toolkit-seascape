"""Reusable geodesic water-path mechanisms for marine graph consumers."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pyproj import Geod
from shapely import covers, from_wkb, points, prepare
from shapely.geometry import LineString
from shapely.prepared import prep

GEOD = Geod(ellps="WGS84")


def _densified_geodesic_line(
    source_lon: float,
    source_lat: float,
    target_lon: float,
    target_lat: float,
    maximum_segment_m: float,
) -> tuple[LineString, float]:
    _azimuth, _back_azimuth, direct_distance = GEOD.inv(
        source_lon, source_lat, target_lon, target_lat
    )
    direct_distance = float(direct_distance)
    interior_count = max(0, int(math.ceil(direct_distance / maximum_segment_m)) - 1)
    interior = (
        GEOD.npts(source_lon, source_lat, target_lon, target_lat, interior_count)
        if interior_count
        else []
    )
    return (
        LineString([(source_lon, source_lat), *interior, (target_lon, target_lat)]),
        direct_distance,
    )


def water_path_metrics(
    source_lon: float,
    source_lat: float,
    target_lon: float,
    target_lat: float,
    water_geometry: Any,
    *,
    maximum_segment_m: float,
    outside_tolerance_m: float,
    prepared_water: Any | None = None,
) -> tuple[float, float, bool]:
    """Return geodesic distance, water fraction, and passability for a segment."""

    line, direct_distance = _densified_geodesic_line(
        source_lon,
        source_lat,
        target_lon,
        target_lat,
        maximum_segment_m,
    )
    path_distance = abs(float(GEOD.geometry_length(line)))
    if path_distance <= 0.0:
        return direct_distance, 1.0, True
    prepared = prepared_water if prepared_water is not None else prep(from_wkb(water_geometry.wkb))
    if prepared.covers(line):
        return direct_distance, 1.0, True
    water_part = line.intersection(water_geometry)
    water_distance = min(path_distance, abs(float(GEOD.geometry_length(water_part))))
    outside_distance = max(0.0, path_distance - water_distance)
    fraction = float(np.clip(water_distance / path_distance, 0.0, 1.0))
    return direct_distance, fraction, outside_distance <= outside_tolerance_m + 1e-9


def directional_water_fraction(
    longitude: float,
    latitude: float,
    bearing: float,
    maximum_distance_m: float,
    water_geometry: Any,
    *,
    maximum_segment_m: float = 100.0,
) -> float:
    """Return uninterrupted water fraction along a sampled geodesic bearing."""

    sample_count = max(2, int(math.ceil(maximum_distance_m / maximum_segment_m)) + 1)
    distances = np.linspace(0.0, maximum_distance_m, sample_count)
    longitudes, latitudes, _back_azimuth = GEOD.fwd(
        np.full(sample_count, float(longitude)),
        np.full(sample_count, float(latitude)),
        np.full(sample_count, float(bearing)),
        distances,
    )
    prepare(water_geometry)
    in_water = np.asarray(covers(water_geometry, points(longitudes, latitudes)), dtype=bool)
    first_land = np.flatnonzero(~in_water)
    if not len(first_land):
        return 1.0
    stop = int(first_land[0])
    if stop == 0:
        return 0.0
    return float(np.clip(distances[stop - 1] / maximum_distance_m, 0.0, 1.0))
