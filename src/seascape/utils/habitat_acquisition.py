"""Source acquisition helpers for the benthic habitat product families.

The helpers support immutable HTTP files and archives, ArcGIS feature layers,
public OGC WFS layers, and explicitly user-supplied rasters. Source-specific
ecological interpretation remains inside each leaf package.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.artifacts import checksum_artifact as _sha256
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HabitatDownloadConfig:
    """Resolved acquisition settings shared by one habitat leaf package."""

    section_name: str
    bbox: dict[str, float]
    raw_dir: Path
    request_timeout_seconds: float
    page_size: int
    overwrite: bool
    sources: dict[str, dict[str, Any]]


def load_habitat_download_config(
    section_name: str,
    config_path: str | Path,
) -> HabitatDownloadConfig:
    """Load the acquisition portion of a habitat-family configuration."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get(section_name), section_name)
    download = _mapping(section.get("download"), f"{section_name}.download")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    timeout = float(download.get("request_timeout_seconds", 180.0))
    page_size = int(download.get("page_size", 2_000))
    if timeout <= 0 or page_size < 1:
        raise ValueError("Habitat download timeout and page size must be positive.")
    sources = _mapping(download.get("sources"), f"{section_name}.download.sources")
    if not sources:
        raise ValueError(f"{section_name}.download.sources must not be empty.")
    return HabitatDownloadConfig(
        section_name=section_name,
        bbox=bbox_from_config(section),
        raw_dir=_resolve(download["raw_dir"], base_dir),
        request_timeout_seconds=timeout,
        page_size=page_size,
        overwrite=bool(download.get("overwrite", False)),
        sources={
            name: _mapping(value, f"{section_name}.sources.{name}")
            for name, value in sources.items()
        },
    )


def _response_json(response: requests.Response, context: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"{context} request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context} returned a non-object JSON response.")
    if payload.get("error"):
        raise RuntimeError(f"{context} returned an error: {payload['error']}")
    return payload


