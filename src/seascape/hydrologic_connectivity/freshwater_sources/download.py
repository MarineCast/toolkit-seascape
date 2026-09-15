"""Download river networks and river polygons needed to locate and size mouths."""

from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import tempfile
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

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"

SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "bc_stream_network": (
        "OBJECTID",
        "LINEAR_FEATURE_ID",
        "EDGE_TYPE",
        "BLUE_LINE_KEY",
        "WATERSHED_KEY",
        "FWA_WATERSHED_CODE",
        "LOCAL_WATERSHED_CODE",
        "WATERSHED_GROUP_CODE",
        "DOWNSTREAM_ROUTE_MEASURE",
        "LENGTH_METRE",
        "FEATURE_SOURCE",
        "GNIS_ID",
        "GNIS_NAME",
        "STREAM_ORDER",
        "STREAM_MAGNITUDE",
        "FEATURE_CODE",
    ),
    "bc_river_polygons": (
        "OBJECTID",
        "WATERBODY_POLY_ID",
        "WATERBODY_KEY",
        "AREA_HA",
        "GNIS_NAME_1",
        "BLUE_LINE_KEY",
        "FEATURE_CODE",
        "FEATURE_AREA_SQM",
        "FEATURE_LENGTH_M",
    ),
    "us_network_flowlines": (
        "objectid",
        "gnis_name",
        "lengthkm",
        "reachcode",
        "ftype",
        "fcode",
        "flowdir",
        "comid",
        "vpuid",
        "streamorde",
        "fromnode",
        "tonode",
        "hydroseq",
        "terminalpa",
        "terminalfl",
        "totdasqkm",
    ),
    "us_river_polygons": (
        "objectid",
        "permanent_identifier",
        "gnis_name",
        "areasqkm",
        "ftype",
        "fcode",
        "nhdplusid",
        "vpuid",
        "purpcode",
    ),
}


@dataclass(frozen=True)
class ArcGISSource:
    """One configured ArcGIS feature-layer extract."""

    name: str
    layer_url: str
    raw_path: Path
    where: str
    fields: tuple[str, ...]
    context_buffer_km: float
    query_tile_degrees: float


@dataclass(frozen=True)
class FreshwaterDownloadConfig:
    """Resolved paths and source parameters for acquisition."""

    bbox: dict[str, float]
    context_buffer_km: float
    arcgis_query_tile_degrees: float
    raw_dir: Path
    request_timeout_seconds: float
    overwrite: bool
    hydrorivers_url: str
    hydrorivers_archive_path: Path
    hydrorivers_extract_dir: Path
    arcgis_sources: tuple[ArcGISSource, ...]

    @property
    def context_bbox(self) -> dict[str, float]:
        """Return an approximate geodetic bbox expanded by the context distance."""

        return _expanded_bbox(self.bbox, self.context_buffer_km)

    def source_bbox(self, source: ArcGISSource) -> dict[str, float]:
        """Return the source-specific detailed-service query extent."""

        return _expanded_bbox(self.bbox, source.context_buffer_km)


def _expanded_bbox(bbox: Mapping[str, float], distance_km: float) -> dict[str, float]:
    """Expand a WGS84 bbox by an approximate metric distance."""

    latitude = (bbox["min_lat"] + bbox["max_lat"]) / 2.0
    latitude_padding = distance_km / 110.574
    longitude_padding = distance_km / (111.320 * max(math.cos(math.radians(latitude)), 0.1))
    return {
        "min_lon": bbox["min_lon"] - longitude_padding,
        "min_lat": bbox["min_lat"] - latitude_padding,
        "max_lon": bbox["max_lon"] + longitude_padding,
        "max_lat": bbox["max_lat"] + latitude_padding,
    }


