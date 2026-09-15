"""Build one cross-border-consistent distance-to-estuary covariate."""

from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import box

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.geo.geometry import normalize_polygonal_geometry, safe_polygonal_union
from seascape.spatial_support.water_network.graph import (
    WaterGraph,
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    attach_points_to_graph,
    load_model_area_support,
    load_water_graph,
    multi_source_shortest_paths,
)
from seascape.utils.artifacts import (
    build_manifest,
)
from seascape.utils.artifacts import checksum_artifact as _sha256
from seascape.utils.artifacts import (
    stage_parquet_family,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.spatial import project_h3_centers
from seascape.utils.values import clean_optional_text

from .download import DEFAULT_CONFIG_PATH, load_estuarine_download_config

LOGGER = logging.getLogger(__name__)

BC_SOURCE = "BC_PECP_DATABASIN"
US_SOURCE = "US_PMEP"

FEATURE_COLUMNS = [
    "H3_INDEX",
    "DISTANCE_TO_ESTUARY_M",
    "WATER_NETWORK_DISTANCE_TO_ESTUARY_M",
    "WATER_COMPONENT_ID",
    "NETWORK_CONNECTOR_METHOD",
    "NETWORK_CONNECTOR_DISTANCE_M",
    "NETWORK_DISTANCE_QC_REASON",
]
ESTUARY_COLUMNS = [
    "ESTUARY_ID",
    "ESTUARY_NAME",
    "SOURCE_DATASET",
    "SOURCE_FEATURE_ID",
    "SOURCE_REGION",
    "LOCATION_METHOD",
    "WITHIN_MODEL_BBOX",
    "MARINE_GRAPH_H3_INDEX",
    "MARINE_GRAPH_SNAP_DISTANCE_M",
    "SOURCE_TO_WATER_DISTANCE_M",
    "MARINE_GRAPH_WATER_PATH_FRACTION",
    "MARINE_GRAPH_CONNECTION_QC_REASON",
    "MARINE_NETWORK_COMPONENT_ID",
    "geometry",
]


@dataclass(frozen=True)
class EstuarineConnectivityConfig:
    """Resolved source, support, and output paths for estuary distance."""

    bbox: dict[str, float]
    context_bbox: dict[str, float]
    context_buffer_km: float
    h3_resolution: int
    projected_crs: str
    water_polygon_path: Path
    land_polygon_path: Path
    bc_estuaries_path: Path
    us_estuary_points_path: Path
    processed_dir: Path
    estuary_path: Path
    feature_path: Path
    estuary_graph_snap_max_km: float


def load_estuarine_connectivity_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> EstuarineConnectivityConfig:
    """Load and validate the narrowed estuary-distance build contract."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("estuarine_connectivity"), "estuarine_connectivity")
    processing = _mapping(section.get("processing"), "estuarine_connectivity.processing")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    download = load_estuarine_download_config(path)
    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("estuarine_connectivity.processing.h3_resolution must be 8.")
    graph_snap_max_km = float(processing.get("estuary_graph_snap_max_km", 15.0))
    if graph_snap_max_km <= 0:
        raise ValueError("estuary_graph_snap_max_km must be positive.")
    processed_dir = _resolve(processing["processed_directory"], base_dir)
    return EstuarineConnectivityConfig(
        bbox=download.bbox,
        context_bbox=download.query_bbox,
        context_buffer_km=download.context_buffer_km,
        h3_resolution=resolution,
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        water_polygon_path=_resolve(processing["water_polygon_path"], base_dir),
        land_polygon_path=_resolve(processing["land_polygon_path"], base_dir),
        bc_estuaries_path=_resolve(processing["bc_estuaries_path"], base_dir),
        us_estuary_points_path=_resolve(processing["us_estuary_points_path"], base_dir),
        processed_dir=processed_dir,
        estuary_path=processed_dir / str(processing["estuary_filename"]),
        feature_path=processed_dir / str(processing["feature_filename"]),
        estuary_graph_snap_max_km=graph_snap_max_km,
    )


_clean_text = clean_optional_text


def _source_identifier(value: Any, fallback: Any) -> str:
    if value is not None and not pd.isna(value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = math.nan
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
        text = _clean_text(value)
        if text:
            return text
    text = _clean_text(fallback)
    if not text:
        raise ValueError("Estuary source feature is missing a usable identifier.")
    return text


def _bbox_polygon(bbox_value: Mapping[str, float]):
    return box(
        float(bbox_value["min_lon"]),
        float(bbox_value["min_lat"]),
        float(bbox_value["max_lon"]),
        float(bbox_value["max_lat"]),
    )


def _read_vector(path: Path):
    import geopandas as gpd

    if not path.exists():
        raise FileNotFoundError(f"Estuary source not found: {path}. Run download.py first.")
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"Estuary source has no CRS: {path}")
    if frame.geometry.name != "geometry":
        frame = frame.rename_geometry("geometry")
    return frame.to_crs("EPSG:4326")


def _load_bc_points(config: EstuarineConnectivityConfig):
    import geopandas as gpd

    frame = _read_vector(config.bc_estuaries_path)
    required = {"EST_NO", "EST_NAME"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"B.C. estuary source is missing fields: {missing}")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame.geometry = frame.geometry.map(normalize_polygonal_geometry)
    context = _bbox_polygon(config.context_bbox)
    frame = frame.loc[~frame.geometry.is_empty & frame.geometry.intersects(context)].copy()
    frame.geometry = frame.geometry.map(
        lambda geometry: normalize_polygonal_geometry(geometry.intersection(context))
    )
    frame = frame.loc[~frame.geometry.is_empty].copy()
    projected = frame.to_crs(config.projected_crs)
    projected.geometry = projected.geometry.representative_point()
    points = projected.to_crs("EPSG:4326")
    source_ids = [
        _source_identifier(value, fallback)
        for value, fallback in zip(
            frame["EST_NO"],
            frame["OBJECTID"] if "OBJECTID" in frame else frame.index,
            strict=True,
        )
    ]
    return gpd.GeoDataFrame(
        {
            "ESTUARY_ID": [f"BC_PECP_{int(value):04d}" for value in source_ids],
            "ESTUARY_NAME": frame["EST_NAME"].map(_clean_text).to_numpy(),
            "SOURCE_DATASET": BC_SOURCE,
            "SOURCE_FEATURE_ID": source_ids,
            "SOURCE_REGION": "British Columbia",
            "LOCATION_METHOD": "POLYGON_INTERIOR_REPRESENTATIVE_POINT",
        },
        geometry=points.geometry.to_numpy(),
        crs="EPSG:4326",
    )


def _load_pmep_points(config: EstuarineConnectivityConfig):
    import geopandas as gpd

    frame = _read_vector(config.us_estuary_points_path)
    required = {"PMEP_EstuaryID", "Estuary_Name"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"PMEP estuary source is missing fields: {missing}")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame = frame.loc[
        frame.geometry.geom_type.eq("Point")
        & frame.geometry.intersects(_bbox_polygon(config.context_bbox))
    ].copy()
    source_ids = [
        _source_identifier(value, fallback)
        for value, fallback in zip(
            frame["PMEP_EstuaryID"],
            frame["OBJECTID"] if "OBJECTID" in frame else frame.index,
            strict=True,
        )
    ]
    return gpd.GeoDataFrame(
        {
            "ESTUARY_ID": [f"US_PMEP_{int(value):04d}" for value in source_ids],
            "ESTUARY_NAME": frame["Estuary_Name"].map(_clean_text).to_numpy(),
            "SOURCE_DATASET": US_SOURCE,
            "SOURCE_FEATURE_ID": source_ids,
            "SOURCE_REGION": "U.S. West Coast",
            "LOCATION_METHOD": "SOURCE_POINT",
        },
        geometry=frame.geometry.to_numpy(),
        crs="EPSG:4326",
    )


def _load_estuary_inventory(config: EstuarineConnectivityConfig):
    import geopandas as gpd

    inventory = gpd.GeoDataFrame(
        pd.concat([_load_bc_points(config), _load_pmep_points(config)], ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326",
    )
    inventory["WITHIN_MODEL_BBOX"] = inventory.geometry.intersects(_bbox_polygon(config.bbox))
    inventory["MARINE_GRAPH_H3_INDEX"] = pd.Series([None] * len(inventory), dtype="string")
    inventory["MARINE_GRAPH_SNAP_DISTANCE_M"] = np.nan
    inventory["SOURCE_TO_WATER_DISTANCE_M"] = np.nan
    inventory["MARINE_GRAPH_WATER_PATH_FRACTION"] = np.nan
    inventory["MARINE_GRAPH_CONNECTION_QC_REASON"] = pd.Series(
        [None] * len(inventory), dtype="string"
    )
    inventory["MARINE_NETWORK_COMPONENT_ID"] = pd.Series([None] * len(inventory), dtype="string")
    inventory = inventory.sort_values("ESTUARY_ID").reset_index(drop=True)
    inventory = inventory.loc[:, ESTUARY_COLUMNS]
    if inventory.empty or inventory["ESTUARY_ID"].duplicated().any():
        raise ValueError("Mapped estuary inventory must contain unique, nonempty locations.")
    if inventory.geometry.is_empty.any() or inventory.geometry.isna().any():
        raise ValueError("Mapped estuary inventory contains missing point geometry.")
    return inventory


def _spatial_support(config: EstuarineConnectivityConfig):
    import geopandas as gpd

    if not config.water_polygon_path.exists():
        raise FileNotFoundError(
            f"Canonical marine-water geometry not found: {config.water_polygon_path}"
        )
    frame = gpd.read_parquet(config.water_polygon_path)
    if frame.crs is None:
        raise ValueError(f"Canonical marine-water geometry has no CRS: {config.water_polygon_path}")
    target_water = safe_polygonal_union(
        frame.to_crs("EPSG:4326"),
        clip_geometry=_bbox_polygon(config.bbox),
    )
    if target_water.is_empty:
        raise ValueError("Canonical marine-water geometry is empty in the model bbox.")
    if not config.land_polygon_path.exists():
        raise FileNotFoundError(f"Land polygons not found: {config.land_polygon_path}")
    if config.land_polygon_path.suffix.lower() in {".parquet", ".geoparquet"}:
        land = gpd.read_parquet(config.land_polygon_path)
    else:
        land = gpd.read_file(config.land_polygon_path)
    if land.crs is None:
        raise ValueError(f"Land polygons have no CRS: {config.land_polygon_path}")
    context_land = safe_polygonal_union(
        land.to_crs("EPSG:4326"),
        clip_geometry=_bbox_polygon(config.context_bbox),
    )
    if context_land.is_empty:
        raise ValueError("Land geometry is empty in the marine-network context.")
    context_water = safe_polygonal_union(
        frame.to_crs("EPSG:4326"),
        clip_geometry=_bbox_polygon(config.context_bbox),
    )
    return target_water, context_water, context_land


def _snap_estuaries_to_graph(
    estuaries: Any,
    graph: WaterGraph,
    water_geometry: Any,
    config: EstuarineConnectivityConfig,
):
    geographic = estuaries.to_crs("EPSG:4326").reset_index(drop=True)
    attachment = attach_points_to_graph(
        graph,
        geographic.geometry.x.to_numpy(dtype="float64"),
        geographic.geometry.y.to_numpy(dtype="float64"),
        water_geometry,
        source_water_max_distance_m=config.estuary_graph_snap_max_km * 1_000.0,
        graph_connector_max_distance_m=config.estuary_graph_snap_max_km * 1_000.0,
    )
    output = estuaries.copy()
    output["MARINE_GRAPH_H3_INDEX"] = attachment["GRAPH_H3_INDEX"].astype("string")
    output["MARINE_GRAPH_SNAP_DISTANCE_M"] = attachment["GRAPH_CONNECTOR_DISTANCE_M"].to_numpy()
    output["SOURCE_TO_WATER_DISTANCE_M"] = attachment["SOURCE_TO_WATER_DISTANCE_M"].to_numpy()
    output["MARINE_GRAPH_WATER_PATH_FRACTION"] = attachment["WATER_PATH_FRACTION"].to_numpy()
    output["MARINE_GRAPH_CONNECTION_QC_REASON"] = attachment["QC_REASON"].astype("string")
    component = graph.support.set_index("H3_INDEX")["WATER_COMPONENT_ID"]
    output["MARINE_NETWORK_COMPONENT_ID"] = output["MARINE_GRAPH_H3_INDEX"].map(component)
    return output.loc[:, ESTUARY_COLUMNS]


def _build_features(
    target_water: Any,
    context_water: Any,
    context_land: Any,
    estuaries: Any,
    config: EstuarineConnectivityConfig,
    config_path: str | Path,
) -> tuple[pd.DataFrame, Any, dict[str, int | float]]:
    target_support = load_model_area_support(config.h3_resolution, config_path)
    target_cells = target_support["H3_INDEX"].astype(str).tolist()
    if not target_cells:
        raise ValueError("Canonical model-area support is empty.")
    _, _, target_x, target_y = project_h3_centers(target_cells, config.projected_crs)
    target_coordinates = np.column_stack((target_x, target_y))
    projected_estuaries = estuaries.to_crs(config.projected_crs)
    estuary_coordinates = np.column_stack(
        (projected_estuaries.geometry.x, projected_estuaries.geometry.y)
    )
    distances, _ = cKDTree(estuary_coordinates).query(target_coordinates, k=1)
    distances = np.asarray(distances, dtype="float64")
    if not np.isfinite(distances).all() or (distances < 0).any():
        raise ValueError("Distance-to-estuary values must be finite and nonnegative.")
    if float(distances.max()) >= config.context_buffer_km * 1_000:
        raise ValueError(
            "Maximum distance reaches the source context buffer; increase "
            "estuarine_connectivity.download.context_buffer_km."
        )

    graph = load_water_graph(
        config.h3_resolution,
        config_path,
        bbox=(
            config.context_bbox["min_lon"],
            config.context_bbox["min_lat"],
            config.context_bbox["max_lon"],
            config.context_bbox["max_lat"],
        ),
    )
    graph_cells = graph.cells.astype(str).tolist()
    estuaries = _snap_estuaries_to_graph(estuaries, graph, context_water, config)
    connected_estuaries = estuaries.loc[estuaries["MARINE_GRAPH_H3_INDEX"].notna()].reset_index(
        drop=True
    )
    if connected_estuaries.empty:
        raise ValueError("No mapped estuary has a water-valid canonical graph connector.")
    graph_distances, _owners = multi_source_shortest_paths(
        graph,
        [
            (str(cell), float(distance), int(index))
            for index, (cell, distance) in enumerate(
                zip(
                    connected_estuaries["MARINE_GRAPH_H3_INDEX"],
                    connected_estuaries["MARINE_GRAPH_SNAP_DISTANCE_M"],
                    strict=True,
                )
            )
        ],
    )
    target_graph_indices, target_connectors, target_qc = target_graph_mapping(graph, target_cells)
    mapped = target_graph_indices >= 0
    reachable = np.zeros(len(target_cells), dtype=bool)
    reachable[mapped] = np.isfinite(graph_distances[target_graph_indices[mapped]])
    network_distances = np.full(len(target_cells), np.nan, dtype="float64")
    network_distances[reachable] = (
        graph_distances[target_graph_indices[reachable]] + target_connectors[reachable]
    )
    network_distances[reachable] = np.maximum(network_distances[reachable], distances[reachable])
    lineage = graph.support.set_index("H3_INDEX").loc[target_cells]
    qc = np.where(
        reachable,
        target_qc,
        np.where(pd.isna(target_qc), "no_connected_estuary_in_component", target_qc),
    )

    features = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "DISTANCE_TO_ESTUARY_M": distances,
            "WATER_NETWORK_DISTANCE_TO_ESTUARY_M": network_distances,
            "WATER_COMPONENT_ID": lineage["WATER_COMPONENT_ID"].tolist(),
            "NETWORK_CONNECTOR_METHOD": lineage["CONNECTOR_METHOD"].tolist(),
            "NETWORK_CONNECTOR_DISTANCE_M": lineage["CONNECTOR_DISTANCE_M"].tolist(),
            "NETWORK_DISTANCE_QC_REASON": qc,
        },
        columns=FEATURE_COLUMNS,
    )
    graph_stats: dict[str, int | float] = {
        "marine_graph_h3_cell_count": len(graph_cells),
        "canonical_terminal_connector_count": int(
            (lineage["GRAPH_CONNECTION_STATUS"] == "terminal_connector").sum()
        ),
        "canonical_disconnected_target_count": int((~reachable).sum()),
    }
    return features, estuaries, graph_stats


def _validate(
    features: pd.DataFrame,
    estuaries: pd.DataFrame,
    config: EstuarineConnectivityConfig,
) -> None:
    if list(features.columns) != FEATURE_COLUMNS:
        raise ValueError(f"Unexpected estuary-distance schema: {list(features.columns)}")
    if features.empty or not features["H3_INDEX"].is_unique:
        raise ValueError("Estuary-distance features must retain unique canonical H3 support.")
    if features["DISTANCE_TO_ESTUARY_M"].isna().any():
        raise ValueError("Straight distance to estuary cannot be null.")
    straight_values = pd.to_numeric(features["DISTANCE_TO_ESTUARY_M"], errors="raise").to_numpy(
        dtype="float64"
    )
    if not np.isfinite(straight_values).all() or (straight_values < 0).any():
        raise ValueError("DISTANCE_TO_ESTUARY_M must be finite and nonnegative.")
    network_values = pd.to_numeric(
        features["WATER_NETWORK_DISTANCE_TO_ESTUARY_M"], errors="raise"
    ).to_numpy(dtype="float64")
    finite_network = network_values[np.isfinite(network_values)]
    if np.isinf(network_values).any() or (finite_network < 0).any():
        raise ValueError("WATER_NETWORK_DISTANCE_TO_ESTUARY_M must be nonnegative where available.")
    disconnected = np.isnan(network_values)
    if features.loc[disconnected, "NETWORK_DISTANCE_QC_REASON"].isna().any():
        raise ValueError("Null marine-connected distances must preserve a network QC reason.")
    if (
        features["WATER_NETWORK_DISTANCE_TO_ESTUARY_M"] + 1e-6 < features["DISTANCE_TO_ESTUARY_M"]
    ).any():
        raise ValueError("Marine-connected distance cannot be shorter than straight distance.")
    if list(estuaries.columns) != ESTUARY_COLUMNS:
        raise ValueError(f"Unexpected mapped-estuary schema: {list(estuaries.columns)}")
    if estuaries.empty or estuaries["ESTUARY_ID"].duplicated().any():
        raise ValueError("Mapped estuary inventory must contain unique locations.")
    disconnected = estuaries["MARINE_GRAPH_H3_INDEX"].isna()
    if estuaries.loc[disconnected, "MARINE_GRAPH_CONNECTION_QC_REASON"].isna().any():
        raise ValueError("Disconnected mapped estuaries must preserve a graph QC reason.")
    snap_distance = pd.to_numeric(
        estuaries["MARINE_GRAPH_SNAP_DISTANCE_M"], errors="raise"
    ).to_numpy(dtype="float64")
    if (
        np.isinf(snap_distance).any()
        or (snap_distance[np.isfinite(snap_distance)] < 0).any()
        or (
            snap_distance[np.isfinite(snap_distance)] > config.estuary_graph_snap_max_km * 1_000
        ).any()
    ):
        raise ValueError("Mapped-estuary graph snap distances violate the configured limit.")
    source_counts = estuaries["SOURCE_DATASET"].value_counts()
    if BC_SOURCE not in source_counts or US_SOURCE not in source_counts:
        raise ValueError("Mapped estuary inventory must retain both B.C. and U.S. sources.")


def build_estuarine_connectivity(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path]:
    """Build the estuary inventory and straight plus marine-connected distances."""

    config = load_estuarine_connectivity_config(config_path)
    estuaries = _load_estuary_inventory(config)
    target_water, context_water, context_land = _spatial_support(config)
    features, estuaries, graph_stats = _build_features(
        target_water,
        context_water,
        context_land,
        estuaries,
        config,
        config_path,
    )
    _validate(features, estuaries, config)

    publisher = stage_parquet_family(
        config.processed_dir,
        ((features, config.feature_path), (estuaries, config.estuary_path)),
    )

    source_counts = estuaries["SOURCE_DATASET"].value_counts().sort_index()
    manifest = build_manifest(
        dataset_family="environment.seascape.estuarine_connectivity",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "B.C. Pacific Estuary Conservation Program inventory",
                "path": str(config.bc_estuaries_path),
                "checksum": _sha256(config.bc_estuaries_path),
                "license": "Open Government Licence - British Columbia",
            },
            {
                "name": "U.S. Pacific Marine and Estuarine Fish Habitat Partnership",
                "path": str(config.us_estuary_points_path),
                "checksum": _sha256(config.us_estuary_points_path),
                "license": "U.S. Government public data",
            },
        ],
        upstream_artifacts=[
            {
                "path": str(config.water_polygon_path),
                "checksum": _sha256(config.water_polygon_path),
            },
            {
                "path": str(config.land_polygon_path),
                "checksum": _sha256(config.land_polygon_path),
            },
        ],
        attribution=[
            {
                "text": "B.C. Pacific Estuary Conservation Program",
                "license": "Open Government Licence - British Columbia",
            },
            {
                "text": "Pacific Marine and Estuarine Fish Habitat Partnership",
                "license": "U.S. Government public data",
            },
        ],
        source_completeness="partial",
    )
    manifest_path = config.processed_dir / "estuarine_connectivity_manifest.json"
    publisher.publish_manifest(manifest_path, manifest)
    LOGGER.info(
        "Built estuary distance: %d H3 cells and %d estuary points (%s)",
        len(features),
        len(estuaries),
        ", ".join(f"{key}={value}" for key, value in source_counts.items()),
    )
    return config.feature_path, config.estuary_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for path in build_estuarine_connectivity(args.config):
        print(path)
    return 0


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "ESTUARY_COLUMNS",
    "FEATURE_COLUMNS",
    "build_estuarine_connectivity",
    "load_estuarine_connectivity_config",
]


if __name__ == "__main__":
    raise SystemExit(main())
