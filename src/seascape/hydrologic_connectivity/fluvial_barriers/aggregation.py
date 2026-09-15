"""Feature-aware R8-to-R6 aggregation for fluvial-barrier evidence."""

from __future__ import annotations

import numpy as np
import pandas as pd


def aggregate_r8_to_r6(
    features: pd.DataFrame,
    confidence: pd.DataFrame,
    parent_child: pd.DataFrame,
    support_r6: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select the nearest barrier-affected child for each canonical r6 parent."""

    from .sources import PREFIX, validate_feature_table

    mapping = parent_child[["CHILD_H3_INDEX", "PARENT_H3_INDEX"]].copy()
    mapping["CHILD_H3_INDEX"] = mapping["CHILD_H3_INDEX"].astype(str)
    mapping["PARENT_H3_INDEX"] = mapping["PARENT_H3_INDEX"].astype(str)
    valid_children = set(features["H3_INDEX"].astype(str))
    valid_parents = set(support_r6["H3_INDEX"].astype(str))
    mapping = mapping.loc[
        mapping["CHILD_H3_INDEX"].isin(valid_children)
        & mapping["PARENT_H3_INDEX"].isin(valid_parents)
    ]
    joined = mapping.merge(
        features,
        left_on="CHILD_H3_INDEX",
        right_on="H3_INDEX",
        how="inner",
        validate="many_to_one",
    )
    joined["_rank"] = pd.to_numeric(
        joined["WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M"], errors="coerce"
    ).fillna(np.inf)
    joined["_mouth_rank"] = pd.to_numeric(
        joined["WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M"], errors="coerce"
    ).fillna(np.inf)
    selected = (
        joined.sort_values(["PARENT_H3_INDEX", "_rank", "_mouth_rank", "CHILD_H3_INDEX"])
        .drop_duplicates("PARENT_H3_INDEX")
        .copy()
    )
    feature_columns = list(features.columns)
    r6 = selected[feature_columns].copy()
    r6["H3_INDEX"] = selected["PARENT_H3_INDEX"].to_numpy()
    r6["H3_RESOLUTION"] = 6
    r6 = r6.sort_values("H3_INDEX").reset_index(drop=True)
    child_confidence = confidence.rename(columns={"H3_INDEX": "CHILD_H3_INDEX"})
    conf_joined = mapping.merge(child_confidence, on="CHILD_H3_INDEX", how="inner")
    confidence_rows = []
    for parent, rows in conf_joined.groupby("PARENT_H3_INDEX", sort=True):
        sources = sorted(
            {
                source
                for value in rows[f"{PREFIX}_SOURCE_DATASETS"].dropna().astype(str)
                for source in value.split("|")
                if source
            }
        )
        years = pd.to_numeric(rows[f"{PREFIX}_LATEST_SURVEY_YEAR"], errors="coerce")
        confidence_rows.append(
            {
                "H3_INDEX": parent,
                "H3_RESOLUTION": 6,
                f"{PREFIX}_CONFIDENCE": int(rows[f"{PREFIX}_CONFIDENCE"].max()),
                f"{PREFIX}_UNMAPPED_AREA": bool(rows[f"{PREFIX}_UNMAPPED_AREA"].all()),
                f"{PREFIX}_SOURCE_DATASETS": "|".join(sources) or None,
                f"{PREFIX}_EVIDENCE_BASIS": "authoritative mapped inventory; HydroRIVERS topology fallback",
                f"{PREFIX}_LATEST_SURVEY_YEAR": years.max() if years.notna().any() else np.nan,
            }
        )
    r6_confidence = pd.DataFrame(confidence_rows).sort_values("H3_INDEX").reset_index(drop=True)
    validate_feature_table(r6, 6)
    if set(r6["H3_INDEX"].astype(str)) != set(r6_confidence["H3_INDEX"].astype(str)):
        raise ValueError("Fluvial-barrier r6 feature/confidence support differs.")
    return r6, r6_confidence
