"""Feature-aware R8-to-R6 aggregation for anthropogenic covariates."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from seascape.utils.values import pipe_delimited_union as _pipe_union


def aggregate_r8_to_r6(
    features: pd.DataFrame,
    confidence: pd.DataFrame,
    crosswalk: pd.DataFrame,
    parent_support: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the anthropogenic feature-aware r8-to-r6 aggregation contract."""

    from .sources import (
        CONFIDENCE_FAMILIES,
        DISTANCE_FEATURES,
        validate_confidence_table,
        validate_feature_table,
    )

    child = features.merge(
        crosswalk[["CHILD_H3_INDEX", "PARENT_H3_INDEX", "CHILD_WATER_AREA_M2"]],
        left_on="H3_INDEX",
        right_on="CHILD_H3_INDEX",
        how="inner",
        validate="one_to_one",
    )
    child_confidence = confidence.merge(
        crosswalk[["CHILD_H3_INDEX", "PARENT_H3_INDEX"]],
        left_on="H3_INDEX",
        right_on="CHILD_H3_INDEX",
        how="inner",
        validate="one_to_one",
    )
    support = parent_support.set_index("H3_INDEX")
    distance_columns = list(DISTANCE_FEATURES)
    qc_columns = [value.removesuffix("_M") + "_QC_REASON" for value in distance_columns]
    output_rows: list[dict[str, Any]] = []
    for parent, rows in child.groupby("PARENT_H3_INDEX", sort=True):
        weights = rows["CHILD_WATER_AREA_M2"].to_numpy(dtype="float64")
        parent_area = float(weights.sum())
        armored = float(rows["SHORELINE_ARMORING_LENGTH_M"].sum())
        surveyed = float(rows["SHORELINE_SURVEYED_LENGTH_M"].sum())
        dredged = float(rows["DREDGED_AREA_M2"].sum())
        disposal = float(rows["DISPOSAL_SITE_AREA_M2"].sum())
        aquaculture = float(rows["AQUACULTURE_FOOTPRINT_AREA_M2"].sum())
        row: dict[str, Any] = {
            "H3_INDEX": str(parent),
            "H3_RESOLUTION": 6,
            "NATIVE_CHILD_WATER_AREA_M2": parent_area,
            "SHORELINE_ARMORING_LENGTH_M": armored,
            "SHORELINE_SURVEYED_LENGTH_M": surveyed,
            "SHORELINE_ARMORING_FRAC": (
                float(np.clip(armored / surveyed, 0.0, 1.0)) if surveyed > 0 else np.nan
            ),
            "DREDGED_AREA_M2": dredged,
            "DREDGED_AREA_FRAC": (
                float(np.clip(dredged / parent_area, 0.0, 1.0))
                if parent_area > 0 and rows["DREDGED_AREA_FRAC"].notna().any()
                else np.nan
            ),
            "DISPOSAL_SITE_AREA_M2": disposal,
            "DISPOSAL_SITE_AREA_FRAC": (
                float(np.clip(disposal / parent_area, 0.0, 1.0))
                if parent_area > 0 and rows["DISPOSAL_SITE_AREA_FRAC"].notna().any()
                else np.nan
            ),
            "AQUACULTURE_FOOTPRINT_AREA_M2": aquaculture,
            "AQUACULTURE_FOOTPRINT_FRAC": (
                float(np.clip(aquaculture / parent_area, 0.0, 1.0))
                if aquaculture > 0 and parent_area > 0
                else np.nan
            ),
            "ARTIFICIAL_REEF_PRESENCE": (
                1.0 if rows["ARTIFICIAL_REEF_PRESENCE"].eq(1.0).any() else np.nan
            ),
            "AQUACULTURE_PRESENCE": (1.0 if rows["AQUACULTURE_PRESENCE"].eq(1.0).any() else np.nan),
            "WATER_COMPONENT_ID": support.loc[str(parent), "WATER_COMPONENT_ID"],
            "NETWORK_CONNECTOR_METHOD": support.loc[str(parent), "CONNECTOR_METHOD"],
            "NETWORK_CONNECTOR_DISTANCE_M": support.loc[str(parent), "CONNECTOR_DISTANCE_M"],
            "NETWORK_DISTANCE_QC_REASON": support.loc[str(parent), "GRAPH_QC_REASON"],
        }
        for column in distance_columns:
            row[column] = rows[column].min(skipna=True)
            qc_column = column.removesuffix("_M") + "_QC_REASON"
            row[qc_column] = None if rows[column].notna().any() else _pipe_union(rows[qc_column])
        for column in (
            "OVERWATER_STRUCTURE_COUNT_WITHIN_5KM",
            "OVERWATER_STRUCTURE_DENSITY_PER_KM2",
        ):
            valid = rows[column].notna()
            row[column] = (
                float(np.average(rows.loc[valid, column].astype(float), weights=weights[valid]))
                if valid.any()
                else np.nan
            )
        output_rows.append(row)
    confidence_rows: list[dict[str, Any]] = []
    for parent, rows in child_confidence.groupby("PARENT_H3_INDEX", sort=True):
        row = {"H3_INDEX": str(parent), "H3_RESOLUTION": 6}
        for family in [*CONFIDENCE_FAMILIES, "ANTHROPOGENIC"]:
            source_column = f"{family}_SOURCE_DATASETS"
            sources = _pipe_union(rows[source_column])
            row[source_column] = sources
            row[f"{family}_SOURCE_COUNT"] = len(sources.split("|")) if sources else 0
            row[f"{family}_CONFIDENCE"] = int(rows[f"{family}_CONFIDENCE"].max())
            row[f"{family}_UNMAPPED_AREA"] = bool(rows[f"{family}_UNMAPPED_AREA"].any())
        confidence_rows.append(row)
    feature_frame = pd.DataFrame(output_rows)
    confidence_frame = pd.DataFrame(confidence_rows)
    missing_qc = set(qc_columns).difference(feature_frame.columns)
    if missing_qc:
        raise AssertionError(f"R6 feature aggregation omitted distance QC: {sorted(missing_qc)}")
    validate_feature_table(feature_frame, 6)
    validate_confidence_table(confidence_frame, 6, feature_frame["H3_INDEX"])
    return feature_frame, confidence_frame
