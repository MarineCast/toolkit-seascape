"""Orchestrate GEBCO download, H3 build, and inspection-map generation."""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.config.presentation import DEFAULT_PRESENTATION_CONFIG_PATH
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.h3 import cell_to_parent
from seascape.publication import (
    TransactionalSeascapePublisher,
)
from seascape.utils.artifacts import (
    build_manifest,
    capture_staged_parquet_artifact,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import (
    resolve_project_path,
)

from .build import DEPTH_BANDS_M, build_bathymetry_parquet
from .download import download_gebco_geotiff
from .inspect import build_bathymetry_map


@dataclass(frozen=True)
class BathymetryExportConfig:
    """One additional H3 aggregation export."""

    h3_resolution: int
    processed_path: Path


@dataclass(frozen=True)
class BathymetryConfig:
    """Resolved configuration shared by all bathymetry stages."""

    bbox: dict[str, float]
    provider: str
    release: str
    native_resolution_arc_seconds: float
    grid_name: str
    data_source_name: str
    format_name: str
    api_base_url: str
    raw_path: Path
    request_timeout_seconds: float
    poll_interval_seconds: float
    poll_timeout_seconds: float
    overwrite: bool
    h3_resolution: int
    h3_grid_path_template: str
    h3_grid_path: Path
    water_polygon_path: Path
    processed_path: Path
    bathymetry_sign: str
    depth_quantiles: tuple[float, ...]
    local_depth_anomaly_neighborhood_rings: int
    water_neighborhood_path_template: str
    isobath_levels_m: tuple[float, ...]
    isobath_distance_projected_crs: str
    smoothing_projected_crs: str
    smoothing_output_crs: str
    smoothing_analysis_pixel_size_m: float
    smoothing_output_pixel_size_m: float
    smoothing_gaussian_sigma_km: float
    smoothing_fill_opacity: float
    additional_exports: tuple[BathymetryExportConfig, ...]


def _required(section: Mapping[str, Any], name: str, key: str) -> Any:
    if key not in section or section[key] in (None, ""):
        raise ValueError(f"Missing required config key: {name}.{key}")
    return section[key]


def load_bathymetry_config(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> BathymetryConfig:
    """Load and resolve the bathymetry section of the seascape configuration."""

    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("bathymetry"), "bathymetry")
    source = _mapping(section.get("source"), "bathymetry.source")
    processing = _mapping(section.get("processing"), "bathymetry.processing")
    map_config = _mapping(section.get("map"), "bathymetry.map")

    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()

    h3_resolution = int(_required(processing, "bathymetry.processing", "h3_resolution"))
    if not 0 <= h3_resolution <= 15:
        raise ValueError("bathymetry.processing.h3_resolution must be between 0 and 15.")
    grid_template = str(_required(processing, "bathymetry.processing", "h3_grid_path_template"))
    bathymetry_sign = str(processing.get("bathymetry_sign", "positive_down"))
    if bathymetry_sign not in {"positive_down", "negative_elevation"}:
        raise ValueError(
            "bathymetry.processing.bathymetry_sign must be 'positive_down' "
            "or 'negative_elevation'."
        )

    quantile_values = processing.get("depth_quantiles", [0.10, 0.25, 0.75, 0.90])
    if not isinstance(quantile_values, list) or not quantile_values:
        raise ValueError("bathymetry.processing.depth_quantiles must be a non-empty list.")
    depth_quantiles = tuple(sorted(float(value) for value in quantile_values))
    if any(not 0.0 < value < 1.0 for value in depth_quantiles):
        raise ValueError("bathymetry.processing.depth_quantiles values must be between 0 and 1.")
    if len(set(depth_quantiles)) != len(depth_quantiles):
        raise ValueError("bathymetry.processing.depth_quantiles must not contain duplicates.")
    if 0.5 in depth_quantiles:
        raise ValueError(
            "bathymetry.processing.depth_quantiles must not include 0.5; "
            "BATHYMETRY_MEDIAN is always produced."
        )

    anomaly_config = _mapping(
        processing.get("local_depth_anomaly", {}),
        "bathymetry.processing.local_depth_anomaly",
    )
    anomaly_rings = int(anomaly_config.get("neighborhood_rings", 2))
    if anomaly_rings < 1:
        raise ValueError(
            "bathymetry.processing.local_depth_anomaly.neighborhood_rings " "must be at least 1."
        )
    water_network = _mapping(raw.get("water_network"), "water_network")
    water_network_output_dir = resolve_project_path(
        _required(water_network, "water_network", "output_dir"), base_dir
    )
    neighborhood_filename_template = str(
        water_network.get(
            "neighborhood_filename_template",
            "H3_WATER_NEIGHBORHOODS_RES_{res}.parquet",
        )
    )
    water_neighborhood_path_template = str(
        water_network_output_dir / neighborhood_filename_template
    )

    isobath_config = _mapping(
        processing.get("isobaths"),
        "bathymetry.processing.isobaths",
    )
    isobath_values = _required(
        isobath_config,
        "bathymetry.processing.isobaths",
        "levels_m",
    )
    if not isinstance(isobath_values, list) or not isobath_values:
        raise ValueError("bathymetry.processing.isobaths.levels_m must be a non-empty list.")
    isobath_levels_m = tuple(sorted(float(value) for value in isobath_values))
    if any(value <= 0.0 for value in isobath_levels_m):
        raise ValueError("bathymetry.processing.isobaths.levels_m values must be positive.")
    if len(set(isobath_levels_m)) != len(isobath_levels_m):
        raise ValueError("bathymetry.processing.isobaths.levels_m must not contain duplicates.")

    raw_dir = resolve_project_path(_required(source, "bathymetry.source", "raw_dir"), base_dir)
    raw_filename = str(_required(source, "bathymetry.source", "raw_filename"))
    if Path(raw_filename).name != raw_filename or not raw_filename.lower().endswith(
        (".tif", ".tiff")
    ):
        raise ValueError("bathymetry.source.raw_filename must be a GeoTIFF filename.")

    additional_exports: list[BathymetryExportConfig] = []
    for index, value in enumerate(processing.get("additional_exports", [])):
        export = _mapping(value, f"bathymetry.processing.additional_exports[{index}]")
        export_name = f"bathymetry.processing.additional_exports[{index}]"
        resolution = int(_required(export, export_name, "h3_resolution"))
        if not 0 <= resolution <= 15:
            raise ValueError(f"{export_name}.h3_resolution must be between 0 and 15.")
        if resolution == h3_resolution or any(
            item.h3_resolution == resolution for item in additional_exports
        ):
            raise ValueError(f"Duplicate bathymetry export resolution: {resolution}.")
        additional_exports.append(
            BathymetryExportConfig(
                h3_resolution=resolution,
                processed_path=resolve_project_path(
                    _required(export, export_name, "processed_path"), base_dir
                ),
            )
        )

    return BathymetryConfig(
        bbox=bbox_from_config(section),
        provider=str(source.get("provider", "GEBCO")),
        release=str(_required(source, "bathymetry.source", "release")),
        native_resolution_arc_seconds=float(source.get("native_resolution_arc_seconds", 15)),
        grid_name=str(_required(source, "bathymetry.source", "grid_name")),
        data_source_name=str(_required(source, "bathymetry.source", "data_source_name")),
        format_name=str(_required(source, "bathymetry.source", "format_name")),
        api_base_url=str(_required(source, "bathymetry.source", "api_base_url")).rstrip("/"),
        raw_path=raw_dir / raw_filename,
        request_timeout_seconds=float(source.get("request_timeout_seconds", 120)),
        poll_interval_seconds=float(source.get("poll_interval_seconds", 5)),
        poll_timeout_seconds=float(source.get("poll_timeout_seconds", 1800)),
        overwrite=bool(source.get("overwrite", False)),
        h3_resolution=h3_resolution,
        h3_grid_path_template=grid_template,
        h3_grid_path=resolve_project_path(grid_template.format(res=h3_resolution), base_dir),
        water_polygon_path=resolve_project_path(
            _required(processing, "bathymetry.processing", "water_polygon_path"), base_dir
        ),
        processed_path=resolve_project_path(
            _required(processing, "bathymetry.processing", "processed_path"), base_dir
        ),
        bathymetry_sign=bathymetry_sign,
        depth_quantiles=depth_quantiles,
        local_depth_anomaly_neighborhood_rings=anomaly_rings,
        water_neighborhood_path_template=water_neighborhood_path_template,
        isobath_levels_m=isobath_levels_m,
        isobath_distance_projected_crs=str(
            isobath_config.get("distance_projected_crs", "EPSG:32610")
        ),
        smoothing_projected_crs=str(map_config.get("smoothing_projected_crs", "EPSG:32610")),
        smoothing_output_crs=str(map_config.get("smoothing_output_crs", "EPSG:3857")),
        smoothing_analysis_pixel_size_m=float(
            map_config.get("smoothing_analysis_pixel_size_m", 250.0)
        ),
        smoothing_output_pixel_size_m=float(map_config.get("smoothing_output_pixel_size_m", 100.0)),
        smoothing_gaussian_sigma_km=float(map_config.get("smoothing_gaussian_sigma_km", 1.5)),
        smoothing_fill_opacity=float(map_config.get("smoothing_fill_opacity", 0.82)),
        additional_exports=tuple(additional_exports),
    )


def recompute_parent_depth_bands(
    child_path: Path,
    parent_path: Path,
    *,
    parent_resolution: int,
) -> None:
    """Replace parent composition counts/fractions with sums of child counts."""

    child = pd.read_parquet(child_path)
    parent = pd.read_parquet(parent_path)
    count_columns = [f"BATHYMETRY_PIXEL_COUNT_{token}_M" for token, _lower, _upper in DEPTH_BANDS_M]
    required = {"H3_INDEX", *count_columns}
    for name, frame in (("child", child), ("parent", parent)):
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"Bathymetry {name} table lacks depth-band columns: {missing}")
    child_counts = child.loc[:, ["H3_INDEX", *count_columns]].copy()
    child_counts["H3_INDEX"] = (
        child_counts["H3_INDEX"]
        .astype(str)
        .map(lambda cell: cell_to_parent(cell, parent_resolution))
    )
    grouped = child_counts.groupby("H3_INDEX", sort=True, observed=True)[count_columns].sum(
        min_count=1
    )
    parent["H3_INDEX"] = parent["H3_INDEX"].astype(str)
    parent = parent.set_index("H3_INDEX").copy()
    unknown = sorted(set(grouped.index).difference(parent.index))
    if unknown:
        raise ValueError(
            f"Child bathymetry maps to parents outside canonical support: {unknown[:5]}"
        )
    parent.loc[grouped.index, count_columns] = grouped
    total = parent[count_columns].sum(axis=1, min_count=1)
    parent["BATHYMETRY_PIXEL_COUNT"] = total
    for token, _lower, _upper in DEPTH_BANDS_M:
        count = f"BATHYMETRY_PIXEL_COUNT_{token}_M"
        fraction = f"BATHYMETRY_FRAC_{token}_M"
        parent[fraction] = parent[count].div(total.where(total > 0))
    parent = parent.reset_index()
    parent.to_parquet(parent_path, index=False)


