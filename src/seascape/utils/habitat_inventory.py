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

EVIDENCE_EXTENSION_COLUMNS = [
    "GEOMETRY_ROLE",
    "SURVEY_EVENT_ID",
    "SURVEY_COMPLETENESS",
    "OBSERVATION_START_YEAR",
    "OBSERVATION_END_YEAR",
    "AVAILABLE_YEAR",
    "SOURCE_PRIORITY",
]


def normalize_inventory(frame: Any) -> Any:
    """Validate and canonicalize a source-specific habitat inventory."""

    import geopandas as gpd

    if not isinstance(frame, gpd.GeoDataFrame):
        frame = gpd.GeoDataFrame(frame, geometry="geometry")
    missing = sorted(set(NORMALIZED_INVENTORY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Normalized habitat inventory is missing columns: {missing}")
    defaults = {
        "GEOMETRY_ROLE": "observation",
        "SURVEY_EVENT_ID": None,
        "SURVEY_COMPLETENESS": "unknown",
        "OBSERVATION_START_YEAR": frame["OBSERVATION_YEAR"],
        "OBSERVATION_END_YEAR": frame["OBSERVATION_YEAR"],
        "AVAILABLE_YEAR": pd.NA,
        "SOURCE_PRIORITY": 0,
    }
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = default
    frame = frame.loc[
        :, [*NORMALIZED_INVENTORY_COLUMNS, *EVIDENCE_EXTENSION_COLUMNS]
    ].copy()
    if frame.crs is None:
        raise ValueError("Normalized habitat inventory must retain CRS metadata.")
    frame = frame.to_crs("EPSG:4326")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    # A well-formed, empty mapped layer is valid evidence of no mapped records;
    # source existence and integrity are checked by its source loader.
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
        raise ValueError(
            "Habitat evidence class must be direct, generalized, or modeled."
        )
    allowed_mode = {"observed", "modeled"}
    if not set(frame["OBSERVED_VS_MODELED"].dropna()).issubset(allowed_mode):
        raise ValueError("OBSERVED_VS_MODELED must contain only observed or modeled.")
    allowed_status = {"present", "absent", "potential", "surveyed"}
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
    frame["CONFIDENCE_CLASS"] = pd.to_numeric(
        frame["CONFIDENCE_CLASS"], errors="raise"
    ).astype("int8")
    if not frame["CONFIDENCE_CLASS"].between(0, 3).all():
        raise ValueError("Habitat confidence classes must be integers in [0, 3].")
    frame["OBSERVATION_YEAR"] = pd.to_numeric(
        frame["OBSERVATION_YEAR"], errors="coerce"
    ).astype("Int16")
    for column in ("OBSERVATION_START_YEAR", "OBSERVATION_END_YEAR"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int16")
    if (
        frame["OBSERVATION_START_YEAR"].notna()
        & frame["OBSERVATION_END_YEAR"].notna()
        & frame["OBSERVATION_START_YEAR"].gt(frame["OBSERVATION_END_YEAR"])
    ).any():
        raise ValueError("Observation period start must not exceed end year.")
    frame["AVAILABLE_YEAR"] = pd.to_numeric(
        frame["AVAILABLE_YEAR"], errors="coerce"
    ).astype("Int16")
    frame["SOURCE_PRIORITY"] = pd.to_numeric(
        frame["SOURCE_PRIORITY"], errors="raise"
    ).astype("int16")
    if not set(frame["GEOMETRY_ROLE"].dropna()).issubset(
        {"observation", "survey_footprint"}
    ):
        raise ValueError("GEOMETRY_ROLE must be observation or survey_footprint.")
    if not set(frame["SURVEY_COMPLETENESS"].dropna()).issubset({"complete", "unknown"}):
        raise ValueError("SURVEY_COMPLETENESS must be complete or unknown.")
    footprint = frame["GEOMETRY_ROLE"].eq("survey_footprint")
    if (footprint & ~frame["OBSERVATION_STATUS"].eq("surveyed")).any():
        raise ValueError("Survey footprints require surveyed observation status.")
    if (footprint & frame["OBSERVATION_YEAR"].isna()).any():
        raise ValueError("Survey footprints require an observation year.")
    if (footprint & frame["SURVEY_EVENT_ID"].isna()).any():
        raise ValueError("Survey footprints require a survey event ID.")
    if (frame["OBSERVATION_STATUS"].eq("surveyed") & ~footprint).any():
        raise ValueError("Surveyed status requires survey_footprint geometry role.")
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
        "GEOMETRY_ROLE",
        "SURVEY_EVENT_ID",
        "SURVEY_COMPLETENESS",
    ):
        frame[column] = frame[column].map(clean_optional_text).astype("string")
    return frame.sort_values("RECORD_ID").reset_index(drop=True)
