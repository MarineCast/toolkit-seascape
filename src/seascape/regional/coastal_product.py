"""Origin-defined native R8 indexed rays and censored opposing-axis summaries."""

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from .coastal_index import IndexedFirstExit
from .coastal_origin import metric_record, origin_record
from .coastal_serialization import nullable_origin_h3
from .contract import RegionalError
from .geometry import cells, inventory

METHOD = "continuous_first_exit_v2_indexed__explicit_focal_origin_contract_v1"
ORIGIN_FIELDS = {
    "H3_INDEX": pa.string(),
    "H3_RESOLUTION": pa.int8(),
    "ORIGIN_LONGITUDE": pa.float64(),
    "ORIGIN_LATITUDE": pa.float64(),
    "ORIGIN_METHOD": pa.string(),
    "ORIGIN_SOURCE_H3_INDEX": pa.string(),
    "ORIGIN_WITHIN_FOCAL_H3": pa.bool_(),
    "ORIGIN_IS_CONNECTOR_PROXY": pa.bool_(),
    "ORIGIN_METRIC_SCOPE": pa.string(),
    "FOCAL_FULL_H3_WITHIN_REGISTERED_EXTENT": pa.bool_(),
    "FOCAL_GENERALIZED_FALLBACK": pa.bool_(),
    "FOCAL_NATIVE_LAND_FOOTPRINT_UNKNOWN": pa.bool_(),
    "FOCAL_POLICY_EDGE_REVIEW": pa.bool_(),
}
RAY_FIELDS = {
    "ORIGIN_CONNECTED_MAPPED_WATER_RUN_BOUND_M": pa.float64(),
    "ORIGIN_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M": pa.float64(),
    "FOCAL_IN_CELL_MAPPED_GEOMETRY_BOUNDARY_DISTANCE_M": pa.float64(),
    "FIRST_EXIT_STATUS": pa.string(),
    "CONFIGURED_LIMIT_CENSORED": pa.bool_(),
    "WHOLE_RAY_REGISTERED_CONTEXT_CENSORED": pa.bool_(),
    "FOCAL_IN_CELL_ORIGIN_ELIGIBLE": pa.bool_(),
    "WHOLE_RAY_FINE_SOURCE_ACCURACY_QUALIFIED": pa.bool_(),
    "PRIMARY_PHYSICAL_FETCH_M": pa.float64(),
    "FULL_PHYSICAL_FETCH_QUALIFIED": pa.bool_(),
    "SOURCE_COMPLETENESS": pa.string(),
    "BEARING_INDEX": pa.int8(),
    "BEARING_DEG": pa.float64(),
    "BOUNDARY_FRAGMENT_CANDIDATES": pa.int32(),
    "METHOD_VERSION": pa.string(),
}
SUMMARY_FIELDS = {
    "SOURCE_EDGE_RAY_COUNT": pa.int8(),
    "CONFIGURED_CAP_RAY_COUNT": pa.int8(),
    "INVALID_ORIGIN_RAY_COUNT": pa.int8(),
    "ALL16_RAYS_WITHIN_REGISTERED_CONTEXT": pa.bool_(),
    "ALL8_OPPOSING_AXES_HAVE_MAPPED_ENDPOINTS": pa.bool_(),
    "ORIGIN_MEAN_CAPPED_CONNECTED_RUN_BOUND_M": pa.float64(),
    "ORIGIN_MIN_OPPOSING_CONNECTED_RUN_SUM_BOUND_M": pa.float64(),
    "ORIGIN_MIN_OPPOSING_AXIS_HAS_CAP": pa.bool_(),
    "FOCAL_IN_CELL_MEAN_CAPPED_CONNECTED_RUN_BOUND_M": pa.float64(),
    "FOCAL_IN_CELL_MIN_OPPOSING_CONNECTED_RUN_SUM_BOUND_M": pa.float64(),
    "PRIMARY_PHYSICAL_WATERBODY_WIDTH_M": pa.float64(),
    "WHOLE_RAY_FINE_SOURCE_ACCURACY_QUALIFIED": pa.bool_(),
    "SOURCE_COMPLETENESS": pa.string(),
    "METHOD_VERSION": pa.string(),
}


