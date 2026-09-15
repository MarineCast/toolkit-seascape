"""Configuration, source normalization, and river topology for fluvial connectivity."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import Point, box

from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.geo.geometry import normalize_polygonal_geometry, safe_polygonal_union
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.spatial import (
    expanded_bbox_polygon as _expanded_bbox,
)
from seascape.utils.spatial import (
    load_polygon_layer as _read_polygon_layer,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"

HYDRORIVERS_SOURCE = "HYDRORIVERS_V10"

FEATURE_COLUMNS = [
    "H3_INDEX",
    "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M",
    "EUCLIDEAN_DISTANCE_TO_FLUVIAL_MOUTH_M",
    "FLUVIAL_PATH_DETOUR_M",
    "FLUVIAL_PATH_DETOUR_RATIO",
    "FLUVIAL_MOUTH_REACHABLE",
    "STRUCTURAL_DISCONTINUITY_FLAG",
    "NEAREST_FLUVIAL_MOUTH_ID",
    "NEAREST_RIVER_BASIN_ID",
    "NEAREST_OUTLET_SUBBASIN_ID",
    "CONNECTED_UPSTREAM_SEGMENT_COUNT",
    "CONNECTED_TRIBUTARY_JUNCTION_COUNT",
    "CONNECTED_HEADWATER_COUNT",
    "CONNECTED_STRAHLER_ORDER",
    "CONNECTED_UPSTREAM_NETWORK_LENGTH_KM",
    "CONNECTED_UPSTREAM_DISTANCE_KM",
    "CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2",
    "SOURCE_NETWORK_TOPOLOGY_GAP_COUNT",
    "MARINE_NETWORK_COMPONENT_ID",
    "MAPPED_FLUVIAL_MOUTH_COUNT_IN_COMPONENT",
    "NETWORK_CONNECTOR_METHOD",
    "NETWORK_CONNECTOR_DISTANCE_M",
    "NETWORK_DISTANCE_QC_REASON",
]

CROSSWALK_COLUMNS = [
    "H3_INDEX",
    "FLUVIAL_MOUTH_ID",
    "RIVER_BASIN_ID",
    "OUTLET_SUBBASIN_ID",
    "WATER_NETWORK_DISTANCE_M",
    "MARINE_NETWORK_COMPONENT_ID",
    "STRUCTURAL_DISCONTINUITY_FLAG",
    "CROSSWALK_METHOD",
]

NETWORK_SEGMENT_COLUMNS = [
    "FLUVIAL_SEGMENT_ID",
    "SOURCE_DATASET",
    "HYRIV_ID",
    "NEXT_DOWN_ID",
    "RIVER_BASIN_ID",
    "SUBBASIN_ID",
    "ALONG_NETWORK_DISTANCE_TO_OUTLET_KM",
    "UPSTREAM_DISTANCE_KM",
    "SEGMENT_LENGTH_KM",
    "LOCAL_CATCHMENT_AREA_KM2",
    "UPSTREAM_DRAINAGE_AREA_KM2",
    "STRAHLER_ORDER",
    "CLASSICAL_ORDER",
    "FLOW_ORDER",
    "DIRECT_UPSTREAM_SEGMENT_COUNT",
    "SOURCE_NETWORK_TOPOLOGY_GAP",
    "geometry",
]

MOUTH_COLUMNS = [
    "FLUVIAL_MOUTH_ID",
    "SOURCE_DATASET",
    "HYRIV_ID",
    "RIVER_BASIN_ID",
    "OUTLET_SUBBASIN_ID",
    "CONNECTED_UPSTREAM_SEGMENT_COUNT",
    "CONNECTED_TRIBUTARY_JUNCTION_COUNT",
    "CONNECTED_HEADWATER_COUNT",
    "CONNECTED_STRAHLER_ORDER",
    "CONNECTED_UPSTREAM_NETWORK_LENGTH_KM",
    "CONNECTED_UPSTREAM_DISTANCE_KM",
    "CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2",
    "SOURCE_NETWORK_TOPOLOGY_GAP_COUNT",
    "COAST_DISTANCE_M",
    "GRAPH_SNAP_DISTANCE_M",
    "SOURCE_TO_WATER_DISTANCE_M",
    "GRAPH_CONNECTOR_WATER_PATH_FRACTION",
    "GRAPH_CONNECTION_QC_REASON",
    "MARINE_NETWORK_COMPONENT_ID",
    "geometry",
]

HYDRORIVERS_ATTRIBUTE_COLUMNS = [
    "HYRIV_ID",
    "NEXT_DOWN",
    "MAIN_RIV",
    "LENGTH_KM",
    "DIST_DN_KM",
    "DIST_UP_KM",
    "CATCH_SKM",
    "UPLAND_SKM",
    "ENDORHEIC",
    "ORD_STRA",
    "ORD_CLAS",
    "ORD_FLOW",
    "HYBAS_L12",
]


@dataclass(frozen=True)
class FluvialConnectivityConfig:
    """Resolved fluvial-network inputs, parameters, and output paths."""

    bbox: dict[str, float]
    h3_resolution: int
    projected_crs: str
    water_polygon_path: Path
    land_polygon_path: Path
    hydrorivers_path: Path
    processed_dir: Path
    feature_path: Path
    crosswalk_path: Path
    network_segments_path: Path
    network_mouths_path: Path
    network_context_buffer_km: float
    mouth_coast_tolerance_m: float
    mouth_graph_snap_max_km: float


def load_fluvial_connectivity_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> FluvialConnectivityConfig:
    """Load and validate the fluvial-connectivity build contract."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("fluvial_connectivity"), "fluvial_connectivity")
    processing = _mapping(
        section.get("processing"),
        "fluvial_connectivity.processing",
    )
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("fluvial_connectivity.processing.h3_resolution must be 8.")
    context_buffer_km = float(processing.get("network_context_buffer_km", 60))
    coast_tolerance_m = float(processing.get("mouth_coast_tolerance_m", 5_000))
    snap_max_km = float(processing.get("mouth_graph_snap_max_km", 5))
    if min(context_buffer_km, coast_tolerance_m, snap_max_km) <= 0:
        raise ValueError("Fluvial-connectivity distance settings must be positive.")
    processed_dir = _resolve(processing["processed_directory"], base_dir)
    return FluvialConnectivityConfig(
        bbox=bbox_from_config(section),
        h3_resolution=resolution,
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        water_polygon_path=_resolve(processing["water_polygon_path"], base_dir),
        land_polygon_path=_resolve(processing["land_polygon_path"], base_dir),
        hydrorivers_path=_resolve(processing["hydrorivers_path"], base_dir),
        processed_dir=processed_dir,
        feature_path=processed_dir / str(processing["feature_filename"]),
        crosswalk_path=processed_dir / str(processing["crosswalk_filename"]),
        network_segments_path=processed_dir / str(processing["network_segments_filename"]),
        network_mouths_path=processed_dir / str(processing["network_mouths_filename"]),
        network_context_buffer_km=context_buffer_km,
        mouth_coast_tolerance_m=coast_tolerance_m,
        mouth_graph_snap_max_km=snap_max_km,
    )


