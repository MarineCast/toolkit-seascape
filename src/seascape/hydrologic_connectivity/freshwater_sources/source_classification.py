"""Documented source-type and permanence classification for freshwater data."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from seascape.utils.values import clean_optional_text


def finite_number(value: Any) -> float | None:
    """Return a finite numeric value without inferring missing values."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def nhd_feature_type(value: Any) -> int | None:
    """Normalize supported NHD feature-type codes and documented text labels."""

    code = finite_number(value)
    if code is not None:
        return int(code)
    normalized = (clean_optional_text(value) or "").lower().replace("/", "").replace(" ", "")
    return {"streamriver": 460, "artificialpath": 558}.get(normalized)


def nhd_flowline_mask(frame: Any) -> pd.Series:
    return frame["FTYPE"].map(nhd_feature_type).isin((460, 558))


def bc_stream_mask(frame: Any) -> pd.Series:
    edge = pd.to_numeric(frame.get("EDGE_TYPE"), errors="coerce")
    return edge.lt(1_200) | edge.isna()


def source_classification(dataset: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only explicitly documented source type and permanence values."""

    source_type = "unknown"
    source_type_field = None
    source_type_code = None
    permanence = "unknown"
    permanence_field = None
    permanence_code = None
    if dataset == "US_NHD_SMALL_SCALE":
        source_type_field = "FTYPE"
        source_type_code = clean_optional_text(row.get("FTYPE"))
        if source_type_code == "StreamRiver":
            source_type = "natural_channel"
        elif source_type_code == "CanalDitch":
            source_type = "artificial_channel"
        permanence_field = "FCODE"
        permanence_code = clean_optional_text(row.get("FCODE"))
        permanence = {
            "46006": "perennial",
            "46003": "intermittent",
            "46007": "ephemeral",
        }.get(permanence_code, "unknown")
    elif dataset == "HYDRORIVERS_V10":
        source_type = "natural_channel"
        source_type_field = "DATASET_DEFINITION"
        source_type_code = "HYDRORIVERS_RIVER_NETWORK"
    elif dataset == "BC_FWA_STREAM_NETWORK":
        source_type_field = "FEATURE_CODE"
        source_type_code = clean_optional_text(row.get("FEATURE_CODE"))
        permanence_field = "EDGE_TYPE"
        permanence_code = clean_optional_text(row.get("EDGE_TYPE"))
    return {
        "MOUTH_SOURCE_TYPE": source_type,
        "MOUTH_SOURCE_TYPE_SOURCE_FIELD": source_type_field,
        "MOUTH_SOURCE_TYPE_SOURCE_CODE": source_type_code,
        "MOUTH_PERMANENCE_CLASS": permanence,
        "MOUTH_PERMANENCE_SOURCE_FIELD": permanence_field,
        "MOUTH_PERMANENCE_SOURCE_CODE": permanence_code,
    }


__all__ = [
    "bc_stream_mask",
    "finite_number",
    "nhd_feature_type",
    "nhd_flowline_mask",
    "source_classification",
]
