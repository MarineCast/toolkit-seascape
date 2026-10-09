"""Stream native R8 terrain form without coercing source NULL QC to NaN."""

import pyarrow as pa
import pyarrow.parquet as pq

from .contract import RegionalError
from .terrain_form import METHOD_VERSION, classify


def run(job):
    if job.resolution != 8:
        raise RegionalError("Terrain form requires native R8")
    names = [
        "H3_INDEX",
        "BATHYMETRY",
        "SLOPE_MEAN_NATIVE_RASTER",
        "TERRAIN_POSITION_RING_4_Z",
        "FOCAL_NATIVE_MARINE_DEPTH_PRESENT",
        "CONTEXT_HOP4_COMPLETE",
        "TERRAIN_POSITION_RING_4_Z_QC_REASON",
    ]
    keys = job.keys()
    count = 0
    writer = None
    try:
        for batch in pq.ParquetFile(job.source("terrain")).iter_batches(
            batch_size=job.limits["batch_rows"], columns=names, use_threads=False
        ):
            values = batch.to_pydict()
            if values["H3_INDEX"] != keys[count : count + batch.num_rows]:
                raise RegionalError(
                    "Terrain input does not exactly align with reporting keys"
                )
            labels, reasons = classify(*(values[name] for name in names[1:]))
            output = pa.table(
                {
                    "H3_INDEX": values["H3_INDEX"],
                    "H3_RESOLUTION": pa.array([8] * batch.num_rows, type=pa.int64()),
                    "TERRAIN_FORM_PROXY": pa.array(labels, type=pa.string()),
                    "TERRAIN_FORM_PROXY_STATUS": reasons.tolist(),
                }
            )
            # Preserve all eligibility inputs and their Arrow nulls/types.
            for name in names[1:]:
                output = output.append_column(
                    "INPUT__" + name, batch.column(batch.schema.get_field_index(name))
                )
            if writer is None:
                writer = pq.ParquetWriter(
                    job.output / "metrics.parquet", output.schema, compression="zstd"
                )
            writer.write_table(output)
            count += batch.num_rows
            job.guard()
    finally:
        if writer:
            writer.close()
    if count != len(keys):
        raise RegionalError("Terrain reporting rows missing")
    return METHOD_VERSION, {
        "rows": count,
        "coverage": "heuristic_context_gated_proxy_not_geological_confidence",
    }
