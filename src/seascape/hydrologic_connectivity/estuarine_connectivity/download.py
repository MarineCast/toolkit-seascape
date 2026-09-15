"""Download B.C. and U.S. estuary locations for the Seascape Toolkit model area."""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
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

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"

BC_FIELDS = (
    "FID",
    "OBJECTID",
    "EST_NO",
    "EST_NAME",
    "CODE_LET",
    "ECOREGION",
    "Hectares",
    "IMP_CLASS",
    "TYPE_Emmet",
    "TYPE_Durr",
    "ORIG_NAME",
)
PMEP_FIELDS = (
    "OBJECTID",
    "PMEP_EstuaryID",
    "Estuary_Name",
    "Data_Source",
    "CMECS_Class",
    "PMEP_Region",
    "System_Order",
    "Estuary_Hectares",
)


@dataclass(frozen=True)
class EstuarineDownloadConfig:
    """Resolved acquisition settings for the two estuary-location sources."""

    bbox: dict[str, float]
    context_buffer_km: float
    raw_dir: Path
    request_timeout_seconds: float
    service_poll_seconds: float
    service_poll_timeout_seconds: float
    overwrite: bool
    bc_dataset_id: str
    bc_raw_path: Path
    pmep_layer_url: str
    pmep_raw_path: Path

    @property
    def query_bbox(self) -> dict[str, float]:
        """Return a conservative WGS84 bbox around the model support."""

        latitude = (self.bbox["min_lat"] + self.bbox["max_lat"]) / 2.0
        latitude_padding = self.context_buffer_km / 110.574
        longitude_padding = self.context_buffer_km / (
            111.320 * max(math.cos(math.radians(latitude)), 0.1)
        )
        return {
            "min_lon": self.bbox["min_lon"] - longitude_padding,
            "min_lat": self.bbox["min_lat"] - latitude_padding,
            "max_lon": self.bbox["max_lon"] + longitude_padding,
            "max_lat": self.bbox["max_lat"] + latitude_padding,
        }


def load_estuarine_download_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> EstuarineDownloadConfig:
    """Load and validate the estuary-location acquisition contract."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("estuarine_connectivity"), "estuarine_connectivity")
    download = _mapping(section.get("download"), "estuarine_connectivity.download")
    sources = _mapping(download.get("sources"), "estuarine_connectivity.download.sources")
    bc = _mapping(sources.get("bc_pecp"), "sources.bc_pecp")
    pmep = _mapping(sources.get("us_pmep"), "sources.us_pmep")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    raw_dir = _resolve(download["raw_dir"], base_dir)
    context_buffer_km = float(download.get("context_buffer_km", 75.0))
    timeout = float(download.get("request_timeout_seconds", 180.0))
    poll_seconds = float(download.get("service_poll_seconds", 2.0))
    poll_timeout = float(download.get("service_poll_timeout_seconds", 120.0))
    if min(context_buffer_km, timeout, poll_seconds, poll_timeout) <= 0:
        raise ValueError("Estuarine download distances and timeouts must be positive.")
    return EstuarineDownloadConfig(
        bbox=bbox_from_config(section),
        context_buffer_km=context_buffer_km,
        raw_dir=raw_dir,
        request_timeout_seconds=timeout,
        service_poll_seconds=poll_seconds,
        service_poll_timeout_seconds=poll_timeout,
        overwrite=bool(download.get("overwrite", False)),
        bc_dataset_id=str(bc["dataset_id"]),
        bc_raw_path=raw_dir / str(bc["raw_filename"]),
        pmep_layer_url=str(pmep["layer_url"]).rstrip("/"),
        pmep_raw_path=raw_dir / str(pmep["raw_filename"]),
    )


def _response_json(response: requests.Response, context: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"{context} request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context} returned a non-object JSON response.")
    if "error" in payload or "error_message" in payload:
        error = payload.get("error", payload.get("error_message"))
        raise RuntimeError(f"{context} returned an error: {error}")
    return payload


def _databasin_authorization(
    session: requests.Session,
    dataset_id: str,
    *,
    timeout: float,
    poll_seconds: float,
    poll_timeout: float,
) -> dict[str, Any]:
    """Start Data Basin's public native service and return proxy credentials."""

    authorization_url = "https://databasin.org/api/v1/mapservers/service-authorization/"
    body = {"objects": [{"dataset": f"/api/v1/datasets/{dataset_id}/"}]}
    deadline = time.monotonic() + poll_timeout
    while True:
        response = session.patch(authorization_url, json=body, timeout=timeout)
        payload = _response_json(response, "Data Basin service authorization")
        objects = payload.get("objects")
        if not isinstance(objects, list) or len(objects) != 1:
            raise RuntimeError("Data Basin returned invalid service-authorization metadata.")
        authorization = objects[0]
        if not isinstance(authorization, dict):
            raise RuntimeError("Data Basin service authorization was not an object.")
        status = str(authorization.get("status", ""))
        if status == "running":
            required = {"token", "expires", "host", "version"}
            missing = sorted(required.difference(authorization))
            if missing:
                raise RuntimeError(f"Data Basin authorization is missing fields: {missing}")
            return authorization
        if status == "error":
            raise RuntimeError("Data Basin could not start the B.C. estuary map service.")
        if status not in {"pending", "starting", "stopping"}:
            raise RuntimeError(f"Unexpected Data Basin service status: {status!r}")
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for the B.C. estuary map service.")
        time.sleep(poll_seconds)


