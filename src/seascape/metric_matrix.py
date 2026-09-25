"""Assemble cataloged H3 seascape fields into one release-bound Parquet matrix."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from seascape.core.artifacts.checksums import checksum_path
from seascape.products import resolve_product

_RELEASE_MANIFEST = Path(
    "data/processed/domain/environmental_layer/seascape/seascape_release_manifest.json"
)


@dataclass(frozen=True)
class MetricMatrixResult:
    path: Path
    row_count: int
    field_count: int
    resolutions: tuple[int, ...]
    source_validation: str
    source_release_id: str | None


def _read_catalog(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("products"), dict):
        raise ValueError(f"Invalid Seascape feature catalog: {path}")
    return catalog


def _legacy_status(workspace: Path) -> tuple[dict[str, Any], list[str]]:
    path = workspace / _RELEASE_MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"Legacy Seascape release manifest not found: {path}")
    release = json.loads(path.read_text(encoding="utf-8"))
    if release.get("schema_version") != 1 or release.get("artifact_release_passed") is not True:
        raise ValueError("Legacy source must have an audited schema-1 release manifest")
    mismatches: list[str] = []
    for relative, expected in release.get("family_manifest_checksums", {}).items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Legacy manifest path escapes workspace: {relative}")
        candidate = workspace / relative_path
        if not candidate.is_file() or checksum_path(candidate) != expected:
            mismatches.append(str(relative))
    return release, mismatches


def _validated_table(
    path: Path,
    *,
    resolution: int,
    expected_keys: list[str] | None,
    selected: list[str],
) -> tuple[pa.Table, list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    schema = pq.read_schema(path)
    required = {"H3_INDEX", *selected}
    absent = required.difference(schema.names)
    if absent:
        raise ValueError(f"Missing cataloged columns in {path}: {sorted(absent)}")
    columns = [
        "H3_INDEX",
        *(["H3_RESOLUTION"] if "H3_RESOLUTION" in schema.names else []),
        *selected,
    ]
    table = pq.read_table(path, columns=columns)
    keys = table.column("H3_INDEX").to_pylist()
    if any(not isinstance(key, str) or not key for key in keys):
        raise ValueError(f"Null or invalid H3_INDEX in {path}")
    if len(keys) != len(set(keys)):
        raise ValueError(f"Duplicate H3_INDEX in {path}")
    if any(not h3.is_valid_cell(key) or h3.get_resolution(key) != resolution for key in keys):
        raise ValueError(f"Invalid or wrong-resolution H3_INDEX in {path}")
    if "H3_RESOLUTION" in table.column_names:
        actual = set(table.column("H3_RESOLUTION").to_pylist())
        if actual != {resolution}:
            raise ValueError(f"H3_RESOLUTION mismatch in {path}: {actual}")
    if expected_keys is None:
        order = sorted(range(len(keys)), key=keys.__getitem__)
        return table.take(pa.array(order, type=pa.int64())), sorted(keys)
    if set(keys) != set(expected_keys):
        raise ValueError(f"H3 support mismatch in {path}")
    positions = {key: position for position, key in enumerate(keys)}
    order = [positions[key] for key in expected_keys]
    return table.take(pa.array(order, type=pa.int64())), expected_keys


def build_metric_matrix(
    *,
    workspace: str | Path,
    output: str | Path,
    resolutions: tuple[int, ...] = (6, 8),
    legacy_unverified: bool = False,
    catalog_path: str | Path | None = None,
    overwrite: bool = False,
) -> MetricMatrixResult:
    """Write one H3 cell by catalog field matrix from an exact Seascape source.

    The normal path resolves every table from one audited schema-3 toolkit release.
    ``legacy_unverified`` is an explicit bridge for retained schema-1 materializations;
    it records manifest mismatches and must not be presented as a certified release.
    """

    root = Path(workspace).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    selected_resolutions = tuple(sorted(set(resolutions)))
    if not selected_resolutions or not set(selected_resolutions).issubset({6, 8}):
        raise ValueError("Seascape matrix resolutions must be R6 and/or R8")
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)

    release_id: str | None = None
    released_datasets: dict[tuple[str, int], str] = {}
    legacy_release: dict[str, Any] | None = None
    family_mismatches: list[str] = []
    if legacy_unverified:
        if catalog_path is None:
            raise ValueError("Legacy source requires an explicit --catalog path")
        legacy_release, family_mismatches = _legacy_status(root)
        catalog_file = Path(catalog_path).expanduser().resolve()
        source_validation = "legacy_structural_only"
    else:
        if catalog_path is not None:
            raise ValueError("A validated release uses its own archived feature catalog")
        support = resolve_product(
            workspace=root, product="h3_marine_support", resolution=selected_resolutions[0]
        )
        release_id = support.release_id
        generation = root / ".seascape/releases" / release_id
        catalog_file = generation / "config/feature_catalog.yaml"
        release = json.loads((generation / _RELEASE_MANIFEST).read_text(encoding="utf-8"))
        if release.get("release_id") != release_id or not isinstance(release.get("products"), dict):
            raise ValueError("Invalid archived Seascape release product index")
        for dataset_id, record in release["products"].items():
            if record.get("resolution") is None:
                continue
            key = (str(record["path"]), int(record["resolution"]))
            if key in released_datasets:
                raise ValueError(f"Ambiguous released Seascape collection: {key}")
            released_datasets[key] = dataset_id
        source_validation = "schema3_release_verified"
    catalog = _read_catalog(catalog_file)
    catalog_checksum = checksum_path(catalog_file)
    products = catalog["products"]
    if "h3_marine_support" not in products:
        raise ValueError("Seascape catalog has no canonical H3 marine support")

    table_records: list[dict[str, Any]] = []
    field_records: dict[str, dict[str, Any]] = {}
    resolution_tables: list[pa.Table] = []
    for resolution in selected_resolutions:
        support_keys: list[str] | None = None
        output_columns: dict[str, pa.ChunkedArray | pa.Array] = {}
        for product_id in ("h3_marine_support", *sorted(set(products) - {"h3_marine_support"})):
            product = products[product_id]
            relative = product.get("collection", {}).get("paths", {}).get(resolution)
            if relative is None:
                continue
            if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError(f"Invalid catalog collection path for {product_id}: {relative}")
            if legacy_unverified:
                path = (root / relative).resolve()
                if not path.is_relative_to(root):
                    raise ValueError(f"Collection path escapes workspace: {relative}")
                dataset_id = f"legacy.{product_id}.r{resolution}"
                checksum = checksum_path(path)
            else:
                released_dataset = released_datasets.get((relative, resolution))
                if released_dataset is None:
                    raise ValueError(
                        f"Catalog collection is absent from the release: {relative} at R{resolution}"
                    )
                artifact = resolve_product(
                    workspace=root,
                    product=released_dataset,
                    resolution=resolution,
                    release_id=release_id,
                )
                path = artifact.path
                dataset_id = artifact.dataset_id
                checksum = artifact.checksum
                if artifact.grain != ("H3_INDEX",):
                    raise ValueError(f"Unexpected grain for {dataset_id}: {artifact.grain}")
                generation = root / ".seascape/releases" / str(release_id)
                if path.relative_to(generation) != Path(relative):
                    raise ValueError(f"Release path disagrees with catalog for {dataset_id}")
            if destination == path:
                raise ValueError("Matrix output cannot replace an input table")
            features = product.get("features", {})
            if not isinstance(features, dict):
                raise ValueError(f"Invalid feature mapping for {product_id}")
            for column, feature in features.items():
                if resolution in feature.get("collection_paths", {}) and feature["collection_paths"][resolution] != relative:
                    raise ValueError(f"Feature path disagrees with product path: {product_id}.{column}")
            selected = sorted(
                column
                for column, feature in features.items()
                if resolution in feature.get("collection_paths", {})
            )
            table, support_keys = _validated_table(
                path,
                resolution=resolution,
                expected_keys=support_keys,
                selected=selected,
            )
            if not output_columns:
                output_columns["H3_INDEX"] = table.column("H3_INDEX")
                output_columns["H3_RESOLUTION"] = pa.array(
                    [resolution] * table.num_rows, type=pa.int8()
                )
            for column in selected:
                name = f"{product_id}__{column}"
                if name in output_columns:
                    raise ValueError(f"Duplicate matrix column: {name}")
                values = table.column(column)
                if pa.types.is_dictionary(values.type) or pa.types.is_string(values.type):
                    values = values.cast(pa.large_string())
                output_columns[name] = values
                feature = features[column]
                record = field_records.setdefault(
                    name,
                    {
                        "product_id": product_id,
                        "source_column": column,
                        "unit": feature.get("unit"),
                        "role": feature.get("role"),
                        "variable_kind": feature.get("variable_kind"),
                        "available_resolutions": feature.get("available_resolutions", []),
                        "source_types_by_resolution": {},
                    },
                )
                record["source_types_by_resolution"][str(resolution)] = str(
                    table.column(column).type
                )
            table_records.append(
                {
                    "product_id": product_id,
                    "dataset_id": dataset_id,
                    "resolution": resolution,
                    "path": str(path),
                    "checksum": checksum,
                    "row_count": table.num_rows,
                }
            )
        if support_keys is None:
            raise ValueError(f"No canonical H3 support at R{resolution}")
        resolution_tables.append(pa.table(output_columns))

    matrix = pa.concat_tables(resolution_tables, promote_options="permissive")
    metadata = {
        "schema_version": 1,
        "product_id": "environment.seascape.h3_metric_matrix",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "grain": ["H3_INDEX", "H3_RESOLUTION"],
        "source_validation": source_validation,
        "source_release_id": release_id,
        "legacy_release_schema": legacy_release.get("schema_version") if legacy_release else None,
        "legacy_model_policy_complete": legacy_release.get("model_policy_complete") if legacy_release else None,
        "legacy_family_manifest_mismatches": family_mismatches,
        "catalog_checksum": catalog_checksum,
        "resolutions": selected_resolutions,
        "fields": field_records,
        "source_tables": table_records,
        "missingness": "Nulls are retained; coverage, evidence, state, and QC columns remain separate from physical variables.",
    }
    schema_metadata = dict(matrix.schema.metadata or {})
    schema_metadata[b"seascape_metric_matrix"] = json.dumps(
        metadata, sort_keys=True, default=str
    ).encode("utf-8")
    matrix = matrix.replace_schema_metadata(schema_metadata)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        pq.write_table(matrix, temporary, compression="zstd")
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return MetricMatrixResult(
        path=destination,
        row_count=matrix.num_rows,
        field_count=matrix.num_columns - 2,
        resolutions=selected_resolutions,
        source_validation=source_validation,
        source_release_id=release_id,
    )


__all__ = ["MetricMatrixResult", "build_metric_matrix"]