def _spatial_support(config: FluvialConnectivityConfig):
    water = _read_polygon_layer(config.water_polygon_path)
    land = _read_polygon_layer(config.land_polygon_path)
    target_box = box(
        config.bbox["min_lon"],
        config.bbox["min_lat"],
        config.bbox["max_lon"],
        config.bbox["max_lat"],
    )
    context_box = _expanded_bbox(config.bbox, config.network_context_buffer_km)
    land_guard_box = _expanded_bbox(config.bbox, config.network_context_buffer_km + 10)
    target_water = safe_polygonal_union(water, clip_geometry=target_box)
    guarded_land = safe_polygonal_union(land, clip_geometry=land_guard_box)
    context_land = normalize_polygonal_geometry(guarded_land.intersection(context_box))
    if target_water.is_empty or context_land.is_empty:
        raise ValueError("Fluvial-connectivity water or land support is empty.")
    context_water = safe_polygonal_union(water, clip_geometry=context_box)
    return target_water, context_water, context_box, context_land, guarded_land.boundary


def _load_hydrorivers_context(path: Path, context_box: Any):
    import geopandas as gpd

    if not path.exists():
        raise FileNotFoundError(
            f"HydroRIVERS source not found: {path}. Run freshwater_sources/download.py first."
        )
    frame = gpd.read_file(path, bbox=context_box.bounds)
    if frame.crs is None:
        raise ValueError(f"HydroRIVERS source has no CRS: {path}")
    frame = frame.to_crs("EPSG:4326")
    frame.columns = [
        str(column).upper() if column != frame.geometry.name else column for column in frame.columns
    ]
    if frame.geometry.name != "geometry":
        frame = frame.rename_geometry("geometry")
    frame = frame.explode(index_parts=False, ignore_index=True)
    frame = frame.loc[frame.geom_type.eq("LineString")].reset_index(drop=True)
    if frame.empty:
        raise ValueError("HydroRIVERS contains no linework in the graph context.")
    return frame


