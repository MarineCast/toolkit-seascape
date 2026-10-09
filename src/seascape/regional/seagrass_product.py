"""Block streamed full-R6 positive footprint processing, without water clipping."""

from contextlib import ExitStack

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio

from .contract import RegionalError
from .seagrass import cell_geometries, positive_metrics, select_blocks

METHOD = "native_positive_pixel_footprint_overlap_epsg6933_full_h3_lonlat_vertex_polygon_segmentized_0p001deg_v1"


def run(job):
    if job.resolution != 6:
        raise RegionalError("Positive footprint operator supports native R6 only")
    keys = job.keys()
    geographic, projected = cell_geometries(keys)
    counts = np.zeros(len(keys), dtype=np.int64)
    areas = np.zeros(len(keys), dtype=float)
    expected = np.zeros(len(keys), dtype=np.int64)
    completed = np.zeros(len(keys), dtype=np.int64)
    tiles = job.settings.get("raster_tiles")
    if tiles is None:
        tiles = [
            {"input": name} for name in sorted(job.inputs) if name.startswith("tile_")
        ]
    if not tiles:
        raise RegionalError("Explicit tile_ inputs or raster_tiles required")
    paths = []
    from pathlib import PurePosixPath
    from zipfile import ZipFile

    for tile in tiles:
        path = job.source(tile["input"])
        if "member" in tile:
            member = PurePosixPath(tile["member"])
            if member.is_absolute() or ".." in member.parts:
                raise RegionalError("Archive member must be a relative retained path")
            with ZipFile(path) as archive:
                if archive.namelist().count(member.as_posix()) != 1:
                    raise RegionalError("Archive member missing or duplicated")
            paths.append(f"zip://{path}!{member.as_posix()}")
        else:
            paths.append(path)
    with ExitStack() as stack:
        sources = [stack.enter_context(rasterio.open(path)) for path in paths]
        headers = []
        for source in sources:
            if (
                source.crs.to_epsg() != 4326
                or source.transform.b != 0
                or source.transform.d != 0
                or source.transform.a <= 0
                or source.transform.e >= 0
                or source.dtypes != ("uint8",)
                or source.scales != (1.0,)
                or source.offsets != (0.0,)
            ):
                raise RegionalError(
                    "Unsupported native positive-footprint raster header"
                )
            headers.append(
                {
                    "bounds_wgs84": list(source.bounds),
                    "resolution": list(source.res),
                    "block_shapes": list(source.block_shapes),
                    "shape": [source.height, source.width],
                }
            )
        # Overlapping tile extents would double-count source footprints.
        import shapely

        for i, a in enumerate(headers):
            for b in headers[i + 1 :]:
                if (
                    shapely.box(*a["bounds_wgs84"])
                    .intersection(shapely.box(*b["bounds_wgs84"]))
                    .area
                    > 1e-12
                ):
                    raise RegionalError(
                        "Overlapping source tile extents require explicit deduplication"
                    )
        blocks = select_blocks(headers, geographic)
        for _, _, _, *candidates in blocks:
            expected[candidates] += 1
        for tile, row, col, *candidates in blocks:
            source = sources[tile]
            bh, bw = source.block_shapes[0]
            window = rasterio.windows.Window(
                col * bw,
                row * bh,
                min(bw, source.width - col * bw),
                min(bh, source.height - row * bh),
            )
            raw = source.read(1, window=window)
            values, _ = positive_metrics(
                raw, source.transform, row * bh, col * bw, candidates, keys, projected
            )
            for index, value in values.items():
                counts[index] += value["positive_pixel_center_count"]
                areas[index] += value["modeled_positive_footprint_overlap_m2"]
            completed[candidates] += 1
            job.guard()
    if not np.array_equal(completed, expected):
        raise RegionalError("Incomplete block processing; amounts cannot be published")
    full_coverage = [
        shapely.union_all(
            [shapely.box(*head["bounds_wgs84"]) for head in headers]
        ).covers(cell)
        for cell in geographic
    ]
    table = pa.table(
        {
            "H3_INDEX": keys,
            "H3_RESOLUTION": [6] * len(keys),
            "POSITIVE_PIXEL_CENTER_COUNT": pa.array(counts, mask=expected == 0),
            "MODELED_POSITIVE_FOOTPRINT_OVERLAP_M2": pa.array(
                areas, mask=expected == 0
            ),
            "EXPECTED_SOURCE_BLOCKS": expected,
            "COMPLETED_SOURCE_BLOCKS": completed,
            "FULL_H3_WITHIN_AVAILABLE_SOURCE_TILES": full_coverage,
            "FOOTPRINT_STATUS": np.where(
                expected == 0,
                "outside_available_source_tiles",
                np.where(
                    full_coverage,
                    "available_model_positive_evidence_unknown_absence",
                    "partial_source_tile_extent_unknown_absence",
                ),
            ).tolist(),
            "METHOD_VERSION": [METHOD] * len(keys),
        }
    )
    pq.write_table(table, job.output / "metrics.parquet", compression="zstd")
    return METHOD, {
        "rows": len(keys),
        "blocks": len(blocks),
        "positive_center_count": int(counts.sum()),
        "retained_overlap_m2": float(areas.sum()),
        "source_period": [
            job.inputs[tile["input"]].qualification["observation_period"]
            for tile in tiles
        ],
        "survey_absence_qualified": False,
    }