def load_freshwater_download_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> FreshwaterDownloadConfig:
    """Load and validate the freshwater acquisition configuration."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("freshwater_sources"), "freshwater_sources")
    download = _mapping(section.get("download"), "freshwater_sources.download")
    sources = _mapping(download.get("sources"), "freshwater_sources.download.sources")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    raw_dir = _resolve(download["raw_dir"], base_dir)
    context_buffer_km = float(download.get("context_buffer_km", 250.0))
    tile_degrees = float(download.get("arcgis_query_tile_degrees", 1.0))
    timeout = float(download.get("request_timeout_seconds", 180.0))
    if context_buffer_km <= 0.0:
        raise ValueError("freshwater_sources.download.context_buffer_km must be positive.")
    if timeout <= 0.0:
        raise ValueError("freshwater_sources.download.request_timeout_seconds must be positive.")
    if not 0.1 <= tile_degrees <= 5.0:
        raise ValueError("arcgis_query_tile_degrees must be between 0.1 and 5 degrees.")

    hydrorivers = _mapping(sources.get("hydrorivers"), "sources.hydrorivers")
    arcgis_sources: list[ArcGISSource] = []
    for name, fields in SOURCE_FIELDS.items():
        source = _mapping(sources.get(name), f"sources.{name}")
        arcgis_sources.append(
            ArcGISSource(
                name=name,
                layer_url=str(source["layer_url"]).rstrip("/"),
                raw_path=raw_dir / str(source["raw_filename"]),
                where=str(source.get("where", "1=1")),
                fields=fields,
                context_buffer_km=float(source.get("context_buffer_km", context_buffer_km)),
                query_tile_degrees=float(source.get("query_tile_degrees", tile_degrees)),
            )
        )
    if any(source.context_buffer_km <= 0.0 for source in arcgis_sources):
        raise ValueError("ArcGIS source context buffers must be positive.")
    if any(not 0.1 <= source.query_tile_degrees <= 5.0 for source in arcgis_sources):
        raise ValueError("ArcGIS source query tiles must be between 0.1 and 5 degrees.")

    return FreshwaterDownloadConfig(
        bbox=bbox_from_config(section),
        context_buffer_km=context_buffer_km,
        arcgis_query_tile_degrees=tile_degrees,
        raw_dir=raw_dir,
        request_timeout_seconds=timeout,
        overwrite=bool(download.get("overwrite", False)),
        hydrorivers_url=str(hydrorivers["url"]),
        hydrorivers_archive_path=raw_dir / str(hydrorivers["archive_filename"]),
        hydrorivers_extract_dir=raw_dir / str(hydrorivers["extracted_directory"]),
        arcgis_sources=tuple(arcgis_sources),
    )


def _response_json(response: requests.Response, context: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"{context} request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context} returned a non-object JSON response.")
    if "error" in payload:
        raise RuntimeError(f"{context} returned an ArcGIS error: {payload['error']}")
    return payload


def _query_parameters(source: ArcGISSource, bbox: Mapping[str, float]) -> dict[str, Any]:
    envelope = ",".join(str(bbox[key]) for key in ("min_lon", "min_lat", "max_lon", "max_lat"))
    return {
        "f": "json",
        "where": source.where,
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
    }


def _query_tiles(
    bbox: Mapping[str, float],
    tile_degrees: float,
) -> list[dict[str, float]]:
    """Split a query envelope into bounded ArcGIS requests."""

    tiles: list[dict[str, float]] = []
    longitude = float(bbox["min_lon"])
    while longitude < float(bbox["max_lon"]):
        next_longitude = min(longitude + tile_degrees, float(bbox["max_lon"]))
        latitude = float(bbox["min_lat"])
        while latitude < float(bbox["max_lat"]):
            next_latitude = min(latitude + tile_degrees, float(bbox["max_lat"]))
            tiles.append(
                {
                    "min_lon": longitude,
                    "min_lat": latitude,
                    "max_lon": next_longitude,
                    "max_lat": next_latitude,
                }
            )
            latitude = next_latitude
        longitude = next_longitude
    return tiles


def _arcgis_object_ids(
    session: requests.Session,
    source: ArcGISSource,
    *,
    bbox: Mapping[str, float],
    tile_degrees: float,
    timeout: float,
) -> tuple[list[int], str]:
    """Collect unique object IDs with tiled requests to avoid service proxy limits."""

    tiles = _query_tiles(bbox, tile_degrees)
    object_ids: set[int] = set()
    object_id_field = "OBJECTID"
    for index, tile in enumerate(tiles, start=1):
        id_params = _query_parameters(source, tile)
        id_params["returnIdsOnly"] = "true"
        payload = _response_json(
            session.get(f"{source.layer_url}/query", params=id_params, timeout=timeout),
            f"{source.name} object-ID tile {index}/{len(tiles)}",
        )
        object_ids.update(int(value) for value in payload.get("objectIds") or [])
        object_id_field = str(payload.get("objectIdFieldName") or object_id_field)
        if index % 10 == 0 or index == len(tiles):
            LOGGER.info(
                "Queried %s ID tiles: %d/%d (%d unique features)",
                source.name,
                index,
                len(tiles),
                len(object_ids),
            )
    return sorted(object_ids), object_id_field


def _download_arcgis_geojson(
    session: requests.Session,
    source: ArcGISSource,
    *,
    bbox: Mapping[str, float],
    tile_degrees: float,
    timeout: float,
    overwrite: bool,
) -> tuple[Path, int]:
    if source.raw_path.exists() and not overwrite:
        with source.raw_path.open(encoding="utf-8") as existing:
            count = len(json.load(existing).get("features", []))
        LOGGER.info(
            "Using existing %s extract (%d features): %s", source.name, count, source.raw_path
        )
        return source.raw_path, count

    source.raw_path.parent.mkdir(parents=True, exist_ok=True)
    object_ids, object_id_field = _arcgis_object_ids(
        session,
        source,
        bbox=bbox,
        tile_degrees=tile_degrees,
        timeout=timeout,
    )
    features: list[dict[str, Any]] = []
    chunk_size = 500
    for start in range(0, len(object_ids), chunk_size):
        chunk = object_ids[start : start + chunk_size]
        params = {
            "f": "geojson",
            "objectIds": ",".join(map(str, chunk)),
            "outFields": ",".join(source.fields),
            "returnGeometry": "true",
            "returnZ": "false",
            "returnM": "false",
            "outSR": "4326",
        }
        response = session.get(f"{source.layer_url}/query", params=params, timeout=timeout)
        geojson = _response_json(response, f"{source.name} feature query")
        batch = geojson.get("features")
        if not isinstance(batch, list):
            raise RuntimeError(f"{source.name} query did not return a GeoJSON feature list.")
        features.extend(batch)
        downloaded = min(start + len(chunk), len(object_ids))
        if downloaded % 10_000 == 0 or downloaded == len(object_ids):
            LOGGER.info(
                "Downloaded %s features: %d/%d",
                source.name,
                downloaded,
                len(object_ids),
            )

    if len(features) != len(object_ids):
        returned = {
            int(feature.get("properties", {}).get(object_id_field))
            for feature in features
            if feature.get("properties", {}).get(object_id_field) is not None
        }
        missing = sorted(set(object_ids).difference(returned))
        raise RuntimeError(
            f"{source.name} returned {len(features)} features for {len(object_ids)} IDs; "
            f"missing {len(missing)} IDs."
        )

    document = {
        "type": "FeatureCollection",
        "name": source.name,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    partial = source.raw_path.with_suffix(source.raw_path.suffix + ".part")
    try:
        with partial.open("w", encoding="utf-8") as output:
            json.dump(document, output, separators=(",", ":"))
        partial.replace(source.raw_path)
    finally:
        partial.unlink(missing_ok=True)
    LOGGER.info("Saved %s extract (%d features): %s", source.name, len(features), source.raw_path)
    return source.raw_path, len(features)


def _download_file(
    session: requests.Session,
    url: str,
    destination: Path,
    *,
    timeout: float,
    overwrite: bool,
) -> Path:
    if destination.exists() and not overwrite:
        LOGGER.info("Using existing archive: %s", destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with session.get(url, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
        partial.replace(destination)
    except requests.RequestException as exc:
        raise RuntimeError(f"Download failed for {url}: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)
    LOGGER.info("Saved archive: %s", destination)
    return destination


def _extract_zip(archive_path: Path, destination: Path, *, overwrite: bool) -> Path:
    shapefiles = sorted(destination.rglob("*.shp")) if destination.exists() else []
    if shapefiles and not overwrite:
        LOGGER.info("Using existing HydroRIVERS extraction: %s", destination)
        return destination
    if not zipfile.is_zipfile(archive_path):
        raise RuntimeError(f"HydroRIVERS download is not a ZIP archive: {archive_path}")
    destination.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="hydrorivers_extract_", dir=destination.parent))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                member_path = (temporary / member.filename).resolve()
                if (
                    temporary.resolve() not in member_path.parents
                    and member_path != temporary.resolve()
                ):
                    raise RuntimeError(f"Unsafe path in HydroRIVERS archive: {member.filename}")
            archive.extractall(temporary)
        extracted_shapefiles = sorted(temporary.rglob("*.shp"))
        if len(extracted_shapefiles) != 1:
            raise RuntimeError(
                "Expected one HydroRIVERS Shapefile; "
                f"found {len(extracted_shapefiles)} in {archive_path}."
            )
        if destination.exists() and overwrite:
            shutil.rmtree(destination)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    LOGGER.info("Extracted HydroRIVERS: %s", destination)
    return destination


def download_freshwater_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    overwrite: bool | None = None,
    session: requests.Session | None = None,
) -> tuple[Path, ...]:
    """Download, extract, and inventory all configured freshwater sources."""

    config = load_freshwater_download_config(config_path)
    overwrite = config.overwrite if overwrite is None else bool(overwrite)
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", "Seascape Toolkit/0.1 river-mouth builder")

    archive = _download_file(
        http,
        config.hydrorivers_url,
        config.hydrorivers_archive_path,
        timeout=config.request_timeout_seconds,
        overwrite=overwrite,
    )
    extracted = _extract_zip(archive, config.hydrorivers_extract_dir, overwrite=overwrite)

    outputs: list[Path] = [archive, extracted]
    records: dict[str, int] = {}
    query_bboxes: dict[str, dict[str, float]] = {}
    for source in config.arcgis_sources:
        source_bbox = config.source_bbox(source)
        output, count = _download_arcgis_geojson(
            http,
            source,
            bbox=source_bbox,
            tile_degrees=source.query_tile_degrees,
            timeout=config.request_timeout_seconds,
            overwrite=overwrite,
        )
        outputs.append(output)
        records[source.name] = count
        query_bboxes[source.name] = source_bbox

    manifest = {
        "schema_version": 1,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "model_bbox_wgs84": config.bbox,
        "hydrorivers_context_bbox_wgs84": config.context_bbox,
        "hydrorivers_context_buffer_km": config.context_buffer_km,
        "arcgis_query_tile_degrees": config.arcgis_query_tile_degrees,
        "sources": {
            "hydrorivers": {
                "url": config.hydrorivers_url,
                "archive": str(archive),
                "sha256": _sha256(archive),
            },
            **{
                source.name: {
                    "layer_url": source.layer_url,
                    "where": source.where,
                    "context_buffer_km": source.context_buffer_km,
                    "query_tile_degrees": source.query_tile_degrees,
                    "query_bbox_wgs84": query_bboxes[source.name],
                    "path": str(source.raw_path),
                    "feature_count": records[source.name],
                    "sha256": _sha256(source.raw_path),
                }
                for source in config.arcgis_sources
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
    outputs.append(manifest_path)
    LOGGER.info("Saved freshwater-source download manifest: %s", manifest_path)
    return tuple(outputs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for path in download_freshwater_sources(args.config, overwrite=args.overwrite):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
