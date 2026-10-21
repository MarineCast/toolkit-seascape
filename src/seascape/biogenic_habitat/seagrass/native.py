"""Bounded native-H3 positive-model amounts, independent of water-network products."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import rasterio
import shapely
from numpy.typing import NDArray
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform

from seascape.domain_parquets import METADATA_KEY, validate_table
from seascape.utils.habitat_raster import discover_geotiffs

TO_AREA = Transformer.from_crs(4326, 6933, always_xy=True)
PREFIX = "SEAGRASS_MODEL__"
METHOD = (
    "native_positive_pixel_footprint_overlap_epsg6933_full_h3_segmentized_0p001deg_v1"
)


@dataclass(frozen=True)
class NativeFootprintResult:
    table: pa.Table
    report: dict[str, Any]


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def native_cell_geometries(keys: Sequence[str]) -> tuple[list[Any], list[Any]]:
    geographic = [
        Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(key)]) for key in keys
    ]
    west, south, east, north = shapely.total_bounds(geographic)
    if east - west > 180 or max(abs(south), abs(north)) > 85:
        raise ValueError("Native footprint support must be regional and non-polar")
    projected = [
        transform(TO_AREA.transform, shapely.segmentize(g, 0.001)) for g in geographic
    ]
    return geographic, projected


def positive_pixel_metrics(
    raw: np.ndarray,
    affine: Any,
    row_offset: int,
    col_offset: int,
    candidates: Sequence[int],
    keys: Sequence[str],
    projected: Sequence[Any],
    *,
    resolution: int,
) -> tuple[dict[int, tuple[int, float]], dict[str, float]]:
    """Centre membership and footprint intersection are deliberately separate."""
    if np.any((raw != 0) & (raw != 1)):
        raise ValueError("Unexpected seagrass raster class; expected binary 0/1")
    rows, cols = np.nonzero(raw == 1)
    west = affine.c + (col_offset + cols) * affine.a
    east = west + affine.a
    north = affine.f + (row_offset + rows) * affine.e
    south = north + affine.e
    xmin, ymin = TO_AREA.transform(west, south)
    xmax, ymax = TO_AREA.transform(east, north)
    pixels = shapely.box(xmin, ymin, xmax, ymax)
    source_area = float(np.sum((xmax - xmin) * (ymax - ymin)))
    indexes = {keys[i]: i for i in candidates}
    count: Counter[int] = Counter()
    for lon, lat in zip((west + east) / 2, (south + north) / 2, strict=True):
        key = h3.latlng_to_cell(float(lat), float(lon), resolution)
        if key in indexes:
            count[indexes[key]] += 1
    result = {}
    retained = 0.0
    for i in candidates:
        hit = shapely.intersects(pixels, projected[i])
        area = float(
            np.sum(shapely.area(shapely.intersection(pixels[hit], projected[i])))
        )
        retained += area
        if area or count[i]:
            result[i] = count[i], area
    if retained > source_area * (1 + 1e-8) + 0.001:
        raise ValueError("Native footprint partition exceeds source pixel area")
    return result, {"positive_pixels": len(rows), "source_area_m2": source_area}


def _blocks(
    headers: Sequence[dict[str, Any]], geographic: Sequence[Any]
) -> list[list[int]]:
    tree = shapely.STRtree(geographic)
    west, south, east, north = shapely.total_bounds(geographic)
    rows = []
    for tile, head in enumerate(headers):
        left, bottom, right, top = head["bounds"]
        dx, dy = head["resolution"]
        bh, bw = head["block_shape"]
        height, width = head["shape"]
        c0 = max(0, math.floor((max(west, left) - left) / dx / bw))
        c1 = min(math.ceil(width / bw), math.ceil((min(east, right) - left) / dx / bw))
        r0 = max(0, math.floor((top - min(north, top)) / dy / bh))
        r1 = min(
            math.ceil(height / bh), math.ceil((top - max(south, bottom)) / dy / bh)
        )
        for r in range(r0, r1):
            cols = np.arange(c0, c1)
            xmin = left + cols * bw * dx
            ymax = top - r * bh * dy
            boxes = shapely.box(
                xmin,
                max(bottom, ymax - bh * dy),
                np.minimum(right, xmin + bw * dx),
                ymax,
            )
            hits = tree.query(boxes, predicate="intersects")
            for local in np.unique(hits[0]):
                indexes = sorted(int(i) for i in hits[1, hits[0] == local])
                rows.append([tile, r, int(cols[local]), *indexes])
    return rows


def build_native_positive_footprints(
    archive: str | Path,
    keys: Sequence[str],
    *,
    resolution: int,
    composite_start_year: int,
    composite_end_year: int,
    expected_sha256: str | None = None,
    max_cells: int = 200_000,
    max_blocks: int = 100_000,
    max_seconds: float = 3600,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> NativeFootprintResult:
    """Compute available positive-model amounts; missing coverage is never absence."""
    started = time.monotonic()
    code_hash = _digest(Path(__file__))
    path = Path(archive).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".zip":
        raise ValueError(
            "Supply the compressed source ZIP; no download or extraction occurs"
        )
    if not 1 <= composite_start_year <= composite_end_year < 9999:
        raise ValueError("Composite years must be ordered calendar years")
    if min(max_cells, max_blocks, max_seconds) <= 0 or not math.isfinite(max_seconds):
        raise ValueError("Native footprint resource bounds must be positive")
    if not keys or len(keys) > max_cells or len(set(keys)) != len(keys):
        raise ValueError("Supply unique, nonempty native keys within max_cells")
    ordered = sorted(keys)
    if any(
        not h3.is_valid_cell(k) or h3.get_resolution(k) != resolution for k in ordered
    ):
        raise ValueError("Native H3 identity/resolution mismatch")
    checksum = _digest(path)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("Source archive checksum differs from the pinned identity")
    geographic, projected = native_cell_geometries(ordered)
    extent = shapely.box(*shapely.total_bounds(geographic))
    paths = discover_geotiffs(path)
    if len(paths) > 2048:
        raise ValueError("Source raster member bound exceeded")
    headers = []
    with rasterio.Env(GDAL_CACHEMAX=32 * 1024**2):
        for member in paths:
            with rasterio.open(member) as source:
                if source.crs is None or source.crs.to_epsg() != 4326:
                    raise ValueError("Seagrass source must retain EPSG:4326")
                if not shapely.intersects(extent, shapely.box(*source.bounds)):
                    continue
                affine = source.transform
                if (
                    source.count != 1
                    or source.dtypes[0] != "uint8"
                    or source.nodata != 0
                    or affine.b
                    or affine.d
                    or affine.a <= 0
                    or affine.e >= 0
                ):
                    raise ValueError(
                        "Unsupported seagrass band, mask or affine contract"
                    )
                headers.append(
                    {
                        "path": str(member),
                        "bounds": tuple(source.bounds),
                        "resolution": source.res,
                        "block_shape": source.block_shapes[0],
                        "shape": source.shape,
                    }
                )
    rectangles = [shapely.box(*h["bounds"]) for h in headers]
    for i, a in enumerate(rectangles):
        if any(
            shapely.area(shapely.intersection(a, b)) > 1e-10
            for b in rectangles[i + 1 :]
        ):
            raise ValueError(
                "Overlapping source tile rectangles would double count pixels"
            )
    available = shapely.union_all(rectangles)
    status = [
        "full_cell_inside_available_tile_rectangles"
        if available.covers(g)
        else "partial_cell_inside_available_tile_rectangles"
        if available.intersects(g)
        else "no_available_tile_rectangle"
        for g in geographic
    ]
    blocks = _blocks(headers, geographic)
    if len(blocks) > max_blocks:
        raise ValueError("Source block bound exceeded before pixel processing")
    expected: NDArray[np.int64] = np.zeros(len(ordered), dtype="int64")
    processed: NDArray[np.int64] = np.zeros(len(ordered), dtype="int64")
    counts: NDArray[np.int64] = np.zeros(len(ordered), dtype="int64")
    areas: NDArray[np.float64] = np.zeros(len(ordered), dtype="float64")
    for block in blocks:
        expected[block[3:]] += 1
    completed = 0
    with rasterio.Env(GDAL_CACHEMAX=32 * 1024**2):
        for tile, header in enumerate(headers):
            bh, bw = header["block_shape"]
            with rasterio.open(header["path"]) as source:
                for _, br, bc, *candidates in (b for b in blocks if b[0] == tile):
                    if time.monotonic() - started > max_seconds:
                        raise RuntimeError("Native footprint time bound exceeded")
                    window = rasterio.windows.Window(bc * bw, br * bh, bw, bh)
                    raw = source.read(1, window=window)
                    if not np.array_equal(
                        source.read_masks(1, window=window) != 0, raw != 0
                    ):
                        raise ValueError(
                            "Source mask semantics differ from binary zero/nodata"
                        )
                    values, _ = positive_pixel_metrics(
                        raw,
                        source.transform,
                        br * bh,
                        bc * bw,
                        candidates,
                        ordered,
                        projected,
                        resolution=resolution,
                    )
                    for i, (count, area) in values.items():
                        counts[i] += count
                        areas[i] += area
                    processed[candidates] += 1
                    completed += 1
                    if progress and (completed % 512 == 0 or completed == len(blocks)):
                        progress(
                            {
                                "completed_blocks": completed,
                                "expected_blocks": len(blocks),
                                "elapsed_seconds": time.monotonic() - started,
                            }
                        )
    if not np.array_equal(processed, expected) or _digest(path) != checksum:
        raise ValueError("Source bytes or processing completion changed")
    if (
        not np.all(np.isfinite(areas))
        or np.any(areas < 0)
        or np.any(areas > shapely.area(projected) * (1 + 1e-8) + 0.001)
    ):
        raise ValueError("Invalid native positive-footprint bounds")
    has_source = expected > 0
    n = len(ordered)
    if _digest(Path(__file__)) != code_hash:
        raise ValueError("Native footprint source code changed during processing")
    table = pa.table(
        {
            "H3_INDEX": ordered,
            "H3_RESOLUTION": [resolution] * n,
            PREFIX + "POSITIVE_PIXEL_CENTER_COUNT": pa.array(counts, mask=~has_source),
            PREFIX + "POSITIVE_FOOTPRINT_OVERLAP_M2": pa.array(areas, mask=~has_source),
            PREFIX + "PROCESSED_SOURCE_BLOCK_COUNT": processed,
            PREFIX + "EXPECTED_SOURCE_BLOCK_COUNT": expected,
            PREFIX + "ALL_AVAILABLE_SOURCE_BLOCKS_COMPLETE": (processed == expected)
            & has_source,
            PREFIX + "SOURCE_TILE_RECTANGLE_STATUS": status,
            PREFIX + "NEGATIVE_OBSERVATION_STATUS": [
                "unavailable_background_nodata_not_absence"
            ]
            * n,
            PREFIX + "SURVEY_COVERAGE_STATUS": ["unavailable_positive_only_model"] * n,
            PREFIX + "SOURCE_COMPOSITE_START_YEAR": [composite_start_year] * n,
            PREFIX + "SOURCE_COMPOSITE_END_YEAR": [composite_end_year] * n,
            PREFIX + "SOURCE_TEMPORAL_PRECISION_CLASS": ["multi_year_composite"] * n,
            PREFIX + "OBSERVED_VS_MODELED": ["modeled"] * n,
            PREFIX + "METHOD_VERSION": [METHOD] * n,
            PREFIX + "SOURCE_CODE_VERSION": [code_hash] * n,
        }
    )
    report = {
        "rows": n,
        "resolution": resolution,
        "source_sha256": checksum,
        "source_path": str(path),
        "code_sha256": code_hash,
        "method": METHOD,
        "composite_start_year": composite_start_year,
        "composite_end_year": composite_end_year,
        "completed_blocks": completed,
        "source_rectangle_counts": dict(Counter(status)),
        "elapsed_seconds": time.monotonic() - started,
        "source_completeness": "partial",
    }
    context = {
        "source_context": {checksum: report},
        "temporal_support": {"precision": "multi_year_composite"},
        "fields": {
            name: {
                str(resolution): {
                    "resolution": resolution,
                    "unit": "m2"
                    if name.endswith("OVERLAP_M2")
                    else "year"
                    if name.endswith("YEAR")
                    else "boolean"
                    if name.endswith("COMPLETE")
                    else "count"
                    if name.endswith("COUNT")
                    else "category",
                    "support": "full native H3 cell; no water clip",
                    "temporal_support": "source composite",
                    "modeling_eligibility": "not_assigned_requires_downstream_review",
                }
            }
            for name in table.column_names
            if name not in {"H3_INDEX", "H3_RESOLUTION"}
        },
        "limits": {
            "source_completeness": "partial",
            "physical_full_catalog_qualified": False,
            "survey_coverage": "unavailable",
            "negative_observations": "unavailable",
            "source_doi": "10.5281/zenodo.18612240",
            "source_license": "CC BY 4.0",
        },
    }
    return NativeFootprintResult(
        table.replace_schema_metadata(
            {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
        ),
        report,
    )


def combine_native_composites(tables: Sequence[pa.Table]) -> pa.Table:
    """Retain explicit source intervals and contexts on matching native H3 support."""
    if not tables:
        raise ValueError("Supply at least one native composite table")
    periods: list[pa.Table] = []
    contexts: dict[str, Any] = {}
    support: dict[int, set[str]] = {}
    fields: dict[str, Any] = {}
    for table in tables:
        validate_table(table, dynamic=False)
        years = []
        for suffix in ("START_YEAR", "END_YEAR"):
            column = PREFIX + "SOURCE_COMPOSITE_" + suffix
            if column not in table.column_names or table[column].null_count:
                raise ValueError("Explicit non-null composite years are required")
            values = pc.unique(table[column]).to_pylist()
            if len(values) != 1 or type(values[0]) is not int:
                raise ValueError(
                    "Each input must describe exactly one composite period"
                )
            years.append(values[0])
        start, end = years
        if not 1 <= start <= end < 9999:
            raise ValueError("Composite years must be ordered calendar years")
        context = json.loads((table.schema.metadata or {}).get(METADATA_KEY, b"{}"))
        for resolution in pc.unique(table["H3_RESOLUTION"]).to_pylist():
            native = table.filter(pc.equal(table["H3_RESOLUTION"], resolution))
            keys = set(native["H3_INDEX"].to_pylist())
            if resolution in support and support[resolution] != keys:
                raise ValueError("Native support differs between composite periods")
            support[resolution] = keys
            identity = f"{start}-{end}:r{resolution}"
            if identity in contexts:
                raise ValueError("Duplicate native composite period/resolution")
            contexts[identity] = context
            for name, definition in context.get("fields", {}).items():
                fields.setdefault(name, {}).update(
                    {str(resolution): definition.get(str(resolution), definition)}
                )
        for column in ("date", "source_period_start", "source_period_end_exclusive"):
            if column in table.column_names:
                raise ValueError(f"Composite interval column already exists: {column}")
            value = (
                date(end + 1, 1, 1)
                if column.endswith("end_exclusive")
                else date(start, 1, 1)
            )
            table = table.append_column(
                column, pa.array([value] * table.num_rows, type=pa.date32())
            )
        periods.append(table)
    joined = pa.concat_tables(periods, promote_options="permissive")
    for column in ("source_period_start", "source_period_end_exclusive"):
        fields[column] = {
            str(resolution): {
                "unit": "date",
                "support": "source composite interval",
                "modeling_eligibility": "temporal_qualification_not_predictor",
            }
            for resolution in support
        }
    context = {
        "fields": fields,
        "composite_contexts": contexts,
        "temporal_support": {
            "precision": "multi_year_composite",
            "start_column": "source_period_start",
            "end_exclusive_column": "source_period_end_exclusive",
            "date_role": "source_interval_start_not_annual_or_daily_observation",
        },
        "availability_known": False,
        "limits": {
            "source_completeness": "partial",
            "physical_full_catalog_qualified": False,
            "negative_observations": "unavailable",
            "survey_coverage": "unavailable",
            "model_readiness_established": False,
            "operational_historical_replay_established": False,
            "native_time_support": "Source composites only; no interpolation or daily expansion",
        },
    }
    return validate_table(
        joined.replace_schema_metadata(
            {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
        ),
        dynamic=True,
    )
