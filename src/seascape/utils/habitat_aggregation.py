"""Feature-aware R8-to-R6 aggregation and validation for habitat surfaces."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .values import pipe_delimited_union as _pipe_union


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return np.nan
    return float(
        np.average(values.loc[valid].astype(float), weights=weights.loc[valid].astype(float))
    )


def _aggregate_persistence(rows: pd.DataFrame, prefix: str) -> tuple[float, str | None]:
    """Aggregate persistence only when every contributing estimate has one basis."""

    value_column = f"{prefix}_PERSISTENCE_RATIO"
    basis_column = f"{prefix}_PERSISTENCE_BASIS"
    valid = rows[value_column].notna() & rows[basis_column].notna()
    if not valid.any():
        return np.nan, None
    bases = sorted(set(rows.loc[valid, basis_column].astype(str)))
    basis = "|".join(bases)
    if len(bases) != 1:
        return np.nan, basis
    if bases[0] == "surveyed_years":
        weights = rows[f"{prefix}_YEARS_SURVEYED"].astype(float)
    elif bases[0] == "mapped_binned_proportion_midpoint":
        weights = rows["CHILD_WATER_AREA_M2"].astype(float)
    else:
        raise ValueError(f"Unsupported persistence basis: {bases[0]}")
    return _weighted_mean(rows[value_column], weights), bases[0]


def aggregate_r8_to_r6(
    features: pd.DataFrame,
    confidence: pd.DataFrame,
    crosswalk: pd.DataFrame,
    parent_support: pd.DataFrame,
    *,
    prefix: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the explicit feature-aware r8-to-r6 aggregation contract."""

    child = features.merge(
        crosswalk[["CHILD_H3_INDEX", "PARENT_H3_INDEX", "CHILD_WATER_AREA_M2"]],
        left_on="H3_INDEX",
        right_on="CHILD_H3_INDEX",
        how="left",
        validate="one_to_one",
    )
    if child["PARENT_H3_INDEX"].isna().any():
        raise ValueError("Every native habitat cell must have an H3 r6 parent.")
    child_conf = confidence.merge(
        crosswalk[["CHILD_H3_INDEX", "PARENT_H3_INDEX", "CHILD_WATER_AREA_M2"]],
        left_on="H3_INDEX",
        right_on="CHILD_H3_INDEX",
        how="left",
        validate="one_to_one",
    )
    p = prefix
    feature_rows: list[dict[str, Any]] = []
    confidence_rows: list[dict[str, Any]] = []
    for parent, rows in child.groupby("PARENT_H3_INDEX", sort=True):
        water_area = float(rows["CHILD_WATER_AREA_M2"].sum())
        habitat_area = float(rows[f"{p}_AREA_M2"].sum())
        persistence, persistence_basis = _aggregate_persistence(rows, p)
        feature_rows.append(
            {
                "H3_INDEX": str(parent),
                "H3_RESOLUTION": 6,
                "NATIVE_CHILD_WATER_AREA_M2": water_area,
                f"{p}_AREA_M2": habitat_area,
                f"{p}_FRAC": habitat_area / water_area if water_area > 0 else 0.0,
                f"{p}_MAX_LOCAL_FRAC": float(rows[f"{p}_FRAC"].max()),
                f"{p}_DISTANCE_M": rows[f"{p}_DISTANCE_M"].min(skipna=True),
                f"{p}_AREA_WITHIN_5KM_M2": _weighted_mean(
                    rows[f"{p}_AREA_WITHIN_5KM_M2"],
                    rows["CHILD_WATER_AREA_M2"],
                ),
                f"{p}_OCCUPIED_CHILD_COUNT": int(rows[f"{p}_OCCUPIED_CHILD_COUNT"].sum()),
                f"{p}_PATCH_COUNT": int(rows[f"{p}_PATCH_COUNT"].sum()),
                f"{p}_LARGEST_PATCH_AREA_M2": float(rows[f"{p}_LARGEST_PATCH_AREA_M2"].max()),
                f"{p}_MEAN_PATCH_AREA_M2": (
                    habitat_area / float(rows[f"{p}_PATCH_COUNT"].sum())
                    if rows[f"{p}_PATCH_COUNT"].sum() > 0
                    else 0.0
                ),
                f"{p}_EDGE_LENGTH_M": float(rows[f"{p}_EDGE_LENGTH_M"].sum()),
                f"{p}_EDGE_DENSITY_M_PER_KM2": (
                    float(rows[f"{p}_EDGE_LENGTH_M"].sum()) / (water_area / 1_000_000.0)
                    if water_area > 0
                    else 0.0
                ),
                f"{p}_FRAGMENTATION_INDEX": (
                    float(
                        np.clip(
                            1.0 - float(rows[f"{p}_LARGEST_PATCH_AREA_M2"].max()) / habitat_area,
                            0.0,
                            1.0,
                        )
                    )
                    if habitat_area > 0
                    else 0.0
                ),
                f"{p}_FIRST_YEAR": rows[f"{p}_FIRST_YEAR"].min(skipna=True),
                f"{p}_LAST_YEAR": rows[f"{p}_LAST_YEAR"].max(skipna=True),
                f"{p}_YEARS_OBSERVED": int(rows[f"{p}_YEARS_OBSERVED"].max()),
                f"{p}_YEARS_SURVEYED": int(rows[f"{p}_YEARS_SURVEYED"].max()),
                f"{p}_PERSISTENCE_RATIO": persistence,
                f"{p}_PERSISTENCE_BASIS": persistence_basis,
                f"{p}_RECENT_5YR_PRESENCE": bool(rows[f"{p}_RECENT_5YR_PRESENCE"].any()),
                f"{p}_RECENCY_YEARS": rows[f"{p}_RECENCY_YEARS"].min(skipna=True),
                f"{p}_OBSERVED_PRESENCE": bool(rows[f"{p}_OBSERVED_PRESENCE"].any()),
                f"{p}_OBSERVED_ABSENCE": bool(
                    not rows[f"{p}_OBSERVED_PRESENCE"].any() and rows[f"{p}_OBSERVED_ABSENCE"].any()
                ),
                f"{p}_UNSURVEYED": bool(rows[f"{p}_UNSURVEYED"].all()),
                "NETWORK_DISTANCE_QC_REASON": (
                    None
                    if rows[f"{p}_DISTANCE_M"].notna().any()
                    else "no_child_with_reachable_mapped_habitat"
                ),
            }
        )
    confidence_name = f"{p}_CONFIDENCE"
    for parent, rows in child_conf.groupby("PARENT_H3_INDEX", sort=True):
        datasets = _pipe_union(rows[f"{p}_SOURCE_DATASETS"])
        surveyed_area = (
            rows[f"{p}_SURVEYED_AREA_FRAC"].astype(float)
            * rows["CHILD_WATER_AREA_M2"].astype(float)
        ).sum()
        parent_water_area = float(rows["CHILD_WATER_AREA_M2"].sum())
        confidence_rows.append(
            {
                "H3_INDEX": str(parent),
                "H3_RESOLUTION": 6,
                f"{p}_SOURCE_DATASETS": datasets,
                f"{p}_SOURCE_COUNT": len(datasets.split("|")) if datasets else 0,
                f"{p}_LATEST_SURVEY_YEAR": rows[f"{p}_LATEST_SURVEY_YEAR"].max(skipna=True),
                f"{p}_SURVEY_METHOD": _pipe_union(rows[f"{p}_SURVEY_METHOD"]),
                f"{p}_SPATIAL_PRECISION_CLASS": _pipe_union(rows[f"{p}_SPATIAL_PRECISION_CLASS"]),
                f"{p}_TEMPORAL_PRECISION_CLASS": _pipe_union(rows[f"{p}_TEMPORAL_PRECISION_CLASS"]),
                f"{p}_OBSERVED_VS_MODELED": _pipe_union(rows[f"{p}_OBSERVED_VS_MODELED"]),
                confidence_name: int(rows[confidence_name].max()),
                f"{p}_SURVEYED_AREA_FRAC": min(
                    1.0, surveyed_area / parent_water_area if parent_water_area > 0 else 0.0
                ),
                f"{p}_UNMAPPED_AREA": bool(surveyed_area < parent_water_area - 1e-6),
            }
        )
    parent_features = pd.DataFrame(feature_rows)
    parent_confidence = pd.DataFrame(confidence_rows)
    lineage_columns = [
        "H3_INDEX",
        "WATER_COMPONENT_ID",
        "CONNECTOR_METHOD",
        "CONNECTOR_DISTANCE_M",
    ]
    lineage = parent_support.loc[:, lineage_columns].copy()
    parent_features = parent_features.merge(
        lineage, on="H3_INDEX", how="left", validate="one_to_one"
    ).rename(
        columns={
            "CONNECTOR_METHOD": "NETWORK_CONNECTOR_METHOD",
            "CONNECTOR_DISTANCE_M": "NETWORK_CONNECTOR_DISTANCE_M",
        }
    )
    for table in (parent_features, parent_confidence):
        for column in table.columns:
            if column.endswith(("FIRST_YEAR", "LAST_YEAR", "LATEST_SURVEY_YEAR")):
                table[column] = pd.to_numeric(table[column], errors="coerce").astype("Int16")
    validate_surface_tables(parent_features, parent_confidence, prefix, 6)
    return parent_features, parent_confidence


