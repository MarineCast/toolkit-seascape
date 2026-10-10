"""Explicit focal versus actual-origin semantics for partial current-mask rays."""

import math

import h3
import shapely


def origin_record(key, support, prior=None):
    row = support.loc[key]
    if bool(row.GRAPH_NODE_ELIGIBLE):
        source = key
        lon = float(row.REPRESENTATIVE_POINT_LONGITUDE)
        lat = float(row.REPRESENTATIVE_POINT_LATITUDE)
        method = "native_graph_water_representative_point"
    elif (
        isinstance(row.CONNECTOR_TARGET_H3_INDEX, str)
        and row.CONNECTOR_TARGET_H3_INDEX in support.index
    ):
        source = row.CONNECTOR_TARGET_H3_INDEX
        connected = support.loc[source]
        lon = float(connected.REPRESENTATIVE_POINT_LONGITUDE)
        lat = float(connected.REPRESENTATIVE_POINT_LATITUDE)
        method = "bound_native_terminal_connector_target_representative_point"
    else:
        source = None
        lat, lon = h3.cell_to_latlng(key)
        method = "unmapped_H3_centre_diagnostic_only"
    if prior is not None and key in prior.index:
        old = prior.loc[key]
        if str(old.ORIGIN_METHOD) == "unmapped_H3_centre_diagnostic_only":
            lat, lon = h3.cell_to_latlng(key)
            source = None
            method = "unmapped_H3_centre_diagnostic_only"
        if (
            abs(lon - float(old.ORIGIN_LONGITUDE)) > 1e-12
            or abs(lat - float(old.ORIGIN_LATITUDE)) > 1e-12
        ):
            raise ValueError("Prior origin policy mismatch: stop")
        method = str(old.ORIGIN_METHOD)
    polygon = shapely.Polygon(
        [(lng, latitude) for latitude, lng in h3.cell_to_boundary(key)]
    )
    within = bool(polygon.covers(shapely.Point(lon, lat)))
    proxy = source is not None and source != key
    return {
        "H3_INDEX": key,
        "H3_RESOLUTION": 8,
        "ORIGIN_LONGITUDE": lon,
        "ORIGIN_LATITUDE": lat,
        "ORIGIN_METHOD": method,
        "ORIGIN_SOURCE_H3_INDEX": source,
        "ORIGIN_WITHIN_FOCAL_H3": within,
        "ORIGIN_IS_CONNECTOR_PROXY": proxy,
        "ORIGIN_METRIC_SCOPE": "connector_target_point_proxy;not_focal_in_cell"
        if proxy
        else (
            "focal_native_water_representative_point"
            if source
            else "unmapped_focal_H3_centre;water_validity_unqualified"
        ),
        "FOCAL_FULL_H3_WITHIN_REGISTERED_EXTENT": bool(
            row.FULL_H3_WITHIN_SOURCE_RECTANGLE
        ),
    }


def metric_record(origin, distance, status):
    if status not in {
        "origin_not_mapped_water",
        "origin_outside_registered_source_extent",
        "source_extent_exit",
        "configured_limit_censored",
        "mapped_geometry_boundary",
    }:
        raise ValueError("Unknown ray status: stop")
    invalid = status.startswith("origin_")
    edge = status == "source_extent_exit"
    cap = status == "configured_limit_censored"
    mapped = status == "mapped_geometry_boundary"
    if invalid and distance is not None:
        raise ValueError("Invalid origin must have NULL distance")
    if not invalid and (
        distance is None
        or not math.isfinite(distance)
        or distance < 0
        or distance > 50000
    ):
        raise ValueError("Ray bound outside declared range")
    if cap and distance != 50000:
        raise ValueError("Cap must equal declared search bound")
    focal_in_cell = bool(
        origin["ORIGIN_WITHIN_FOCAL_H3"]
        and not origin["ORIGIN_IS_CONNECTOR_PROXY"]
        and not invalid
    )
    return {
        "ORIGIN_CONNECTED_MAPPED_WATER_RUN_BOUND_M": distance,
        "ORIGIN_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M": distance if mapped else None,
        "FOCAL_IN_CELL_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M": distance
        if mapped and focal_in_cell
        else None,
        "FIRST_EXIT_STATUS": status,
        "CONFIGURED_LIMIT_CENSORED": cap,
        "WHOLE_RAY_REGISTERED_CONTEXT_CENSORED": edge
        or status == "origin_outside_registered_source_extent",
        "FOCAL_IN_CELL_ORIGIN_ELIGIBLE": focal_in_cell,
        "WHOLE_RAY_FINE_SOURCE_ACCURACY_QUALIFIED": False,
        "PRIMARY_PHYSICAL_FETCH_M": None,
        "FULL_PHYSICAL_FETCH_QUALIFIED": False,
        "SOURCE_COMPLETENESS": "partial",
    }
