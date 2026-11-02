"""Direct R6 point substrate and finite-inventory proximity orchestration."""

from contextlib import ExitStack

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from pyproj import Transformer
from scipy.spatial import cKDTree

from .contract import RegionalError
from .geometry import points
from .proximity import finite_inventory_metrics
from .substrate import METHOD, sample, sediment_summary


def substrate(job):
    if job.resolution != 6:
        raise RegionalError(
            "Direct substrate requires R6; no aggregation or upsampling"
        )
    keys = job.keys()
    support = points(job, keys)
    writer = None
    counts = {}
    with ExitStack() as stack:
        sources = {
            name: stack.enter_context(rasterio.open(job.source(name.lower())))
            for name in ("ROCK", "GRAVEL", "SAND", "MUD")
        }
        for name, source in sources.items():
            if list(source.transform) != [
                0.1,
                0.0,
                -180.0,
                0.0,
                -0.1,
                90.0,
                0.0,
                0.0,
                1.0,
            ]:
                raise RegionalError(f"Unexpected modeled substrate alignment: {name}")
        try:
            for first in range(0, len(keys), min(job.limits["batch_rows"], 512)):
                s = support.iloc[first : first + min(job.limits["batch_rows"], 512)]
                columns = {
                    "H3_INDEX": s.H3_INDEX.tolist(),
                    "H3_RESOLUTION": [6] * len(s),
                }
                composition = []
                for name, source in sources.items():
                    values, weights, neighbors, _ = sample(
                        source,
                        s.REPRESENTATIVE_POINT_LONGITUDE,
                        s.REPRESENTATIVE_POINT_LATITUDE,
                    )
                    field = (
                        "MODELED_ROCK_PRESENCE_SCORE"
                        if name == "ROCK"
                        else "MODELED_SEDIMENT_" + name + "_FRACTION"
                    )
                    columns[field] = pa.array(
                        values, type=pa.float64(), from_pandas=True
                    )
                    columns[name + "_POINT_SAMPLE_STATUS"] = np.where(
                        np.isfinite(values), "available", "source_unavailable"
                    ).tolist()
                    columns[name + "_VALID_NEIGHBOR_WEIGHT"] = weights
                    columns[name + "_VALID_POSITIVE_WEIGHT_NEIGHBORS"] = neighbors
                    columns[name + "_MASK_STATUS"] = np.where(
                        weights == 0,
                        "all_contributing_neighbors_missing",
                        np.where(
                            weights < 1 - 1e-12,
                            "partial_neighbors_renormalized",
                            "full_weight_available",
                        ),
                    ).tolist()
                    counts[name] = counts.get(name, 0) + int(np.isfinite(values).sum())
                    if name != "ROCK":
                        composition.append(values)
                summary = [sediment_summary(*v) for v in zip(*composition, strict=True)]
                columns.update(
                    SEDIMENT_TEXTURE_STATUS=[v[0] for v in summary],
                    SEDIMENT_FRACTION_SUM=pa.array(
                        [v[1] for v in summary], type=pa.float64()
                    ),
                    SEDIMENT_NORMALIZED_ENTROPY=pa.array(
                        [v[2] for v in summary], type=pa.float64()
                    ),
                    DERIVATION_METHOD=[METHOD] * len(s),
                    SOURCE_GRID_DEGREES=[0.1] * len(s),
                    SOURCE_OBSERVATION_PERIOD=pa.nulls(len(s), type=pa.string()),
                    PHYSICAL_HARDNESS=pa.nulls(len(s), type=pa.float64()),
                    H3_AREAL_SUBSTRATE_COVERAGE=pa.nulls(len(s), type=pa.float64()),
                    JOINT_ROCK_SEDIMENT_FRACTION=pa.nulls(len(s), type=pa.float64()),
                )
                table = pa.table(columns)
                if writer is None:
                    writer = pq.ParquetWriter(
                        job.output / "metrics.parquet", table.schema, compression="zstd"
                    )
                writer.write_table(table)
                job.guard()
        finally:
            if writer:
                writer.close()
    return METHOD, {
        "rows": len(keys),
        "available_by_variable": counts,
        "support": "point_not_areal",
        "observation_dates": "unknown",
    }


def proximity(job):
    keys = job.keys()
    if job.resolution != 8:
        raise RegionalError("Finite provider/estuary proximity requires native R8")
    import h3

    locations = np.asarray([h3.cell_to_latlng(k) for k in keys])
    source = job.table("inventory").to_pydict()
    xname = job.settings.get("x_column", "X_M")
    yname = job.settings.get("y_column", "Y_M")
    identifier = job.settings.get("id_column", "SOURCE_ID")
    if job.settings.get("projected_crs", "EPSG:32610") != "EPSG:32610":
        raise RegionalError("Reviewed finite proximity requires EPSG:32610")
    xy = np.column_stack((source[xname], source[yname])).astype(float)
    ids = source[identifier]
    if len(set(ids)) != len(ids) or any(v is None for v in ids):
        raise RegionalError("Inventory IDs must be unique/non-null")
    if not len(xy) or not np.isfinite(xy).all():
        raise RegionalError("Finite nonempty qualified source inventory required")
    tree = cKDTree(xy)
    transform = Transformer.from_crs(4326, 32610, always_xy=True)
    target = np.column_stack(
        transform.transform(
            locations[:, 1],
            locations[:, 0],
        )
    )
    writer = None
    try:
        for first in range(0, len(keys), min(512, job.limits["batch_rows"])):
            local = target[first : first + min(512, job.limits["batch_rows"])]
            distance, positions, kernel = finite_inventory_metrics(local, xy, tree)
            columns = {
                "H3_INDEX": keys[first : first + len(local)],
                "H3_RESOLUTION": [job.resolution] * len(local),
                "NEAREST_SOURCE_ID": [str(ids[i]) for i in positions],
                "MINIMUM_DISTANCE_M": distance,
                "PROXIMITY_STATUS": ["finite_inventory_euclidean_not_network"]
                * len(local),
            }
            if job.operator == "freshwater":
                columns["FINITE_INVENTORY_EXPONENTIAL_5KM_SUM"] = kernel
            table = pa.table(columns)
            if writer is None:
                writer = pq.ParquetWriter(
                    job.output / "metrics.parquet", table.schema, compression="zstd"
                )
            writer.write_table(table)
            job.guard()
    finally:
        if writer:
            writer.close()
    return (
        "finite_inventory_euclidean_epsg32610_v3"
        if job.operator == "freshwater"
        else "mapped_estuary_representative_point_euclidean_epsg32610_v2",
        {
            "rows": len(keys),
            "inventory_rows": len(xy),
            "coverage": "finite_source_inventory_not_global",
            "source_selection": job.inputs["inventory"].qualification,
        },
    )