def _atomic_json(document: Mapping[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with partial.open("w", encoding="utf-8") as output:
            json.dump(document, output, separators=(",", ":"))
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _validate_expected_file(path: Path, source: Mapping[str, Any]) -> None:
    expected_bytes = source.get("expected_bytes")
    if expected_bytes is not None and path.stat().st_size != int(expected_bytes):
        raise RuntimeError(
            f"Source size is {path.stat().st_size}, expected {int(expected_bytes)}: {path}"
        )
    expected_md5 = str(source.get("md5", "")).strip().lower()
    if expected_md5:
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_md5:
            raise RuntimeError(
                f"Source MD5 is {digest.hexdigest()}, expected {expected_md5}: {path}"
            )


def _download_http_file(
    session: requests.Session,
    source: Mapping[str, Any],
    destination: Path,
    *,
    timeout: float,
) -> int:
    method = str(source.get("http_method", "GET")).strip().upper()
    if method not in {"GET", "POST"}:
        raise ValueError(f"Unsupported HTTP download method: {method}")
    response = session.request(method, str(source["url"]), timeout=timeout, stream=True)
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"HTTP download failed for {source['url']}: {exc}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with partial.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    if destination.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(destination) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    raise RuntimeError(f"Downloaded ZIP has a corrupt member: {bad_member}")
        except zipfile.BadZipFile as exc:
            raise RuntimeError(f"Downloaded archive is not a valid ZIP: {destination}") from exc
    _validate_expected_file(destination, source)
    return int(destination.stat().st_size)


def _query_envelope(bbox: Mapping[str, float]) -> str:
    return ",".join(str(float(bbox[key])) for key in ("min_lon", "min_lat", "max_lon", "max_lat"))


def _build_overpass_query(
    source: Mapping[str, Any],
    bbox: Mapping[str, float],
) -> str:
    """Build a bounded metadata-preserving Overpass query from configured filters."""

    filters = source.get("query_filters")
    if not isinstance(filters, list) or not filters:
        raise ValueError("Overpass sources require a non-empty query_filters list.")
    clean_filters: list[str] = []
    for value in filters:
        item = str(value).strip()
        if not item.startswith("[") or not item.endswith("]") or ";" in item or "\n" in item:
            raise ValueError(f"Unsafe or invalid Overpass filter: {item!r}")
        clean_filters.append(item)
    south = float(bbox["min_lat"])
    west = float(bbox["min_lon"])
    north = float(bbox["max_lat"])
    east = float(bbox["max_lon"])
    timeout = int(source.get("query_timeout_seconds", 180))
    if timeout < 1:
        raise ValueError("Overpass query_timeout_seconds must be positive.")
    bounds = f"({south},{west},{north},{east})"
    statements = "\n".join(f"  nwr{item}{bounds};" for item in clean_filters)
    geometry_mode = str(source.get("geometry_mode", "geom")).strip().lower()
    if geometry_mode not in {"geom", "center"}:
        raise ValueError("Overpass geometry_mode must be 'geom' or 'center'.")
    return f"[out:json][timeout:{timeout}];\n(\n{statements}\n);\n" f"out meta {geometry_mode};"


def _overpass_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
    metadata = document.get("_orcacast")
    if not isinstance(metadata, Mapping):
        return {}
    return {
        key: metadata.get(key)
        for key in (
            "endpoint",
            "endpoints_used",
            "query_sha256",
            "query_timeout_seconds",
            "geometry_mode",
            "tile_degrees",
            "tile_count",
        )
        if metadata.get(key) is not None
    }


def _overpass_tiles(
    bbox: Mapping[str, float],
    tile_degrees: float | None,
) -> list[dict[str, float]]:
    if tile_degrees is None:
        return [{key: float(value) for key, value in bbox.items()}]
    size = float(tile_degrees)
    if size <= 0:
        raise ValueError("Overpass tile_degrees must be positive when configured.")
    lon_count = max(1, math.ceil((float(bbox["max_lon"]) - float(bbox["min_lon"])) / size))
    lat_count = max(1, math.ceil((float(bbox["max_lat"]) - float(bbox["min_lat"])) / size))
    tiles: list[dict[str, float]] = []
    for lat_index in range(lat_count):
        min_lat = float(bbox["min_lat"]) + lat_index * size
        max_lat = min(float(bbox["max_lat"]), min_lat + size)
        for lon_index in range(lon_count):
            min_lon = float(bbox["min_lon"]) + lon_index * size
            max_lon = min(float(bbox["max_lon"]), min_lon + size)
            tiles.append(
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                }
            )
    return tiles


def _download_overpass(
    session: requests.Session,
    source: Mapping[str, Any],
    destination: Path,
    *,
    bbox: Mapping[str, float],
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    """Download one bounded OSM/OpenSeaMap snapshot with endpoint fallback."""

    configured_endpoints = source.get("endpoints")
    if configured_endpoints is None:
        configured_endpoints = [source.get("url")]
    if not isinstance(configured_endpoints, list):
        raise ValueError("Overpass endpoints must be a list.")
    endpoints = [str(value).strip() for value in configured_endpoints if str(value).strip()]
    if not endpoints:
        raise ValueError("Overpass sources require at least one endpoint.")
    attempts = int(source.get("attempts_per_endpoint", 2))
    backoff = float(source.get("retry_backoff_seconds", 2.0))
    request_delay = float(source.get("request_delay_seconds", 0.0))
    if attempts < 1 or backoff < 0 or request_delay < 0:
        raise ValueError("Overpass retry settings must be non-negative and attempts positive.")
    tiles = _overpass_tiles(bbox, source.get("tile_degrees"))
    queries = [_build_overpass_query(source, tile) for tile in tiles]
    query_sha256 = hashlib.sha256("\n".join(queries).encode("utf-8")).hexdigest()
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    endpoints_used: list[str] = []
    response_metadata: dict[str, Any] = {}
    for tile_index, query in enumerate(queries):
        failures: list[str] = []
        tile_document: dict[str, Any] | None = None
        for endpoint in endpoints:
            for attempt in range(attempts):
                try:
                    response = session.post(endpoint, data={"data": query}, timeout=timeout)
                    tile_document = _response_json(response, f"Overpass query for {endpoint}")
                    elements = tile_document.get("elements")
                    if not isinstance(elements, list):
                        raise RuntimeError(
                            f"Overpass endpoint returned invalid elements: {endpoint}"
                        )
                    endpoints_used.append(endpoint)
                    break
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    failures.append(f"{endpoint} attempt {attempt + 1}: {exc}")
                    if attempt + 1 < attempts and backoff:
                        time.sleep(backoff * (attempt + 1))
            if tile_document is not None:
                break
        if tile_document is None:
            raise RuntimeError(
                f"All Overpass endpoints failed for tile {tile_index + 1}/{len(tiles)}: "
                + " | ".join(failures)
            )
        if not response_metadata:
            response_metadata = {
                key: tile_document.get(key)
                for key in ("version", "generator", "osm3s")
                if tile_document.get(key) is not None
            }
        for element in tile_document.get("elements", []):
            key = (str(element.get("type")), int(element.get("id")))
            existing = merged.get(key)
            if existing is None or int(element.get("version", 0)) >= int(
                existing.get("version", 0)
            ):
                merged[key] = element
        if request_delay and tile_index + 1 < len(queries):
            time.sleep(request_delay)
    if not merged:
        raise RuntimeError("All Overpass tiles completed but returned no elements.")
    document = {
        **response_metadata,
        "elements": [merged[key] for key in sorted(merged)],
        "_orcacast": {
            "endpoint": endpoints_used[0],
            "endpoints_used": sorted(set(endpoints_used)),
            "queries": queries,
            "query_sha256": query_sha256,
            "query_timeout_seconds": int(source.get("query_timeout_seconds", 180)),
            "geometry_mode": str(source.get("geometry_mode", "geom")).strip().lower(),
            "tile_degrees": source.get("tile_degrees"),
            "tile_count": len(tiles),
            "downloaded_at_utc": datetime.now(UTC).isoformat(),
        },
    }
    _atomic_json(document, destination)
    return len(merged), _overpass_metadata(document)


def _download_arcgis(
    session: requests.Session,
    source: Mapping[str, Any],
    destination: Path,
    *,
    bbox: Mapping[str, float],
    timeout: float,
    page_size: int,
) -> int:
    layer_url = str(source["layer_url"]).rstrip("/")
    query_url = f"{layer_url}/query"
    base_params = {
        "f": "json",
        "where": str(source.get("where", "1=1")),
        "geometry": _query_envelope(bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }
    id_payload = _response_json(
        session.get(
            query_url,
            params={**base_params, "returnIdsOnly": "true", "returnGeometry": "false"},
            timeout=timeout,
        ),
        f"ArcGIS object-id query for {layer_url}",
    )
    object_ids = sorted({int(value) for value in (id_payload.get("objectIds") or [])})
    if not object_ids:
        raise RuntimeError(
            f"ArcGIS source returned no features in the configured bbox: {layer_url}"
        )
    fields = source.get("fields", "*")
    out_fields = (
        ",".join(str(value) for value in fields) if isinstance(fields, list) else str(fields)
    )
    features: list[dict[str, Any]] = []
    for offset in range(0, len(object_ids), page_size):
        batch = object_ids[offset : offset + page_size]
        payload = _response_json(
            # ArcGIS object-ID lists can exceed common proxy URL limits even at
            # the service's advertised page size. The query endpoint accepts
            # form-encoded POST with the same parameters.
            session.post(
                query_url,
                data={
                    "f": "geojson",
                    "objectIds": ",".join(map(str, batch)),
                    "outFields": out_fields,
                    "returnGeometry": "true",
                    "returnZ": "false",
                    "returnM": "false",
                    "outSR": "4326",
                },
                timeout=timeout,
            ),
            f"ArcGIS feature query for {layer_url}",
        )
        batch_features = payload.get("features")
        if not isinstance(batch_features, list):
            raise RuntimeError(f"ArcGIS source returned invalid features: {layer_url}")
        features.extend(batch_features)
    if len(features) != len(object_ids):
        raise RuntimeError(
            f"ArcGIS source returned {len(features)} features for {len(object_ids)} object IDs."
        )
    _atomic_json({"type": "FeatureCollection", "features": features}, destination)
    return len(features)


def _download_wfs(
    session: requests.Session,
    source: Mapping[str, Any],
    destination: Path,
    *,
    bbox: Mapping[str, float],
    timeout: float,
    page_size: int,
) -> int:
    url = str(source["url"])
    type_name = str(source["type_name"])
    features: list[dict[str, Any]] = []
    expected: int | None = None
    start_index = 0
    axis_order = str(source.get("bbox_axis_order", "lon_lat")).strip().lower()
    srs_name = str(source.get("srs_name", "EPSG:4326")).strip()
    if not srs_name:
        raise ValueError("WFS srs_name must not be empty.")
    if axis_order == "lon_lat":
        query_bbox = _query_envelope(bbox)
    elif axis_order == "lat_lon":
        query_bbox = ",".join(
            str(float(bbox[key])) for key in ("min_lat", "min_lon", "max_lat", "max_lon")
        )
    else:
        raise ValueError("WFS bbox_axis_order must be 'lon_lat' or 'lat_lon'.")
    while expected is None or start_index < expected:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": type_name,
            "outputFormat": "application/json",
            "srsName": srs_name,
            "bbox": f"{query_bbox},{srs_name}",
            "count": str(page_size),
            "startIndex": str(start_index),
        }
        sort_by = str(source.get("sort_by", "")).strip()
        if sort_by:
            params["sortBy"] = sort_by
        payload = _response_json(
            session.get(url, params=params, timeout=timeout),
            f"WFS feature query for {type_name}",
        )
        batch = payload.get("features")
        if not isinstance(batch, list):
            raise RuntimeError(f"WFS source returned invalid features: {type_name}")
        if expected is None:
            try:
                expected = int(payload["numberMatched"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"WFS source omitted numberMatched: {type_name}") from exc
            if expected < 1:
                raise RuntimeError(f"WFS source returned no features: {type_name}")
        if not batch:
            raise RuntimeError(f"WFS pagination ended before numberMatched for {type_name}")
        features.extend(batch)
        start_index += len(batch)
    if expected is None or len(features) != expected:
        raise RuntimeError(f"WFS source returned {len(features)} of {expected} expected features.")
    _atomic_json({"type": "FeatureCollection", "features": features}, destination)
    return len(features)


def _extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"Unsafe ZIP member path: {member.filename}")
        archive.extractall(destination)


def _validate_existing(path: Path, kind: str) -> int:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"Existing habitat source is invalid: {path}")
    if kind in {"arcgis", "wfs", "overpass"}:
        with path.open(encoding="utf-8") as source:
            document = json.load(source)
        records = document.get("elements" if kind == "overpass" else "features")
        if not isinstance(records, list) or not records:
            label = "OSM elements" if kind == "overpass" else "GeoJSON features"
            raise RuntimeError(f"Existing habitat source has no {label}: {path}")
        return len(records)
    return int(path.stat().st_size)


def acquisition_identity(source: Mapping[str, Any], bbox: Mapping[str, float]) -> str:
    """Bind cached bytes to the complete source/query configuration and footprint."""
    identity = {
        "source": {k: v for k, v in source.items() if k not in {"enabled", "large"}},
        "bbox": dict(bbox),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def validate_cached_source(path: Path, identity: str, previous: Mapping[str, Any]) -> None:
    """Never assign a new source identity or retrieval date to unverified old bytes."""
    if previous.get("acquisition_identity") != identity or previous.get("sha256") != _sha256(path):
        raise ValueError(
            f"Cached source identity or checksum is unverified/changed: {path}. "
            "Recollect with --overwrite; the previous manifest is preserved."
        )


def download_habitat_sources(
    section_name: str,
    config_path: str | Path,
    *,
    include_large: bool = False,
    overwrite: bool | None = None,
) -> tuple[list[Path], Path]:
    """Download configured sources and write a checksum-bearing manifest."""

    config = load_habitat_download_config(section_name, config_path)
    replace = config.overwrite if overwrite is None else bool(overwrite)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.raw_dir / "download_manifest.json"
    previous_manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    previous_sources = {item["name"]: item for item in previous_manifest.get("sources", [])}
    # Preflight every reused source before any network request or mutation.
    for name, source in config.sources.items():
        if not source.get("enabled", True) or (source.get("large", False) and not include_large):
            continue
        path = config.raw_dir / str(source["raw_filename"])
        if path.exists() and not replace:
            validate_cached_source(
                path, acquisition_identity(source, config.bbox), previous_sources.get(name, {})
            )
    outputs: list[Path] = []
    manifest_sources: list[dict[str, Any]] = []
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Seascape Toolkit habitat pipeline/1.0"})
        for name, source in config.sources.items():
            source_metadata = {
                "name": name,
                "kind": source.get("kind"),
                "source_url": source.get("url", source.get("layer_url", source.get("dataset_url"))),
                "endpoints": source.get("endpoints"),
                "dataset_url": source.get("dataset_url"),
                "dataset_version": source.get("dataset_version"),
                "variable": source.get("variable"),
                "units": source.get("units"),
                "type_name": source.get("type_name"),
                "srs_name": source.get("srs_name"),
                "sort_by": source.get("sort_by"),
                "geometry_mode": source.get("geometry_mode"),
                "tile_degrees": source.get("tile_degrees"),
                "evidence_class": source.get("evidence_class"),
                "license": source.get("license"),
                "attribution": source.get("attribution"),
            }
            if not bool(source.get("enabled", True)):
                manifest_sources.append({**source_metadata, "status": "disabled"})
                continue
            if bool(source.get("large", False)) and not include_large:
                manifest_sources.append({**source_metadata, "status": "skipped_large"})
                continue
            kind = str(source["kind"]).strip().lower()
            destination = config.raw_dir / str(source["raw_filename"])
            result_metadata: dict[str, Any] = {}
            if destination.exists() and not replace:
                count = _validate_existing(destination, kind)
                if kind == "overpass":
                    with destination.open(encoding="utf-8") as input_file:
                        result_metadata = _overpass_metadata(json.load(input_file))
                status = "existing"
            elif kind == "local_raster":
                if not destination.exists():
                    raise FileNotFoundError(f"Place the configured local raster at {destination}")
                # Explicit --overwrite imports caller-supplied bytes; never claim a retrieval.
                count = _validate_existing(destination, kind)
                status = "supplied_local"
            elif kind in {"http_archive", "http_file"}:
                count = _download_http_file(
                    session,
                    source,
                    destination,
                    timeout=config.request_timeout_seconds,
                )
                status = "downloaded"
            elif kind == "arcgis":
                count = _download_arcgis(
                    session,
                    source,
                    destination,
                    bbox=config.bbox,
                    timeout=config.request_timeout_seconds,
                    page_size=config.page_size,
                )
                status = "downloaded"
            elif kind == "wfs":
                count = _download_wfs(
                    session,
                    source,
                    destination,
                    bbox=config.bbox,
                    timeout=config.request_timeout_seconds,
                    page_size=config.page_size,
                )
                status = "downloaded"
            elif kind == "overpass":
                count, result_metadata = _download_overpass(
                    session,
                    source,
                    destination,
                    bbox=config.bbox,
                    timeout=config.request_timeout_seconds,
                )
                status = "downloaded"
            else:
                raise ValueError(f"Unsupported habitat source kind {kind!r} for {name}.")
            _validate_expected_file(destination, source)
            if bool(source.get("extract", False)):
                extract_dir = config.raw_dir / str(
                    source.get("extract_directory", destination.stem)
                )
                if replace or not extract_dir.exists():
                    _extract_zip(destination, extract_dir)
            outputs.append(destination)
            manifest_sources.append(
                {
                    **source_metadata,
                    "status": status,
                    "acquisition_identity": acquisition_identity(source, config.bbox),
                    "retrieved_at_utc": (
                        previous_sources[name].get("retrieved_at_utc")
                        if status == "existing"
                        else (None if status == "supplied_local" else datetime.now(UTC).isoformat())
                    ),
                    "path": str(destination),
                    "count_or_bytes": count,
                    "sha256": _sha256(destination),
                    **result_metadata,
                },
            )
            LOGGER.info("%s habitat source %s -> %s", status, name, destination)
    manifest_path = config.raw_dir / "download_manifest.json"
    payload = {
        "schema_version": 1,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "section": section_name,
        "model_bbox_wgs84": config.bbox,
        "include_large": include_large,
        "sources": manifest_sources,
    }
    partial = manifest_path.with_suffix(".json.part")
    try:
        with partial.open("w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
        partial.replace(manifest_path)
    finally:
        partial.unlink(missing_ok=True)
    return outputs, manifest_path
