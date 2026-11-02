"""Regression for baseline cancellation in nearly flat OLS planes."""

import math
from decimal import Decimal, localcontext

import numpy as np

from seascape.seafloor_physiography.geomorphometry.build import (
    _plane_coefficients,
    _plane_metrics,
)


def test_near_flat_gradient_matches_independent_decimal_solution():
    keys = ["a", "b", "c", "d"]
    centers = dict(
        zip(
            keys,
            [(0.0, 0.0), (2000.0, 0.0), (2000.0, 2000.0), (0.0, 2000.0)],
            strict=True,
        )
    )
    depths = {k: 30000.0 + x * 1e-8 + y * 2e-8 for k, (x, y) in centers.items()}
    with localcontext() as ctx:
        ctx.prec = 60
        z = [Decimal.from_float(depths[k]) for k in keys]
        expected = [
            float((z[1] + z[2] - z[0] - z[3]) / 4000),
            float((z[2] + z[3] - z[0] - z[1]) / 4000),
        ]
    actual = _plane_coefficients(keys, depths, centers)
    np.testing.assert_allclose(actual[:2], expected, atol=1e-20, rtol=1e-12)
    _, aspect = _plane_metrics("a", keys[1:], depths, centers)
    assert abs(aspect - math.degrees(math.atan2(*expected))) < 1e-9


def test_flat_depth_has_no_aspect():
    centers = {"a": (0.0, 0.0), "b": (1000.0, 0.0), "c": (0.0, 1000.0)}
    slope, aspect = _plane_metrics(
        "a", ["b", "c"], dict.fromkeys(centers, 30000.0), centers
    )
    assert slope == 0
    assert math.isnan(aspect)
