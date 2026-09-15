"""Configuration contract for canonical H3 marine support and water networks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"


def _resolutions(value: Any) -> tuple[int, ...]:
    raw = (value,) if isinstance(value, int) else tuple(value)
    resolutions = tuple(dict.fromkeys(int(item) for item in raw))
    if not resolutions:
        raise ValueError("water_network.resolutions must not be empty.")
    if any(item not in {6, 8} for item in resolutions):
        raise ValueError("water_network.resolutions currently supports exactly H3 r6 and r8.")
    return resolutions


@dataclass(frozen=True)
class WaterNetworkConfig:
    """Resolved configuration for the canonical spatial-support product family."""

    bbox: dict[str, float]
    model_bbox: dict[str, float]
    resolutions: tuple[int, ...]
    water_mask_version: str
    spatial_support_version: str
    water_polygon_path: Path
    h3_geometry_output_dir: Path
    output_dir: Path
    support_filename_template: str
    model_support_filename_template: str
    full_geometry_filename_template: str
    clipped_geometry_filename_template: str
    edge_filename_template: str
    connector_filename_template: str
    neighborhood_filename_template: str
    radius_sum_operator_filename: str
    reachable_water_area_filename: str
    canonical_radius_m: float
    parent_child_filename: str
    maximum_neighborhood_hops: int
    minimum_water_fraction: float
    minimum_water_area_m2: float
    area_tolerance_m2: float
    passability_tolerance_m: float
    geodesic_segment_max_m: float
    connector_max_distance_m: dict[int, float]
    connector_candidate_limit: int
    edge_chunk_size: int
    max_workers: int

    def support_path(self, resolution: int) -> Path:
        return self.h3_geometry_output_dir / self.support_filename_template.format(res=resolution)

    def model_support_path(self, resolution: int) -> Path:
        return self.h3_geometry_output_dir / self.model_support_filename_template.format(
            res=resolution
        )

    def full_geometry_path(self, resolution: int) -> Path:
        return self.h3_geometry_output_dir / self.full_geometry_filename_template.format(
            res=resolution
        )

    def clipped_geometry_path(self, resolution: int) -> Path:
        return self.h3_geometry_output_dir / self.clipped_geometry_filename_template.format(
            res=resolution
        )

    def edge_path(self, resolution: int) -> Path:
        return self.output_dir / self.edge_filename_template.format(res=resolution)

    def connector_path(self, resolution: int) -> Path:
        return self.output_dir / self.connector_filename_template.format(res=resolution)

    def neighborhood_path(self, resolution: int) -> Path:
        return self.output_dir / self.neighborhood_filename_template.format(res=resolution)

    @property
    def radius_sum_operator_path(self) -> Path:
        return self.output_dir / self.radius_sum_operator_filename

    @property
    def reachable_water_area_path(self) -> Path:
        return self.output_dir / self.reachable_water_area_filename

    @property
    def parent_child_path(self) -> Path:
        return self.h3_geometry_output_dir / self.parent_child_filename

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "_dataset_manifest.json"


def load_water_network_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> WaterNetworkConfig:
    """Load and validate the canonical marine-support configuration."""

    raw = load_data_config(resolve_config_path(config_path), domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("water_network"), "water_network")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    resolutions = _resolutions(section.get("resolutions", (6, 8)))
    connector_raw = _mapping(
        section.get("connector_max_distance_m", {6: 7500.0, 8: 1000.0}),
        "water_network.connector_max_distance_m",
    )
    connector_limits = {
        resolution: float(connector_raw.get(resolution, connector_raw.get(str(resolution), 0.0)))
        for resolution in resolutions
    }
    numeric_positive = {
        "minimum_water_area_m2": float(section.get("minimum_water_area_m2", 1.0)),
        "area_tolerance_m2": float(section.get("area_tolerance_m2", 1.0)),
        "passability_tolerance_m": float(section.get("passability_tolerance_m", 1.0)),
        "geodesic_segment_max_m": float(section.get("geodesic_segment_max_m", 100.0)),
    }
    if any(value <= 0.0 for value in numeric_positive.values()):
        raise ValueError(f"Water-network metric tolerances must be positive: {numeric_positive}")
    minimum_fraction = float(section.get("minimum_water_fraction", 0.01))
    if not 0.0 <= minimum_fraction <= 1.0:
        raise ValueError("water_network.minimum_water_fraction must be in [0, 1].")
    if any(value <= 0.0 for value in connector_limits.values()):
        raise ValueError("Every configured connector maximum must be positive.")
    candidate_limit = int(section.get("connector_candidate_limit", 16))
    chunk_size = int(section.get("edge_chunk_size", 50_000))
    workers = int(section.get("max_workers", 8))
    maximum_neighborhood_hops = int(section.get("maximum_neighborhood_hops", 4))
    canonical_radius_m = float(section.get("canonical_radius_m", 5000.0))
    if min(candidate_limit, chunk_size, workers, maximum_neighborhood_hops) < 1:
        raise ValueError(
            "Connector candidate limit, edge chunk size, workers, and maximum "
            "neighborhood hops must be positive."
        )
    if canonical_radius_m <= 0:
        raise ValueError("water_network.canonical_radius_m must be positive.")
    water_mask_version = str(section.get("water_mask_version", "")).strip()
    support_version = str(section.get("spatial_support_version", "")).strip()
    if not water_mask_version or not support_version:
        raise ValueError("Water-mask and spatial-support versions must be non-empty.")
    return WaterNetworkConfig(
        bbox=bbox_from_config(section),
        model_bbox=bbox_from_config({"area": section.get("model_area", "model_area")}),
        resolutions=resolutions,
        water_mask_version=water_mask_version,
        spatial_support_version=support_version,
        water_polygon_path=_resolve(section["water_polygon_path"], base_dir),
        h3_geometry_output_dir=_resolve(section["h3_geometry_output_dir"], base_dir),
        output_dir=_resolve(section["output_dir"], base_dir),
        support_filename_template=str(
            section.get("support_filename_template", "H3_MARINE_SUPPORT_RES_{res}.parquet")
        ),
        model_support_filename_template=str(
            section.get(
                "model_support_filename_template",
                "H3_MODEL_AREA_SUPPORT_RES_{res}.parquet",
            )
        ),
        full_geometry_filename_template=str(
            section.get(
                "full_geometry_filename_template",
                "H3_MARINE_FULL_CELL_GEOMETRY_RES_{res}.parquet",
            )
        ),
        clipped_geometry_filename_template=str(
            section.get(
                "clipped_geometry_filename_template",
                "H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_{res}.parquet",
            )
        ),
        edge_filename_template=str(
            section.get("edge_filename_template", "H3_WATER_PASSABLE_EDGES_RES_{res}.parquet")
        ),
        connector_filename_template=str(
            section.get("connector_filename_template", "H3_WATER_CONNECTORS_RES_{res}.parquet")
        ),
        neighborhood_filename_template=str(
            section.get(
                "neighborhood_filename_template",
                "H3_WATER_NEIGHBORHOODS_RES_{res}.parquet",
            )
        ),
        radius_sum_operator_filename=str(
            section.get(
                "radius_sum_operator_filename",
                "H3_WATER_RADIUS_OPERATOR_RES_8_5000M.npz",
            )
        ),
        reachable_water_area_filename=str(
            section.get(
                "reachable_water_area_filename",
                "H3_REACHABLE_WATER_AREA_RES_8_5000M.parquet",
            )
        ),
        canonical_radius_m=canonical_radius_m,
        parent_child_filename=str(
            section.get("parent_child_filename", "H3_PARENT_CHILD_RES_8_TO_RES_6.parquet")
        ),
        maximum_neighborhood_hops=maximum_neighborhood_hops,
        minimum_water_fraction=minimum_fraction,
        minimum_water_area_m2=numeric_positive["minimum_water_area_m2"],
        area_tolerance_m2=numeric_positive["area_tolerance_m2"],
        passability_tolerance_m=numeric_positive["passability_tolerance_m"],
        geodesic_segment_max_m=numeric_positive["geodesic_segment_max_m"],
        connector_max_distance_m=connector_limits,
        connector_candidate_limit=candidate_limit,
        edge_chunk_size=chunk_size,
        max_workers=workers,
    )
