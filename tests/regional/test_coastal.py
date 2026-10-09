"""Narrow-barrier, registered-edge, origin and censoring regression cases."""

import pytest
import shapely
from pyproj import Geod

from seascape.regional.coastal import continuous_first_exit

G = Geod(ellps="WGS84")
LON = -123.0
LAT = 48.0


def x(m):
    return G.fwd(LON, LAT, 90, m)[0]


def extent():
    return shapely.box(LON - 0.02, LAT - 0.02, LON + 0.02, LAT + 0.02)


def barrier(a, b):
    return extent().difference(shapely.box(x(a), LAT - 0.003, x(b), LAT + 0.003))


@pytest.mark.parametrize(
    "start,end", [(45, 55), (180.283, 188.542), (252.029, 273.385)]
)
def test_continuous_first_exit_stops_at_narrow_barrier_between_sample_stations(
    start, end
):
    result = continuous_first_exit(LON, LAT, 90, 1000, barrier(start, end), extent())
    assert result["mapped_boundary_distance_m"] == pytest.approx(start, abs=0.05)
    assert result["first_exit_status"] == "mapped_geometry_boundary"
    assert (
        not result["configured_limit_censored"]
        and not result["source_context_censored"]
    )


def test_registered_extent_edge_is_censored_not_measured_shore():
    edge = shapely.box(LON - 0.02, LAT - 0.02, x(750), LAT + 0.02)
    result = continuous_first_exit(LON, LAT, 90, 1000, edge, edge)
    assert result["connected_water_run_bound_m"] == pytest.approx(750, abs=0.05)
    assert result["mapped_boundary_distance_m"] is None
    assert (
        result["first_exit_status"] == "source_extent_exit"
        and result["source_context_censored"]
    )


def test_wider_water_does_not_fill_unregistered_exterior():
    edge = shapely.box(LON - 0.02, LAT - 0.02, x(750), LAT + 0.02)
    result = continuous_first_exit(LON, LAT, 90, 1000, extent(), edge)
    assert result["first_exit_status"] == "source_extent_exit"
    assert result["mapped_boundary_distance_m"] is None


def test_configured_limit_stays_cap_censored_not_measured_shore():
    result = continuous_first_exit(LON, LAT, 90, 500, barrier(550, 650), extent())
    assert result["connected_water_run_bound_m"] == 500
    assert result["mapped_boundary_distance_m"] is None
    assert (
        result["configured_limit_censored"]
        and result["first_exit_status"] == "configured_limit_censored"
    )


def test_origin_on_land_is_unknown_not_zero_shore_distance():
    result = continuous_first_exit(x(50), LAT, 90, 500, barrier(45, 55), extent())
    assert result["first_exit_status"] == "origin_not_mapped_water"
    assert (
        result["connected_water_run_bound_m"] is None
        and result["mapped_boundary_distance_m"] is None
    )


def test_origin_outside_source_is_unknown():
    result = continuous_first_exit(LON - 0.03, LAT, 90, 500, extent(), extent())
    assert result["first_exit_status"] == "origin_outside_registered_source_extent"
    assert (
        result["source_context_censored"]
        and result["connected_water_run_bound_m"] is None
    )


@pytest.mark.parametrize("limit,segment", [(0, 100), (1000, 0), (-1, 100)])
def test_invalid_distance_parameters_rejected(limit, segment):
    with pytest.raises(ValueError, match="bounds must be positive"):
        continuous_first_exit(
            LON, LAT, 90, limit, extent(), extent(), maximum_segment_m=segment
        )


def test_invalid_native_geometry_is_not_silently_repaired():
    bad = shapely.Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    with pytest.raises(ValueError, match="no silent repair"):
        continuous_first_exit(LON, LAT, 90, 500, bad, extent())


def test_cached_validity_context_is_bound_to_exact_immutable_source_objects():
    from seascape.regional.coastal import RegisteredGeometryContext

    water = extent()
    source = extent()
    context = RegisteredGeometryContext(water, source)
    result = continuous_first_exit(
        LON, LAT, 90, 500, water, source, validated_context=context
    )
    assert result["configured_limit_censored"]
    with pytest.raises(ValueError, match="exact immutable geometry objects"):
        continuous_first_exit(
            LON, LAT, 90, 500, extent(), source, validated_context=context
        )


def test_indexed_events_match_continuous_kernel_with_thin_barrier():
    from seascape.regional.coastal_index import IndexedFirstExit

    water = barrier(45, 55)
    source = extent()
    indexed = IndexedFirstExit(water, source)
    for bearing in (0, 22.5, 90, 180, 270):
        distance, status, _ = indexed.calculate(LON, LAT, bearing)
        expected = continuous_first_exit(LON, LAT, bearing, 50000, water, source)
        assert status == expected["first_exit_status"]
        assert distance == pytest.approx(
            expected["connected_water_run_bound_m"], abs=1e-5
        )
