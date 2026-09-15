"""Configuration boundary for canonical territorial-water geometry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.config import (
    require_mapping,
    resolve_project_path,
)

DEFAULT_PROCESSED_OUT_DIR = (
    "data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry"
)
DEFAULT_WATER_POLYGON_FILENAME = "TERRITORIAL_WATER_POLYGON.parquet"


def load_water_geometry_config(config_path: str | Path) -> dict[str, Any]:
    """Load configuration for the canonical territorial-water product."""

    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    water_geometry = require_mapping(raw.get("water_geometry", {}), "water_geometry")
    build = require_mapping(
        water_geometry.get("build", {}),
        "water_geometry.build",
    )
    download = require_mapping(water_geometry.get("download", {}), "water_geometry.download")
    base_dir = (project_root() / Path(raw.get("base_directory", ".")).expanduser()).resolve()
    output_dir = resolve_project_path(
        water_geometry.get(
            "processed_out_dir",
            DEFAULT_PROCESSED_OUT_DIR,
        ),
        base_dir,
    )
    sources = download.get("sources") or {}
    return {
        "base_dir": base_dir,
        "output_path": output_dir
        / str(build.get("output_filename", DEFAULT_WATER_POLYGON_FILENAME)),
        "bbox": bbox_from_config(build),
        "alaska_boundary_snap_tolerance_m": float(
            build.get("alaska_boundary_snap_tolerance_m", 75_000.0)
        ),
        "raw_paths": require_mapping(sources, "water_geometry.download.sources"),
        "log_level": str(raw.get("log_level", "INFO")).upper(),
    }