def validate_surface_tables(
    features: pd.DataFrame,
    confidence: pd.DataFrame,
    prefix: str,
    resolution: int,
) -> None:
    if features.empty or confidence.empty:
        raise ValueError("Habitat features and confidence tables must be nonempty.")
    for table in (features, confidence):
        if not table["H3_INDEX"].is_unique or table["H3_INDEX"].isna().any():
            raise ValueError("Habitat tables require one unique row per H3 cell.")
        if not table["H3_RESOLUTION"].eq(resolution).all():
            raise ValueError("Habitat table resolution metadata is inconsistent.")
    if set(features["H3_INDEX"]) != set(confidence["H3_INDEX"]):
        raise ValueError("Habitat feature and confidence support must match exactly.")
    fraction = pd.to_numeric(features[f"{prefix}_FRAC"], errors="raise")
    if not fraction.between(0.0, 1.0 + 1e-9).all():
        raise ValueError("Habitat fractions must be in [0, 1].")
    confidence_values = pd.to_numeric(confidence[f"{prefix}_CONFIDENCE"], errors="raise")
    if not confidence_values.between(0, 3).all():
        raise ValueError("Habitat confidence must remain in [0, 3].")
    state_total = (
        features[f"{prefix}_OBSERVED_PRESENCE"].astype(int)
        + features[f"{prefix}_OBSERVED_ABSENCE"].astype(int)
        + features[f"{prefix}_UNSURVEYED"].astype(int)
    )
    if not state_total.eq(1).all():
        raise ValueError("Presence, explicit absence, and unsurveyed must remain three-state.")


__all__ = ["aggregate_r8_to_r6", "validate_surface_tables"]
