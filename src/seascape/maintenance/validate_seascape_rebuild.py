"""Compare a disposable seascape rebuild with the canonical product tables.

The comparison is intentionally catalog-driven: materialized products whose
``metric_family`` is ``seascape`` and the catalog's supporting products are
considered.  It checks Arrow schemas, row identity, missingness, infinity counts,
numerical values/distributions, and categorical values/counts without modifying
either artifact tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from seascape.core.config.paths import project_root

DEFAULT_CATALOG = Path("config/feature_catalog.yaml")


def _catalog_tables(catalog: Mapping[str, Any]) -> list[tuple[str, str, Path, list[str]]]:
    products = catalog.get("products")
    if not isinstance(products, Mapping):
        raise ValueError("Environment feature catalog has no products mapping.")

    tables: list[tuple[str, str, Path, list[str]]] = []
    for product_id, product in products.items():
        if not isinstance(product, Mapping) or product.get("metric_family") != "seascape":
            continue
        collection = product.get("collection")
        if not isinstance(collection, Mapping):
            raise ValueError(f"Seascape product {product_id!r} has no collection mapping.")
        paths = collection.get("paths")
        if not isinstance(paths, Mapping):
            raise ValueError(f"Seascape product {product_id!r} has no collection paths.")
        index_columns = [str(value) for value in collection.get("index_columns", [])]
        for resolution, relative_path in paths.items():
            tables.append(
                (str(product_id), f"R{int(resolution)}", Path(str(relative_path)), index_columns)
            )

    supporting = catalog.get("supporting_products", {})
    if not isinstance(supporting, Mapping):
        raise ValueError("Environment feature catalog supporting_products must be a mapping.")
    for product_id, product in supporting.items():
        if not isinstance(product, Mapping):
            continue
        path = product.get("path")
        if path:
            tables.append((f"support/{product_id}", "native", Path(str(path)), []))
        path_template = product.get("path_template")
        if path_template:
            for resolution in product.get("resolutions", []):
                tables.append(
                    (
                        f"support/{product_id}",
                        f"R{int(resolution)}",
                        Path(str(path_template).format(resolution=int(resolution))),
                        [],
                    )
                )
    return sorted(tables, key=lambda value: (value[0], value[1]))


def _h3_hash(frame: pd.DataFrame) -> str | None:
    columns = sorted(column for column in frame.columns if column.endswith("H3_INDEX"))
    if not columns:
        return None
    values = sorted(
        "\x1f".join("<NULL>" if pd.isna(value) else str(value) for value in row)
        for row in frame[columns].itertuples(index=False, name=None)
    )
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _sorted(frame: pd.DataFrame, index_columns: list[str]) -> pd.DataFrame:
    usable = [column for column in index_columns if column in frame.columns]
    if not usable:
        usable = sorted(column for column in frame.columns if column.endswith("H3_INDEX"))
    if usable:
        return frame.sort_values(usable, kind="mergesort", na_position="last").reset_index(
            drop=True
        )
    return frame.reset_index(drop=True)


def _numeric_summary(series: pd.Series) -> dict[str, float | int | None]:
    finite = series[np.isfinite(series.to_numpy(dtype=float, na_value=np.nan))].astype(float)
    if finite.empty:
        return {"count": 0, "min": None, "median": None, "max": None, "mean": None}
    return {
        "count": int(finite.size),
        "min": float(finite.min()),
        "median": float(finite.median()),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
    }


def _stable_scalar(value: Any) -> str:
    if value is None:
        return "<NULL>"
    missing = pd.isna(value)
    if isinstance(missing, (bool, np.bool_)) and missing:
        return "<NULL>"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def compare_table(
    canonical_path: Path,
    candidate_path: Path,
    *,
    index_columns: list[str],
    relative_tolerance: float,
    absolute_tolerance: float,
) -> dict[str, Any]:
    """Return a JSON-serializable parity report for one Parquet table."""

    failures: list[str] = []
    if not canonical_path.exists():
        return {"passed": False, "failures": [f"missing canonical table: {canonical_path}"]}
    if not candidate_path.exists():
        return {"passed": False, "failures": [f"missing candidate table: {candidate_path}"]}

    canonical_schema = pq.read_schema(canonical_path)
    candidate_schema = pq.read_schema(candidate_path)
    schema_matches = canonical_schema.equals(candidate_schema, check_metadata=False)
    if not schema_matches:
        failures.append("Arrow schema differs")

    canonical = _sorted(pd.read_parquet(canonical_path), index_columns)
    candidate = _sorted(pd.read_parquet(candidate_path), index_columns)
    if canonical.shape != candidate.shape:
        failures.append(f"shape differs: canonical={canonical.shape}, candidate={candidate.shape}")
    if canonical.columns.tolist() != candidate.columns.tolist():
        failures.append("column order differs")

    canonical_hash = _h3_hash(canonical)
    candidate_hash = _h3_hash(candidate)
    if canonical_hash != candidate_hash:
        failures.append("H3 cell hash differs")

    canonical_nulls = {column: int(value) for column, value in canonical.isna().sum().items()}
    candidate_nulls = {column: int(value) for column, value in candidate.isna().sum().items()}
    if canonical_nulls != candidate_nulls:
        failures.append("null counts differ")

    canonical_infinities: dict[str, int] = {}
    candidate_infinities: dict[str, int] = {}
    numerical_summaries: dict[str, dict[str, Any]] = {}
    categorical_counts: dict[str, dict[str, Any]] = {}
    common_columns = [column for column in canonical.columns if column in candidate.columns]
    same_shape = canonical.shape[0] == candidate.shape[0]
    for column in common_columns:
        left = canonical[column]
        right = candidate[column]
        if pd.api.types.is_numeric_dtype(left.dtype) and pd.api.types.is_numeric_dtype(right.dtype):
            left_values = left.to_numpy(dtype=float, na_value=np.nan)
            right_values = right.to_numpy(dtype=float, na_value=np.nan)
            canonical_infinities[column] = int(np.isinf(left_values).sum())
            candidate_infinities[column] = int(np.isinf(right_values).sum())
            numerical_summaries[column] = {
                "canonical": _numeric_summary(left),
                "candidate": _numeric_summary(right),
            }
            if same_shape and not np.allclose(
                left_values,
                right_values,
                rtol=relative_tolerance,
                atol=absolute_tolerance,
                equal_nan=True,
            ):
                failures.append(f"numeric values differ: {column}")
        elif same_shape:
            left_values = left.map(_stable_scalar)
            right_values = right.map(_stable_scalar)
            if not left_values.equals(right_values):
                failures.append(f"categorical values differ: {column}")
            if max(left_values.nunique(), right_values.nunique()) <= 100:
                left_counts = left_values.value_counts(dropna=False).sort_index().to_dict()
                right_counts = right_values.value_counts(dropna=False).sort_index().to_dict()
                categorical_counts[column] = {
                    "canonical": {str(key): int(value) for key, value in left_counts.items()},
                    "candidate": {str(key): int(value) for key, value in right_counts.items()},
                }
                if left_counts != right_counts:
                    failures.append(f"categorical counts differ: {column}")

    if canonical_infinities != candidate_infinities:
        failures.append("infinity counts differ")

    return {
        "passed": not failures,
        "failures": failures,
        "schema_matches": schema_matches,
        "rows": {"canonical": len(canonical), "candidate": len(candidate)},
        "h3_hash": {"canonical": canonical_hash, "candidate": candidate_hash},
        "null_counts": {"canonical": canonical_nulls, "candidate": candidate_nulls},
        "infinity_counts": {
            "canonical": canonical_infinities,
            "candidate": candidate_infinities,
        },
        "numerical_summaries": numerical_summaries,
        "categorical_counts": categorical_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--canonical-root", type=Path, default=project_root())
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rtol", type=float, default=1e-12)
    parser.add_argument("--atol", type=float, default=1e-12)
    args = parser.parse_args()

    canonical_root = args.canonical_root.resolve()
    candidate_root = args.candidate_root.resolve()
    catalog_path = args.catalog
    if not catalog_path.is_absolute():
        catalog_path = canonical_root / catalog_path
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    table_reports: dict[str, Any] = {}
    for product_id, resolution, relative_path, index_columns in _catalog_tables(catalog):
        key = f"{product_id}:{resolution}"
        table_reports[key] = compare_table(
            canonical_root / relative_path,
            candidate_root / relative_path,
            index_columns=index_columns,
            relative_tolerance=args.rtol,
            absolute_tolerance=args.atol,
        )
        status = "pass" if table_reports[key]["passed"] else "FAIL"
        print(f"[{status}] {key}: {relative_path}")

    failed = [key for key, report in table_reports.items() if not report["passed"]]
    payload = {
        "catalog_path": str(catalog_path),
        "canonical_root": str(canonical_root),
        "candidate_root": str(candidate_root),
        "table_count": len(table_reports),
        "failed_table_count": len(failed),
        "passed": not failed,
        "failed_tables": failed,
        "tables": table_reports,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Wrote comparison report: {args.output}")
    else:
        print(rendered)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
