from __future__ import annotations

import pandas as pd
import pytest

from seascape.modeling.feature_policy import (
    apply_feature_policy,
    apply_scale_selection,
    audit_collinearity,
    build_feature_policy,
    infer_scale_group,
    select_scales_one_standard_error,
)


def test_scale_group_removes_radius_but_not_mechanism() -> None:
    assert infer_scale_group("RELIEF_RING_4_M") == "RELIEF_SCALE_M"
    assert infer_scale_group("KELP_AREA_WITHIN_5KM_M2") == "KELP_AREA_SCALE_M2"


def test_one_standard_error_selects_smallest_eligible_candidate() -> None:
    scores = pd.DataFrame(
        {
            "scale_group": ["depth", "depth", "depth"],
            "candidate": ["ring_1", "ring_2", "ring_4"],
            "mean_log_loss": [0.50, 0.49, 0.489],
            "se_log_loss": [0.01, 0.01, 0.02],
            "mean_pr_auc": [0.30, 0.31, 0.32],
            "feature_count": [1, 2, 4],
        }
    )
    assert select_scales_one_standard_error(scores) == {"depth": "ring_1"}


def test_scale_freeze_requires_every_declared_group_and_valid_candidate() -> None:
    policy = {
        "unresolved_scale_groups": {"depth": ["ring_1", "ring_2"]},
        "features": [
            {
                "column": candidate,
                "scale_group": "depth",
                "included_by_default": True,
                "selected_scale": None,
                "exclusion_reason": None,
            }
            for candidate in ("ring_1", "ring_2")
        ],
    }
    with pytest.raises(ValueError, match="cover every unresolved group"):
        apply_scale_selection(policy, {})
    with pytest.raises(ValueError, match="outside their groups"):
        apply_scale_selection(policy, {"depth": "ring_4"})
    apply_scale_selection(policy, {"depth": "ring_1"})
    assert policy["scale_selection_status"] == "frozen_from_inner_rolling_origin_scores"
    assert policy["unresolved_scale_groups"] == {}
    assert policy["features"][1]["exclusion_reason"] == "scale_not_selected_by_inner_folds"


def test_policy_excludes_qc_and_applies_selected_columns() -> None:
    catalog = {
        "products": {
            "bathymetry": {
                "features": {
                    "BATHYMETRY": {
                        "role": "predictor",
                        "variable_kind": "feature_variable",
                        "available_resolutions": [8],
                    },
                    "SURVEY_COVERAGE_FRAC": {
                        "role": "coverage",
                        "variable_kind": "metadata",
                        "available_resolutions": [8],
                    },
                    "QC_REASON": {
                        "role": "evidence",
                        "variable_kind": "metadata",
                        "available_resolutions": [8],
                    },
                }
            }
        }
    }
    policy = build_feature_policy(catalog, catalog_checksum="fixture")
    selected = apply_feature_policy(
        pd.DataFrame({"H3_INDEX": ["a"], "BATHYMETRY": [10.0]}),
        policy,
    )
    assert selected.columns.tolist() == ["H3_INDEX", "BATHYMETRY"]

    prefixed = apply_feature_policy(
        pd.DataFrame({"H3_INDEX": ["a"], "bathymetry__BATHYMETRY": [10.0]}),
        policy,
    )
    assert prefixed.columns.tolist() == ["H3_INDEX", "bathymetry__BATHYMETRY"]
    metadata = [record for record in policy["features"] if record["variable_kind"] == "metadata"]
    assert metadata
    assert all(not record["included_by_default"] for record in metadata)


def test_policy_excludes_all_null_materialized_feature_variables(tmp_path) -> None:
    product_path = tmp_path / "habitat.parquet"
    pd.DataFrame(
        {
            "H3_INDEX": ["a", "b"],
            "AVAILABLE": [1.0, 2.0],
            "UNAVAILABLE": [None, None],
        }
    ).to_parquet(product_path, index=False)
    catalog = {
        "products": {
            "habitat": {
                "features": {
                    column: {
                        "role": "predictor",
                        "variable_kind": "feature_variable",
                        "available_resolutions": [8],
                        "collection_paths": {8: product_path.name},
                    }
                    for column in ("AVAILABLE", "UNAVAILABLE")
                }
            }
        }
    }
    catalog["products"]["habitat"]["features"]["MISSING"] = {
        "role": "predictor",
        "variable_kind": "feature_variable",
        "available_resolutions": [8],
        "collection_paths": {8: "missing.parquet"},
    }

    policy = build_feature_policy(
        catalog,
        catalog_checksum="fixture",
        materialization_root=tmp_path,
    )
    records = {record["column"]: record for record in policy["features"]}

    assert records["AVAILABLE"]["included_by_default"] is True
    assert records["AVAILABLE"]["materialization_status"] == "has_non_null_values"
    assert records["AVAILABLE"]["materialized_non_null_resolutions"] == [8]
    assert records["UNAVAILABLE"]["included_by_default"] is False
    assert records["UNAVAILABLE"]["exclusion_reason"] == "materialized_all_null"
    assert records["UNAVAILABLE"]["materialized_all_null_resolutions"] == [8]
    assert records["MISSING"]["included_by_default"] is False
    assert records["MISSING"]["exclusion_reason"] == "materialized_artifact_unavailable"
    assert records["MISSING"]["materialized_unavailable_resolutions"] == [8]


def test_collinearity_audit_finds_exact_and_high_correlation_pairs() -> None:
    values = list(range(120))
    frame = pd.DataFrame({"A": values, "B": values, "C": list(reversed(values))})
    policy = {
        "features": [{"column": column, "included_by_default": True} for column in frame.columns]
    }
    audit = audit_collinearity(frame, policy)
    exact = audit.loc[audit["EXACT_DUPLICATE"]]
    assert {tuple(value) for value in exact[["LEFT_COLUMN", "RIGHT_COLUMN"]].to_numpy()} == {
        ("A", "B")
    }
    assert audit["ABS_SPEARMAN_RHO"].min() == pytest.approx(1.0)