def _databasin_layer_url(dataset_id: str, authorization: Mapping[str, Any]) -> str:
    expires = datetime.fromisoformat(str(authorization["expires"]).replace("Z", "+00:00"))
    expires_epoch = int(expires.timestamp())
    return (
        f"https://databasin.org/ags-proxy/{authorization['token']}/{expires_epoch}/"
        f"{authorization['host']}/arcgis/rest/services/{dataset_id[:2]}/"
        f"{dataset_id}_{int(authorization['version'])}/MapServer/0"
    )


def _existing_feature_count(path: Path) -> int:
    with path.open(encoding="utf-8") as source:
        document = json.load(source)
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError(f"Existing estuary GeoJSON has no features: {path}")
    return len(features)


def _save_geojson(document: Mapping[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with partial.open("w", encoding="utf-8") as output:
            json.dump(document, output, separators=(",", ":"))
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def _query_parameters(
    bbox_value: Mapping[str, float],
    *,
    fields: tuple[str, ...],
) -> dict[str, str]:
    envelope = ",".join(
        str(bbox_value[key]) for key in ("min_lon", "min_lat", "max_lon", "max_lat")
    )
    return {
        "f": "geojson",
        "where": "1=1",
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(fields),
        "returnGeometry": "true",
        "returnZ": "false",
        "returnM": "false",
        "outSR": "4326",
    }


def _download_bc_estuaries(
    session: requests.Session,
    config: EstuarineDownloadConfig,
    *,
    overwrite: bool,
) -> tuple[Path, int]:
    if config.bc_raw_path.exists() and not overwrite:
        count = _existing_feature_count(config.bc_raw_path)
        LOGGER.info("Using existing B.C. estuary extract (%d polygons)", count)
        return config.bc_raw_path, count

    authorization = _databasin_authorization(
        session,
        config.bc_dataset_id,
        timeout=config.request_timeout_seconds,
        poll_seconds=config.service_poll_seconds,
        poll_timeout=config.service_poll_timeout_seconds,
    )
    response = session.get(
        f"{_databasin_layer_url(config.bc_dataset_id, authorization)}/query",
        params=_query_parameters(config.query_bbox, fields=BC_FIELDS),
        timeout=config.request_timeout_seconds,
    )
    document = _response_json(response, "Data Basin B.C. estuary query")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("The B.C. estuary query returned no GeoJSON features.")
    _save_geojson(document, config.bc_raw_path)
    LOGGER.info("Saved B.C. PECP-derived estuaries (%d polygons)", len(features))
    return config.bc_raw_path, len(features)


def _download_pmep_estuaries(
    session: requests.Session,
    config: EstuarineDownloadConfig,
    *,
    overwrite: bool,
) -> tuple[Path, int]:
    if config.pmep_raw_path.exists() and not overwrite:
        count = _existing_feature_count(config.pmep_raw_path)
        LOGGER.info("Using existing PMEP estuary extract (%d points)", count)
        return config.pmep_raw_path, count

    response = session.get(
        f"{config.pmep_layer_url}/query",
        params=_query_parameters(config.query_bbox, fields=PMEP_FIELDS),
        timeout=config.request_timeout_seconds,
    )
    document = _response_json(response, "PMEP U.S. estuary query")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("The PMEP estuary query returned no GeoJSON features.")
    geometry_types = {
        feature.get("geometry", {}).get("type")
        for feature in features
        if isinstance(feature, Mapping)
    }
    if geometry_types != {"Point"}:
        raise RuntimeError(f"PMEP estuary query returned unexpected geometry: {geometry_types}")
    _save_geojson(document, config.pmep_raw_path)
    LOGGER.info("Saved PMEP U.S. estuaries (%d points)", len(features))
    return config.pmep_raw_path, len(features)


def download_estuarine_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    overwrite: bool | None = None,
    session: requests.Session | None = None,
) -> tuple[Path, ...]:
    """Download and inventory the configured cross-border estuary locations."""

    config = load_estuarine_download_config(config_path)
    overwrite = config.overwrite if overwrite is None else bool(overwrite)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", "Seascape Toolkit/0.1 estuary-distance builder")

    bc_path, bc_count = _download_bc_estuaries(http, config, overwrite=overwrite)
    pmep_path, pmep_count = _download_pmep_estuaries(http, config, overwrite=overwrite)
    manifest = {
        "schema_version": 2,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "model_bbox_wgs84": config.bbox,
        "query_bbox_wgs84": config.query_bbox,
        "context_buffer_km": config.context_buffer_km,
        "sources": {
            "bc_pecp_databasin": {
                "dataset_page": f"https://databasin.org/datasets/{config.bc_dataset_id}/",
                "dataset_id": config.bc_dataset_id,
                "path": str(bc_path),
                "feature_count": bc_count,
                "sha256": _sha256(bc_path),
                "location_normalization": (
                    "The build converts each mapped polygon to one interior representative point."
                ),
                "coverage_warning": (
                    "Public PECP-derived subset containing only estuaries linked to a unique "
                    "watershed; it is not the complete PECP inventory."
                ),
            },
            "us_pmep_estuary_points": {
                "dataset_page": "https://www.pacificfishhabitat.org/data/estuary-points",
                "arcgis_item": (
                    "https://psmfc.maps.arcgis.com/home/item.html"
                    "?id=b24c6540f92644b0b0a92b4267ef469d"
                ),
                "layer_url": config.pmep_layer_url,
                "path": str(pmep_path),
                "feature_count": pmep_count,
                "sha256": _sha256(pmep_path),
                "coverage_warning": (
                    "PMEP includes U.S. West Coast estuaries selected for current or future "
                    "potential fish habitat; it is an inventory, not exhaustive ground truth."
                ),
            },
        },
    }
    manifest_path = config.raw_dir / "download_manifest.json"
    partial = manifest_path.with_suffix(".json.part")
    try:
        with partial.open("w", encoding="utf-8") as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
        partial.replace(manifest_path)
    finally:
        partial.unlink(missing_ok=True)
    LOGGER.info("Saved estuary-source download manifest: %s", manifest_path)
    return bc_path, pmep_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for path in download_estuarine_sources(args.config, overwrite=args.overwrite):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
