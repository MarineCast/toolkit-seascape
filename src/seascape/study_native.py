"""Exact native receipts and bounded non-reporting probes; no regional qualification.

Real pilots require separate support evidence. Neither API acquires sources or publishes.
Budgets are preflight/cooperative checks, not an OS hard allocation guarantee.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import resource
import shutil
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
from pyproj import CRS, Geod, Transformer
from shapely.geometry import Polygon, mapping, shape

from seascape._study_contract import canonical_bytes, unique_object
from seascape.core.code_identity import package_code_identity
from seascape.core.geo.h3 import cell_to_polygon
from seascape.study import StudyConfig, StudyConfigError
from seascape.study_routes import PinnedInput, route_bathymetry
from seascape.study_support import VerifiedStudySupport, _read_pinned

SCOPES = {"native_source_probe", "real_source_pilot"}
CAPABILITIES = ["bathymetry_r6", "bathymetry_native_r8"]


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise StudyConfigError(f"{label} requires exactly {sorted(keys)}.")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudyConfigError(f"{label} requires nonempty text.")
    return value


def _digest(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise StudyConfigError("Expected lowercase raw SHA256.")
    return value


@dataclass(frozen=True)
class NativeArtifact:
    role: str
    relative_path: str
    raw_sha256: str
    byte_size: int
    encoding: str

    @classmethod
    def parse(cls, value: Any) -> NativeArtifact:
        record = _object(
            value,
            {"role", "relative_path", "raw_sha256", "byte_size", "encoding"},
            "artifact",
        )
        if type(record["byte_size"]) is not int or record["byte_size"] <= 0:
            raise StudyConfigError("Artifact byte_size must be positive.")
        return cls(
            _text(record["role"], "role"),
            _text(record["relative_path"], "path"),
            _digest(record["raw_sha256"]),
            record["byte_size"],
            _text(record["encoding"], "encoding"),
        )

    def capture(self, base: Path, data_root: Path, limit: int) -> bytes:
        raw = _read_pinned(
            base,
            data_root,
            self.relative_path,
            self.raw_sha256,
            min(limit, self.byte_size),
        )
        if len(raw) != self.byte_size:
            raise StudyConfigError("Captured artifact byte_size mismatch.")
        return raw


@dataclass(frozen=True)
class NativeBudget:
    max_input_bytes_each: int
    max_total_staging_bytes: int
    max_decoded_pixels: int
    max_rows: int
    max_h3_candidates: int
    memory_stop_bytes: int
    elapsed_stop_seconds: int

    @classmethod
    def parse(cls, value: Any) -> NativeBudget:
        names = set(cls.__dataclass_fields__)
        record = _object(
            value, names | {"network_bytes", "workers"}, "execution_budget"
        )
        if (
            type(record["network_bytes"]) is not int
            or record["network_bytes"] != 0
            or type(record["workers"]) is not int
            or record["workers"] != 1
        ):
            raise StudyConfigError("Native pilot requires zero network and one worker.")
        if any(type(record[n]) is not int or record[n] <= 0 for n in names):
            raise StudyConfigError("All resource limits must be positive integers.")
        if (
            record["max_input_bytes_each"] > 16 * 1024**2
            or record["max_total_staging_bytes"] > 128 * 1024**2
            or record["max_decoded_pixels"] > 1_000_000
            or record["max_rows"] > 100_000
            or record["max_h3_candidates"] > 2000
            or record["elapsed_stop_seconds"] > 900
        ):
            raise StudyConfigError("Receipt exceeds bounded pilot limits.")
        return cls(**{n: record[n] for n in names})


@dataclass(frozen=True)
class NativeReceipt:
    scope: str
    source: NativeArtifact
    evidence: tuple[NativeArtifact, ...]
    source_identity: dict[str, Any]
    measured_header: dict[str, Any]
    interpretation: dict[str, Any]
    probe_cells: tuple[str, ...]
    budget: NativeBudget
    qualification: dict[str, Any] | None

    @classmethod
    def parse(cls, raw: bytes) -> NativeReceipt:
        value = json.loads(raw, object_pairs_hook=unique_object)
        record = _object(
            value,
            {
                "interface_version",
                "scope",
                "source",
                "evidence",
                "source_identity",
                "measured_header",
                "interpretation",
                "probe_cells",
                "execution_budget",
                "qualification",
            },
            "native receipt",
        )
        if (
            type(record["interface_version"]) is not int
            or record["interface_version"] != 1
            or record["scope"] not in SCOPES
        ):
            raise StudyConfigError("Unknown native receipt version/scope.")
        source = NativeArtifact.parse(record["source"])
        if source.role != "native_elevation" or source.encoding != "GeoTIFF":
            raise StudyConfigError("First pilot accepts native_elevation GeoTIFF only.")
        if not isinstance(record["evidence"], list) or not record["evidence"]:
            raise StudyConfigError(
                "Pinned source interpretation/license evidence required."
            )
        evidence = tuple(NativeArtifact.parse(v) for v in record["evidence"])
        identity = _object(
            record["source_identity"],
            {
                "provider_asset_id",
                "evidence_type",
                "archive_artifact",
                "member_name",
                "version",
                "observation_period",
                "date_precision",
                "retrieved_at",
                "as_of",
                "license_id",
                "license_evidence_sha256",
                "interpretation_evidence_sha256",
            },
            "source_identity",
        )
        if identity["evidence_type"] not in {
            "synthetic_software_acceptance",
            "compiled_elevation_information_product",
        }:
            raise StudyConfigError(
                "First native interface requires an explicit supported evidence type."
            )
        for name in (
            "provider_asset_id",
            "version",
            "license_id",
            "as_of",
        ):
            _text(identity[name], name)
        for name in ("retrieved_at", "as_of"):
            value = identity[name]
            if name == "retrieved_at" and value is None:
                continue  # Retained cache acquisition time can honestly be unknown.
            try:
                stamp = datetime.fromisoformat(_text(value, name))
                if stamp.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError as exc:
                raise StudyConfigError(
                    "Retrieval/as-of must be timezone-aware; unknown retrieval stays null."
                ) from exc
        if identity["date_precision"] not in {
            "unknown",
            "year",
            "month",
            "day",
            "range",
        }:
            raise StudyConfigError("Unsupported observation date precision.")
        if (
            identity["date_precision"] == "unknown"
            and identity["observation_period"] is not None
        ):
            raise StudyConfigError("Unknown observation dates must remain null.")
        if identity["date_precision"] != "unknown":
            _text(identity["observation_period"], "observation_period")
        period = identity["observation_period"]
        precision = identity["date_precision"]
        formats = {
            "year": r"[0-9]{4}",
            "month": r"[0-9]{4}-[0-9]{2}",
            "day": r"[0-9]{4}-[0-9]{2}-[0-9]{2}",
        }
        if precision in formats and re.fullmatch(formats[precision], period) is None:
            raise StudyConfigError(
                "Observation dates must retain declared precision; no fabricated day."
            )
        if precision == "range" and (not isinstance(period, str) or "/" not in period):
            raise StudyConfigError(
                "Observation range requires explicit source-relative endpoints."
            )
        _text(identity["member_name"], "member_name")
        if identity["archive_artifact"] is not None:
            archive = NativeArtifact.parse(identity["archive_artifact"])
            if archive not in evidence:
                raise StudyConfigError(
                    "Archive identity must be an exact captured evidence artifact."
                )
        # A missing retained archive remains explicitly null; the member bytes still stay pinned.
        hashes = {a.raw_sha256 for a in evidence}
        if any(
            _digest(identity[n]) not in hashes
            for n in ("license_evidence_sha256", "interpretation_evidence_sha256")
        ):
            raise StudyConfigError(
                "Source interpretation/license evidence is not bound."
            )
        header = _object(
            record["measured_header"],
            {
                "band",
                "crs_wkt",
                "authority",
                "axis_order",
                "affine",
                "width",
                "height",
                "dtype",
                "pixel_interpretation",
                "scale",
                "offset",
                "nodata",
                "validity_mask_policy",
                "band_units",
            },
            "measured_header",
        )
        if (
            header["axis_order"] != "longitude_latitude"
            or header["validity_mask_policy"] != "rasterio_mask_and_finite"
        ):
            raise StudyConfigError("Unsupported axis/validity interpretation.")
        if any(
            type(header[n]) is not int or header[n] <= 0
            for n in ("band", "width", "height")
        ) or any(
            type(header[n]) not in (int, float) or not math.isfinite(header[n])
            for n in ("scale", "offset")
        ):
            raise StudyConfigError(
                "Native header dimensions/scaling must have finite numeric types."
            )
        interpretation = _object(
            record["interpretation"],
            {
                "units",
                "raw_sign",
                "output_sign",
                "vertical_reference",
                "vertical_reference_status",
                "transformation",
            },
            "interpretation",
        )
        if (
            interpretation["units"] != "m"
            or interpretation["raw_sign"] != "negative_elevation"
            or interpretation["output_sign"] != "positive_down"
            or interpretation["transformation"] != "none"
        ):
            raise StudyConfigError(
                "First pilot requires metre negative-elevation inputs without conversion."
            )
        _text(interpretation["vertical_reference"], "vertical_reference")
        if interpretation["vertical_reference_status"] not in {
            "documented_source_relative",
            "unknown",
        }:
            raise StudyConfigError("Invalid vertical reference status.")
        cells = record["probe_cells"]
        if (
            not isinstance(cells, list)
            or not cells
            or len(set(cells)) != len(cells)
            or any(
                not isinstance(c, str)
                or not h3.is_valid_cell(c)
                or h3.get_resolution(c) not in (6, 8)
                for c in cells
            )
        ):
            raise StudyConfigError(
                "Explicit unique R6/R8 probe cells required; no implicit enumeration."
            )
        budget = NativeBudget.parse(record["execution_budget"])
        if len(cells) > budget.max_h3_candidates:
            raise StudyConfigError("Explicit cell limit exceeded.")
        qualification = record["qualification"]
        if record["scope"] == "native_source_probe":
            if qualification is not None:
                raise StudyConfigError(
                    "Non-reporting probe cannot claim shared support qualification."
                )
        else:
            qualification = _object(
                qualification,
                {
                    "artifact",
                    "method",
                    "version",
                    "producer",
                    "checked_at",
                    "status",
                    "bindings",
                    "evidence",
                },
                "qualification",
            )
            if (
                qualification["status"] != "source_relative_checked"
                or qualification["producer"] != "bathymetry"
            ):
                raise StudyConfigError(
                    "Real pilot requires checked bathymetry qualification."
                )
            for n in ("method", "version", "checked_at"):
                _text(qualification[n], n)
            NativeArtifact.parse(qualification["artifact"])
            if interpretation["vertical_reference_status"] == "unknown":
                raise StudyConfigError(
                    "Unknown vertical datum is unqualified for a real-source pilot."
                )
        return cls(
            record["scope"],
            source,
            evidence,
            identity,
            header,
            interpretation,
            tuple(cells),
            budget,
            qualification,
        )


class NativeMonitor:
    def __init__(self, budget: NativeBudget):
        self.budget = budget
        self.start = time.monotonic()
        self.peak_rss_bytes = 0

    def check(self) -> None:
        # macOS ru_maxrss is bytes; Linux is KiB. This toolkit supports both.
        import sys

        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            rss *= 1024
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
        if (
            rss > self.budget.memory_stop_bytes
            or time.monotonic() - self.start > self.budget.elapsed_stop_seconds
        ):
            raise StudyConfigError("Cooperative native RSS/time stop reached.")

    def receipt(self) -> dict[str, Any]:
        return {
            "elapsed_seconds": time.monotonic() - self.start,
            "peak_rss_bytes": self.peak_rss_bytes,
            "enforcement": "preflight_and_cooperative_checks_not_OS_hard_bound",
            "network_bytes": 0,
            "workers": 1,
        }


def measured_native_header(raster: Any) -> dict[str, Any]:
    return {
        "band": 1,
        "crs_wkt": raster.crs.to_wkt() if raster.crs else None,
        "authority": raster.crs.to_string() if raster.crs else None,
        "axis_order": "longitude_latitude",
        "affine": list(raster.transform),
        "width": raster.width,
        "height": raster.height,
        "dtype": raster.dtypes[0],
        "pixel_interpretation": raster.tags().get("AREA_OR_POINT", "Area"),
        "scale": raster.scales[0],
        "offset": raster.offsets[0],
        "nodata": raster.nodata,
        "validity_mask_policy": "rasterio_mask_and_finite",
        "band_units": raster.units[0],
    }


def inspect_native_source(
    raw: bytes, receipt: NativeReceipt, monitor: NativeMonitor
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Measure native full-cell pixel coverage without shared reporting claims."""
    with rasterio.io.MemoryFile(raw) as memory, memory.open() as raster:
        if (
            raster.count != 1
            or measured_native_header(raster) != receipt.measured_header
        ):
            raise StudyConfigError("Captured native header differs from receipt.")
        t = raster.transform
        if (
            raster.crs is None
            or raster.crs.to_epsg() != 4326
            or raster.scales != (1.0,)
            or raster.offsets != (0.0,)
            or t.b != 0
            or t.d != 0
            or t.a <= 0
            or t.e >= 0
            or not math.isclose(t.a, 1 / 240, abs_tol=1e-12)
            or not math.isclose(-t.e, 1 / 240, abs_tol=1e-12)
        ):
            raise StudyConfigError(
                "First native pilot requires identity-scaled north-up WGS84 15-arc-second grid."
            )
        if raster.width * raster.height > receipt.budget.max_decoded_pixels:
            raise StudyConfigError("Decoded pixel budget exceeded before decode.")
        footprint = Polygon(
            [
                t * p
                for p in [
                    (0, 0),
                    (raster.width, 0),
                    (raster.width, raster.height),
                    (0, raster.height),
                ]
            ]
        )
        cells = set(receipt.probe_cells)
        counts: dict[str, Counter[str]] = {c: Counter() for c in cells}
        # Enumerate each full H3 cell's grid-aligned bounding window, including missing outside pixels.
        # Duplicate center visits at shared bounds do not count twice because H3 assignment is exact.
        visited = 0
        for cell in sorted(cells):
            monitor.check()
            polygon = cell_to_polygon(cell)
            west, south, east, north = polygon.bounds
            inv = ~t
            col0, row0 = inv * (west, north)
            col1, row1 = inv * (east, south)
            r0, r1 = math.floor(row0) - 1, math.ceil(row1) + 1
            c0, c1 = math.floor(col0) - 1, math.ceil(col1) + 1
            visited += (r1 - r0) * (c1 - c0)
            if visited > receipt.budget.max_decoded_pixels:
                raise StudyConfigError("Full-cell coverage pixel-work budget exceeded.")
            for row in range(r0, r1):
                monitor.check()
                values = None
                if 0 <= row < raster.height:
                    values = raster.read(
                        1,
                        window=rasterio.windows.Window(0, row, raster.width, 1),
                        masked=True,
                    )[0]
                for col in range(c0, c1):
                    lon, lat = t * (col + 0.5, row + 0.5)
                    if h3.latlng_to_cell(lat, lon, h3.get_resolution(cell)) != cell:
                        continue
                    bucket = counts[cell]
                    bucket["EXPECTED_PIXELS"] += 1
                    if values is None or col < 0 or col >= raster.width:
                        bucket["OUTSIDE_CROP_PIXELS"] += 1
                    elif np.ma.is_masked(values[col]) or not np.isfinite(values[col]):
                        bucket["NODATA_PIXELS"] += 1
                    elif values[col] < 0:
                        bucket["VALID_MARINE_PIXELS"] += 1
                    else:
                        bucket["LAND_PIXELS"] += 1
        records = []
        for c, bucket in counts.items():
            record: dict[str, Any] = {
                n: bucket[n]
                for n in (
                    "EXPECTED_PIXELS",
                    "VALID_MARINE_PIXELS",
                    "LAND_PIXELS",
                    "NODATA_PIXELS",
                    "OUTSIDE_CROP_PIXELS",
                )
            }
            expected = record["EXPECTED_PIXELS"]
            missing = record["NODATA_PIXELS"] + record["OUTSIDE_CROP_PIXELS"]
            record.update(
                H3_INDEX=c,
                H3_RESOLUTION=h3.get_resolution(c),
                SUPPORT_ROLE="native_source_probe",
                VALID_MARINE_FRACTION=record["VALID_MARINE_PIXELS"] / expected
                if expected
                else None,
                MISSING_PIXEL_FRACTION=missing / expected if expected else None,
                COVERAGE_STATUS="no_native_pixel_centers"
                if not expected
                else "partial_native_support"
                if missing
                else "full_native_grid_support",
                MARINE_SAMPLE_STATUS="valid_native_samples"
                if record["VALID_MARINE_PIXELS"]
                else "no_valid_native_marine_samples",
                FULL_CELL_WITHIN_NATIVE_EXTENT=footprint.covers(cell_to_polygon(c)),
            )
            records.append(record)
        extent = list(footprint.bounds)
        projection = CRS.from_epsg(32610)
        area = projection.area_of_use
        transformer = Transformer.from_crs(4326, projection, always_xy=True)
        geod = Geod(ellps="WGS84")
        diagnostic = []
        corners = list(footprint.exterior.coords)[:-1]
        for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
            x, y = transformer.transform(*a)
            xx, yy = transformer.transform(*b)
            distance = geod.inv(*a, *b)[2]
            projected = math.hypot(xx - x, yy - y)
            diagnostic.append(
                {
                    "geodesic_m": distance,
                    "projected_m": projected,
                    "relative_difference": projected / distance - 1,
                }
            )
        return pd.DataFrame(records), {
            "footprint": mapping(footprint),
            "footprint_derivation": "all_four_affine_pixel_outer_corners",
            "sampling_grain": "native_pixel_centers_in_full_H3_cells",
            "coverage_pixel_work": visited,
            "projection": {
                "crs": "EPSG:32610",
                "actual_used_extent_wgs84": extent,
                "outside_crs_area_of_use": not (
                    extent[0] >= area.west
                    and extent[2] <= area.east
                    and extent[1] >= area.south
                    and extent[3] <= area.north
                ),
                "distance_diagnostic": diagnostic,
                "regional_metric_accuracy_claim": False,
            },
            "isobath": {
                "claim": "nearest_contour_observed_within_pinned_source_crop",
                "global_nearest_claim": False,
            },
            "native_stencil_policy": "probe_measures_pixels_only_no_slope_stencil_qualification",
            "vertical_reference": receipt.interpretation["vertical_reference"],
        }


