"""Classified native shoreline candidate."""

import pyarrow as pa
import pyarrow.parquet as pq

from .contract import RegionalError
from .geometry import cells, inventory, points


def shoreline(job):
    from .shoreline_union import _aggregate_lengths

    keys = job.keys()
    source = inventory(job)
    support = points(job, keys)
    required = ["IS_PHYSICALLY_CLASSIFIED", "SEGMENT_ID"]
    if any(name not in source for name in required):
        raise RegionalError("Normalized shoreline inventory required")
    writer = None
    try:
        for first in range(0, len(keys), min(1024, job.limits["batch_rows"])):
            selected = keys[first : first + min(1024, job.limits["batch_rows"])]
            frame = _aggregate_lengths(
                source,
                cells(selected),
                support.iloc[first : first + len(selected)],
                projected_crs="EPSG:32610",
                include_evidence_diagnostics=True,
            )
            frame["H3_RESOLUTION"] = job.resolution
            frame["SOURCE_COVERAGE_STATUS"] = job.inputs["inventory"].qualification[
                "coverage_status"
            ]
            frame["SHORELINE_CLASSIFIED_SHARE_OF_MAPPED_LENGTH_FRAC"] = (
                frame.SHORELINE_CLASSIFIED_COVERAGE_FRAC
            )
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(
                    job.output / "metrics.parquet", table.schema, compression="zstd"
                )
            writer.write_table(table)
            job.guard()
    finally:
        if writer:
            writer.close()
    return "native_full_h3_physical_shoreline_unique_union_v2", {
        "rows": len(keys),
        "classification": "nonexclusive_evidence_union_no_survey_absence",
    }
