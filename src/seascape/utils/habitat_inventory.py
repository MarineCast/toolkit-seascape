"""Canonical inventory normalization shared by habitat surface families."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .values import clean_optional_text

NORMALIZED_INVENTORY_COLUMNS = [
    "RECORD_ID",
    "HABITAT_TYPE",
    "SOURCE_DATASET",
    "SOURCE_FEATURE_ID",
    "EVIDENCE_CLASS",
    "OBSERVED_VS_MODELED",
    "OBSERVATION_STATUS",
    "OBSERVATION_YEAR",
    "COMPOSITION_ELIGIBLE",
    "SUPPORTS_AREA",
    "COVERAGE_WEIGHT",
    "SOURCE_PERSISTENCE_RATIO",
    "CONFIDENCE_CLASS",
    "SURVEY_METHOD",
    "SPATIAL_PRECISION_CLASS",
    "TEMPORAL_PRECISION_CLASS",
    "geometry",
]


def normalize_inventory(frame: Any) -> Any:
    """Validate and canonicalize a source-specific habitat inventory."""

    import geopandas as gpd

    if not isinstance(frame, gpd.GeoDataFrame):
        frame = gpd.GeoDataFrame(frame, geometry="geometry")
    missing = sorted(set(NORMALIZED_INVENTORY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Normalized habitat inventory is missing columns: {missing}")
    frame = frame.loc[:, NORMALIZED_INVENTORY_COLUMNS].copy()
    if frame.crs is None:
        raise ValueError("Normalized habitat inventory must retain CRS metadata.")
    frame = frame.to_crs("EPSG:4326")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if frame.empty:
        raise ValueError("Normalized habitat inventory contains no usable geometry.")
    frame["RECORD_ID"] = frame["RECORD_ID"].astype("string")
    if frame["RECORD_ID"].isna().any() or frame["RECORD_ID"].duplicated().any():
        raise ValueError("Normalized habitat record IDs must be non-null and unique.")
    allowed_evidence = {
        "direct_observation",
        "generalized_mapping",
        "modeled_occurrence",
        "modeled_potential",
    }
    if not set(frame["EVIDENCE_CLASS"].dropna()).issubset(allowed_evidence):
        raise ValueError("Habitat evidence class must be direct, generalized, or modeled.")
    allowed_mode = {"observed", "modeled"}
    if not set(frame["OBSERVED_VS_MODELED"].dropna()).issubset(allowed_mode):
        raise ValueError("OBSERVED_VS_MODELED must contain only observed or modeled.")
    allowed_status = {"present", "absent", "potential"}
    if not set(frame["OBSERVATION_STATUS"].dropna()).issubset(allowed_status):
        raise ValueError("Habitat status must be present, absent, or potential.")
    for column in ("COMPOSITION_ELIGIBLE", "SUPPORTS_AREA"):
        frame[column] = frame[column].fillna(False).astype(bool)
    frame["COVERAGE_WEIGHT"] = pd.to_numeric(frame["COVERAGE_WEIGHT"], errors="raise")
    if not frame["COVERAGE_WEIGHT"].between(0.0, 1.0).all():
        raise ValueError("Habitat coverage weights must be in [0, 1].")
    frame["SOURCE_PERSISTENCE_RATIO"] = pd.to_numeric(
        frame["SOURCE_PERSISTENCE_RATIO"], errors="coerce"
    )
    if not frame["SOURCE_PERSISTENCE_RATIO"].dropna().between(0.0, 1.0).all():
        raise ValueError("Source persistence ratios must be null or in [0, 1].")
    frame["CONFIDENCE_CLASS"] = pd.to_numeric(frame["CONFIDENCE_CLASS"], errors="raise").astype(
        "int8"
    )
    if not frame["CONFIDENCE_CLASS"].between(0, 3).all():
        raise ValueError("Habitat confidence classes must be integers in [0, 3].")
    frame["OBSERVATION_YEAR"] = pd.to_numeric(frame["OBSERVATION_YEAR"], errors="coerce").astype(
        "Int16"
    )
    for column in (
        "HABITAT_TYPE",
        "SOURCE_DATASET",
        "SOURCE_FEATURE_ID",
        "EVIDENCE_CLASS",
        "OBSERVED_VS_MODELED",
        "OBSERVATION_STATUS",
        "SURVEY_METHOD",
        "SPATIAL_PRECISION_CLASS",
        "TEMPORAL_PRECISION_CLASS",
    ):
        frame[column] = frame[column].map(clean_optional_text).astype("string")
    return frame.sort_values("RECORD_ID").reset_index(drop=True)