def verify_graph_dependency_closure(
    edges: pd.DataFrame,
    neighborhoods: pd.DataFrame,
    focal_cells: tuple[str, ...],
    compute_cells: tuple[str, ...],
    hops: int,
    *,
    summary_hops: int = 0,
    neighbor_fit_hops: int = 0,
    openness_hops: int = 0,
) -> dict[str, Any]:
    """Prove neighborhood/depth closure against pinned passable edges; not mask qualification."""
    required = max(hops, summary_hops + neighbor_fit_hops, openness_hops)
    if type(required) is not int or required < 1:
        raise StudyConfigError("Invalid graph dependency hop bound.")
    adjacency: dict[str, set[str]] = {}
    needed = {"SOURCE_H3_INDEX", "TARGET_H3_INDEX", "EDGE_IS_WATER_PASSABLE"}
    if not needed.issubset(edges) or not {
        "SOURCE_H3_INDEX",
        "TARGET_H3_INDEX",
        "MINIMUM_HOP_COUNT",
    }.issubset(neighborhoods):
        raise StudyConfigError("Graph dependency evidence columns missing.")
    if (
        edges.duplicated(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).any()
        or neighborhoods.duplicated(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).any()
    ):
        raise StudyConfigError("Duplicate graph dependency records.")
    for a, b, passable in edges[
        ["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "EDGE_IS_WATER_PASSABLE"]
    ].itertuples(index=False, name=None):
        if type(passable) not in (bool, np.bool_):
            raise StudyConfigError("Passability must be boolean.")
        if passable:
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
    if any(
        type(k) not in (int, np.int64, np.int32) or k < 0
        for k in neighborhoods.MINIMUM_HOP_COUNT
    ):
        raise StudyConfigError(
            "Minimum hop counts must be nonnegative integers; no truncation."
        )
    declared = {
        (a, b): int(k)
        for a, b, k in neighborhoods[
            ["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "MINIMUM_HOP_COUNT"]
        ].itertuples(index=False, name=None)
    }
    closure: set[str] = set()
    for focal in focal_cells:
        distance = {focal: 0}
        queue = deque([focal])
        while queue:
            node = queue.popleft()
            if distance[node] == required:
                continue
            for neighbor in adjacency.get(node, set()):
                if neighbor not in distance:
                    distance[neighbor] = distance[node] + 1
                    queue.append(neighbor)
        for node, k in distance.items():
            if node not in compute_cells or declared.get((focal, node)) != k:
                raise StudyConfigError("Incomplete graph/depth dependency closure.")
        declared_for_focal = {
            b: k for (a, b), k in declared.items() if a == focal and k <= required
        }
        if declared_for_focal != distance:
            raise StudyConfigError(
                "Neighborhoods do not match pinned passable-edge closure."
            )
        closure.update(distance)
    return {
        "required_depth_dependency_graph_hops": required,
        "depth_dependency_cells": sorted(closure),
        "complete_relative_to_pinned_passable_edges": True,
        "canonical_edge_completeness": "requires_pinned_qualification_evidence",
    }


def _receipt_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise StudyConfigError("Native receipt/config exceeds 1MiB before parse.")
    return raw


def run_native_source_probe(
    manifest_path: str | Path, data_root: str | Path, workspace: str | Path
) -> dict[str, Any]:
    """Inspect one cached source with no approved mask/reporting claims and no acquisition."""
    path = Path(manifest_path).resolve()
    raw_receipt = _receipt_bytes(path)
    if len(raw_receipt) > 1024**2:
        raise StudyConfigError("Native receipt exceeds 1MiB.")
    receipt = NativeReceipt.parse(raw_receipt)
    if receipt.scope != "native_source_probe":
        raise StudyConfigError("This API requires native_source_probe scope.")
    code_identity = package_code_identity(Path(workspace))
    monitor = NativeMonitor(receipt.budget)
    monitor.check()
    artifacts = (receipt.source, *receipt.evidence)
    total = len(raw_receipt) + sum(a.byte_size for a in artifacts)
    if total * 2 + 1024**2 > receipt.budget.max_total_staging_bytes:
        raise StudyConfigError("Total retained/input/output staging budget exceeded.")
    destination = Path(workspace).resolve()
    ancestor = destination
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < receipt.budget.max_total_staging_bytes:
        raise StudyConfigError("Insufficient current free space for reserved staging.")
    captured = [
        a.capture(
            path.parent, Path(data_root).resolve(), receipt.budget.max_input_bytes_each
        )
        for a in artifacts
    ]
    monitor.check()
    coverage, measured = inspect_native_source(captured[0], receipt, monitor)
    monitor.check()
    if package_code_identity(destination) != code_identity:
        raise StudyConfigError("Package code changed during native probe.")
    run = destination / "native-source-probes" / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    # No source-relative processing failure is hidden or promoted as a release.
    try:
        (run / "input-manifest.json").write_bytes(raw_receipt)
        for i, (artifact, data) in enumerate(zip(artifacts, captured, strict=True)):
            (run / f"input-{i}.bin").write_bytes(data)
        coverage.to_parquet(run / "native-coverage.parquet", index=False)
        output = {
            "scope": "native_source_probe",
            "status": "native_evidence_measured",
            "shared_reporting_qualified": False,
            "production_ready": False,
            "artifact_release_passed": False,
            "regional_release_eligible": False,
            "source_raw_sha256": receipt.source.raw_sha256,
            "source_identity": receipt.source_identity,
            "measured": measured,
            "resources": monitor.receipt(),
            "code_identity": code_identity,
            "complete_native_support": bool(
                (
                    (coverage.COVERAGE_STATUS == "full_native_grid_support")
                    & coverage.FULL_CELL_WITHIN_NATIVE_EXTENT
                ).all()
            ),
            "scientific_accuracy_qualified": False,
            "generation": str(run),
        }
        monitor.check()
        output["inventory_raw_sha256"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in run.iterdir()
            if p.is_file()
        }
        (run / "probe-receipt.json").write_bytes(canonical_bytes(output))
        actual = sum(p.stat().st_size for p in run.iterdir() if p.is_file())
        if actual > receipt.budget.max_total_staging_bytes:
            raise StudyConfigError("Actual retained staging exceeds budget.")
        return output
    except Exception as exc:
        (run / "failure-receipt.json").write_bytes(
            canonical_bytes(
                {
                    "status": "failed",
                    "error": str(exc),
                    "resources": monitor.receipt(),
                    "production_ready": False,
                }
            )
        )
        raise


def _bounded_parquet(raw: bytes, limit: int) -> pd.DataFrame:
    parquet = pq.ParquetFile(BytesIO(raw))
    if parquet.metadata.num_rows > limit:
        raise StudyConfigError("Parquet row budget exceeded before decode.")
    return parquet.read().to_pandas()


def _support_bindings(
    study: StudyConfig, support: VerifiedStudySupport, settings: dict[str, Any]
) -> dict[str, Any]:
    identity = json.loads(support.identity_json)
    return {
        "study_config_sha256": study.config_sha256,
        "mask_raw_sha256": support.mask_sha256,
        "mask_revision": support.mask_revision,
        "mask_hash_policy": "sha256_exact_file_bytes",
        "reporting_r6_sha256": identity["reporting_membership"]["sha256"],
        "native_reporting_r8_sha256": identity["native_reporting_r8"]["sha256"],
        "compute_membership_sha256": {
            str(m["resolution"]): m["sha256"] for m in identity["compute_memberships"]
        },
        "selected_capabilities": CAPABILITIES,
        "method_settings_sha256": hashlib.sha256(canonical_bytes(settings)).hexdigest(),
    }


def run_real_source_pilot(
    study: StudyConfig,
    support: VerifiedStudySupport,
    manifest_path: str | Path,
    workspace: str | Path,
    configs: dict[int, Any],
) -> dict[str, Any]:
    """Bounded, retained bathymetry pilot; never a regional release or automatic acquisition.

    Qualification is executable byte/header/coverage/graph evidence, not a permission gate.
    External resource coordination remains necessary because cooperative checks cannot prevent
    a transient allocation inside the existing scientific functions.
    """
    from seascape.core.geo.crs import require_metric_crs
    from seascape.study import load_study_config
    from seascape.study_support import MembershipArtifact

    path = Path(manifest_path).resolve()
    if (
        path.parent != study.source.parent
        or study.payload["storage"]["data_root"] != "../Data"
    ):
        raise StudyConfigError("Pilot receipt must use explicit config/../Data layout.")
    raw_receipt = _receipt_bytes(path)
    if len(raw_receipt) > 1024**2:
        raise StudyConfigError("Native receipt exceeds 1MiB.")
    receipt = NativeReceipt.parse(raw_receipt)
    if (
        receipt.scope != "real_source_pilot"
        or support.producer != "bathymetry"
        or support.config_sha256 != study.config_sha256
    ):
        raise StudyConfigError("Real pilot scope/study/producer mismatch.")
    if set(configs) != {6, 8}:
        raise StudyConfigError(
            "Pilot requires exactly R6 and native R8 bathymetry settings."
        )
    names = (
        "bathymetry_sign",
        "depth_quantiles",
        "local_depth_anomaly_neighborhood_rings",
        "isobath_levels_m",
        "isobath_distance_projected_crs",
    )
    settings = {name: getattr(configs[6], name) for name in names}
    if any(
        {name: getattr(configs[r], name) for name in names} != settings
        or configs[r].h3_resolution != r
        for r in (6, 8)
    ):
        raise StudyConfigError("Pilot scientific settings/resolution mismatch.")
    if (
        settings["bathymetry_sign"] != "positive_down"
        or type(settings["local_depth_anomaly_neighborhood_rings"]) is not int
        or not 1 <= settings["local_depth_anomaly_neighborhood_rings"] <= 4
        or settings["isobath_distance_projected_crs"] != "EPSG:32610"
    ):
        raise StudyConfigError("Unsupported bounded bathymetry pilot method settings.")
    require_metric_crs(settings["isobath_distance_projected_crs"])
    for name in ("depth_quantiles", "isobath_levels_m"):
        values = settings[name]
        if (
            not isinstance(values, (list, tuple))
            or not values
            or len(values) > 32
            or len(set(values)) != len(values)
            or any(
                not math.isfinite(v)
                or v <= 0
                or (name == "depth_quantiles" and (v >= 1 or v == 0.5))
                for v in values
            )
        ):
            raise StudyConfigError("Invalid bounded pilot quantile/contour settings.")
    cells = tuple(sorted(set(support.compute_r6) | set(support.compute_r8)))
    if (
        set(receipt.probe_cells) != set(cells)
        or len(cells) > receipt.budget.max_h3_candidates
    ):
        raise StudyConfigError(
            "Receipt must cover the exact bounded compute-cell union."
        )
    code_identity = package_code_identity(Path(workspace))
    monitor = NativeMonitor(receipt.budget)
    monitor.check()
    q = receipt.qualification
    assert q is not None
    qspec = NativeArtifact.parse(q["artifact"])
    qraw = qspec.capture(
        path.parent, study.data_root, receipt.budget.max_input_bytes_each
    )
    qualified = _object(
        json.loads(qraw, object_pairs_hook=unique_object),
        {
            "bindings",
            "method_settings",
            "method_version",
            "mask",
            "coverage",
            "graphs",
            "checks",
            "evidence",
        },
        "qualification artifact",
    )
    bindings = _support_bindings(study, support, settings)
    if (
        q["bindings"] != bindings
        or qualified["bindings"] != bindings
        or canonical_bytes(qualified["method_settings"]) != canonical_bytes(settings)
    ):
        raise StudyConfigError(
            "Qualification config/mask/membership/method binding mismatch."
        )
    _text(qualified["method_version"], "method_version")
    mask = _object(
        qualified["mask"],
        {"artifact", "revision", "encoding", "source_qualification_artifact"},
        "mask qualification",
    )
    mask_artifact = NativeArtifact.parse(mask["artifact"])
    if (
        mask_artifact.raw_sha256 != support.mask_sha256
        or mask["revision"] != support.mask_revision
        or mask["encoding"] != "RFC7946_WGS84_Polygon_or_MultiPolygon_exact_UTF8_bytes"
    ):
        raise StudyConfigError("Mask encoding/revision/raw-byte binding mismatch.")
    mask_source = NativeArtifact.parse(mask["source_qualification_artifact"])
    coverage_spec = NativeArtifact.parse(qualified["coverage"])
    if not isinstance(qualified["graphs"], list) or len(qualified["graphs"]) != 2:
        raise StudyConfigError("Qualified R6/R8 graph records required.")
    graph_records = {}
    artifacts = [
        receipt.source,
        *receipt.evidence,
        qspec,
        mask_artifact,
        mask_source,
        coverage_spec,
    ]
    for graph in qualified["graphs"]:
        graph = _object(
            graph,
            {
                "resolution",
                "nodes",
                "edges",
                "neighborhoods",
                "passability_evidence",
                "maximum_hops",
            },
            "graph qualification",
        )
        resolution = graph["resolution"]
        if (
            type(resolution) is not int
            or resolution not in (6, 8)
            or resolution in graph_records
            or type(graph["maximum_hops"]) is not int
            or not settings["local_depth_anomaly_neighborhood_rings"]
            <= graph["maximum_hops"]
            <= 4
        ):
            raise StudyConfigError("Invalid graph resolution/hop qualification.")
        graph_records[resolution] = graph
        for name in ("nodes", "edges", "neighborhoods", "passability_evidence"):
            artifacts.append(NativeArtifact.parse(graph[name]))
    identity = json.loads(support.identity_json)
    membership_specs = [
        MembershipArtifact(**identity["reporting_membership"]),
        *[MembershipArtifact(**v) for v in identity["compute_memberships"]],
    ]
    for m in membership_specs:
        raw = _read_pinned(
            path.parent,
            study.data_root,
            m.relative_path,
            m.sha256,
            receipt.budget.max_input_bytes_each,
        )
        artifacts.append(
            NativeArtifact(
                "membership", m.relative_path, m.sha256, len(raw), "sorted_H3_LF"
            )
        )
    if (
        not isinstance(qualified["checks"], dict)
        or set(qualified["checks"])
        != {
            "mask_source_relative",
            "canonical_graph_edges_and_connectors",
            "source_interpretation",
        }
        or any(v != "source_relative_checked" for v in qualified["checks"].values())
    ):
        raise StudyConfigError(
            "Explicit source-relative qualification checks required."
        )
    if not isinstance(qualified["evidence"], list) or not isinstance(
        q["evidence"], list
    ):
        raise StudyConfigError(
            "Qualification evidence must be pinned artifact records."
        )
    artifacts.extend(
        NativeArtifact.parse(a) for a in qualified["evidence"] + q["evidence"]
    )
    # De-duplicate paths only when their exact identities agree.
    unique: dict[str, NativeArtifact] = {}
    for a in artifacts:
        if a.relative_path in unique and unique[a.relative_path] != a:
            raise StudyConfigError("Conflicting artifact identities at one path.")
        unique[a.relative_path] = a
    total = (
        len(raw_receipt)
        + len(_receipt_bytes(study.source))
        + sum(a.byte_size for a in unique.values())
    )
    if total * 2 + 4 * 1024**2 > receipt.budget.max_total_staging_bytes:
        raise StudyConfigError("Total pilot staging budget exceeded.")
    destination = Path(workspace).resolve()
    ancestor = destination
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < receipt.budget.max_total_staging_bytes:
        raise StudyConfigError("Insufficient current free space.")
    captured = {
        key: a.capture(
            path.parent, study.data_root, receipt.budget.max_input_bytes_each
        )
        for key, a in unique.items()
    }
    monitor.check()
    mask_value = json.loads(captured[mask_artifact.relative_path])
    geometry = shape(mask_value)
    if (
        geometry.geom_type not in ("Polygon", "MultiPolygon")
        or geometry.is_empty
        or not geometry.is_valid
    ):
        raise StudyConfigError("Qualified mask is not a valid nonempty polygon.")
    mask_evidence = json.loads(
        captured[mask_source.relative_path], object_pairs_hook=unique_object
    )
    if (
        mask_evidence.get("mask_raw_sha256") != support.mask_sha256
        or mask_evidence.get("status") != "source_relative_checked"
    ):
        raise StudyConfigError("Mask source qualification is not bound/checked.")
    coverage, measured = inspect_native_source(
        captured[receipt.source.relative_path], receipt, monitor
    )
    expected = _bounded_parquet(
        captured[coverage_spec.relative_path], receipt.budget.max_rows
    )
    if list(expected.columns) != list(coverage.columns) or not expected.sort_values(
        "H3_INDEX"
    ).reset_index(drop=True).equals(
        coverage.sort_values("H3_INDEX").reset_index(drop=True)
    ):
        raise StudyConfigError(
            "Pinned native coverage disagrees with independently measured pixels."
        )
    graph_results = {}
    for resolution, graph in graph_records.items():
        nodes = _bounded_parquet(
            captured[graph["nodes"]["relative_path"]], receipt.budget.max_rows
        )
        if (
            "H3_INDEX" not in nodes
            or nodes.H3_INDEX.duplicated().any()
            or not set(support.cells(resolution, role="compute")).issubset(
                nodes.H3_INDEX
            )
        ):
            raise StudyConfigError("Graph node evidence does not cover compute cells.")
        edge_frame = _bounded_parquet(
            captured[graph["edges"]["relative_path"]], receipt.budget.max_rows
        )
        neighbor_frame = _bounded_parquet(
            captured[graph["neighborhoods"]["relative_path"]], receipt.budget.max_rows
        )
        passability = json.loads(
            captured[graph["passability_evidence"]["relative_path"]],
            object_pairs_hook=unique_object,
        )
        if (
            passability.get("status") != "source_relative_checked"
            or passability.get("mask_raw_sha256") != support.mask_sha256
            or passability.get("edges_raw_sha256") != graph["edges"]["raw_sha256"]
            or passability.get("nodes_raw_sha256") != graph["nodes"]["raw_sha256"]
            or passability.get("canonical_edge_and_connector_completeness") is not True
        ):
            raise StudyConfigError(
                "Canonical edge/passability evidence binding missing."
            )
        graph_results[str(resolution)] = verify_graph_dependency_closure(
            edge_frame,
            neighbor_frame,
            support.cells(resolution, role="reporting"),
            support.cells(resolution, role="compute"),
            settings["local_depth_anomaly_neighborhood_rings"],
        )
    monitor.check()
    # All semantic and source evidence checks occur before creating any generation.
    if package_code_identity(destination) != code_identity:
        raise StudyConfigError("Package code changed during pilot preflight.")
    run = destination / ".seascape/real-source-pilots" / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    try:
        (run / "input-manifest.json").write_bytes(raw_receipt)
        (run / "code-identity.json").write_bytes(canonical_bytes(code_identity))
        base = run / "inputs/config"
        data = run / "inputs/Data"
        base.mkdir(parents=True)
        data.mkdir()
        study_raw = _receipt_bytes(study.source)
        if hashlib.sha256(study_raw).hexdigest() != study.raw_file_sha256:
            raise StudyConfigError("Study config changed during pilot preflight.")
        (base / "study.json").write_bytes(study_raw)
        for name, raw in captured.items():
            target = (base / name).resolve()
            if not target.is_relative_to(data):
                raise StudyConfigError("Retained artifact escapes Data.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        retained_study = load_study_config(base / "study.json", planning=True)
        # The immutable support object was verified before entry. Its exact mask/membership
        # bytes were recaptured above; do not enumerate a whole regional mask in a bounded pilot.
        retained_support = support
        coverage.to_parquet(run / "native-coverage.parquet", index=False)
        products = run / "products"
        products.mkdir()
        metadata = canonical_bytes(
            {
                "version": receipt.source_identity["version"],
                "observation_period": receipt.source_identity["observation_period"],
                "license": receipt.source_identity["license_id"],
                "evidence_type": receipt.source_identity["evidence_type"],
            }
        ).decode()
        results = {}
        for resolution in (6, 8):
            monitor.check()
            graph = graph_records[resolution]
            graph_meta = canonical_bytes(
                {
                    "version": qualified["method_version"],
                    "observation_period": "static derived support",
                    "license": "upstream mask/source terms",
                    "evidence_type": "source-relative checked graph",
                    "study_config_sha256": study.config_sha256,
                    "mask_sha256": support.mask_sha256,
                    "compute_membership_sha256": bindings["compute_membership_sha256"][
                        str(resolution)
                    ],
                    "maximum_graph_hops": graph["maximum_hops"],
                }
            ).decode()
            result = route_bathymetry(
                configs[resolution],
                retained_study,
                retained_support,
                raster=PinnedInput(
                    receipt.source.relative_path, receipt.source.raw_sha256, metadata
                ),
                neighborhoods=PinnedInput(
                    graph["neighborhoods"]["relative_path"],
                    graph["neighborhoods"]["raw_sha256"],
                    graph_meta,
                ),
                maximum_graph_hops=graph["maximum_hops"],
                max_input_bytes=receipt.budget.max_input_bytes_each,
                max_pixels_and_rows=receipt.budget.max_decoded_pixels,
            )
            monitor.check()
            result.write_reporting(products / f"bathymetry_r{resolution}.parquet")
            result.write_compute(products / f"compute_bathymetry_r{resolution}.parquet")
            # Counts are independently enumerated from row-window reads above.
            counts = (
                coverage[coverage.H3_RESOLUTION == resolution]
                .set_index("H3_INDEX")
                .VALID_MARINE_PIXELS
            )
            actual = (
                result.compute.set_index("H3_INDEX")
                .BATHYMETRY_PIXEL_COUNT.fillna(0)
                .astype(int)
            )
            if not actual.equals(
                counts.reindex(actual.index).astype(int).rename(actual.name)
            ):
                raise StudyConfigError(
                    "Independent native pixel counts disagree with routed output."
                )
            samples = result.reporting[result.reporting.BATHYMETRY.notna()]
            sample_checks = []
            if not samples.empty:
                cell = str(samples.iloc[0].H3_INDEX)
                independent = independent_native_statistics(
                    captured[receipt.source.relative_path],
                    cell,
                    tuple(settings["depth_quantiles"]),
                    monitor,
                )
                row = result.reporting.set_index("H3_INDEX").loc[cell]
                for field, expected_value in independent.items():
                    if not math.isclose(
                        float(row[field]), expected_value, rel_tol=1e-12, abs_tol=1e-12
                    ):
                        raise StudyConfigError(
                            "Independent native statistic/quantile check failed."
                        )
                    sample_checks.append(
                        {
                            "cell": cell,
                            "field": field,
                            "expected": expected_value,
                            "actual": float(row[field]),
                        }
                    )
            results[str(resolution)] = {
                "independent_sample_checks": sample_checks,
                "reporting_rows": len(result.reporting),
                "compute_rows": len(result.compute),
            }
        output = {
            "scope": "real_source_pilot",
            "code_identity": code_identity,
            "status": "software_contract_acceptance"
            if receipt.source_identity["evidence_type"]
            == "synthetic_software_acceptance"
            else "source_relative_pilot_checked",
            "source_identity": receipt.source_identity,
            "real_source_pilot_executed": receipt.source_identity["evidence_type"]
            != "synthetic_software_acceptance",
            "production_ready": False,
            "artifact_release_passed": False,
            "regional_release_eligible": False,
            "selected_capabilities": CAPABILITIES,
            "optional_terrain_selected": False,
            "global_nearest_claim": False,
            "scientific_accuracy_qualified": False,
            "bindings": bindings,
            "measured": measured,
            "graph_closure": graph_results,
            "products": results,
            "resources": monitor.receipt(),
            "generation": str(run),
        }
        monitor.check()
        output["inventory_raw_sha256"] = {
            str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in run.rglob("*")
            if p.is_file()
        }
        if package_code_identity(destination) != code_identity:
            raise StudyConfigError(
                "Package code changed during scientific pilot computation."
            )
        (run / "pilot-receipt.json").write_bytes(canonical_bytes(output))
        if (
            sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
            > receipt.budget.max_total_staging_bytes
        ):
            raise StudyConfigError("Actual retained staging exceeded budget.")
        return output
    except Exception as exc:
        (run / "failure-receipt.json").write_bytes(
            canonical_bytes(
                {
                    "status": "failed",
                    "error": str(exc),
                    "resources": monitor.receipt(),
                    "production_ready": False,
                }
            )
        )
        raise


def independent_native_statistics(
    raw: bytes, cell: str, quantiles: tuple[float, ...], monitor: NativeMonitor
) -> dict[str, float]:
    """Independent row-window sample reduction, without producer helpers or clipped mask."""
    values = []
    with rasterio.io.MemoryFile(raw) as memory, memory.open() as raster:
        polygon = cell_to_polygon(cell)
        west, south, east, north = polygon.bounds
        inverse = ~raster.transform
        left, top = inverse * (west, north)
        right, bottom = inverse * (east, south)
        for row in range(
            max(0, math.floor(top) - 1), min(raster.height, math.ceil(bottom) + 1)
        ):
            monitor.check()
            data = raster.read(
                1, window=rasterio.windows.Window(0, row, raster.width, 1), masked=True
            )[0]
            for col in range(
                max(0, math.floor(left) - 1), min(raster.width, math.ceil(right) + 1)
            ):
                value = data[col]
                if np.ma.is_masked(value) or not np.isfinite(value) or value >= 0:
                    continue
                lon, lat = raster.transform * (col + 0.5, row + 0.5)
                if h3.latlng_to_cell(lat, lon, h3.get_resolution(cell)) == cell:
                    values.append(-float(value))
    if not values:
        raise StudyConfigError("Independent sample cell has no native marine pixels.")
    array = np.asarray(values)
    result = {
        "BATHYMETRY": float(np.mean(array)),
        "BATHYMETRY_MEDIAN": float(np.median(array)),
        "BATHYMETRY_MIN": float(np.min(array)),
        "BATHYMETRY_MAX": float(np.max(array)),
        "BATHYMETRY_STD": float(np.std(array)),
        "BATHYMETRY_PIXEL_COUNT": float(len(array)),
    }
    result.update(
        {
            f"BATHYMETRY_Q{round(q * 100):02d}": float(np.quantile(array, q))
            for q in quantiles
        }
    )
    return result