def run(job):
    if job.resolution != 8:
        raise RegionalError("Origin-defined coastal rays require native R8")
    keys = job.keys()
    water = shapely.union_all(inventory(job, "water").to_crs(4326).geometry.to_numpy())
    extent = shapely.union_all(
        inventory(job, "extent").to_crs(4326).geometry.to_numpy()
    )
    engine = IndexedFirstExit(water, extent)
    if "origins" in job.inputs:
        origins = job.table("origins").to_pylist()
        if [row["H3_INDEX"] for row in origins] != keys:
            raise RegionalError(
                "Frozen coastal origins must exactly align with reporting keys"
            )
    else:
        support = (
            job.table("support")
            .to_pandas()
            .set_index("H3_INDEX", verify_integrity=True)
        )
        if not support.index.is_unique or not set(keys) <= set(support.index):
            raise RegionalError("Coastal origin support missing or duplicated")
        prior = (
            job.table("prior_origins")
            .to_pandas()
            .set_index("H3_INDEX", verify_integrity=True)
            if "prior_origins" in job.inputs
            else None
        )
        origins = [origin_record(key, support, prior) for key in keys]
        for row in origins:
            for flag in (
                "GENERALIZED_FALLBACK",
                "NATIVE_LAND_FOOTPRINT_UNKNOWN",
                "POLICY_EDGE_REVIEW",
            ):
                row["FOCAL_" + flag] = (
                    support.loc[row["H3_INDEX"], flag] if flag in support else None
                )
    for row, polygon in zip(origins, cells(keys).geometry, strict=True):
        if not np.isfinite(row["ORIGIN_LONGITUDE"]) or not np.isfinite(
            row["ORIGIN_LATITUDE"]
        ):
            raise RegionalError("Coastal origin coordinates must be finite")
        row["ORIGIN_SOURCE_H3_INDEX"] = nullable_origin_h3(
            row["ORIGIN_SOURCE_H3_INDEX"]
        )
        within = polygon.covers(
            shapely.Point(row["ORIGIN_LONGITUDE"], row["ORIGIN_LATITUDE"])
        )
        proxy = (
            row["ORIGIN_SOURCE_H3_INDEX"] is not None
            and row["ORIGIN_SOURCE_H3_INDEX"] != row["H3_INDEX"]
        )
        if (
            row["ORIGIN_WITHIN_FOCAL_H3"] != within
            or row["ORIGIN_IS_CONNECTOR_PROXY"] != proxy
        ):
            raise RegionalError(
                "Coastal origin contract disagrees with native geometry or source identity"
            )
    ray_schema = pa.schema(list((ORIGIN_FIELDS | RAY_FIELDS).items()))
    summary_schema = pa.schema(list((ORIGIN_FIELDS | SUMMARY_FIELDS).items()))
    with (
        pq.ParquetWriter(
            job.output / "bearings.parquet", ray_schema, compression="zstd"
        ) as rays,
        pq.ParquetWriter(
            job.output / "metrics.parquet", summary_schema, compression="zstd"
        ) as summaries,
    ):
        for first in range(0, len(origins), min(128, job.limits["batch_rows"])):
            rayrows = []
            summaryrows = []
            for origin in origins[first : first + min(128, job.limits["batch_rows"])]:
                base = {name: origin.get(name) for name in ORIGIN_FIELDS}
                bounds = []
                statuses = []
                for bearing_index in range(16):
                    distance, status, candidates = engine.calculate(
                        origin["ORIGIN_LONGITUDE"],
                        origin["ORIGIN_LATITUDE"],
                        bearing_index * 22.5,
                    )
                    bounds.append(distance)
                    statuses.append(status)
                    rayrows.append(
                        {
                            **base,
                            **metric_record(origin, distance, status),
                            "BEARING_INDEX": bearing_index,
                            "BEARING_DEG": bearing_index * 22.5,
                            "BOUNDARY_FRAGMENT_CANDIDATES": candidates,
                            "METHOD_VERSION": METHOD,
                        }
                    )
                values = np.array(
                    [float(v) if v is not None else np.nan for v in bounds]
                )
                unknown = (
                    np.isnan(values).any()
                    or "source_extent_exit" in statuses
                    or "origin_outside_registered_source_extent" in statuses
                )
                caps = np.array(
                    [status == "configured_limit_censored" for status in statuses]
                )
                axes = values[:8] + values[8:]
                mean = None if unknown else float(values.mean())
                minimum = None if unknown else float(axes.min())
                focal = (
                    not origin["ORIGIN_IS_CONNECTOR_PROXY"]
                    and origin["ORIGIN_WITHIN_FOCAL_H3"]
                )
                summaryrows.append(
                    {
                        **base,
                        "SOURCE_EDGE_RAY_COUNT": sum(
                            status == "source_extent_exit" for status in statuses
                        ),
                        "CONFIGURED_CAP_RAY_COUNT": int(caps.sum()),
                        "INVALID_ORIGIN_RAY_COUNT": sum(
                            status.startswith("origin_") for status in statuses
                        ),
                        "ALL16_RAYS_WITHIN_REGISTERED_CONTEXT": not unknown,
                        "ALL8_OPPOSING_AXES_HAVE_MAPPED_ENDPOINTS": not unknown
                        and not caps.any(),
                        "ORIGIN_MEAN_CAPPED_CONNECTED_RUN_BOUND_M": mean,
                        "ORIGIN_MIN_OPPOSING_CONNECTED_RUN_SUM_BOUND_M": minimum,
                        "ORIGIN_MIN_OPPOSING_AXIS_HAS_CAP": None
                        if unknown
                        else bool((caps[:8] | caps[8:])[int(axes.argmin())]),
                        "FOCAL_IN_CELL_MEAN_CAPPED_CONNECTED_RUN_BOUND_M": mean
                        if focal
                        else None,
                        "FOCAL_IN_CELL_MIN_OPPOSING_CONNECTED_RUN_SUM_BOUND_M": minimum
                        if focal
                        else None,
                        "PRIMARY_PHYSICAL_WATERBODY_WIDTH_M": None,
                        "WHOLE_RAY_FINE_SOURCE_ACCURACY_QUALIFIED": False,
                        "SOURCE_COMPLETENESS": "partial",
                        "METHOD_VERSION": METHOD,
                    }
                )
            rays.write_table(pa.Table.from_pylist(rayrows, schema=ray_schema))
            summaries.write_table(
                pa.Table.from_pylist(summaryrows, schema=summary_schema)
            )
            job.guard()
    return METHOD, {
        "rows": len(keys),
        "ray_rows": 16 * len(keys),
        "maximum_search_m": 50000,
        "maximum_segment_m": 100,
        "source_accuracy": "unqualified_mapped_geometry",
        "physical_fetch_and_width": "unqualified_null",
    }
