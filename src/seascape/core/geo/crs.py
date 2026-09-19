"""Coordinate-unit contracts for planar scientific calculations."""

from __future__ import annotations

import math
from typing import Any

from pyproj import CRS


def require_metric_crs(value: Any) -> CRS:
    """Require two projected horizontal axes measured in meters.

    Projection suitability for the study region remains the caller's responsibility.
    Geographic and foot-based coordinates must never be labeled as meters.
    """
    crs = CRS.from_user_input(value)
    axes = crs.axis_info
    if (
        not crs.is_projected
        or len(axes) < 2
        or any(
            not math.isclose(
                axis.unit_conversion_factor, 1.0, rel_tol=0.0, abs_tol=1e-12
            )
            for axis in axes[:2]
        )
    ):
        raise ValueError(
            f"Scientific projected CRS must have horizontal axes in meters: {value}"
        )
    return crs


def validate_metric_crs_settings(value: Any) -> None:
    """Validate every explicitly named projected-CRS setting in a configuration."""
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).endswith("projected_crs") or key == "equal_area_crs":
                require_metric_crs(child)
            else:
                validate_metric_crs_settings(child)
    elif isinstance(value, list):
        for child in value:
            validate_metric_crs_settings(child)
