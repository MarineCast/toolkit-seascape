from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from seascape.governance.feature_eligibility import (
    apply_feature_eligibility,
    audit_collinearity,
    build_feature_eligibility,
    infer_scale_group,
)


def test_scale_group_records_alternatives_without_selecting_one() -> None:
    catalog = {
        "products": {
            "geomorphometry": {
                "metric_family": "seascape",
                "features": {
                    column: {
                        "role": "predictor",
                        "variable_kind": "feature_variable",
                        "available_resolutions": [8],
                    }
                    for column in ("RELIEF_RING_1_M", "RELIEF_RING_4_M")
                },
            }
        }
    }

    eligibility = build_feature_eligibility(catalog, catalog_checksum="fixture")

    assert infer_scale_group("RELIEF_RING_4_M") == "RELIEF_SCALE_M"
    assert eligibility["alternate_scale_groups"] == {
        "geomorphometry:RELIEF_SCALE_M": ["RELIEF_RING_1_M", "RELIEF_RING_4_M"]
    }
    assert all(record["eligible"] for record in eligibility["features"])
    rendered = str(eligibility).lower()
    assert "log_loss" not in rendered
    assert "pr_auc" not in rendered
    assert "rolling_origin" not in rendered


def test_eligibility_excludes_metadata_and_applies_all_static_candidates() -> None:
    catalog = {
        "products": {
            "bathymetry": {
                "metric_family": "seascape",
                "features": {
                    "BATHYMETRY": {
                        "role": "predictor",
                        "variable_kind": "feature_variable",
                        "available_resolutions": [8],
                    },
                    "QC_REASON": {
                        "role": "evidence",
                        "variable_kind": "metadata",
                        "available_resolutions": [8],
                    },
                },
            }
        }
    }
    eligibility = build_feature_eligibility(catalog, catalog_checksum="fixture")
    selected = apply_feature_eligibility(
        pd.DataFrame({"H3_INDEX": ["a"], "BATHYMETRY": [10.0]}), eligibility
    )

    assert selected.columns.tolist() == ["H3_INDEX", "BATHYMETRY"]
    metadata = [record for record in eligibility["features"] if record["column"] == "QC_REASON"]
    assert metadata[0]["eligible"] is False


def test_eligibility_excludes_all_null_and_unavailable_materializations(
    tmp_path: Path,
) -> None:
    product_path = tmp_path / "habitat.parquet"
    pd.DataFrame(
        {"H3_INDEX": ["a", "b"], "AVAILABLE": [1.0, 2.0], "ALL_NULL": [None, None]}
    ).to_parquet(product_path, index=False)
    catalog = {
        "products": {
            "habitat": {
                "metric_family": "seascape",
                "features": {
                    column: {
                        "role": "predictor",
                        "variable_kind": "feature_variable",
                        "available_resolutions": [8],
                        "collection_paths": {8: path},
                    }
                    for column, path in (
                        ("AVAILABLE", product_path.name),
                        ("ALL_NULL", product_path.name),
                        ("MISSING", "missing.parquet"),
                    )
                },
            }
        }
    }

    eligibility = build_feature_eligibility(
        catalog, catalog_checksum="fixture", materialization_root=tmp_path
    )
    records = {record["column"]: record for record in eligibility["features"]}

    assert records["AVAILABLE"]["eligible"] is True
    assert records["ALL_NULL"]["exclusion_reason"] == "materialized_all_null"
    assert records["MISSING"]["exclusion_reason"] == "materialized_artifact_unavailable"


def test_collinearity_is_diagnostic_for_eligible_physical_fields() -> None:
    values = list(range(120))
    frame = pd.DataFrame({"A": values, "B": values, "C": list(reversed(values))})
    eligibility = {
        "features": [
            {"column": column, "eligible": True} for column in frame.columns
        ]
    }
    audit = audit_collinearity(frame, eligibility)
    exact = audit.loc[audit["EXACT_DUPLICATE"]]
    assert {tuple(value) for value in exact[["LEFT_COLUMN", "RIGHT_COLUMN"]].to_numpy()} == {
        ("A", "B")
    }
    assert audit["ABS_SPEARMAN_RHO"].min() == pytest.approx(1.0)
