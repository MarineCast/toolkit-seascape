import h3
import pandas as pd
import pytest

from seascape.regional.coastal_origin import metric_record, origin_record


def support_pair():
    key = h3.latlng_to_cell(48, -123, 8)
    neighbor = next(x for x in h3.grid_disk(key, 1) if x != key)
    lat, lon = h3.cell_to_latlng(neighbor)
    frame = pd.DataFrame(
        [
            {
                "H3_INDEX": key,
                "GRAPH_NODE_ELIGIBLE": False,
                "CONNECTOR_TARGET_H3_INDEX": neighbor,
                "REPRESENTATIVE_POINT_LONGITUDE": -123,
                "REPRESENTATIVE_POINT_LATITUDE": 48,
                "FULL_H3_WITHIN_SOURCE_RECTANGLE": True,
            },
            {
                "H3_INDEX": neighbor,
                "GRAPH_NODE_ELIGIBLE": True,
                "CONNECTOR_TARGET_H3_INDEX": None,
                "REPRESENTATIVE_POINT_LONGITUDE": lon,
                "REPRESENTATIVE_POINT_LATITUDE": lat,
                "FULL_H3_WITHIN_SOURCE_RECTANGLE": True,
            },
        ]
    ).set_index("H3_INDEX")
    return key, neighbor, frame


def test_off_cell_connector_is_explicit_proxy_and_focal_metric_NULL():
    key, neighbor, frame = support_pair()
    origin = origin_record(key, frame)
    assert (
        origin["ORIGIN_SOURCE_H3_INDEX"] == neighbor
        and origin["ORIGIN_IS_CONNECTOR_PROXY"]
        and not origin["ORIGIN_WITHIN_FOCAL_H3"]
    )
    metric = metric_record(origin, 25.0, "mapped_geometry_boundary")
    assert (
        metric["ORIGIN_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M"] == 25
        and metric["FOCAL_IN_CELL_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M"] is None
    )


def test_unmapped_origin_never_moves_silently():
    key, _, frame = support_pair()
    frame.loc[key, "CONNECTOR_TARGET_H3_INDEX"] = None
    origin = origin_record(key, frame)
    assert origin["ORIGIN_SOURCE_H3_INDEX"] is None
    assert (
        metric_record(origin, None, "origin_not_mapped_water")[
            "ORIGIN_CONNECTED_MAPPED_WATER_RUN_BOUND_M"
        ]
        is None
    )


def test_cap_and_edge_are_bounds_and_not_mapped_shores():
    key, _, frame = support_pair()
    origin = origin_record(key, frame)
    for value, status in [
        (50000.0, "configured_limit_censored"),
        (750.0, "source_extent_exit"),
    ]:
        assert (
            metric_record(origin, value, status)[
                "ORIGIN_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M"
            ]
            is None
        )


def test_unknown_cannot_be_observed_zero():
    key, _, frame = support_pair()
    origin = origin_record(key, frame)
    with pytest.raises(ValueError, match="NULL"):
        metric_record(origin, 0.0, "origin_not_mapped_water")


def test_range_and_cap_invariants_stop():
    key, _, frame = support_pair()
    origin = origin_record(key, frame)
    with pytest.raises(ValueError, match="range"):
        metric_record(origin, 50001.0, "mapped_geometry_boundary")
    with pytest.raises(ValueError, match="Cap"):
        metric_record(origin, 49000.0, "configured_limit_censored")


def test_frozen_invalid_centre_anchor_is_not_moved_to_graph_point():
    key, _, frame = support_pair()
    frame.loc[key, "GRAPH_NODE_ELIGIBLE"] = True
    lat, lon = h3.cell_to_latlng(key)
    prior = pd.DataFrame(
        [
            {
                "H3_INDEX": key,
                "ORIGIN_LONGITUDE": lon,
                "ORIGIN_LATITUDE": lat,
                "ORIGIN_METHOD": "unmapped_H3_centre_diagnostic_only",
            }
        ]
    ).set_index("H3_INDEX")
    origin = origin_record(key, frame, prior)
    assert (
        origin["ORIGIN_SOURCE_H3_INDEX"] is None
        and origin["ORIGIN_LONGITUDE"] == lon
        and origin["ORIGIN_LATITUDE"] == lat
    )


def test_unrecognized_status_is_stop_condition():
    key, _, frame = support_pair()
    origin = origin_record(key, frame)
    with pytest.raises(ValueError, match="Unknown"):
        metric_record(origin, 10.0, "unregistered_status")
