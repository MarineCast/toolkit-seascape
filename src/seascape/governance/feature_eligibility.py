"""Generate and audit species-neutral Seascape feature eligibility metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from seascape.core.config.paths import project_root
from seascape.publication import SeascapeSnapshot, read_seascape_parquet

DEFAULT_CATALOG_PATH = Path("config/feature_catalog.yaml")
DEFAULT_ELIGIBILITY_PATH = Path("config/feature_eligibility.yaml")
ELIGIBLE_ROLES = {"predictor", "categorical", "state"}
DETERMINISTIC_EXCLUSIONS = {
    "SURFACE_AREA_RATIO_FROM_SLOPE": "deterministic_transform_of_slope",
}
PRODUCT_FIELD_EXCLUSIONS = {
    ("bathymetry", "BATHYMETRY_LOCAL_ANOMALY"): (
        "signed_duplicate_of_geomorphometry_terrain_position_ring_2"
    ),
    ("geomorphic_units", "BROAD_TERRAIN_POSITION_M"): (
        "duplicate_of_geomorphometry_terrain_position_ring_4_m"
    ),
    ("geomorphic_units", "BROAD_TERRAIN_POSITION_Z"): (
        "duplicate_of_geomorphometry_terrain_position_ring_4_z"
    ),
    ("geomorphometry", "DEPTH_RANGE_RING_1_M"): (
        "duplicate_of_geomorphometry_relief"
    ),
    ("geomorphometry", "GENERAL_CURVATURE"): "signed_duplicate_of_curvature",
    ("geomorphometry", "TERRAIN_POSITION"): (
        "duplicate_of_geomorphometry_terrain_position_ring_1_m"
    ),
    ("exposure_and_enclosure", "ENCLOSURE_INDEX"): (
        "deterministic_complement_of_openness_to_ocean_index"
    ),
    ("fluvial_barriers", "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M"): (
        "duplicate_of_fluvial_connectivity_distance"
    ),
}
COMPOSITE_DUPLICATE_FIELDS = {
    "kelp": {
        "KELP_AREA_WITHIN_5KM_M2",
        "KELP_DISTANCE_M",
        "KELP_FRAC",
        "KELP_MAX_LOCAL_FRAC",
        "KELP_PERSISTENCE_RATIO",
    },
    "seagrass": {
        "SEAGRASS_AREA_WITHIN_5KM_M2",
        "SEAGRASS_DISTANCE_M",
        "SEAGRASS_FRAC",
        "SEAGRASS_MAX_LOCAL_FRAC",
    },
    "reef_habitat": {
        "ROCKY_REEF_AREA_WITHIN_5KM_M2",
        "ROCKY_REEF_DISTANCE_M",
        "ROCKY_REEF_FRAC",
    },
}
SCALE_PATTERNS = (
    re.compile(r"_RING_\d+(?=_|$)"),
    re.compile(r"_RADIUS_\d+(?:_\d+)?KM(?=_|$)"),
    re.compile(r"_WITHIN_\d+(?:_\d+)?KM(?=_|$)"),
    re.compile(r"_\d+(?:_\d+)?KM(?=_|$)"),
)


def infer_scale_group(column: str) -> str:
    """Collapse encoded radius/ring tokens into a deterministic scale family."""

    output = column
    for pattern in SCALE_PATTERNS:
        output = pattern.sub("_SCALE", output)
    return output


def infer_topology(product_id: str, column: str) -> str:
    """Describe the physical spatial mechanism represented by a field."""

    if "WATER_NETWORK" in column or "NETWORK_DISTANCE" in column:
        return "water_network"
    if product_id in {"geomorphometry", "geomorphic_units", "bathymetry"} and any(
        token in column for token in ("RING", "LOCAL_ANOMALY", "BPI", "TPI")
    ):
        return "water_connected_neighborhood"
    if product_id in {"exposure_and_enclosure", "waterbody_morphometry"}:
        return "purpose_built_geometry"
    if column.startswith("STRAIGHT_DISTANCE") or column.startswith("DISTANCE_TO"):
        return "projected_straight_line"
    return "within_cell_or_nonspatial"


def _exclusion_reason(
    product_id: str,
    role: str,
    column: str,
    variable_kind: str,
) -> str | None:
    if variable_kind != "feature_variable":
        return f"catalog_variable_kind:{variable_kind}"
    if role not in ELIGIBLE_ROLES:
        return f"catalog_role:{role}"
    if product_id == "h3_marine_support":
        return "canonical_support_not_predictor"
    if (product_id, column) in PRODUCT_FIELD_EXCLUSIONS:
        return PRODUCT_FIELD_EXCLUSIONS[(product_id, column)]
    if column in COMPOSITE_DUPLICATE_FIELDS.get(product_id, set()):
        return "duplicate_of_model_ready_benthic_habitat_panel"
    if column in DETERMINISTIC_EXCLUSIONS:
        return DETERMINISTIC_EXCLUSIONS[column]
    if any(
        token in column
        for token in (
            "QC_REASON",
            "SOURCE_DATASET",
            "VERSION",
            "CHECKSUM",
            "CONNECTOR_METHOD",
            "GRAPH_",
            "PIXEL_COUNT",
        )
    ):
        return "provenance_coverage_or_qc"
    return None


def _materialized_feature_availability(
    products: Mapping[str, Any],
    materialization_root: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    references: dict[tuple[str, str], list[tuple[int, Path]]] = {}
    requested_columns: dict[Path, set[str]] = {}
    for product_id, product in products.items():
        features = product.get("features", {})
        if not isinstance(features, Mapping):
            continue
        for column, feature in features.items():
            collection_paths = feature.get("collection_paths", {})
            if not isinstance(collection_paths, Mapping):
                continue
            key = (str(product_id), str(column))
            for resolution, raw_path in collection_paths.items():
                path = Path(str(raw_path)).expanduser()
                if not path.is_absolute():
                    path = materialization_root / path
                path = path.resolve()
                references.setdefault(key, []).append((int(resolution), path))
                requested_columns.setdefault(path, set()).add(str(column))

    column_has_value: dict[tuple[Path, str], bool] = {}
    unavailable_paths: set[Path] = set()
    for path, columns in requested_columns.items():
        if not path.exists():
            unavailable_paths.add(path)
            continue
        try:
            frame = pd.read_parquet(path, columns=sorted(columns))
        except Exception as exc:
            raise ValueError(
                f"Cannot inspect materialized seascape feature table {path}: {exc}"
            ) from exc
        for column in columns:
            column_has_value[(path, column)] = bool(frame[column].notna().any())

    availability: dict[tuple[str, str], dict[str, Any]] = {}
    for key, paths in references.items():
        non_null: set[int] = set()
        all_null: set[int] = set()
        unavailable: set[int] = set()
        for resolution, path in paths:
            if path in unavailable_paths:
                unavailable.add(resolution)
            elif column_has_value[(path, key[1])]:
                non_null.add(resolution)
            else:
                all_null.add(resolution)
        if non_null:
            status = "has_non_null_values"
        elif all_null and unavailable:
            status = "all_null_or_unavailable"
        elif all_null:
            status = "all_null"
        else:
            status = "unavailable"
        availability[key] = {
            "materialization_status": status,
            "materialized_non_null_resolutions": sorted(non_null),
            "materialized_all_null_resolutions": sorted(all_null),
            "materialized_unavailable_resolutions": sorted(unavailable),
        }
    return availability


def seascape_catalog_subset(catalog: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Return only Seascape products and their stable content checksum."""

    products = catalog.get("products", {})
    if not isinstance(products, Mapping):
        raise ValueError("Feature catalog has no products mapping.")
    subset = {
        "schema_version": catalog.get("schema_version"),
        "catalog_id": "environment.seascape.subset",
        "products": {
            str(product_id): product
            for product_id, product in products.items()
            if isinstance(product, Mapping) and product.get("metric_family") == "seascape"
        },
    }
    encoded = json.dumps(subset, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return subset, hashlib.sha256(encoded).hexdigest()


def build_feature_eligibility(
    catalog: Mapping[str, Any],
    *,
    catalog_checksum: str,
    materialization_root: Path | None = None,
) -> dict[str, Any]:
    """Build field-level physical eligibility without choosing model features or scales."""

    products = catalog.get("products")
    if not isinstance(products, Mapping):
        raise ValueError("Feature catalog has no products mapping.")
    materialized = (
        _materialized_feature_availability(products, materialization_root.resolve())
        if materialization_root is not None
        else {}
    )
    records: list[dict[str, Any]] = []
    for product_id, product in sorted(products.items()):
        features = product.get("features", {})
        if not isinstance(features, Mapping):
            continue
        for column, feature in sorted(features.items()):
            role = str(feature.get("role", "unknown"))
            variable_kind = str(
                feature.get(
                    "variable_kind",
                    "feature_variable" if role in ELIGIBLE_ROLES else "metadata",
                )
            )
            exclusion = _exclusion_reason(
                str(product_id), role, str(column), variable_kind
            )
            availability = materialized.get(
                (str(product_id), str(column)),
                {
                    "materialization_status": "not_checked",
                    "materialized_non_null_resolutions": [],
                    "materialized_all_null_resolutions": [],
                    "materialized_unavailable_resolutions": [],
                },
            )
            if exclusion is None:
                status = availability["materialization_status"]
                exclusion = {
                    "all_null": "materialized_all_null",
                    "unavailable": "materialized_artifact_unavailable",
                    "all_null_or_unavailable": "materialized_all_null_or_unavailable",
                }.get(status)
            records.append(
                {
                    "product": str(product_id),
                    "column": str(column),
                    "role": role,
                    "variable_kind": variable_kind,
                    "feature_family": feature.get("metric_family", product_id),
                    "metric_subfamily": feature.get("metric_subfamily"),
                    "unit": feature.get("unit"),
                    "available_resolutions": feature.get("available_resolutions", []),
                    "topology": infer_topology(str(product_id), str(column)),
                    "scale_group": f"{product_id}:{infer_scale_group(str(column))}",
                    "eligible": exclusion is None,
                    "exclusion_reason": exclusion,
                    **availability,
                }
            )
    scale_groups: dict[str, list[str]] = {}
    for record in records:
        if record["eligible"]:
            scale_groups.setdefault(str(record["scale_group"]), []).append(
                str(record["column"])
            )
    alternatives = {
        group: sorted(columns)
        for group, columns in scale_groups.items()
        if len(columns) > 1
    }
    return {
        "schema_version": 1,
        "governance_kind": "species_neutral_static_feature_eligibility",
        "feature_catalog_checksum": catalog_checksum,
        "materialization_policy": (
            "Feature variables are eligible only when at least one cataloged materialized "
            "resolution contains a non-null value. Missing, all-null, QC, provenance, and "
            "deterministically redundant fields remain documented but ineligible."
        ),
        "scale_policy": (
            "Alternate physical scales remain eligible candidates. Downstream applications "
            "select scales using their own targets, validation design, and performance metrics."
        ),
        "alternate_scale_groups": alternatives,
        "features": records,
    }


def _resolve_frame_column(frame: pd.DataFrame, record: Mapping[str, Any]) -> str | None:
    column = str(record["column"])
    product = record.get("product")
    prefixed = f"{product}__{column}" if product else None
    if prefixed and prefixed in frame.columns:
        return prefixed
    return column if column in frame.columns else None


def apply_feature_eligibility(
    frame: pd.DataFrame, eligibility: Mapping[str, Any]
) -> pd.DataFrame:
    """Return keys plus every statically eligible field; do not select among scales."""

    records = eligibility.get("features")
    if not isinstance(records, Sequence):
        raise ValueError("Feature eligibility metadata has no feature records.")
    included = [record for record in records if bool(record.get("eligible"))]
    resolved = [_resolve_frame_column(frame, record) for record in included]
    missing = sorted(
        f"{record.get('product', '<unknown>')}.{record['column']}"
        for record, column in zip(included, resolved, strict=True)
        if column is None
    )
    if missing:
        raise ValueError(f"Feature matrix is missing eligible columns: {missing[:10]}")
    selected = sorted({str(column) for column in resolved if column is not None})
    keys = [column for column in ("H3_INDEX", "WEEK", "DATETIME") if column in frame]
    return frame.loc[:, [*keys, *selected]].copy()


def audit_collinearity(
    frame: pd.DataFrame,
    eligibility: Mapping[str, Any],
    *,
    absolute_spearman_threshold: float = 0.95,
    minimum_overlap: int = 100,
) -> pd.DataFrame:
    """Report physical redundancy; correlation is diagnostic, never model selection."""

    candidates = sorted(
        {
            column
            for record in eligibility["features"]
            if record.get("eligible")
            for column in [_resolve_frame_column(frame, record)]
            if column is not None and pd.api.types.is_numeric_dtype(frame[column])
        }
    )
    rows: list[dict[str, Any]] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            paired = frame[[left, right]].dropna()
            if len(paired) < minimum_overlap:
                continue
            exact = bool(paired[left].equals(paired[right]))
            rho = float(paired[left].corr(paired[right], method="spearman"))
            if exact or (np.isfinite(rho) and abs(rho) >= absolute_spearman_threshold):
                rows.append(
                    {
                        "LEFT_COLUMN": left,
                        "RIGHT_COLUMN": right,
                        "OVERLAP_COUNT": len(paired),
                        "EXACT_DUPLICATE": exact,
                        "SPEARMAN_RHO": rho,
                        "ABS_SPEARMAN_RHO": abs(rho),
                    }
                )
    columns = [
        "LEFT_COLUMN",
        "RIGHT_COLUMN",
        "OVERLAP_COUNT",
        "EXACT_DUPLICATE",
        "SPEARMAN_RHO",
        "ABS_SPEARMAN_RHO",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).sort_values(
        ["EXACT_DUPLICATE", "ABS_SPEARMAN_RHO", "LEFT_COLUMN", "RIGHT_COLUMN"],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH))
    parser.add_argument("--output", default=str(DEFAULT_ELIGIBILITY_PATH))
    parser.add_argument("--panel")
    parser.add_argument("--audit-output")
    parser.add_argument("--materialization-root")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = project_root()
    materialization_root = (
        Path(args.materialization_root).resolve() if args.materialization_root else root
    )
    catalog_path = (root / args.catalog).resolve()
    snapshot = SeascapeSnapshot(root) if materialization_root == root else nullcontext()
    with snapshot:
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        subset, catalog_checksum = seascape_catalog_subset(catalog)
        eligibility = build_feature_eligibility(
            subset,
            catalog_checksum=catalog_checksum,
            materialization_root=materialization_root,
        )
    output = (root / args.output).resolve()
    rendered = yaml.safe_dump(eligibility, sort_keys=False, width=100)
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"Seascape feature eligibility metadata is stale: {output}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    if args.panel:
        audit = audit_collinearity(
            read_seascape_parquet(args.panel, canonical_root=root), eligibility
        )
        audit_path = Path(args.audit_output or "outputs/seascape_collinearity_audit.csv")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit.to_csv(audit_path, index=False)
        print(json.dumps({"eligibility": str(output), "audit": str(audit_path)}, indent=2))
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
