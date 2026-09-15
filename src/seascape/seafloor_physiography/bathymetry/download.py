"""Download the configured GEBCO bathymetry GeoTIFF."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import requests

if TYPE_CHECKING:
    from .pipeline import BathymetryConfig

LOGGER = logging.getLogger(__name__)


def _response_json(response: requests.Response, label: str) -> Any:
    try:
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"GEBCO {label} request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GEBCO {label} returned invalid JSON.") from exc


def _item_by_name(items: Iterable[Mapping[str, Any]], name: str, label: str) -> Mapping[str, Any]:
    match = next((item for item in items if str(item.get("name")) == name), None)
    if match is None:
        raise RuntimeError(f"GEBCO {label} {name!r} was not returned by the download API.")
    return match


def _download_queue_archive(
    session: requests.Session,
    config: BathymetryConfig,
    basket_id: str,
    archive_path: Path,
) -> None:
    download_url = f"{config.api_base_url}/queue/download/{basket_id}"
    try:
        with session.get(
            download_url,
            timeout=config.request_timeout_seconds,
            stream=True,
        ) as response:
            response.raise_for_status()
            with archive_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
    except requests.RequestException as exc:
        raise RuntimeError(f"GEBCO download failed: {exc}") from exc


def _extract_single_geotiff(archive_path: Path, output_path: Path) -> None:
    if not zipfile.is_zipfile(archive_path):
        raise RuntimeError("GEBCO download did not return a ZIP archive.")
    with zipfile.ZipFile(archive_path) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith((".tif", ".tiff"))
        ]
        if len(members) != 1:
            raise RuntimeError(f"Expected one GeoTIFF in the GEBCO archive; found {len(members)}.")
        partial_path = output_path.with_suffix(output_path.suffix + ".part")
        try:
            with archive.open(members[0]) as source, partial_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            partial_path.replace(output_path)
        finally:
            partial_path.unlink(missing_ok=True)


def download_gebco_geotiff(
    config: BathymetryConfig,
    *,
    overwrite: bool | None = None,
    session: requests.Session | None = None,
) -> Path:
    """Request, poll, download, and extract a GEBCO model-area GeoTIFF."""

    overwrite = config.overwrite if overwrite is None else bool(overwrite)
    if config.raw_path.exists() and not overwrite:
        LOGGER.info("Using existing GEBCO GeoTIFF: %s", config.raw_path)
        return config.raw_path

    config.raw_path.parent.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    grids = _response_json(
        http.get(f"{config.api_base_url}/grids", timeout=config.request_timeout_seconds),
        "grids",
    )
    formats = _response_json(
        http.get(f"{config.api_base_url}/formats", timeout=config.request_timeout_seconds),
        "formats",
    )
    grid = _item_by_name(grids, config.grid_name, "grid")
    data_source = _item_by_name(
        grid.get("data_sources", []), config.data_source_name, "data source"
    )
    output_format = _item_by_name(formats, config.format_name, "format")
    bbox = config.bbox
    payload = {
        "id": "0",
        "email": None,
        "submission_date": datetime.now(UTC).isoformat(),
        "processing_status": "new",
        "items": [
            {
                "id": 0,
                "grid_id": int(grid["id"]),
                "data_source_ids": [int(data_source["id"])],
                "formats": [int(output_format["id"])],
                "left": bbox["min_lon"],
                "right": bbox["max_lon"],
                "top": bbox["max_lat"],
                "bottom": bbox["min_lat"],
            }
        ],
    }
    queue = _response_json(
        http.post(
            f"{config.api_base_url}/queue",
            json=payload,
            timeout=config.request_timeout_seconds,
        ),
        "queue submission",
    )
    basket_id = str(queue.get("basketId", "")).strip()
    if not basket_id:
        raise RuntimeError("GEBCO queue submission did not return a basketId.")

    deadline = time.monotonic() + config.poll_timeout_seconds
    while True:
        status_payload = _response_json(
            http.get(
                f"{config.api_base_url}/queue/status/{basket_id}",
                timeout=config.request_timeout_seconds,
            ),
            "queue status",
        )
        status = str(status_payload.get("status", "")).lower()
        if status == "finished":
            break
        if status in {"error", "failed", "cancelled"}:
            detail = status_payload.get("message") or status_payload.get("error_message")
            raise RuntimeError(f"GEBCO queue job {basket_id} failed: {detail or status}")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"GEBCO queue job {basket_id} did not finish within "
                f"{config.poll_timeout_seconds:g} seconds."
            )
        time.sleep(config.poll_interval_seconds)

    archive_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="gebco_", suffix=".zip", dir=config.raw_path.parent, delete=False
        ) as temporary:
            archive_path = Path(temporary.name)
        _download_queue_archive(http, config, basket_id, archive_path)
        _extract_single_geotiff(archive_path, config.raw_path)
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)

    LOGGER.info("Saved GEBCO GeoTIFF: %s", config.raw_path)
    return config.raw_path


def main() -> int:
    import argparse
    from .pipeline import load_bathymetry_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/project.yaml")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    config = load_bathymetry_config(args.config)
    download_gebco_geotiff(config, overwrite=args.overwrite)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
