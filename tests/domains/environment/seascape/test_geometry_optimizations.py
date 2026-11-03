"""Offline parity checks for bounded physical geometry operations."""

import numpy as np
import pytest
from shapely.geometry import LineString, MultiLineString, box

from seascape.coastal_configuration.nearshore_transitions import (
    _eligible_supports,
    _shoreline_near_water_mask,
)
from seascape.spatial_support.water_network.geometry import directional_water_fraction
from seascape.spatial_support.water_network.rays import directional_distances


@pytest.mark.parametrize("chunk", [1, 3, 32])
def test_rays_keep_scalar_samples_and_first_dry_point(chunk):
    water = box(-0.3, -0.3, 0.3, 0.3).difference(box(0.02, -0.01, 0.025, 0.01))
    lon = np.array([0.0, 0.29, 0.4, -0.1])
    lat = np.array([0.0, 0.1, 0.0, -0.1])
    maximum = 12000.0
    expected = np.array(
        [
            [
                maximum * directional_water_fraction(x, y, b, maximum, water)
                for b in np.arange(16) * 22.5
            ]
            for x, y in zip(lon, lat, strict=True)
        ]
    )
    np.testing.assert_array_equal(
        directional_distances(lon, lat, maximum, water, cell_chunk=chunk), expected
    )


@pytest.mark.parametrize("maximum", [1.0, 150.0, 600.0, 6400.0, 6425.0])
def test_rays_do_not_change_sample_spacing(maximum):
    water = box(-0.02, -0.02, 0.02, 0.02)
    expected = [
        [
            maximum * directional_water_fraction(0.0, 0.0, b, maximum, water)
            for b in np.arange(16) * 22.5
        ]
    ]
    np.testing.assert_array_equal(
        directional_distances([0.0], [0.0], maximum, water), expected
    )


def test_ray_coordinate_misalignment_rejected():
    with pytest.raises(ValueError, match="aligned"):
        directional_distances([0.0], [0.0, 1.0], 100.0, box(-1, -1, 1, 1))


def test_intact_shoreline_buffers_across_tiles_and_cache_eviction():
    x = np.linspace(-10000, 50000, 1501)
    shoreline = MultiLineString(
        [
            LineString(np.column_stack([x, 20000 + 2200 * np.sin(x / 1700)])),
            *[
                LineString([(19000 + i * 20, 17000), (19005 + i * 20, 23000)])
                for i in range(40)
            ],
        ]
    )
    water = box(-10000, 0, 50000, 40000)
    width = 600.0
    cells = [
        ("left", box(19000, 17000, 20000, 23000)),
        ("right", box(20000, 17000, 21000, 23000)),
        ("empty", box(70000, 0, 71000, 1000)),
    ]
    expected = (
        shoreline.intersection(box(*water.bounds).buffer(width + 1))
        .buffer(width)
        .intersection(water)
    )
    actual = _eligible_supports(cells, water, shoreline, width)
    for key, geometry in cells:
        reference = geometry.intersection(expected)
        # Use the existing producer acceptance budget in square metres, including
        # its scale-relative term, for both area and geometric support.
        np.testing.assert_allclose(
            actual[key].area, reference.area, atol=1e-6, rtol=1e-9
        )
        assert (
            actual[key].symmetric_difference(reference).area
            <= 1e-6 + 1e-9 * reference.area
        )


def test_local_shore_filter_keeps_exact_buffer_predicate():
    water = box(0, 0, 1000, 1000).difference(box(400, 400, 600, 600))
    lines = np.array(
        [
            LineString([(100, 100), (200, 200)]),
            LineString([(1100, 0), (1100, 1000)]),
            LineString([(1300, 0), (1300, 1000)]),
            LineString([(450, 450), (550, 550)]),
        ],
        dtype=object,
    )
    np.testing.assert_array_equal(
        _shoreline_near_water_mask(lines, water, 100.0),
        [water.buffer(100.0).intersects(line) for line in lines],
    )


def test_buffered_interest_matches_dissolved_reference():
    from shapely.geometry import MultiPolygon, Point

    from seascape.coastal_configuration.nearshore_transitions import BufferedInterest

    geometry = MultiPolygon([box(0, 0, 10, 10), box(15, 0, 25, 10)])
    reference = geometry.buffer(5)
    indexed = BufferedInterest(geometry, 5)
    for x in np.linspace(-6, 31, 75):
        for y in np.linspace(-6, 16, 45):
            point = Point(x, y)
            assert indexed.covers(point) == reference.covers(point)


def test_interest_skips_buffer_for_exact_inside_and_far_cases():
    from shapely.geometry import Point, Polygon

    from seascape.coastal_configuration.nearshore_transitions import BufferedInterest

    polygon = Polygon([(0, 0), (100, 0), (100, 10), (10, 10), (10, 100), (0, 100)])
    interest = BufferedInterest(polygon, 5)

    def forbidden(index):
        raise AssertionError("Unnecessary buffer allocation")

    interest._buffer = forbidden
    assert interest.covers(Point(5, 5))
    assert not interest.covers(Point(80, 80))
