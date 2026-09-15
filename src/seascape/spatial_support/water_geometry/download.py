"""Resolve and download raw GIS inputs used by the water-geometry builder."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import (
    resolve_project_path as _resolve_project_path,
)

DEFAULT_RAW_MARINE_SOURCE_PATHS = {
    "ca_regions_path": (
        "data/raw/gis/marine/FederalMarineBioregions_SHP/FederalMarineBioregions.shp"
    ),
    "wsdot_shorelines_path": (
        "data/raw/gis/marine/WSDOT_-_Major_Shorelines/WSDOT_-_Major_Shorelines.shp"
    ),
    "ws_marine_shoreline_type_path": (
        "data/raw/gis/marine/shstmp-ps-marine-shorelines-2018-nwfsc/"
        "SHSTMP_PS_Marine_Shorelines_2018.shp"
    ),
    "us_coastline_path": ("data/raw/gis/marine/tl_2022_us_coastline/tl_2022_us_coastline.shp"),
    "tz_file_path": "data/raw/gis/marine/World_12NM_v4_20231025/eez_12nm_v4.shp",
    "us_waters_path": (
        "data/raw/gis/marine/USMaritimeLimitsAndBoundariesSHP/" "USMaritimeLimitsNBoundaries.shp"
    ),
}

CONSUMED_WATER_GEOMETRY_SOURCE_NAMES: tuple[str, ...] = tuple(DEFAULT_RAW_MARINE_SOURCE_PATHS)


def _source_path(value: Any, name: str) -> str | Path:
    if isinstance(value, Mapping):
        path = value.get("path")
        if not path:
            raise ValueError(f"Water-geometry source {name!r} is missing 'path'.")
        return str(path)
    if not isinstance(value, (str, Path)):
        raise ValueError(f"Water-geometry source {name!r} must be a path or mapping.")
    return value


def load_water_geometry_source_config(config_path: str | Path) -> dict[str, Any]:
    """Load the configured local paths and optional direct-download URLs."""

    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    water_geometry = _mapping(raw.get("water_geometry", {}), "water_geometry")
    download = _mapping(water_geometry.get("download", {}), "water_geometry.download")
    configured_sources = download.get("sources") or {}
    configured_sources = _mapping(configured_sources, "water_geometry.download.sources")
    sources = {**DEFAULT_RAW_MARINE_SOURCE_PATHS, **configured_sources}
    base_dir = (project_root() / Path(raw.get("base_directory", ".")).expanduser()).resolve()
    return {"base_dir": base_dir, "sources": sources}


def resolve_water_geometry_paths(config_dict: dict[str, Any]) -> dict[str, str]:
    """Resolve raw marine GIS source paths from a builder config dictionary."""

    raw_paths = {
        **DEFAULT_RAW_MARINE_SOURCE_PATHS,
        **dict(config_dict.get("raw_paths", {}) or {}),
    }
    base_dir = Path(config_dict["base_dir"])
    return {
        name: str(_resolve_project_path(_source_path(value, name), base_dir))
        for name, value in raw_paths.items()
    }


def _download_file(url: str, output_path: Path, *, overwrite: bool) -> Path:
    if output_path.exists() and not overwrite:
        return output_path
    if output_path.exists() and output_path.is_dir():
        raise IsADirectoryError(f"Cannot replace directory with a direct download: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        with requests.get(url, stream=True, timeout=180) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def download_water_geometry_sources(
    config_path: str | Path = "config/data/project.yaml",
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    """Materialize configured raw sources or validate their existing local paths.

    A source may be a path string or ``{path: ..., url: ...}``. Direct URLs are
    downloaded atomically. Archive extraction remains explicit: configure the
    extracted dataset path consumed by GeoPandas.
    """

    config = load_water_geometry_source_config(config_path)
    base_dir = Path(config["base_dir"])
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name, value in config["sources"].items():
        output_path = _resolve_project_path(_source_path(value, name), base_dir)
        url = str(value.get("url", "")).strip() if isinstance(value, Mapping) else ""
        if url and (overwrite or not output_path.exists()):
            _download_file(url, output_path, overwrite=overwrite)
        if not output_path.exists():
            missing.append(f"{name}: {output_path}")
        resolved[name] = str(output_path)
    if missing:
        details = "\n  - ".join(missing)
        raise FileNotFoundError(
            "Missing water-geometry sources. Provide local paths or {path, url} "
            f"entries in water_geometry.download.sources:\n  - {details}"
        )
    return resolved


def open_water_geometry_sources(
    data_paths: Mapping[str, str | Path],
    *,
    default_crs: str = "EPSG:4326",
) -> tuple[gpd.GeoDataFrame, ...]:
    """Open the source layers required to build the territorial-water geometry."""

    missing = sorted(set(CONSUMED_WATER_GEOMETRY_SOURCE_NAMES) - set(data_paths))
    if missing:
        raise ValueError(f"Missing consumed water-geometry source path(s): {missing}")

    us_waters = gpd.read_file(data_paths["us_waters_path"]).to_crs(default_crs)
    us_coastline = gpd.read_file(data_paths["us_coastline_path"])
    wsdot_shorelines = gpd.read_file(data_paths["wsdot_shorelines_path"]).to_crs(default_crs)
    ws_marine_shoreline = gpd.read_file(data_paths["ws_marine_shoreline_type_path"])
    ws_marine_shoreline = ws_marine_shoreline[["geometry"]].dissolve().explode()
    ws_marine_shoreline = ws_marine_shoreline.to_crs(default_crs)
    ca_waters = gpd.read_file(data_paths["ca_regions_path"])
    tz_canada = gpd.read_file(data_paths["tz_file_path"])
    return (
        us_waters,
        us_coastline,
        wsdot_shorelines,
        ws_marine_shoreline,
        ca_waters,
        tz_canada,
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Download or validate water-geometry sources.")
    parser.add_argument("--config", default="config/data/project.yaml")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    for name, path in download_water_geometry_sources(
        args.config, overwrite=args.overwrite
    ).items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
