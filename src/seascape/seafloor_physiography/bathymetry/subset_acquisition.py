"""Bounded acquisition of the accepted GEBCO_2026 elevation subset only.

Retains ZIP, member, request and response evidence. No processing, publication,
credentials, implicit fallback, retry of submissions, deletion or cache mutation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import resource
import shutil
import stat
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import rasterio
import requests

from seascape._study_contract import canonical_bytes, unique_object
from seascape.core.code_identity import package_code_identity
from seascape.seafloor_physiography.depth import validate_native_metre_band_units

API = "https://download.gebco.net/api"
BBOX = (-131.0, 45.1, -120.2, 52.3)
WIDTH, HEIGHT = 2592, 1728


class SubsetAcquisitionError(ValueError):
    """Acquisition failed; retained evidence must not be promoted."""


class ProviderAgreementRequired(SubsetAcquisitionError):
    """An explicit provider account/agreement requirement needs user direction."""


@dataclass(frozen=True)
class SubsetBudget:
    transfer_bytes: int = 64 * 1024**2
    staging_bytes: int = 128 * 1024**2
    memory_bytes: int = 512 * 1024**2
    elapsed_seconds: int = 900

    def __post_init__(self) -> None:
        for name, ceiling in [
            ("transfer_bytes", 64 * 1024**2),
            ("staging_bytes", 128 * 1024**2),
            ("memory_bytes", 512 * 1024**2),
            ("elapsed_seconds", 900),
        ]:
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise SubsetAcquisitionError(f"{name} exceeds the accepted bound.")


class _Monitor:
    def __init__(self, budget: SubsetBudget):
        self.budget = budget
        self.start = time.monotonic()
        self.transferred = 0
        self.uploaded = 0
        self.peak = 0

    def check(self) -> None:
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * (
            1 if sys.platform == "darwin" else 1024
        )
        self.peak = max(self.peak, rss)
        if (
            rss > self.budget.memory_bytes
            or time.monotonic() - self.start >= self.budget.elapsed_seconds
        ):
            raise SubsetAcquisitionError(
                "Cooperative acquisition RSS/time stop reached."
            )

    def receipt(self) -> dict[str, Any]:
        return {
            "response_body_bytes": self.transferred,
            "request_body_bytes": self.uploaded,
            "total_body_bytes": self.transferred + self.uploaded,
            "peak_rss_bytes": self.peak,
            "elapsed_seconds": time.monotonic() - self.start,
            "workers": 1,
            "enforcement": "bounded response bodies and staging; cooperative RSS/time, not OS hard transient allocation bound",
        }


def _template(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise SubsetAcquisitionError("Request template exceeds 1MiB.")
    expected = {
        "id": "0",
        "email": None,
        "submission_date": "REPLACE_WITH_ACTUAL_UTC_AT_SUBMISSION",
        "processing_status": "new",
        "items": [
            {
                "id": 0,
                "grid_id": 1,
                "data_source_ids": [1],
                "formats": [2],
                "left": BBOX[0],
                "right": BBOX[2],
                "top": BBOX[3],
                "bottom": BBOX[1],
            }
        ],
    }
    value = json.loads(raw, object_pairs_hook=unique_object)
    if canonical_bytes(value) != canonical_bytes(expected):
        raise SubsetAcquisitionError(
            "Only the exact accepted GEBCO_2026 elevation subset template is supported."
        )
    return raw


def _agreement(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if (
                key
                in {
                    "agreement_required",
                    "requiresAgreement",
                    "account_required",
                    "requiresAccount",
                    "requires_authentication",
                    "requiresLogin",
                    "terms_acceptance_required",
                }
                and child is True
            ):
                raise ProviderAgreementRequired(
                    f"Provider explicitly requires {key}; no acceptance/account action performed."
                )
            _agreement(child)
    elif isinstance(value, list):
        for child in value:
            _agreement(child)
    elif isinstance(value, str) and re.search(
        r"\b(?:sign in|log in|login required|account required|agreement required|accept (?:the )?terms)\b",
        value.casefold(),
    ):
        raise ProviderAgreementRequired(
            "Provider explicitly requests an account/agreement; no acceptance action performed."
        )


def _response(
    http: Any,
    method: str,
    endpoint: str,
    run: Path,
    monitor: _Monitor,
    *,
    payload: Any = None,
    archive: bool = False,
) -> bytes | Path:
    monitor.check()
    remaining_seconds = monitor.budget.elapsed_seconds - (
        time.monotonic() - monitor.start
    )
    kwargs: dict[str, Any] = {
        "headers": {"Accept-Encoding": "identity"},
        "timeout": min(60, remaining_seconds),
        "stream": True,
        "allow_redirects": False,
    }
    if payload is not None:
        outgoing = canonical_bytes(payload)
        if (
            len(outgoing)
            > monitor.budget.transfer_bytes - monitor.transferred - monitor.uploaded
        ):
            raise SubsetAcquisitionError(
                "Request body exceeds transfer budget before submission."
            )
        monitor.uploaded += len(outgoing)
        kwargs["data"] = outgoing
        kwargs["headers"]["Content-Type"] = "application/json"
    response = http.request(method, API + endpoint, **kwargs)
    try:
        monitor.check()
        record = {
            "method": method,
            "url": API + endpoint,
            "status": response.status_code,
            "received_at": datetime.now(UTC).isoformat(),
            "headers": {
                k: response.headers.get(k)
                for k in (
                    "Content-Type",
                    "Content-Length",
                    "Content-Encoding",
                    "ETag",
                    "Last-Modified",
                    "Location",
                )
            },
        }
        number = len(list(run.glob("http-*.json")))
        record_path = run / f"http-{number:03d}.json"
        _stage_check(run, monitor, len(canonical_bytes(record)))
        record_path.write_bytes(canonical_bytes(record))
        if response.status_code in (401, 403):
            raise ProviderAgreementRequired(
                "Provider requires authorization/account or terms review (HTTP 401/403); no credentials or acceptance supplied."
            )
        if 300 <= response.status_code < 400:
            raise SubsetAcquisitionError(
                "Provider redirect rejected; no alternate/global endpoint followed."
            )
        encoding = response.headers.get("Content-Encoding", "identity")
        if encoding not in ("identity", ""):
            raise SubsetAcquisitionError(
                "Compressed HTTP transport rejected so response-body accounting stays explicit."
            )
        length_text = response.headers.get("Content-Length")
        length = None
        if length_text is not None:
            if not re.fullmatch(r"[0-9]+", length_text):
                raise SubsetAcquisitionError("Invalid provider Content-Length.")
            length = int(length_text)
        expected_archive = archive
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if (
            response.status_code >= 400
            or content_type.startswith("text/")
            or content_type == "application/json"
        ):
            archive = False
        limit = monitor.budget.transfer_bytes - monitor.transferred - monitor.uploaded
        if not archive:
            limit = min(limit, 1024**2)
        if limit <= 0 or (length is not None and length > limit):
            raise SubsetAcquisitionError(
                "Provider response exceeds remaining transfer/metadata budget before download."
            )
        _stage_check(run, monitor, length if length is not None else limit)
        target = run / ("source.zip" if archive else f"http-{number:03d}.body")
        received = 0
        with target.open("xb") as stream:
            while received < (length if length is not None else limit):
                monitor.check()
                allowed = min(65536, limit - received)
                if length is not None:
                    allowed = min(allowed, length - received)
                chunk = response.raw.read(allowed, decode_content=False)
                if not chunk:
                    break
                monitor.transferred += len(chunk)
                received += len(chunk)
                if len(chunk) > allowed or received > limit:
                    raise SubsetAcquisitionError(
                        "Response reader exceeded its bounded read request."
                    )
                stream.write(chunk)
            if length is not None and received != length:
                raise SubsetAcquisitionError(
                    "Truncated response differs from declared Content-Length."
                )
            if length is None and received == limit:
                raise SubsetAcquisitionError(
                    "Unknown-size response reached its bound; stopped without reading beyond it."
                )
        record.update(body_bytes=received, body_raw_sha256=_hash(target))
        record_path.write_bytes(canonical_bytes(record))
        if response.status_code >= 400:
            body = target.read_bytes()
            try:
                _agreement(json.loads(body))
            except json.JSONDecodeError:
                pass
            message = body.decode(errors="replace").lower()
            if any(
                s in message
                for s in (
                    "sign in",
                    "log in",
                    "account required",
                    "agreement required",
                    "accept terms",
                )
            ):
                raise ProviderAgreementRequired(
                    "Provider error explicitly requests an account/agreement; no acceptance action performed."
                )
            raise SubsetAcquisitionError(
                f"Provider HTTP error {response.status_code}; no automatic retry."
            )
        if archive:
            return target
        raw = target.read_bytes()
        _agreement(raw.decode(errors="replace"))
        value = json.loads(raw, object_pairs_hook=unique_object)
        _agreement(value)
        if expected_archive:
            raise SubsetAcquisitionError(
                "Provider returned metadata instead of ZIP; no fallback."
            )
        return raw
    finally:
        response.close()


def _stage_check(run: Path, monitor: _Monitor, additional: int) -> None:
    # Reserve 64KiB for a terminal failure receipt even when incoming bytes are refused.
    current = sum(p.stat().st_size for p in run.iterdir() if p.is_file())
    if current + additional + 65536 > monitor.budget.staging_bytes:
        raise SubsetAcquisitionError(
            "Retained staging would exceed budget before writing incoming bytes."
        )


def _json_response(
    http: Any,
    method: str,
    endpoint: str,
    run: Path,
    monitor: _Monitor,
    *,
    payload: Any = None,
) -> Any:
    raw = _response(http, method, endpoint, run, monitor, payload=payload)
    assert isinstance(raw, bytes)
    return json.loads(raw, object_pairs_hook=unique_object)


def _extract(
    archive_path: Path, run: Path, monitor: _Monitor
) -> tuple[Path, dict[str, Any]]:
    if not zipfile.is_zipfile(archive_path):
        raise SubsetAcquisitionError("Provider archive is not ZIP.")
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not members or len(members) > 128:
            raise SubsetAcquisitionError("Archive member count exceeds bound.")
        seen = set()
        total = 0
        rasters = []
        inventory = []
        for member in members:
            monitor.check()
            name = member.filename
            clean = name.rstrip("/")
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (
                not clean
                or member.orig_filename != name
                or len(name) > 512
                or "\\" in name
                or "\x00" in name
                or PurePosixPath(name).is_absolute()
                or any(p in ("", ".", "..") or ":" in p for p in clean.split("/"))
                or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                or member.flag_bits & 1
                or clean in seen
            ):
                raise SubsetAcquisitionError(
                    "Unsafe, duplicate, special or encrypted archive member."
                )
            seen.add(clean)
            total += member.file_size
            if member.file_size > 32 * 1024**2 or total > 32 * 1024**2:
                raise SubsetAcquisitionError(
                    "Uncompressed archive/member size exceeds 32MiB."
                )
            inventory.append(
                {
                    "name": name,
                    "uncompressed_bytes": member.file_size,
                    "compressed_bytes": member.compress_size,
                    "crc32": member.CRC,
                    "directory": member.is_dir(),
                }
            )
            if not member.is_dir() and name.lower().endswith((".tif", ".tiff")):
                rasters.append(member)
        if len(rasters) != 1:
            raise SubsetAcquisitionError(
                "Expected exactly one elevation GeoTIFF; no multi-source fallback."
            )
        member = rasters[0]
        _stage_check(run, monitor, member.file_size)
        destination = run / "GEBCO_2026_ELEVATION_NATIVE_EXTENT.tif"
        written = 0
        digest = hashlib.sha256()
        with archive.open(member) as source, destination.open("xb") as target:
            while written < member.file_size:
                monitor.check()
                chunk = source.read(min(65536, member.file_size - written))
                if not chunk:
                    break
                written += len(chunk)
                digest.update(chunk)
                target.write(chunk)
            if written != member.file_size or source.read(1):
                raise SubsetAcquisitionError(
                    "Actual extracted bytes differ from archive member size."
                )
        return destination, {
            "members": inventory,
            "selected_member": member.filename,
            "member_bytes": written,
            "member_raw_sha256": digest.hexdigest(),
            "archive_raw_sha256": _hash(archive_path),
        }


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _header(path: Path, grid: dict[str, Any]) -> dict[str, Any]:
    with rasterio.open(path) as raster:
        t = raster.transform
        if (
            raster.count != 1
            or raster.crs is None
            or raster.crs.to_epsg() != 4326
            or raster.width != WIDTH
            or raster.height != HEIGHT
            or raster.dtypes != ("int16",)
            or raster.scales != (1.0,)
            or raster.offsets != (0.0,)
            or t.b != 0
            or t.d != 0
            or not math.isclose(t.a, 1 / 240, abs_tol=1e-12, rel_tol=0)
            or not math.isclose(t.e, -1 / 240, abs_tol=1e-12, rel_tol=0)
            or not all(
                math.isclose(actual, expected, abs_tol=1e-10, rel_tol=0)
                for actual, expected in zip(raster.bounds, BBOX, strict=True)
            )
        ):
            raise SubsetAcquisitionError(
                "Returned native header/grid differs from exact accepted subset; no conversion/resampling."
            )
        if raster.nodata is not None and not math.isfinite(raster.nodata):
            raise SubsetAcquisitionError(
                "Nonfinite nodata cannot be preserved in the strict acquisition receipt."
            )
        validate_native_metre_band_units(raster.units[0])
        if raster.units[0] is None and "meters" not in grid["description"].lower():
            raise SubsetAcquisitionError(
                "Absent native units require pinned provider metre interpretation."
            )
        return {
            "crs_wkt": raster.crs.to_wkt(),
            "authority": raster.crs.to_string(),
            "axis_order": "longitude_latitude",
            "affine": list(t),
            "bounds_wsen": list(raster.bounds),
            "width": raster.width,
            "height": raster.height,
            "dtype": raster.dtypes[0],
            "band_units": raster.units[0],
            "interpreted_units": "m",
            "unit_evidence": "explicit native band or captured provider grid description",
            "scale": raster.scales[0],
            "offset": raster.offsets[0],
            "nodata": raster.nodata,
            "pixel_interpretation": raster.tags().get("AREA_OR_POINT", "Area"),
            "native_resolution_arc_seconds": 15,
            "pixel_decode_performed": False,
            "vertical_reference": "Provider assumes mean sea level over heterogeneous data; shallow-water inputs can use other datums. No uniform exact-member datum or transformation claimed.",
        }


def acquire_bounded_gebco_subset(
    request_template: str | Path,
    workspace: str | Path,
    *,
    budget: SubsetBudget = SubsetBudget(),
    _session: Any = None,
) -> dict[str, Any]:
    """Submit once, stream the exact accepted subset, retain/check source evidence.

    Call only after review and resource coordination. Tests inject an offline session.
    """
    raw_template = _template(Path(request_template))
    monitor = _Monitor(budget)
    monitor.check()
    owner = Path(workspace).resolve()
    ancestor = owner
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < budget.staging_bytes:
        raise SubsetAcquisitionError(
            "Insufficient free space for acquisition staging reservation."
        )
    run = owner / "gebco-subset-acquisitions" / uuid.uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    code_root = Path(__file__).resolve().parent
    identity = package_code_identity(code_root)
    http = _session or requests.Session()
    if _session is None:
        http.trust_env = False
    basket_id = None
    try:
        _stage_check(run, monitor, len(raw_template))
        (run / "request-template.json").write_bytes(raw_template)
        grids = _json_response(http, "GET", "/grids", run, monitor)
        formats = _json_response(http, "GET", "/formats", run, monitor)
        grid = next((g for g in grids if g.get("name") == "gebco_2026_global"), None)
        if (
            grid is None
            or grid.get("id") != 1
            or grid.get("projection") != "EPSG:4326"
            or "April 2026" not in grid.get("description", "")
        ):
            raise SubsetAcquisitionError(
                "Fresh catalog does not match pinned GEBCO_2026 global grid."
            )
        source = next(
            (s for s in grid["data_sources"] if s.get("name") == "gebco_2026"), None
        )
        fmt = next((f for f in formats if f.get("name") == "geotiff"), None)
        if (
            source is None
            or source.get("id") != 1
            or fmt is None
            or fmt.get("id") != 2
            or fmt.get("category") != "Data"
        ):
            raise SubsetAcquisitionError(
                "Fresh source/format identity changed; no alternate source/version."
            )
        payload = json.loads(raw_template)
        payload["submission_date"] = datetime.now(UTC).isoformat()
        _stage_check(run, monitor, len(canonical_bytes(payload)))
        (run / "submitted-request.json").write_bytes(canonical_bytes(payload))
        queue = _json_response(http, "POST", "/queue", run, monitor, payload=payload)
        basket_id = queue.get("basketId")
        if (
            not isinstance(basket_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", basket_id) is None
        ):
            raise SubsetAcquisitionError(
                "Queue did not return a safe basketId; no second submission."
            )
        while True:
            status = _json_response(
                http, "GET", "/queue/status/" + basket_id, run, monitor
            )
            state = str(status.get("status", "")).lower()
            if state == "finished":
                break
            if state in ("failed", "error", "cancelled"):
                raise SubsetAcquisitionError(
                    "Provider queue failed; no automatic resubmission."
                )
            if state not in (
                "new",
                "queued",
                "pending",
                "processing",
                "running",
                "submitted",
            ):
                raise SubsetAcquisitionError(
                    "Unknown provider queue status; stop rather than guess."
                )
            monitor.check()
            time.sleep(
                min(
                    10,
                    max(
                        0,
                        monitor.budget.elapsed_seconds
                        - (time.monotonic() - monitor.start),
                    ),
                )
            )
        archive = _response(
            http, "GET", "/queue/download/" + basket_id, run, monitor, archive=True
        )
        assert isinstance(archive, Path)
        member, archive_identity = _extract(archive, run, monitor)
        header = _header(member, grid)
        monitor.check()
        if package_code_identity(code_root) != identity:
            raise SubsetAcquisitionError("Package code changed during acquisition.")
        total = sum(p.stat().st_size for p in run.iterdir() if p.is_file())
        if total + 1024**2 > budget.staging_bytes:
            raise SubsetAcquisitionError("Retained staging exceeds budget.")
        result = {
            "status": "source_acquired_header_checked_not_regionally_qualified",
            "scope": "native_source_acquisition_only",
            "code_identity": identity,
            "generation": str(run),
            "basket_id": basket_id,
            "source_release": "GEBCO_2026",
            "source_doi": "10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa",
            "elevation_sign": "negative underwater; preserved without conversion",
            "reporting_domain_defined_by_acquisition_bbox": False,
            "selected_catalog_grid": grid,
            "selected_catalog_source": source,
            "selected_catalog_format": fmt,
            "acquired_at": datetime.now(UTC).isoformat(),
            "observation_period": None,
            "archive": archive_identity,
            "native_header": header,
            "resources": monitor.receipt(),
            "staging_bytes_before_receipt": total,
            "source_accuracy_qualified": False,
            "shared_reporting_qualified": False,
            "production_ready": False,
            "artifact_release_passed": False,
            "regional_release_eligible": False,
            "terms_url": "https://www.gebco.net/data-products/gridded-bathymetry/terms-of-use",
            "rights": "Public domain subject to GEBCO conditions and attribution; no new agreement/account accepted",
            "static_time_policy": "one source-vintage artifact; no backdating or duplicate annual tables",
            "inventory_raw_sha256": {
                p.name: _hash(p) for p in run.iterdir() if p.is_file()
            },
        }
        _stage_check(run, monitor, len(canonical_bytes(result)))
        (run / "acquisition-receipt.json").write_bytes(canonical_bytes(result))
        monitor.check()
        return result
    except Exception as exc:
        failure = {
            "status": "account_or_agreement_required"
            if isinstance(exc, ProviderAgreementRequired)
            else "failed",
            "error": str(exc),
            "basket_id": basket_id,
            "no_automatic_resubmission": True,
            "resources": monitor.receipt(),
            "production_ready": False,
        }
        (run / "failure-receipt.json").write_bytes(canonical_bytes(failure))
        raise
    finally:
        if _session is None:
            http.close()