def _load_hydrorivers_attributes(path: Path) -> pd.DataFrame:
    import geopandas as gpd

    frame = gpd.read_file(
        path,
        columns=HYDRORIVERS_ATTRIBUTE_COLUMNS,
        ignore_geometry=True,
    )
    missing = sorted(set(HYDRORIVERS_ATTRIBUTE_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"HydroRIVERS is missing required attributes: {missing}")
    for column in HYDRORIVERS_ATTRIBUTE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    integer_columns = [
        "HYRIV_ID",
        "NEXT_DOWN",
        "MAIN_RIV",
        "ENDORHEIC",
        "ORD_STRA",
        "ORD_CLAS",
        "ORD_FLOW",
        "HYBAS_L12",
    ]
    for column in integer_columns:
        frame[column] = frame[column].astype("int64")
    if frame["HYRIV_ID"].duplicated().any():
        raise ValueError("HydroRIVERS HYRIV_ID values must be unique.")
    return frame


def _river_mouth_points(
    context: Any,
    coast_boundary: Any,
    config: FluvialConnectivityConfig,
):
    import geopandas as gpd

    terminal = pd.to_numeric(context["NEXT_DOWN"], errors="coerce").eq(0)
    exorheic = pd.to_numeric(context["ENDORHEIC"], errors="coerce").fillna(0).eq(0)
    candidates = context.loc[terminal & exorheic].copy().to_crs(config.projected_crs)
    if candidates.empty:
        raise ValueError("No exorheic HydroRIVERS outlets intersect the graph context.")
    projected_boundary = (
        gpd.GeoSeries(
            [coast_boundary],
            crs="EPSG:4326",
        )
        .to_crs(config.projected_crs)
        .iloc[0]
    )
    starts = gpd.GeoSeries(
        [Point(line.coords[0]) for line in candidates.geometry],
        index=candidates.index,
        crs=config.projected_crs,
    )
    ends = gpd.GeoSeries(
        [Point(line.coords[-1]) for line in candidates.geometry],
        index=candidates.index,
        crs=config.projected_crs,
    )
    start_distance = starts.distance(projected_boundary).to_numpy(dtype="float64")
    end_distance = ends.distance(projected_boundary).to_numpy(dtype="float64")
    mouth_at_end = end_distance <= start_distance
    candidates["COAST_DISTANCE_M"] = np.where(
        mouth_at_end,
        end_distance,
        start_distance,
    )
    candidates.geometry = gpd.GeoSeries(
        [
            ends.iloc[index] if mouth_at_end[index] else starts.iloc[index]
            for index in range(len(candidates))
        ],
        index=candidates.index,
        crs=config.projected_crs,
    )
    candidates = candidates.loc[
        candidates["COAST_DISTANCE_M"] <= config.mouth_coast_tolerance_m
    ].copy()
    if candidates.empty:
        raise ValueError("No HydroRIVERS outlet lies within the configured coast tolerance.")
    return candidates.reset_index(drop=True)


def _network_attributes(attributes: pd.DataFrame) -> pd.DataFrame:
    output = attributes.copy()
    direct_upstream = output.loc[output["NEXT_DOWN"].ne(0)].groupby("NEXT_DOWN").size()
    output["_DIRECT_UPSTREAM_COUNT"] = (
        output["HYRIV_ID"].map(direct_upstream).fillna(0).astype("int64")
    )
    known_ids = set(output["HYRIV_ID"].tolist())
    output["_TOPOLOGY_GAP"] = output["NEXT_DOWN"].ne(0) & ~output["NEXT_DOWN"].isin(known_ids)
    return output


def _network_summaries(
    attributes: pd.DataFrame,
    basin_ids: set[int],
) -> pd.DataFrame:
    selected = attributes.loc[attributes["MAIN_RIV"].isin(basin_ids)].copy()
    if selected.empty:
        raise ValueError("No full-network attributes match the contextual river outlets.")
    selected["_JUNCTION"] = selected["_DIRECT_UPSTREAM_COUNT"].ge(2).astype("int64")
    selected["_HEADWATER"] = selected["_DIRECT_UPSTREAM_COUNT"].eq(0).astype("int64")
    selected["_TOPOLOGY_GAP_INT"] = selected["_TOPOLOGY_GAP"].astype("int64")
    return (
        selected.groupby("MAIN_RIV", sort=True)
        .agg(
            CONNECTED_UPSTREAM_SEGMENT_COUNT=("HYRIV_ID", "size"),
            CONNECTED_TRIBUTARY_JUNCTION_COUNT=("_JUNCTION", "sum"),
            CONNECTED_HEADWATER_COUNT=("_HEADWATER", "sum"),
            CONNECTED_UPSTREAM_NETWORK_LENGTH_KM=("LENGTH_KM", "sum"),
            SOURCE_NETWORK_TOPOLOGY_GAP_COUNT=("_TOPOLOGY_GAP_INT", "sum"),
        )
        .reset_index()
        .rename(columns={"MAIN_RIV": "RIVER_BASIN_ID"})
    )


def _build_network_products(
    context: Any,
    attributes: pd.DataFrame,
    coast_boundary: Any,
    config: FluvialConnectivityConfig,
):
    import geopandas as gpd

    attributes = _network_attributes(attributes)
    mouths = _river_mouth_points(context, coast_boundary, config)
    mouths["HYRIV_ID"] = pd.to_numeric(mouths["HYRIV_ID"], errors="raise").astype("int64")
    mouths["RIVER_BASIN_ID"] = pd.to_numeric(
        mouths["MAIN_RIV"],
        errors="raise",
    ).astype("int64")
    summaries = _network_summaries(attributes, set(mouths["RIVER_BASIN_ID"]))
    mouths = mouths.merge(summaries, on="RIVER_BASIN_ID", how="left", validate="many_to_one")
    mouths["FLUVIAL_MOUTH_ID"] = HYDRORIVERS_SOURCE + "_" + mouths["HYRIV_ID"].astype(str)
    mouths["SOURCE_DATASET"] = HYDRORIVERS_SOURCE
    mouths["OUTLET_SUBBASIN_ID"] = pd.to_numeric(
        mouths["HYBAS_L12"],
        errors="raise",
    ).astype("int64")
    mouths["CONNECTED_STRAHLER_ORDER"] = pd.to_numeric(
        mouths["ORD_STRA"],
        errors="raise",
    ).astype("int64")
    mouths["CONNECTED_UPSTREAM_DISTANCE_KM"] = pd.to_numeric(
        mouths["DIST_UP_KM"],
        errors="raise",
    )
    mouths["CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2"] = pd.to_numeric(
        mouths["UPLAND_SKM"],
        errors="raise",
    )
    if mouths[list(summaries.columns[1:])].isna().any().any():
        raise ValueError("One or more contextual outlets lack complete network summaries.")

    direct_upstream = attributes.set_index("HYRIV_ID")["_DIRECT_UPSTREAM_COUNT"]
    topology_gap = attributes.set_index("HYRIV_ID")["_TOPOLOGY_GAP"]
    segments = context.copy()
    segments["HYRIV_ID"] = pd.to_numeric(segments["HYRIV_ID"], errors="raise").astype("int64")
    segments["FLUVIAL_SEGMENT_ID"] = HYDRORIVERS_SOURCE + "_" + segments["HYRIV_ID"].astype(str)
    segments["SOURCE_DATASET"] = HYDRORIVERS_SOURCE
    segments["NEXT_DOWN_ID"] = pd.to_numeric(
        segments["NEXT_DOWN"],
        errors="raise",
    ).astype("int64")
    segments["RIVER_BASIN_ID"] = pd.to_numeric(
        segments["MAIN_RIV"],
        errors="raise",
    ).astype("int64")
    segments["SUBBASIN_ID"] = pd.to_numeric(
        segments["HYBAS_L12"],
        errors="raise",
    ).astype("int64")
    renames = {
        "DIST_DN_KM": "ALONG_NETWORK_DISTANCE_TO_OUTLET_KM",
        "DIST_UP_KM": "UPSTREAM_DISTANCE_KM",
        "LENGTH_KM": "SEGMENT_LENGTH_KM",
        "CATCH_SKM": "LOCAL_CATCHMENT_AREA_KM2",
        "UPLAND_SKM": "UPSTREAM_DRAINAGE_AREA_KM2",
        "ORD_STRA": "STRAHLER_ORDER",
        "ORD_CLAS": "CLASSICAL_ORDER",
        "ORD_FLOW": "FLOW_ORDER",
    }
    segments = segments.rename(columns=renames)
    segments["DIRECT_UPSTREAM_SEGMENT_COUNT"] = (
        segments["HYRIV_ID"].map(direct_upstream).fillna(0).astype("int64")
    )
    segments["SOURCE_NETWORK_TOPOLOGY_GAP"] = (
        segments["HYRIV_ID"].map(topology_gap).fillna(False).astype(bool)
    )
    segments = gpd.GeoDataFrame(
        segments.loc[:, NETWORK_SEGMENT_COLUMNS],
        geometry="geometry",
        crs=context.crs,
    ).sort_values("FLUVIAL_SEGMENT_ID")
    return mouths.reset_index(drop=True), segments.reset_index(drop=True), attributes
