"""Acquire OSM mapping from checksum-bound regional extracts without Overpass."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import requests


def _digest(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def _elements(
    stream: BinaryIO, bbox: Mapping[str, float], *, max_nodes: int, max_elements: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Resolve node/way/relation bounds, retaining the existing center semantics."""
    bounds: dict[tuple[str, int], tuple[float, float, float, float]] = {}
    relations: dict[int, list[tuple[str, int]]] = {}
    candidates: dict[tuple[str, int], dict[str, Any]] = {}
    nodes = 0
    events = ET.iterparse(stream, events=("start", "end"))
    _, root = next(events)
    for event, item in events:
        if event != "end" or item.tag not in {"node", "way", "relation"}:
            continue
        kind, identity = item.tag, int(item.attrib["id"])
        key = (kind, identity)
        if kind == "node":
            nodes += 1
            if nodes > max_nodes:
                raise ValueError("OSM referenced-node budget exceeded")
            lon, lat = float(item.attrib["lon"]), float(item.attrib["lat"])
            bounds[key] = (lon, lat, lon, lat)
        elif kind == "way":
            references = [("node", int(nd.attrib["ref"])) for nd in item.findall("nd")]
            if references and all(ref in bounds for ref in references):
                values = [bounds[ref] for ref in references]
                bounds[key] = (
                    min(b[0] for b in values),
                    min(b[1] for b in values),
                    max(b[2] for b in values),
                    max(b[3] for b in values),
                )
        else:
            relations[identity] = [
                (member.attrib["type"], int(member.attrib["ref"]))
                for member in item.findall("member")
            ]
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in item.findall("tag")}
        if tags:
            record = {
                "type": kind,
                "id": identity,
                "tags": tags,
                "version": int(item.attrib.get("version", 0)),
                "timestamp": item.attrib.get("timestamp"),
            }
            previous = candidates.get(key)
            if previous is None or record["version"] >= previous["version"]:
                candidates[key] = record
            if len(candidates) > max_elements:
                raise ValueError("OSM tagged-element budget exceeded")
        root.clear()

    def resolve(key: tuple[str, int], visiting: set[tuple[str, int]]) -> Any:
        if key in bounds:
            return bounds[key]
        if key in visiting or key[0] != "relation" or len(visiting) >= 100:
            return None
        references = relations.get(key[1], [])
        values = [resolve(ref, visiting | {key}) for ref in references]
        if not values or any(value is None for value in values):
            return None
        result = (
            min(b[0] for b in values),
            min(b[1] for b in values),
            max(b[2] for b in values),
            max(b[3] for b in values),
        )
        bounds[key] = result
        return result

    selected = []
    for key, record in sorted(candidates.items()):
        extent = resolve(key, set())
        if extent is None:
            # Incomplete reference closure is an acquisition failure, never an
            # empty-source substitute or a guessed feature center.
            raise ValueError(f"OSM extract has incomplete geometry references: {key}")
        west, south, east, north = extent
        if (
            east < bbox["min_lon"]
            or west > bbox["max_lon"]
            or north < bbox["min_lat"]
            or south > bbox["max_lat"]
        ):
            continue
        lon, lat = (west + east) / 2, (south + north) / 2
        if key[0] == "node":
            record.update(lon=lon, lat=lat)
        else:
            record["center"] = {"lon": lon, "lat": lat}
        selected.append(record)
    return selected, {"referenced_nodes": nodes, "tagged_objects": len(candidates)}


