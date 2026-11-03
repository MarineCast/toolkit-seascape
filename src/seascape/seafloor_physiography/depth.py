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


def validate_native_metre_band_units(units: Any) -> None:
    """Reject explicit nonmetre/unknown band units; no numerical conversion.

    An absent band label needs the caller's source interpretation contract and does not
    itself certify units or vertical datum.
    """
    if units is not None and (
        not isinstance(units, str)
        or units.strip().casefold() not in {"m", "metre", "metres", "meter", "meters"}
    ):
        raise ValueError(
            "Explicit native band units conflict with metre interpretation or are unknown; no conversion is supported."
        )
