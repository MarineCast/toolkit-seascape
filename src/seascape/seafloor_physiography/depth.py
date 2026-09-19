"""Positive-down input contract shared by terrain and sill consumers."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def require_positive_down_config(raw: Mapping[str, Any]) -> None:
    """Reject incompatible or undeclared bathymetry before dependent processing."""
    sign = raw.get("bathymetry", {}).get("processing", {}).get("bathymetry_sign")
    if sign != "positive_down":
        raise ValueError(
            "Terrain and sill products require explicit bathymetry_sign: positive_down; "
            "negative_elevation is supported only for standalone bathymetry exports."
        )


def validate_positive_depth(values: pd.Series) -> None:
    """Reject negative depth values while retaining nodata as missing."""
    depth = pd.to_numeric(values, errors="raise")
    if depth.dropna().lt(0).any():
        raise ValueError(
            "Terrain and sill products require nonnegative positive-down bathymetry."
        )