def download_osm_extract(
    session: requests.Session,
    source: Mapping[str, Any],
    destination: Path,
    *,
    bbox: Mapping[str, float],
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    """Filter retained PBF inputs and emit source-qualified OSM center records."""
    from .habitat_acquisition import _download_http_file

    executable = shutil.which("osmium")
    if executable is None:
        raise RuntimeError("OSM extract acquisition requires osmium-tool on PATH")
    if source.get("geometry_mode", "center") != "center":
        raise ValueError(
            "OSM extract acquisition currently supports center geometry only"
        )
    coverage = source.get("supported_bbox")
    if coverage and (
        bbox["min_lon"] < coverage["min_lon"]
        or bbox["max_lon"] > coverage["max_lon"]
        or bbox["min_lat"] < coverage["min_lat"]
        or bbox["max_lat"] > coverage["max_lat"]
    ):
        raise ValueError("Configure OSM extracts covering the requested source extent")
    extracts, filters = source.get("extracts"), source.get("tag_filters")
    if not extracts or not filters:
        raise ValueError("OSM extracts and tag_filters must be configured")
    cache = Path(source.get("extract_cache_dir", destination.parent / "osm-pbf"))
    if not cache.is_absolute():
        cache = destination.parent / cache
    cache.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipts, paths = [], []
    for item in extracts:
        if shutil.disk_usage(cache).free < 20 * 1024**3:
            raise RuntimeError("OSM extraction requires a 20 GiB free-space reserve")
        if item.get("path"):
            path = Path(item["path"])
            if _digest(path) != item["sha256"]:
                raise ValueError(f"OSM local source checksum mismatch: {path}")
            expected = None
        else:
            response = session.get(item["md5_url"], timeout=timeout)
            response.raise_for_status()
            expected = response.text.split()[0]
            if len(expected) != 32 or any(
                c not in "0123456789abcdef" for c in expected
            ):
                raise ValueError("OSM source returned an invalid MD5 identity")
            path = cache / f"{item['name']}-{expected}.osm.pbf"
            if not path.exists():
                _download_http_file(
                    session,
                    {
                        "url": item["url"],
                        "md5": expected,
                        "maximum_bytes": item.get("maximum_bytes", 2 * 1024**3),
                    },
                    path,
                    timeout=timeout,
                )
            if _digest(path, "md5") != expected:
                raise ValueError(f"OSM source MD5 mismatch: {path}")
        paths.append(path)
        receipts.append(
            {
                "path": str(path),
                "url": item.get("url"),
                "md5": expected,
                "sha256": _digest(path),
                "bytes": path.stat().st_size,
            }
        )
    seconds = float(source.get("processing_timeout_seconds", 1800))
    with tempfile.TemporaryDirectory(
        prefix="osm-extract-", dir=destination.parent
    ) as temp:
        work = Path(temp)
        filtered = []
        for index, path in enumerate(paths):
            target = work / f"selected-{index}.osm.pbf"
            subprocess.run(
                [
                    executable,
                    "tags-filter",
                    str(path),
                    *filters,
                    "--remove-tags",
                    "-o",
                    str(target),
                ],
                check=True,
                timeout=seconds,
                capture_output=True,
            )
            filtered.append(str(target))
        merged = work / "merged.osm.pbf"
        subprocess.run(
            [executable, "merge", *filtered, "-o", str(merged)],
            check=True,
            timeout=seconds,
            capture_output=True,
        )
        xml = work / "selected.osm"
        subprocess.run(
            [executable, "cat", str(merged), "-f", "osm", "-o", str(xml)],
            check=True,
            timeout=seconds,
            capture_output=True,
        )
        with xml.open("rb") as stream:
            elements, statistics = _elements(
                stream,
                bbox,
                max_nodes=int(source.get("maximum_nodes", 2_000_000)),
                max_elements=int(source.get("maximum_elements", 500_000)),
            )
    if not elements:
        raise RuntimeError(
            "OSM extracts returned no selected objects in the requested extent"
        )
    metadata = {
        "method": "geofabrik_pbf_reference_closed_centers_v1",
        "geometry_mode": "center",
        "bbox": dict(bbox),
        "extracts": receipts,
        "tag_filters": list(filters),
        "statistics": statistics,
        "selection": "object_bounding_box_intersects_source_extent",
        "area_footprints_qualified": False,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
        "osmium_version": subprocess.check_output(
            [executable, "--version"], text=True
        ).splitlines()[0],
    }
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        partial.write_text(json.dumps({"elements": elements, "_orcacast": metadata}))
        limit = int(source.get("maximum_bytes", 128 * 1024**2))
        if partial.stat().st_size > limit:
            raise ValueError("OSM selected-source byte budget exceeded")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return len(elements), {"osm_extract": metadata}
