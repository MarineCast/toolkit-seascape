"""Publication orchestration for common r8-to-r6 habitat products."""

from __future__ import annotations

import gc
import logging
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from seascape.core.config.paths import project_root
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.spatial_support.water_network.load import (
    load_model_area_support,
    load_radius_sum_operator,
    load_water_graph,
)

from .artifacts import build_manifest, checksum_artifact, stage_parquet_family
from .habitat_aggregation import aggregate_r8_to_r6
from .habitat_configuration import (
    HabitatSurfaceConfig,
    load_cell_geometry,
    model_bbox_tuple,
)
from .habitat_inventory import normalize_inventory
from .habitat_surface import build_r8_tables

LOGGER = logging.getLogger(__name__)


def build_habitat_products(
    inventory: Any,
    config: HabitatSurfaceConfig,
    config_path: str | Path,
    *,
    source_completeness: Mapping[str, Any] | None = None,
    manifest_metadata: Mapping[str, Any] | None = None,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    """Build normalized inventory plus r8/r6 feature and confidence products."""

    inventory = normalize_inventory(inventory)
    support_r8 = load_model_area_support(config.native_resolution, config_path)
    support_r6 = load_model_area_support(config.model_resolution, config_path)
    cells = load_cell_geometry(config, support_r8)
    graph = load_water_graph(
        config.native_resolution,
        config_path,
        bbox=model_bbox_tuple(config),
        bbox_buffer_m=max(35_000.0, config.marine_buffer_m),
    )
    radius_operator = load_radius_sum_operator(config_path)
    network = load_water_network_config(config_path)
    if radius_operator.radius_m != config.marine_buffer_m:
        raise ValueError("Habitat marine_buffer_m must match the canonical radius-sum operator.")
    r8_features, r8_confidence = build_r8_tables(
        inventory,
        support_r8,
        cells,
        graph,
        radius_operator,
        prefix=config.prefix,
        equal_area_crs=config.equal_area_crs,
        reference_year=config.reference_year,
    )
    del graph, cells, support_r8
    gc.collect()
    if not config.parent_child_path.exists():
        raise FileNotFoundError(
            f"Canonical H3 parent-child crosswalk not found: {config.parent_child_path}"
        )
    crosswalk = pd.read_parquet(config.parent_child_path)
    selected = set(r8_features["H3_INDEX"].astype(str))
    crosswalk = crosswalk.loc[crosswalk["CHILD_H3_INDEX"].astype(str).isin(selected)].copy()
    selected_parents = set(crosswalk["PARENT_H3_INDEX"].astype(str))
    support_r6 = support_r6.loc[support_r6["H3_INDEX"].astype(str).isin(selected_parents)].copy()
    crosswalk = crosswalk.loc[
        crosswalk["PARENT_H3_INDEX"].astype(str).isin(set(support_r6["H3_INDEX"].astype(str)))
    ].copy()
    aggregation_children = set(crosswalk["CHILD_H3_INDEX"].astype(str))
    omitted_children = len(r8_features) - len(aggregation_children)
    if omitted_children:
        LOGGER.warning(
            "%s H3 r8 cells have a geometrically dry H3 r6 parent and are omitted from r6.",
            omitted_children,
        )
    r6_features, r6_confidence = aggregate_r8_to_r6(
        r8_features.loc[r8_features["H3_INDEX"].astype(str).isin(aggregation_children)].copy(),
        r8_confidence.loc[r8_confidence["H3_INDEX"].astype(str).isin(aggregation_children)].copy(),
        crosswalk,
        support_r6,
        prefix=config.prefix,
    )
    paths = (
        config.inventory_path,
        config.feature_path(8),
        config.confidence_path(8),
        config.feature_path(6),
        config.confidence_path(6),
    )
    publisher = stage_parquet_family(
        config.processed_dir,
        tuple(
            zip(
                (inventory, r8_features, r8_confidence, r6_features, r6_confidence),
                paths,
                strict=True,
            )
        ),
    )
    from .habitat_acquisition import load_habitat_download_config

    download = load_habitat_download_config(config.section_name, config_path)
    sources: list[dict[str, Any]] = []
    for name, source in download.sources.items():
        if not bool(source.get("enabled", True)):
            continue
        raw_filename = source.get("raw_filename")
        raw_path = download.raw_dir / str(raw_filename) if raw_filename else None
        record: dict[str, Any] = {
            "name": name,
            "license": source.get("license") or "See authoritative source terms",
            "attribution": source.get("attribution") or name,
            "observation_period": source.get("observation_period"),
            "source_url": source.get("url", source.get("layer_url", source.get("dataset_url"))),
        }
        if raw_path is not None:
            record["path"] = str(raw_path)
            record["status"] = "available" if raw_path.exists() else "not_materialized"
            if raw_path.exists():
                record["checksum"] = checksum_artifact(raw_path)
        sources.append(record)
    declared_status = (
        str(source_completeness.get("status", "")).strip().lower() if source_completeness else ""
    )
    manifest = build_manifest(
        dataset_family=f"environment.seascape.{config.section_name}",
        run_id=publisher.run_id,
        resolved_config={"surface": asdict(config), "sources": download.sources},
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=sources,
        upstream_artifacts=[
            {"path": str(path), "checksum": checksum_artifact(path)}
            for path in (
                config.clipped_geometry_path,
                config.parent_child_path,
                network.radius_sum_operator_path,
                network.manifest_path,
            )
        ],
        attribution=[
            {"text": source["attribution"], "license": source["license"]} for source in sources
        ],
        source_completeness=("partial" if declared_status not in {"", "complete"} else "complete"),
        metadata={
            "radius_operator_lineage": {
                "path": str(network.radius_sum_operator_path),
                "checksum": checksum_artifact(network.radius_sum_operator_path),
                "radius_m": radius_operator.radius_m,
                "support_hash": radius_operator.support_hash,
                "source_support_hash": radius_operator.source_support_hash,
                "graph_checksum": radius_operator.graph_checksum,
            },
            **(
                {"source_completeness_detail": dict(source_completeness)}
                if source_completeness
                else {}
            ),
            **dict(manifest_metadata or {}),
        },
    )
    publisher.publish_manifest(config.manifest_path, manifest)
    return (*paths, config.manifest_path)


__all__ = ["build_habitat_products"]
