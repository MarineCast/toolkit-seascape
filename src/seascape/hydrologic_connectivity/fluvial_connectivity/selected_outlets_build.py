"""Optional selected-outlet product using the normalized HydroRIVERS inventory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.spatial_support.water_network.graph import target_graph_mapping
from seascape.spatial_support.water_network.load import (
    attach_points_to_graph,
    load_model_area_support,
    load_water_graph,
)
from seascape.utils.artifacts import build_manifest, checksum_artifact, stage_parquet_family

from .multiple_outlets import build_outlet_relationships
from .topology import DEFAULT_CONFIG_PATH, load_fluvial_connectivity_config


@dataclass(frozen=True)
class SelectedOutletConfig:
    inventory_path: Path
    water_polygon_path: Path
    output_dir: Path
    selected_ids: tuple[str, ...]
    resolutions: tuple[int, ...]
    projected_crs: str
    max_pairs: int
    max_search_m: float | None
    source_water_max_distance_m: float
    graph_connector_max_distance_m: float


def load_selected_outlet_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> SelectedOutletConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("selected_outlets")
    if not isinstance(section, dict):
        raise ValueError("Configure selected_outlets with explicit selected_ids")
    fluvial = load_fluvial_connectivity_config(config_path)
    selected = tuple(str(value) for value in section.get("selected_ids", ()))
    if not selected or len(selected) != len(set(selected)) or any(not value for value in selected):
        raise ValueError("selected_outlets.selected_ids must contain distinct exact outlet IDs")
    resolutions = tuple(int(value) for value in section.get("resolutions", (8, 6)))
    if not resolutions or not set(resolutions) <= {6, 8} or len(resolutions) != len(set(resolutions)):
        raise ValueError("Selected outlet resolutions must be unique R8 and/or R6")
    max_pairs = int(section.get("max_pairs", 200_000))
    if max_pairs < 1:
        raise ValueError("selected_outlets.max_pairs must be positive")
    max_search = section.get("max_search_m")
    output_dir = project_root() / str(section.get(
        "output_dir",
        "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_connectivity/selected_outlets",
    ))
    if not output_dir.resolve().is_relative_to(project_root().resolve()):
        raise ValueError("Selected outlet output must stay inside the workspace")
    return SelectedOutletConfig(
        fluvial.network_mouths_path,
        fluvial.water_polygon_path,
        output_dir,
        selected,
        resolutions,
        fluvial.projected_crs,
        max_pairs,
        float(max_search) if max_search is not None else None,
        fluvial.mouth_coast_tolerance_m,
        fluvial.mouth_graph_snap_max_km * 1000,
    )


def build_selected_outlets(config_path: str | Path = DEFAULT_CONFIG_PATH) -> tuple[Path, ...]:
    config = load_selected_outlet_config(config_path)
    if not config.inventory_path.is_file():
        raise FileNotFoundError(f"Normalized fluvial mouth inventory missing: {config.inventory_path}")
    inventory = gpd.read_parquet(config.inventory_path)
    if inventory.FLUVIAL_MOUTH_ID.isna().any() or inventory.FLUVIAL_MOUTH_ID.duplicated().any():
        raise ValueError("Normalized outlet IDs must be nonnull and unique")
    missing_ids = set(config.selected_ids) - set(inventory.FLUVIAL_MOUTH_ID.astype(str))
    if missing_ids:
        raise KeyError(f"Selected outlet IDs absent from inventory: {sorted(missing_ids)}")
    selected = inventory.loc[inventory.FLUVIAL_MOUTH_ID.isin(config.selected_ids)].copy()
    selected = selected.sort_values("FLUVIAL_MOUTH_ID").reset_index(drop=True)
    selected["OUTLET_ID"] = selected.FLUVIAL_MOUTH_ID.astype(str)
    selected["SOURCE_ID"] = "HydroRIVERS"
    selected["SOURCE_VERSION"] = "v1.0"
    selected["SOURCE_FEATURE_ID"] = selected.FLUVIAL_MOUTH_ID.astype(str)
    selected["SELECTION_PROVENANCE"] = "explicit_selected_outlets_configuration"
    selected["MULTIPLE_MOUTH_GROUP_ID"] = selected.RIVER_BASIN_ID.astype("string")
    water = gpd.read_parquet(config.water_polygon_path).to_crs("EPSG:4326").geometry.union_all()
    if water.is_empty:
        raise ValueError("Canonical water polygon is empty")
    transformer = Transformer.from_crs("EPSG:4326", config.projected_crs, always_xy=True)
    selected_wgs = selected.to_crs("EPSG:4326")
    x, y = transformer.transform(selected_wgs.geometry.x, selected_wgs.geometry.y)
    selected["OUTLET_X_M"] = x
    selected["OUTLET_Y_M"] = y
    artifacts: list[tuple[object, Path]] = []
    inventory_output = config.output_dir / "SELECTED_OUTLET_INVENTORY.parquet"
    artifacts.append((selected, inventory_output))
    for resolution in config.resolutions:
        support = load_model_area_support(resolution, config_path)
        if len(support) * len(selected) > config.max_pairs:
            raise ValueError(
                f"Selected outlet pair budget exceeded at R{resolution}: "
                f"{len(support)} cells x {len(selected)} outlets > {config.max_pairs}"
            )
        graph = load_water_graph(resolution, config_path)
        attachment = attach_points_to_graph(
            graph,
            selected_wgs.geometry.x.to_numpy(),
            selected_wgs.geometry.y.to_numpy(),
            water,
            source_water_max_distance_m=config.source_water_max_distance_m,
            graph_connector_max_distance_m=config.graph_connector_max_distance_m,
        )
        outlet_rows = selected.drop(columns="geometry").copy()
        outlet_rows["GRAPH_H3_INDEX"] = attachment.GRAPH_H3_INDEX.to_numpy()
        outlet_rows["SOURCE_CONNECTOR_DISTANCE_M"] = (
            attachment.SOURCE_TO_WATER_DISTANCE_M.to_numpy(dtype=float)
            + attachment.GRAPH_CONNECTOR_DISTANCE_M.to_numpy(dtype=float)
        )
        target_position, target_connector, target_qc = target_graph_mapping(
            graph, support.H3_INDEX.astype(str).tolist()
        )
        target_node = [str(graph.cells[int(position)]) if position >= 0 else None for position in target_position]
        target_x, target_y = transformer.transform(
            support.REPRESENTATIVE_POINT_LONGITUDE.to_numpy(dtype=float),
            support.REPRESENTATIVE_POINT_LATITUDE.to_numpy(dtype=float),
        )
        cells = pd.DataFrame({
            "H3_INDEX": support.H3_INDEX.astype(str),
            "H3_RESOLUTION": resolution,
            "REPRESENTATIVE_X_M": target_x,
            "REPRESENTATIVE_Y_M": target_y,
            "GRAPH_H3_INDEX": target_node,
            "TARGET_CONNECTOR_DISTANCE_M": target_connector,
        })
        good_cells = cells.loc[np.asarray(target_position) >= 0]
        good_outlets = outlet_rows.loc[attachment.IS_CONNECTED.to_numpy(dtype=bool)]
        parts = []
        if not good_cells.empty and not good_outlets.empty:
            parts.append(build_outlet_relationships(
                good_cells, good_outlets, graph,
                max_pairs=config.max_pairs,
                max_search_m=config.max_search_m,
            ))
        for outlet in outlet_rows.loc[~attachment.IS_CONNECTED.to_numpy(dtype=bool)].itertuples(index=False):
            parts.append(pd.DataFrame({
                "H3_INDEX": cells.H3_INDEX,
                "H3_RESOLUTION": resolution,
                "OUTLET_ID": outlet.OUTLET_ID,
                "RIVER_BASIN_ID": outlet.RIVER_BASIN_ID,
                "WATER_NETWORK_DISTANCE_M": np.nan,
                "EUCLIDEAN_DISTANCE_M": np.nan,
                "DETOUR_DISTANCE_M": np.nan,
                "DETOUR_RATIO": np.nan,
                "REACHABILITY_STATUS": "source_attachment_unavailable",
                "SOURCE_CONNECTOR_DISTANCE_M": np.nan,
                "TARGET_CONNECTOR_DISTANCE_M": cells.TARGET_CONNECTOR_DISTANCE_M,
                "GRAPH_COMPONENT_ID": None,
                "QC_REASON": attachment.loc[selected.OUTLET_ID.eq(outlet.OUTLET_ID), "QC_REASON"].iloc[0],
            }))
        missing_targets = cells.loc[np.asarray(target_position) < 0]
        if not missing_targets.empty:
            for outlet in good_outlets.itertuples(index=False):
                parts.append(pd.DataFrame({
                    "H3_INDEX": missing_targets.H3_INDEX,
                    "H3_RESOLUTION": resolution,
                    "OUTLET_ID": outlet.OUTLET_ID,
                    "RIVER_BASIN_ID": outlet.RIVER_BASIN_ID,
                    "WATER_NETWORK_DISTANCE_M": np.nan,
                    "EUCLIDEAN_DISTANCE_M": np.nan,
                    "DETOUR_DISTANCE_M": np.nan,
                    "DETOUR_RATIO": np.nan,
                    "REACHABILITY_STATUS": "target_attachment_unavailable",
                    "SOURCE_CONNECTOR_DISTANCE_M": outlet.SOURCE_CONNECTOR_DISTANCE_M,
                    "TARGET_CONNECTOR_DISTANCE_M": np.nan,
                    "GRAPH_COMPONENT_ID": None,
                    "QC_REASON": [target_qc[index] for index in np.flatnonzero(np.asarray(target_position) < 0)],
                }))
        relationships = pd.concat(parts, ignore_index=True).sort_values(["H3_INDEX", "OUTLET_ID"])
        if len(relationships) != len(cells) * len(selected) or relationships.duplicated(["H3_INDEX", "H3_RESOLUTION", "OUTLET_ID"]).any():
            raise ValueError("Selected outlet relationship cardinality mismatch")
        artifacts.append((relationships, config.output_dir / f"OUTLET_RELATIONSHIPS_RES_{resolution}.parquet"))
    publisher = stage_parquet_family(config.output_dir, artifacts)
    manifest = build_manifest(
        dataset_family="environment.seascape.selected_outlets",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[{
            "name": "HydroRIVERS v1.0 selected normalized outlets",
            "path": str(config.inventory_path),
            "checksum": checksum_artifact(config.inventory_path),
            "license": "HydroSHEDS licence terms",
        }],
        upstream_artifacts=[{"path": str(config.water_polygon_path), "checksum": checksum_artifact(config.water_polygon_path)}],
        attribution=[{"text": "HydroRIVERS v1.0, HydroSHEDS", "license": "HydroSHEDS licence terms"}],
        source_completeness="partial",
        metadata={"scientific_method_version": "selected_outlet_sparse_search_v1", "sample_support": "canonical R8/R6 representative point; terminal connectors"},
    )
    publisher.publish_manifest(config.output_dir / "selected_outlets_manifest.json", manifest)
    return tuple(path for _frame, path in artifacts)
