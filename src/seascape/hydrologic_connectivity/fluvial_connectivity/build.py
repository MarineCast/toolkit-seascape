"""Build static fluvial-to-marine structural-connectivity features.

HydroRIVERS supplies one internally consistent directed river network. Marine
distance is calculated over adjacent non-land H3 centers, so islands and
peninsulas obstruct paths. The build deliberately does not interpret missing
dam, culvert, or waterfall records as an absence of physical barriers.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from seascape.core.config.paths import project_root
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
    checksum_artifact,
    stage_parquet_family,
)
from seascape.utils.spatial import project_h3_centers as _cell_centers

from .topology import (
    CROSSWALK_COLUMNS,
    DEFAULT_CONFIG_PATH,
    FEATURE_COLUMNS,
    MOUTH_COLUMNS,
    FluvialConnectivityConfig,
    _build_network_products,
    _load_hydrorivers_attributes,
    _load_hydrorivers_context,
    _spatial_support,
    load_fluvial_connectivity_config,
)

LOGGER = logging.getLogger(__name__)


def _snap_mouths_to_graph(
    mouths: Any,
    graph: WaterGraph,
    water_geometry: Any,
    config: FluvialConnectivityConfig,
):
    projected = mouths.to_crs(config.projected_crs).reset_index(drop=True)
    geographic = mouths.to_crs("EPSG:4326").reset_index(drop=True)
    attachment = attach_points_to_graph(
        graph,
        geographic.geometry.x.to_numpy(dtype="float64"),
        geographic.geometry.y.to_numpy(dtype="float64"),
        water_geometry,
        source_water_max_distance_m=config.mouth_coast_tolerance_m,
        graph_connector_max_distance_m=config.mouth_graph_snap_max_km * 1_000.0,
    )
    projected["_GRAPH_INDEX"] = [
        (
            graph.cell_to_position.get(str(value), -1)
            if value is not None and not pd.isna(value)
            else -1
        )
        for value in attachment["GRAPH_H3_INDEX"]
    ]
    projected["GRAPH_SNAP_DISTANCE_M"] = attachment["GRAPH_CONNECTOR_DISTANCE_M"].to_numpy()
    projected["SOURCE_TO_WATER_DISTANCE_M"] = attachment["SOURCE_TO_WATER_DISTANCE_M"].to_numpy()
    projected["GRAPH_CONNECTOR_WATER_PATH_FRACTION"] = attachment["WATER_PATH_FRACTION"].to_numpy()
    projected["GRAPH_CONNECTION_QC_REASON"] = attachment["QC_REASON"].astype("string")
    if not (projected["_GRAPH_INDEX"] >= 0).any():
        raise ValueError("No fluvial mouth has a water-valid canonical graph connector.")
    dropped = int((projected["_GRAPH_INDEX"] < 0).sum())
    if dropped:
        LOGGER.warning(
            "Preserved %d HydroRIVERS mouths without a water-valid graph connector",
            dropped,
        )
    return projected


def _nullable_owner_values(
    mouths: pd.DataFrame,
    owners: np.ndarray,
    column: str,
    *,
    string: bool = False,
) -> pd.Series:
    reachable = owners >= 0
    values: list[Any] = [None] * len(owners)
    source = mouths[column].to_numpy()
    for index in np.flatnonzero(reachable):
        value = source[owners[index]]
        values[index] = str(value) if string else value
    return pd.Series(values, dtype="string" if string else None)


def _build_marine_products(
    target_water: Any,
    context_water: Any,
    graph: WaterGraph,
    graph_cells: list[str],
    graph_x: np.ndarray,
    graph_y: np.ndarray,
    detour_distance_floor_m: float,
    mouths: Any,
    config: FluvialConnectivityConfig,
    config_path: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, Any]:
    import geopandas as gpd

    all_mouths = _snap_mouths_to_graph(mouths, graph, context_water, config)
    all_mouths = all_mouths.sort_values("FLUVIAL_MOUTH_ID").reset_index(drop=True)
    mouths = all_mouths.loc[all_mouths["_GRAPH_INDEX"] >= 0].reset_index(drop=True)
    mouth_graph_indices = mouths["_GRAPH_INDEX"].to_numpy(dtype=int)
    graph_distances, graph_owners = multi_source_shortest_paths(
        graph,
        [
            (
                graph_cells[int(graph_index)],
                float(connector),
                int(owner),
            )
            for owner, (graph_index, connector) in enumerate(
                zip(
                    mouth_graph_indices,
                    mouths["GRAPH_SNAP_DISTANCE_M"].to_numpy(dtype="float64"),
                    strict=True,
                )
            )
        ],
    )
    graph_lineage = graph.support.set_index("H3_INDEX").loc[graph_cells]
    mouths["MARINE_NETWORK_COMPONENT_ID"] = [
        graph_lineage.iloc[index]["WATER_COMPONENT_ID"] for index in mouth_graph_indices
    ]
    component_mouth_counts = mouths["MARINE_NETWORK_COMPONENT_ID"].value_counts().to_dict()

    target_support = load_model_area_support(config.h3_resolution, config_path)
    target_cells = target_support["H3_INDEX"].astype(str).tolist()
    _, _, target_x, target_y = _cell_centers(target_cells, config.projected_crs)
    target_graph_indices, target_connectors, target_qc = target_graph_mapping(graph, target_cells)
    mapped = target_graph_indices >= 0
    target_owners = np.full(len(target_cells), -1, dtype=int)
    target_owners[mapped] = graph_owners[target_graph_indices[mapped]]
    reachable = mapped & (target_owners >= 0)
    network_distance = np.full(len(target_cells), np.nan, dtype="float64")
    network_distance[reachable] = (
        graph_distances[target_graph_indices[reachable]] + target_connectors[reachable]
    )
    network_distance[~reachable] = np.nan
    canonical_support = graph.support.set_index("H3_INDEX").loc[target_cells]
    target_component_ids = canonical_support["WATER_COMPONENT_ID"].astype("string")

    projected_mouths = gpd.GeoDataFrame(
        mouths,
        geometry="geometry",
        crs=config.projected_crs,
    )
    mouth_x = projected_mouths.geometry.x.to_numpy(dtype="float64")
    mouth_y = projected_mouths.geometry.y.to_numpy(dtype="float64")
    euclidean = np.full(len(target_cells), np.nan, dtype="float64")
    euclidean[reachable] = np.hypot(
        target_x[reachable] - mouth_x[target_owners[reachable]],
        target_y[reachable] - mouth_y[target_owners[reachable]],
    )
    detour_m = np.full(len(target_cells), np.nan, dtype="float64")
    detour_m[reachable] = np.maximum(
        0.0,
        network_distance[reachable] - euclidean[reachable],
    )
    detour = np.full(len(target_cells), np.nan, dtype="float64")
    denominator = np.maximum(euclidean[reachable], detour_distance_floor_m)
    detour[reachable] = np.maximum(1.0, network_distance[reachable] / denominator)

    def owner_numeric(column: str, dtype: str = "float64") -> np.ndarray:
        output = np.full(len(target_cells), np.nan, dtype="float64")
        source = pd.to_numeric(mouths[column], errors="raise").to_numpy(dtype=dtype)
        output[reachable] = source[target_owners[reachable]]
        return output

    feature_data: dict[str, Any] = {
        "H3_INDEX": target_cells,
        "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M": network_distance,
        "EUCLIDEAN_DISTANCE_TO_FLUVIAL_MOUTH_M": euclidean,
        "FLUVIAL_PATH_DETOUR_M": detour_m,
        "FLUVIAL_PATH_DETOUR_RATIO": detour,
        "FLUVIAL_MOUTH_REACHABLE": reachable,
        "STRUCTURAL_DISCONTINUITY_FLAG": ~reachable,
        "NEAREST_FLUVIAL_MOUTH_ID": _nullable_owner_values(
            mouths,
            target_owners,
            "FLUVIAL_MOUTH_ID",
            string=True,
        ),
        "NEAREST_RIVER_BASIN_ID": _nullable_owner_values(
            mouths,
            target_owners,
            "RIVER_BASIN_ID",
            string=True,
        ),
        "NEAREST_OUTLET_SUBBASIN_ID": _nullable_owner_values(
            mouths,
            target_owners,
            "OUTLET_SUBBASIN_ID",
            string=True,
        ),
        "CONNECTED_UPSTREAM_SEGMENT_COUNT": owner_numeric("CONNECTED_UPSTREAM_SEGMENT_COUNT"),
        "CONNECTED_TRIBUTARY_JUNCTION_COUNT": owner_numeric("CONNECTED_TRIBUTARY_JUNCTION_COUNT"),
        "CONNECTED_HEADWATER_COUNT": owner_numeric("CONNECTED_HEADWATER_COUNT"),
        "CONNECTED_STRAHLER_ORDER": owner_numeric("CONNECTED_STRAHLER_ORDER"),
        "CONNECTED_UPSTREAM_NETWORK_LENGTH_KM": owner_numeric(
            "CONNECTED_UPSTREAM_NETWORK_LENGTH_KM"
        ),
        "CONNECTED_UPSTREAM_DISTANCE_KM": owner_numeric("CONNECTED_UPSTREAM_DISTANCE_KM"),
        "CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2": owner_numeric(
            "CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2"
        ),
        "SOURCE_NETWORK_TOPOLOGY_GAP_COUNT": owner_numeric("SOURCE_NETWORK_TOPOLOGY_GAP_COUNT"),
        "MARINE_NETWORK_COMPONENT_ID": target_component_ids.tolist(),
        "MAPPED_FLUVIAL_MOUTH_COUNT_IN_COMPONENT": [
            int(component_mouth_counts.get(component, 0)) for component in target_component_ids
        ],
        "NETWORK_CONNECTOR_METHOD": canonical_support["CONNECTOR_METHOD"].tolist(),
        "NETWORK_CONNECTOR_DISTANCE_M": canonical_support["CONNECTOR_DISTANCE_M"].tolist(),
        "NETWORK_DISTANCE_QC_REASON": np.where(
            reachable,
            target_qc,
            np.where(pd.isna(target_qc), "no_connected_fluvial_mouth_in_component", target_qc),
        ),
    }
    features = pd.DataFrame(feature_data).loc[:, FEATURE_COLUMNS]
    if not features["H3_INDEX"].is_unique:
        raise ValueError("Fluvial feature product must contain unique H3 cells.")
    numeric = features.select_dtypes(include=[np.number])
    if np.isinf(numeric.to_numpy(dtype="float64")).any():
        raise ValueError("Fluvial feature product contains infinite numeric values.")
    if (numeric.dropna() < 0).any().any():
        raise ValueError("Fluvial feature product contains negative numeric values.")

    crosswalk = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "FLUVIAL_MOUTH_ID": features["NEAREST_FLUVIAL_MOUTH_ID"],
            "RIVER_BASIN_ID": features["NEAREST_RIVER_BASIN_ID"],
            "OUTLET_SUBBASIN_ID": features["NEAREST_OUTLET_SUBBASIN_ID"],
            "WATER_NETWORK_DISTANCE_M": network_distance,
            "MARINE_NETWORK_COMPONENT_ID": features["MARINE_NETWORK_COMPONENT_ID"],
            "STRUCTURAL_DISCONTINUITY_FLAG": ~reachable,
            "CROSSWALK_METHOD": np.where(
                reachable,
                "nearest_reachable_hydrorivers_outlet_on_h3_water_graph",
                "no_mapped_outlet_in_marine_graph_component",
            ),
        }
    ).loc[:, CROSSWALK_COLUMNS]
    all_mouths["MARINE_NETWORK_COMPONENT_ID"] = all_mouths["FLUVIAL_MOUTH_ID"].map(
        mouths.set_index("FLUVIAL_MOUTH_ID")["MARINE_NETWORK_COMPONENT_ID"]
    )
    projected_all_mouths = gpd.GeoDataFrame(
        all_mouths,
        geometry="geometry",
        crs=config.projected_crs,
    )
    return (
        features.sort_values("H3_INDEX"),
        crosswalk.sort_values("H3_INDEX"),
        projected_all_mouths.loc[:, MOUTH_COLUMNS].to_crs("EPSG:4326"),
    )


def build_fluvial_connectivity(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path]:
    """Build fluvial network, mouth, H3 feature, and watershed-crosswalk products."""

    config = load_fluvial_connectivity_config(config_path)
    target_water, context_water, context_box, context_land, coast_boundary = _spatial_support(
        config
    )
    graph = load_water_graph(
        config.h3_resolution,
        config_path,
        bbox=tuple(context_box.bounds),
    )
    graph_cells = graph.cells.astype(str).tolist()
    graph_lineage = graph.support.set_index("H3_INDEX").loc[graph_cells]
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", config.projected_crs, always_xy=True)
    graph_x, graph_y = transformer.transform(
        graph_lineage["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(dtype="float64"),
        graph_lineage["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(dtype="float64"),
    )
    graph_x = np.asarray(graph_x, dtype="float64")
    graph_y = np.asarray(graph_y, dtype="float64")
    detour_distance_floor_m = float(np.median(graph.weights_m))
    context = _load_hydrorivers_context(config.hydrorivers_path, context_box)
    attributes = _load_hydrorivers_attributes(config.hydrorivers_path)
    mouths, segments, network_attributes = _build_network_products(
        context,
        attributes,
        coast_boundary,
        config,
    )
    features, crosswalk, mouths = _build_marine_products(
        target_water,
        context_water,
        graph,
        graph_cells,
        graph_x,
        graph_y,
        detour_distance_floor_m,
        mouths,
        config,
        config_path,
    )

    publisher = stage_parquet_family(
        config.processed_dir,
        (
            (segments.to_crs("EPSG:4326"), config.network_segments_path),
            (mouths, config.network_mouths_path),
            (features, config.feature_path),
            (crosswalk, config.crosswalk_path),
        ),
    )

    manifest = build_manifest(
        dataset_family="environment.seascape.fluvial_connectivity",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "HydroRIVERS v1.0 North America",
                "path": str(config.hydrorivers_path),
                "checksum": checksum_artifact(config.hydrorivers_path),
                "license": "HydroSHEDS licence terms",
            }
        ],
        upstream_artifacts=[
            {
                "path": str(config.water_polygon_path),
                "checksum": checksum_artifact(config.water_polygon_path),
            },
            {
                "path": str(config.land_polygon_path),
                "checksum": checksum_artifact(config.land_polygon_path),
            },
        ],
        attribution=[
            {"text": "HydroRIVERS v1.0, HydroSHEDS", "license": "HydroSHEDS licence terms"}
        ],
        source_completeness="partial",
    )
    manifest_path = config.processed_dir / "fluvial_connectivity_manifest.json"
    publisher.publish_manifest(manifest_path, manifest)

    LOGGER.info(
        "Saved %d HydroRIVERS segments, %d mouths, and %d marine H3 features",
        len(segments),
        len(mouths),
        len(features),
    )
    return (
        config.feature_path,
        config.crosswalk_path,
        config.network_segments_path,
        config.network_mouths_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    return parser


def main() -> int:
    args = _parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    paths = build_fluvial_connectivity(args.config)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
