"""Streaming, exact-key native static append with Arrow schema preservation."""

import itertools

import pyarrow as pa
import pyarrow.parquet as pq

from .contract import RegionalError


def run(job):
    base = pq.ParquetFile(job.source("base"))
    sources = job.settings.get("append", [])
    if not sources:
        raise RegionalError("Explicit append entries required")
    readers = [pq.ParquetFile(job.source(item["input"])) for item in sources]
    schema = list(base.schema_arrow)
    mappings = []
    occupied = set(base.schema_arrow.names)
    for item, reader in zip(sources, readers, strict=True):
        prefix = item.get("prefix", "")
        release = item.get("immutable_release_id", "")
        if (
            not prefix.endswith("__")
            or not release
            or reader.metadata.num_rows != base.metadata.num_rows
        ):
            raise RegionalError(
                "Append requires namespace, immutable identity and matching rows"
            )
        mapping = {
            name: prefix + name
            for name in reader.schema_arrow.names
            if name != "H3_INDEX"
        }
        identity = prefix + "SOURCE_IMMUTABLE_RELEASE_ID"
        additions = set(mapping.values()) | {identity}
        if occupied & additions or identity in mapping.values():
            raise RegionalError("Static append namespace collision")
        schema += [
            pa.field(mapping[name], reader.schema_arrow.field(name).type)
            for name in mapping
        ]
        schema += [pa.field(identity, pa.string())]
        occupied |= additions
        mappings.append((mapping, identity, release))
    output_schema = pa.schema(schema, metadata=base.schema_arrow.metadata)
    keys = job.keys()
    count = 0
    path = job.output / "metrics.parquet"
    batch_size = job.limits["batch_rows"]
    iterators = [
        reader.iter_batches(batch_size=batch_size, use_threads=False)
        for reader in [base, *readers]
    ]
    with pq.ParquetWriter(
        path, output_schema, compression="zstd", compression_level=3
    ) as writer:
        for batches in itertools.zip_longest(*iterators):
            if any(batch is None for batch in batches):
                raise RegionalError("Unequal static input batch cardinality")
            first = batches[0]
            native_keys = first.column(
                first.schema.get_field_index("H3_INDEX")
            ).to_pylist()
            if native_keys != keys[count : count + len(native_keys)]:
                raise RegionalError(
                    "Base does not exactly align with reporting registry"
                )
            arrays = list(first.columns)
            for batch, (mapping, identity, release) in zip(
                batches[1:], mappings, strict=True
            ):
                if (
                    batch.num_rows != first.num_rows
                    or batch.column(
                        batch.schema.get_field_index("H3_INDEX")
                    ).to_pylist()
                    != native_keys
                ):
                    raise RegionalError("Append H3 order or cardinality differs")
                arrays += [
                    batch.column(batch.schema.get_field_index(name)) for name in mapping
                ]
                arrays += [pa.array([release] * first.num_rows, type=pa.string())]
            writer.write_batch(pa.RecordBatch.from_arrays(arrays, schema=output_schema))
            count += first.num_rows
            job.guard()
    if count != len(keys):
        raise RegionalError("Incomplete static output")
    # Independent readback verifies all old fields and direct source fields, including NULLs.
    candidate = pq.ParquetFile(path)
    if (
        candidate.schema_arrow != output_schema
        or candidate.schema_arrow.metadata != base.schema_arrow.metadata
    ):
        raise RegionalError("Static schema or metadata changed")
    readback = [
        candidate.iter_batches(batch_size=batch_size, use_threads=False),
        *[
            reader.iter_batches(batch_size=batch_size, use_threads=False)
            for reader in [base, *readers]
        ],
    ]
    for batches in itertools.zip_longest(*readback):
        if any(batch is None for batch in batches):
            raise RegionalError("Readback cardinality differs")
        result, old, *native = batches
        for name in old.schema.names:
            if not result.column(result.schema.get_field_index(name)).equals(
                old.column(old.schema.get_field_index(name))
            ):
                raise RegionalError(f"Old static field changed: {name}")
        for source, (mapping, _, _) in zip(native, mappings, strict=True):
            for name, renamed in mapping.items():
                if not result.column(result.schema.get_field_index(renamed)).equals(
                    source.column(source.schema.get_field_index(name))
                ):
                    raise RegionalError(f"Appended source field changed: {name}")
        job.guard()
    return "static_native_exact_h3_arrow_append_v5", {
        "rows": count,
        "columns": len(output_schema),
        "original_columns": len(base.schema_arrow),
        "readback": "all_old_and_appended_fields_types_nulls_order_metadata",
        "append_bindings": sources,
    }
