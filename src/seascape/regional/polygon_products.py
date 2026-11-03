"""Direct polygon evidence with qualified projection and union semantics."""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from .bivalve import IndexedEvidence
from .contract import RegionalError
from .geometry import cells, inventory, points, projected


def coastal(job):
    from .coastal_product import run

    return run(job)


def bivalve(job):
    keys = job.keys()
    source, evidence = projected(job, crs=32610)
    field = job.settings.get("class_column", "EVIDENCE_CLASS")
    if (
        source[field].isna().any()
        or not source[field].astype(str).str.startswith(("WA_", "BC_")).all()
    ):
        raise RegionalError(
            "Bivalve classes require qualified WA_/BC_ evidence identity"
        )
    engine = IndexedEvidence(list(zip(source.geometry, source[field], strict=True)))
    native = cells(keys).to_crs(32610)
    import h3
    from pyproj import Transformer

    origins = np.asarray([h3.cell_to_latlng(key) for key in keys])
    xx, yy = Transformer.from_crs(4326, 32610, always_xy=True).transform(
        origins[:, 1], origins[:, 0]
    )
    schema = pa.schema(
        [
            ("H3_INDEX", pa.string()),
            ("H3_RESOLUTION", pa.int64()),
            ("MAPPED_UNION_AREA_M2", pa.float64()),
            ("SOURCE_RECORD_SUM_AREA_M2", pa.float64()),
            ("SOURCE_OVERLAP_EXCESS_M2", pa.float64()),
            ("WA_BC_OVERLAP_M2", pa.float64()),
            ("NEAREST_MAPPED_POLYGON_DISTANCE_M", pa.float64()),
            ("CLASS_AREAS_JSON", pa.string()),
            ("INTERSECTING_SOURCE_RECORD_COUNT", pa.int64()),
            ("EVIDENCE_STATUS", pa.string()),
        ]
    )
    with pq.ParquetWriter(
        job.output / "metrics.parquet", schema, compression="zstd"
    ) as writer:
        for first in range(0, len(keys), job.limits["batch_rows"]):
            rows = []
            for i in range(first, min(first + job.limits["batch_rows"], len(keys))):
                values = engine.calculate(
                    native.geometry.iloc[i], shapely.Point(xx[i], yy[i])
                )
                rows.append(
                    dict(
                        H3_INDEX=keys[i],
                        H3_RESOLUTION=job.resolution,
                        MAPPED_UNION_AREA_M2=values["union_area"],
                        SOURCE_RECORD_SUM_AREA_M2=values["record_sum"],
                        SOURCE_OVERLAP_EXCESS_M2=values["overlap_excess"],
                        WA_BC_OVERLAP_M2=values["WA_BC_overlap"],
                        NEAREST_MAPPED_POLYGON_DISTANCE_M=values["distance"],
                        CLASS_AREAS_JSON=json.dumps(
                            values["class_areas"], sort_keys=True
                        ),
                        INTERSECTING_SOURCE_RECORD_COUNT=values["candidate_records"],
                        EVIDENCE_STATUS="generalized_positive_evidence_not_reef_or_survey_absence",
                    )
                )
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
            job.guard()
    return "generalized_mapped_bivalve_polygon_evidence_native_v1", {
        "rows": len(keys),
        "projection_qualification": evidence,
        "source_records": len(source),
    }


def shoreline(job):
    from seascape.coastal_configuration.shoreline_characterization.build import (
        _aggregate_lengths,
    )

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