def run_pipeline(
    config_path: str | Path = "config/data/environment_seascape.yaml",
    *,
    overwrite: bool | None = None,
    skip_download: bool = False,
    skip_map: bool = False,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
) -> tuple[Path, Path, Path | None]:
    """Run download, H3 processing, then inspection-map generation."""

    config = load_bathymetry_config(config_path)
    raw_path = (
        config.raw_path if skip_download else download_gebco_geotiff(config, overwrite=overwrite)
    )
    product_configs = [replace(config, additional_exports=())]
    for export in config.additional_exports:
        product_configs.append(
            replace(
                config,
                h3_resolution=export.h3_resolution,
                h3_grid_path=resolve_project_path(
                    config.h3_grid_path_template.format(res=export.h3_resolution),
                    project_root(),
                ),
                processed_path=export.processed_path,
                additional_exports=(),
            )
        )
    output_dir = config.processed_path.parent
    with TransactionalSeascapePublisher(output_dir) as publisher:
        staged_configs: list[BathymetryConfig] = []
        for product_config in product_configs:
            staged_configs.append(
                replace(
                    product_config,
                    processed_path=publisher.stage_path(product_config.processed_path),
                )
            )
        for staged_config in staged_configs:
            build_bathymetry_parquet(staged_config, raster_path=raw_path)
        staged_by_resolution = {item.h3_resolution: item.processed_path for item in staged_configs}
        if {6, 8}.issubset(staged_by_resolution):
            recompute_parent_depth_bands(
                staged_by_resolution[8],
                staged_by_resolution[6],
                parent_resolution=6,
            )
        processed_paths = [item.processed_path for item in product_configs]
        artifacts = [
            capture_staged_parquet_artifact(publisher, destination)
            for destination in processed_paths
        ]
        upstream_artifacts = []
        for product_config in product_configs:
            for upstream in (
                product_config.h3_grid_path,
                Path(
                    product_config.water_neighborhood_path_template.format(
                        res=product_config.h3_resolution
                    )
                ),
            ):
                upstream_artifacts.append(
                    {"path": str(upstream), "checksum": checksum_path(upstream)}
                )
        manifest = build_manifest(
            dataset_family="environment.seascape.bathymetry",
            run_id=publisher.run_id,
            resolved_config=asdict(config),
            artifacts=artifacts,
            project_root=project_root(),
            sources=[
                {
                    "name": f"{config.provider} {config.release}",
                    "path": str(raw_path),
                    "checksum": checksum_path(raw_path),
                    "license": "GEBCO data are distributed under the CC BY 4.0 license.",
                }
            ],
            upstream_artifacts=upstream_artifacts,
            attribution=[
                {
                    "text": (
                        f"Bathymetry derived from {config.provider} {config.release}; "
                        "not to be used for navigation."
                    ),
                    "license": "CC BY 4.0",
                }
            ],
            source_completeness="complete",
            metadata={
                "bathymetry_sign": config.bathymetry_sign,
                "h3_resolutions": [item.h3_resolution for item in product_configs],
                "depth_band_intervals_m": [
                    "[0,10)",
                    "[10,30)",
                    "[30,50)",
                    "[50,100)",
                    "[100,200)",
                    "[200,infinity)",
                ],
                "neighborhood_semantics": "water_connected_minimum_hops",
            },
        )
        publisher.stage_manifest(output_dir / "bathymetry_manifest.json", manifest)
        publisher.publish()
    processed_path = config.processed_path
    map_path = (
        None
        if skip_map
        else build_bathymetry_map(
            config,
            parquet_path=processed_path,
            presentation_config_path=presentation_config_path,
        )
    )
    return raw_path, processed_path, map_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download GEBCO bathymetry, aggregate it to H3, and inspect it on a map."
    )
    parser.add_argument(
        "--config",
        default="config/data/environment_seascape.yaml",
        help="Seascape config or project config that includes it.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing raw GEBCO GeoTIFF.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use the configured raw GeoTIFF without contacting GEBCO.",
    )
    parser.add_argument(
        "--skip-map",
        action="store_true",
        help="Build the Parquet without generating the inspection map.",
    )
    parser.add_argument(
        "--presentation-config",
        default=DEFAULT_PRESENTATION_CONFIG_PATH,
        help="Shared presentation settings for the inspection-map export.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_pipeline(
        args.config,
        overwrite=True if args.overwrite else None,
        skip_download=args.skip_download,
        skip_map=args.skip_map,
        presentation_config_path=args.presentation_config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
