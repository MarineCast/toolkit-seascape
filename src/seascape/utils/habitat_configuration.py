"""Configuration and canonical-geometry alignment for habitat surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)

from .config import require_mapping, resolve_project_path


@dataclass(frozen=True)
class HabitatSurfaceConfig:
    """Resolved output and spatial-support settings for one habitat family."""

    section_name: str
    prefix: str
    bbox: dict[str, float]
    native_resolution: int
    model_resolution: int
    equal_area_crs: str
    reference_year: int
    marine_buffer_m: float
    processed_dir: Path
    inventory_path: Path
    feature_filename_template: str
    confidence_filename_template: str
    manifest_path: Path
    clipped_geometry_path: Path
    parent_child_path: Path

    def feature_path(self, resolution: int) -> Path:
        return self.processed_dir / self.feature_filename_template.format(res=resolution)

    def confidence_path(self, resolution: int) -> Path:
        return self.processed_dir / self.confidence_filename_template.format(res=resolution)


def load_habitat_surface_config(
    section_name: str,
    prefix: str,
    config_path: str | Path,
) -> HabitatSurfaceConfig:
    """Load and validate the H3 r8-to-r6 habitat build contract."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = require_mapping(raw.get(section_name), section_name)
    processing = require_mapping(section.get("processing"), f"{section_name}.processing")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    native_resolution = int(processing.get("native_h3_resolution", 8))
    model_resolution = int(processing.get("model_h3_resolution", 6))
    if (native_resolution, model_resolution) != (8, 6):
        raise ValueError(f"{section_name} must process at H3 r8 and aggregate to H3 r6.")
    reference_year = int(processing.get("reference_year", datetime.now(UTC).year))
    radius = float(processing.get("marine_buffer_m", 5_000.0))
    if reference_year < 1900 or radius <= 0:
        raise ValueError("Habitat reference year and marine buffer must be positive and valid.")
    processed_dir = resolve_project_path(processing["processed_directory"], base_dir)
    network = load_water_network_config(path)
    return HabitatSurfaceConfig(
        section_name=section_name,
        prefix=prefix.strip().upper(),
        bbox=bbox_from_config(section),
        native_resolution=native_resolution,
        model_resolution=model_resolution,
        equal_area_crs=str(processing.get("equal_area_crs", "EPSG:6933")),
        reference_year=reference_year,
        marine_buffer_m=radius,
        processed_dir=processed_dir,
        inventory_path=processed_dir / str(processing["inventory_filename"]),
        feature_filename_template=str(processing["feature_filename_template"]),
        confidence_filename_template=str(processing["confidence_filename_template"]),
        manifest_path=processed_dir / str(processing["manifest_filename"]),
        clipped_geometry_path=network.clipped_geometry_path(native_resolution),
        parent_child_path=network.parent_child_path,
    )


def model_bbox_tuple(config: HabitatSurfaceConfig) -> tuple[float, float, float, float]:
    return tuple(float(config.bbox[key]) for key in ("min_lon", "min_lat", "max_lon", "max_lat"))


def load_cell_geometry(config: HabitatSurfaceConfig, support: pd.DataFrame):
    """Load water-clipped H3 geometry aligned exactly to canonical support."""

    import geopandas as gpd

    if not config.clipped_geometry_path.exists():
        raise FileNotFoundError(
            f"Canonical water-clipped H3 geometry not found: {config.clipped_geometry_path}"
        )
    geometry = gpd.read_parquet(config.clipped_geometry_path, columns=["H3_INDEX", "geometry"])
    selected = set(support["H3_INDEX"].astype(str))
    geometry = geometry.loc[geometry["H3_INDEX"].astype(str).isin(selected)].copy()
    geometry["H3_INDEX"] = geometry["H3_INDEX"].astype("string")
    geometry = geometry.set_index("H3_INDEX").loc[support["H3_INDEX"].astype(str)].reset_index()
    if len(geometry) != len(support) or geometry.geometry.isna().any():
        raise ValueError("H3 water-clipped geometry and canonical support do not align.")
    return geometry


__all__ = [
    "HabitatSurfaceConfig",
    "load_cell_geometry",
    "load_habitat_surface_config",
    "model_bbox_tuple",
]
