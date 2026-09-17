from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .contracts import DatasetFormat, DatasetSpec, ValidationReport


def validate_table(table: pa.Table, spec: DatasetSpec) -> ValidationReport:
    errors: list[str] = []
    schema_valid = True
    if spec.schema is not None:
        for field in spec.schema:
            index = table.schema.get_field_index(field.name)
            if index < 0:
                errors.append(f"Missing column: {field.name}")
                schema_valid = False
            elif table.schema.field(index).type != field.type:
                errors.append(
                    f"Column {field.name} has type {table.schema.field(index).type}; "
                    f"expected {field.type}"
                )
                schema_valid = False
            if not field.nullable and field.name in table.column_names:
                null_count = table[field.name].null_count
                if null_count:
                    errors.append(
                        f"Non-nullable column {field.name} has {null_count} null values"
                    )
                    schema_valid = False
    key_unique = True
    if spec.primary_key:
        missing = [key for key in spec.primary_key if key not in table.column_names]
        if missing:
            errors.append(f"Missing primary-key columns: {missing}")
            key_unique = False
        elif table.num_rows:
            keys = table.select(spec.primary_key).to_pandas()
            null_count = int(keys.isna().any(axis=1).sum())
            duplicate_count = int(keys.duplicated().sum())
            if null_count:
                errors.append(f"Primary key has {null_count} rows with null values")
                key_unique = False
            if duplicate_count:
                errors.append(f"Primary key has {duplicate_count} duplicate rows")
                key_unique = False
    null_rates = {
        name: table[name].null_count / table.num_rows if table.num_rows else 0.0
        for name in table.column_names
    }
    return ValidationReport(
        valid=not errors,
        dataset_id=str(spec.dataset_id),
        schema_valid=schema_valid,
        key_unique=key_unique,
        errors=tuple(errors),
        metrics={"row_count": table.num_rows, "null_rates": null_rates},
    )


def validate_path(path: Path, spec: DatasetSpec) -> ValidationReport:
    if not path.exists():
        return ValidationReport(
            False, str(spec.dataset_id), errors=(f"Missing artifact: {path}",)
        )
    if spec.format not in {DatasetFormat.PARQUET, DatasetFormat.GEOPARQUET}:
        return ValidationReport(True, str(spec.dataset_id), metrics={"file_count": 1})
    try:
        files = sorted(path.rglob("*.parquet")) if path.is_dir() else [path]
        if not files:
            return ValidationReport(
                False, str(spec.dataset_id), errors=("Parquet dataset has no files",)
            )
        parquet_files = [pq.ParquetFile(item) for item in files]
        schema = parquet_files[0].schema_arrow
        row_count = sum(item.metadata.num_rows for item in parquet_files)
        errors: list[str] = []
        schema_valid = True
        for item in parquet_files[1:]:
            other = item.schema_arrow
            if other.names != schema.names or any(
                other.field(name).type != schema.field(name).type for name in schema.names
            ):
                errors.append("Parquet dataset partitions have inconsistent schemas")
                schema_valid = False
                break
        if spec.schema is not None:
            for field in spec.schema:
                index = schema.get_field_index(field.name)
                if index < 0:
                    errors.append(f"Missing column: {field.name}")
                    schema_valid = False
                elif schema.field(index).type != field.type:
                    errors.append(
                        f"Column {field.name} has type {schema.field(index).type}; "
                        f"expected {field.type}"
                    )
                    schema_valid = False
                if not field.nullable and field.name in schema.names:
                    null_count = sum(
                        item.read(columns=[field.name])[field.name].null_count
                        for item in parquet_files
                    )
                    if null_count:
                        errors.append(
                            f"Non-nullable column {field.name} has {null_count} null values"
                        )
                        schema_valid = False
        key_unique = True
        if spec.primary_key:
            missing = [key for key in spec.primary_key if key not in schema.names]
            if missing:
                errors.append(f"Missing primary-key columns: {missing}")
                key_unique = False
            elif row_count:
                key_tables = [
                    item.read(columns=list(spec.primary_key)) for item in parquet_files
                ]
                keys = pa.concat_tables(
                    key_tables, promote_options="permissive"
                ).to_pandas()
                null_count = int(keys.isna().any(axis=1).sum())
                duplicate_count = int(keys.duplicated().sum())
                if null_count:
                    errors.append(f"Primary key has {null_count} rows with null values")
                    key_unique = False
                if duplicate_count:
                    errors.append(f"Primary key has {duplicate_count} duplicate rows")
                    key_unique = False
        return ValidationReport(
            valid=not errors,
            dataset_id=str(spec.dataset_id),
            schema_valid=schema_valid,
            key_unique=key_unique,
            errors=tuple(errors),
            metrics={"row_count": row_count, "null_rates": {}},
        )
    except Exception as exc:
        return ValidationReport(False, str(spec.dataset_id), errors=(str(exc),))


__all__ = ["validate_path", "validate_table"]
