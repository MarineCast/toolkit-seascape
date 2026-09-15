"""Build cross-border anthropogenic marine-structure features on H3 r8 and r6."""

from __future__ import annotations

import argparse
import gc
import logging
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely import area, intersection, length, union_all
from shapely.geometry import box

from seascape.core.config.paths import project_root
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.spatial_support.water_network.graph import (
    WaterGraph,
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    attach_points_to_graph,
    load_model_area_support,
    load_radius_sum_operator,
    load_reachable_water_area,
    load_water_graph,
    multi_source_shortest_paths,
)
from seascape.utils.acquisition import (
    load_download_config as load_habitat_download_config,
)
from seascape.utils.artifacts import (
    build_manifest,
)
from seascape.utils.artifacts import checksum_artifact as _sha256
from seascape.utils.artifacts import (
    stage_parquet_family,
)
from seascape.utils.surface import (
    load_cell_geometry as _load_cell_geometry,
)
from seascape.utils.surface import (
    load_surface_config as load_habitat_surface_config,
)
from seascape.utils.surface import (
    model_bbox_tuple as _model_bbox_tuple,
)

from .aggregation import aggregate_r8_to_r6
from .download import DEFAULT_CONFIG_PATH, SECTION_NAME
from .sources import (
    CONFIDENCE_FAMILIES,
    DISTANCE_FEATURES,
    OVERWATER_CLASSES,
    PREFIX,
    _processing,
    load_anthropogenic_inventory,
    normalize_anthropogenic_inventory,
    validate_confidence_table,
    validate_feature_table,
)

LOGGER = logging.getLogger(__name__)


def _spatial_pairs(cells: Any, inventory: Any, equal_area_crs: str):
    import geopandas as gpd

    projected_cells = cells.to_crs(equal_area_crs).reset_index(drop=True)
    projected_inventory = inventory.to_crs(equal_area_crs).reset_index(drop=True)
    pairs = gpd.sjoin(
        projected_cells[["H3_INDEX", "geometry"]],
        projected_inventory[["geometry"]],
        how="inner",
        predicate="intersects",
    )[["H3_INDEX", "index_right"]].drop_duplicates()
    return projected_cells, projected_inventory, pairs.reset_index(drop=True)


def _armoring_metrics(
    cells: Any,
    inventory: Any,
    pairs: pd.DataFrame,
    target_cells: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cell_positions = {cell: index for index, cell in enumerate(target_cells)}
    surveyed = np.zeros(len(target_cells), dtype="float64")
    armored = np.zeros(len(target_cells), dtype="float64")
    eligible = inventory.index[
        inventory["SUPPORTS_SHORELINE_DENOMINATOR"].astype(bool)
        & inventory["ARMORING_FRACTION_ESTIMATE"].notna()
    ]
    selected = pairs.loc[pairs["index_right"].isin(set(eligible))]
    for cell, source_index in selected.itertuples(index=False):
        cell_index = cell_positions[str(cell)]
        cell_geometry = cells.geometry.iloc[cell_index]
        source_geometry = inventory.geometry.iloc[int(source_index)]
        shared_length = float(length(intersection(cell_geometry, source_geometry)))
        if shared_length <= 0:
            continue
        surveyed[cell_index] += shared_length
        armored[cell_index] += shared_length * float(
            inventory.loc[int(source_index), "ARMORING_FRACTION_ESTIMATE"]
        )
    fraction = np.divide(
        armored,
        surveyed,
        out=np.full(len(target_cells), np.nan, dtype="float64"),
        where=surveyed > 0,
    )
    return armored, surveyed, np.clip(fraction, 0.0, 1.0)


def _area_metrics(
    cells: Any,
    inventory: Any,
    feature_class: str,
    water_area: np.ndarray,
    *,
    null_non_detection: bool,
) -> tuple[np.ndarray, np.ndarray]:
    records = inventory.loc[
        inventory["IS_CANONICAL"].astype(bool)
        & inventory["FEATURE_CLASS"].eq(feature_class)
        & inventory["SUPPORTS_AREA"].astype(bool)
    ]
    if records.empty:
        return (
            np.zeros(len(cells), dtype="float64"),
            np.full(len(cells), np.nan, dtype="float64"),
        )
    geometry = union_all(records.geometry.to_numpy())
    covered_area = np.asarray(
        area(intersection(cells.geometry.to_numpy(), geometry)), dtype="float64"
    )
    fraction = np.divide(
        covered_area,
        water_area,
        out=np.zeros(len(cells), dtype="float64"),
        where=water_area > 0,
    )
    fraction = np.clip(fraction, 0.0, 1.0)
    if null_non_detection:
        fraction[covered_area <= 0] = np.nan
    return covered_area, fraction


def _direct_cells_by_record(pairs: pd.DataFrame) -> dict[int, list[str]]:
    output: dict[int, list[str]] = {}
    for source_index, rows in pairs.groupby("index_right", sort=False):
        output[int(source_index)] = sorted(set(rows["H3_INDEX"].astype(str)))
    return output


def _external_attachments(
    inventory: Any,
    direct_cells: Mapping[int, list[str]],
    graph: WaterGraph,
    water_geometry: Any,
    processing: Mapping[str, Any],
) -> dict[int, tuple[str, float, str | None]]:
    import geopandas as gpd

    candidates = inventory.loc[
        inventory["IS_CANONICAL"].astype(bool)
        & ~inventory["FEATURE_CLASS"].eq("shoreline_survey")
        & ~inventory.index.isin(direct_cells)
    ]
    if candidates.empty:
        return {}
    points = candidates.geometry.representative_point().to_crs("EPSG:4326")
    projected_points = points.to_crs("EPSG:6933")
    projected_water = gpd.GeoSeries([water_geometry], crs="EPSG:4326").to_crs("EPSG:6933").iloc[0]
    source_to_water = projected_points.distance(projected_water).to_numpy(dtype="float64")
    within = source_to_water <= float(processing["source_water_max_distance_m"])
    output: dict[int, tuple[str, float, str | None]] = {
        int(source_index): ("", np.nan, "source_exceeds_water_entry_tolerance")
        for source_index in candidates.index[~within]
    }
    candidates = candidates.loc[within]
    points = points.loc[within]
    if candidates.empty:
        return output
    attachments = attach_points_to_graph(
        graph,
        points.x.to_numpy(dtype="float64"),
        points.y.to_numpy(dtype="float64"),
        water_geometry,
        source_water_max_distance_m=float(processing["source_water_max_distance_m"]),
        graph_connector_max_distance_m=float(processing["graph_connector_max_distance_m"]),
        candidate_limit=int(processing["graph_connector_candidate_limit"]),
    )
    source_indices = candidates.index.to_list()
    for row in attachments.itertuples(index=False):
        source_index = int(source_indices[int(row.SOURCE_POSITION)])
        if bool(row.IS_CONNECTED):
            output[source_index] = (
                str(row.GRAPH_H3_INDEX),
                float(row.SOURCE_TO_WATER_DISTANCE_M) + float(row.GRAPH_CONNECTOR_DISTANCE_M),
                None,
            )
        else:
            output[source_index] = ("", np.nan, str(row.QC_REASON))
    return output


def _seed_sources(
    inventory: Any,
    feature_class: str,
    direct_cells: Mapping[int, list[str]],
    attachments: Mapping[int, tuple[str, float, str | None]],
    graph: WaterGraph,
) -> tuple[list[tuple[str, float, int]], set[str], dict[int, str]]:
    sources: list[tuple[str, float, int]] = []
    direct_target_cells: set[str] = set()
    failures: dict[int, str] = {}
    records = inventory.loc[
        inventory["IS_CANONICAL"].astype(bool) & inventory["FEATURE_CLASS"].eq(feature_class)
    ]
    for source_index in records.index:
        cells = direct_cells.get(int(source_index), [])
        if cells:
            positions, connectors, reasons = target_graph_mapping(graph, cells)
            for cell, position, connector, reason in zip(
                cells, positions, connectors, reasons, strict=True
            ):
                direct_target_cells.add(str(cell))
                if position >= 0 and np.isfinite(connector):
                    sources.append(
                        (str(graph.cells[int(position)]), float(connector), int(source_index))
                    )
                elif reason is not None and not pd.isna(reason) and str(reason):
                    failures[int(source_index)] = str(reason)
            continue
        attachment = attachments.get(int(source_index))
        if attachment and attachment[0] and np.isfinite(attachment[1]):
            sources.append((attachment[0], float(attachment[1]), int(source_index)))
        else:
            failures[int(source_index)] = (
                attachment[2] if attachment else "source_has_no_water_cell_or_connector"
            )
    return sources, direct_target_cells, failures


def distance_from_seed_sources(
    graph: WaterGraph,
    target_cells: list[str],
    sources: list[tuple[str, float, int]],
    direct_target_cells: set[str] | None = None,
    *,
    empty_reason: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute canonical water-network distance from already attached sources."""

    if not sources:
        return (
            np.full(len(target_cells), np.nan, dtype="float64"),
            np.full(len(target_cells), empty_reason, dtype=object),
        )
    graph_distance, _owners = multi_source_shortest_paths(graph, sources)
    positions, connectors, reasons = target_graph_mapping(graph, target_cells)
    output = np.full(len(target_cells), np.nan, dtype="float64")
    qc = np.empty(len(target_cells), dtype=object)
    qc[:] = None
    for index, (position, connector, reason) in enumerate(
        zip(positions, connectors, reasons, strict=True)
    ):
        if position < 0 or not np.isfinite(connector):
            qc[index] = (
                "target_has_no_graph_mapping"
                if reason is None or pd.isna(reason) or not str(reason)
                else str(reason)
            )
            continue
        value = float(graph_distance[int(position)])
        if not np.isfinite(value):
            qc[index] = "no_mapped_source_in_water_component"
            continue
        output[index] = value + float(connector)
        qc[index] = reason
    if direct_target_cells:
        lookup = {cell: index for index, cell in enumerate(target_cells)}
        for cell in direct_target_cells:
            index = lookup.get(str(cell))
            if index is not None:
                output[index] = 0.0
                qc[index] = None
    return output, qc


def _record_source_cells(
    inventory: Any,
    feature_classes: set[str],
    direct_cells: Mapping[int, list[str]],
    attachments: Mapping[int, tuple[str, float, str | None]],
) -> dict[int, str]:
    output: dict[int, str] = {}
    records = inventory.loc[
        inventory["IS_CANONICAL"].astype(bool) & inventory["FEATURE_CLASS"].isin(feature_classes)
    ]
    for source_index in records.index:
        cells = direct_cells.get(int(source_index), [])
        if cells:
            output[int(source_index)] = cells[0]
        else:
            attachment = attachments.get(int(source_index))
            if attachment and attachment[0] and np.isfinite(attachment[1]):
                output[int(source_index)] = attachment[0]
    return output


def _mapped_presence(
    inventory: Any,
    feature_class: str,
    target_cells: list[str],
    direct_cells: Mapping[int, list[str]],
    attachments: Mapping[int, tuple[str, float, str | None]],
) -> np.ndarray:
    """Mark every directly intersected cell, or the mapped connector cell, as present."""

    output = np.full(len(target_cells), np.nan, dtype="float64")
    positions = {cell: index for index, cell in enumerate(target_cells)}
    records = inventory.loc[
        inventory["IS_CANONICAL"].astype(bool) & inventory["FEATURE_CLASS"].eq(feature_class)
    ]
    for source_index in records.index:
        cells = direct_cells.get(int(source_index), [])
        if not cells:
            attachment = attachments.get(int(source_index))
            cells = (
                [attachment[0]]
                if attachment and attachment[0] and np.isfinite(attachment[1])
                else []
            )
        for cell in cells:
            position = positions.get(str(cell))
            if position is not None:
                output[position] = 1.0
    return output


def _confidence_table(
    inventory: Any,
    target_cells: list[str],
    pairs: pd.DataFrame,
    assigned_cells: Mapping[int, str],
) -> pd.DataFrame:
    records_by_cell: dict[str, set[int]] = {cell: set() for cell in target_cells}
    for cell, source_index in pairs.itertuples(index=False):
        records_by_cell[str(cell)].add(int(source_index))
    for source_index, cell in assigned_cells.items():
        if cell in records_by_cell:
            records_by_cell[cell].add(int(source_index))
    rows: list[dict[str, Any]] = []
    for cell in target_cells:
        source_indices = records_by_cell[cell]
        local = inventory.loc[sorted(source_indices)] if source_indices else inventory.iloc[0:0]
        row: dict[str, Any] = {"H3_INDEX": cell, "H3_RESOLUTION": 8}
        for family, classes in CONFIDENCE_FAMILIES.items():
            selected = local.loc[local["FEATURE_CLASS"].isin(classes)]
            datasets = sorted(set(selected["SOURCE_DATASET"].dropna().astype(str)))
            row[f"{family}_SOURCE_DATASETS"] = "|".join(datasets) or None
            row[f"{family}_SOURCE_COUNT"] = len(datasets)
            row[f"{family}_CONFIDENCE"] = (
                int(selected["CONFIDENCE_CLASS"].max()) if not selected.empty else 0
            )
            row[f"{family}_UNMAPPED_AREA"] = selected.empty
        datasets = sorted(set(local["SOURCE_DATASET"].dropna().astype(str)))
        row["ANTHROPOGENIC_SOURCE_DATASETS"] = "|".join(datasets) or None
        row["ANTHROPOGENIC_SOURCE_COUNT"] = len(datasets)
        row["ANTHROPOGENIC_CONFIDENCE"] = (
            int(local["CONFIDENCE_CLASS"].max()) if not local.empty else 0
        )
        row["ANTHROPOGENIC_UNMAPPED_AREA"] = local.empty
        rows.append(row)
    return pd.DataFrame(rows)


def build_r8_tables(
    inventory: Any,
    support: pd.DataFrame,
    cells: Any,
    graph: WaterGraph,
    radius_operator: Any,
    reachable_water_area: np.ndarray,
    water_geometry: Any,
    processing: Mapping[str, Any],
    *,
    equal_area_crs: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build native-resolution features and parallel source-confidence fields."""

    inventory = normalize_anthropogenic_inventory(inventory)
    canonical = inventory.loc[inventory["IS_CANONICAL"].astype(bool)].copy()
    projected_cells, projected_inventory, pairs = _spatial_pairs(cells, canonical, equal_area_crs)
    target_cells = support["H3_INDEX"].astype(str).tolist()
    water_area = support["WATER_AREA_M2"].to_numpy(dtype="float64")
    direct_cells = _direct_cells_by_record(pairs)
    attachments = _external_attachments(
        projected_inventory.to_crs("EPSG:4326"),
        direct_cells,
        graph,
        water_geometry,
        processing,
    )
    armored_length, surveyed_length, armoring_fraction = _armoring_metrics(
        projected_cells, projected_inventory, pairs, target_cells
    )
    dredged_area, dredged_fraction = _area_metrics(
        projected_cells,
        projected_inventory,
        "dredged_channel",
        water_area,
        null_non_detection=True,
    )
    disposal_area, disposal_fraction = _area_metrics(
        projected_cells,
        projected_inventory,
        "disposal_site",
        water_area,
        null_non_detection=True,
    )
    aquaculture_area, aquaculture_fraction = _area_metrics(
        projected_cells,
        projected_inventory,
        "aquaculture",
        water_area,
        null_non_detection=True,
    )
    feature_data: dict[str, Any] = {
        "H3_INDEX": target_cells,
        "H3_RESOLUTION": 8,
        "SHORELINE_ARMORING_LENGTH_M": armored_length,
        "SHORELINE_SURVEYED_LENGTH_M": surveyed_length,
        "SHORELINE_ARMORING_FRAC": armoring_fraction,
        "DREDGED_AREA_M2": dredged_area,
        "DREDGED_AREA_FRAC": dredged_fraction,
        "DISPOSAL_SITE_AREA_M2": disposal_area,
        "DISPOSAL_SITE_AREA_FRAC": disposal_fraction,
        "AQUACULTURE_FOOTPRINT_AREA_M2": aquaculture_area,
        "AQUACULTURE_FOOTPRINT_FRAC": aquaculture_fraction,
    }
    for output_column, feature_class in DISTANCE_FEATURES.items():
        sources, direct, failures = _seed_sources(
            projected_inventory, feature_class, direct_cells, attachments, graph
        )
        distance, qc = distance_from_seed_sources(
            graph,
            target_cells,
            sources,
            direct,
            empty_reason=(
                next(iter(failures.values())) if failures else f"no_mapped_{feature_class}_source"
            ),
        )
        feature_data[output_column] = distance
        feature_data[output_column.removesuffix("_M") + "_QC_REASON"] = qc
    all_assigned = _record_source_cells(
        projected_inventory,
        set(DISTANCE_FEATURES.values()),
        direct_cells,
        attachments,
    )
    feature_data["ARTIFICIAL_REEF_PRESENCE"] = _mapped_presence(
        projected_inventory,
        "artificial_reef",
        target_cells,
        direct_cells,
        attachments,
    )
    feature_data["AQUACULTURE_PRESENCE"] = _mapped_presence(
        projected_inventory,
        "aquaculture",
        target_cells,
        direct_cells,
        attachments,
    )
    structure_cells = _record_source_cells(
        projected_inventory, OVERWATER_CLASSES, direct_cells, attachments
    )
    structure_values: dict[str, float] = {}
    for source_index, cell in structure_cells.items():
        structure_values[cell] = structure_values.get(cell, 0.0) + max(
            1.0, float(projected_inventory.loc[source_index, "STRUCTURE_COUNT"])
        )
    if structure_values:
        source_values = np.asarray(
            [structure_values.get(cell, 0.0) for cell in radius_operator.source_cells],
            dtype="float64",
        )
        unknown_sources = sorted(set(structure_values).difference(radius_operator.source_cells))
        if unknown_sources:
            raise ValueError(
                "Mapped overwater structures fall outside canonical radius support: "
                + ", ".join(unknown_sources[:5])
            )
        structure_count = radius_operator.apply(
            source_values,
            eligible_sources=source_values > 0,
        )
    else:
        structure_count = np.zeros(len(target_cells), dtype="float64")
    feature_data["OVERWATER_STRUCTURE_COUNT_WITHIN_5KM"] = structure_count
    feature_data["OVERWATER_STRUCTURE_DENSITY_PER_KM2"] = np.divide(
        structure_count,
        reachable_water_area / 1_000_000.0,
        out=np.full(len(target_cells), np.nan, dtype="float64"),
        where=reachable_water_area > 0,
    )
    feature_data["WATER_COMPONENT_ID"] = support["WATER_COMPONENT_ID"].astype(str).to_numpy()
    feature_data["NETWORK_CONNECTOR_METHOD"] = support["CONNECTOR_METHOD"].to_numpy()
    feature_data["NETWORK_CONNECTOR_DISTANCE_M"] = support["CONNECTOR_DISTANCE_M"].to_numpy(
        dtype="float64"
    )
    feature_data["NETWORK_DISTANCE_QC_REASON"] = support["GRAPH_QC_REASON"].to_numpy()
    features = pd.DataFrame(feature_data)
    confidence = _confidence_table(
        projected_inventory,
        target_cells,
        pairs,
        all_assigned,
    )
    validate_feature_table(features, 8)
    validate_confidence_table(confidence, 8, features["H3_INDEX"])
    return features, confidence


def build_anthropogenic_seascape(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    """Build source inventory, H3 feature/confidence tables, and manifest."""

    import geopandas as gpd

    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    processing = _processing(config_path)
    inventory = load_anthropogenic_inventory(config_path)
    bbox = _model_bbox_tuple(config)
    support_r8 = load_model_area_support(8, config_path)
    cells = _load_cell_geometry(config, support_r8)
    graph = load_water_graph(8, config_path, bbox=bbox, bbox_buffer_m=35_000.0)
    radius_operator = load_radius_sum_operator(config_path)
    reachable_frame = load_reachable_water_area(config_path)
    if radius_operator.radius_m != float(processing["marine_buffer_m"]):
        raise ValueError("Anthropogenic marine_buffer_m must match the canonical radius operator.")
    network_config = load_water_network_config(config_path)
    water_frame = gpd.read_parquet(network_config.water_polygon_path).to_crs("EPSG:4326")
    water_bounds = box(bbox[0] - 0.25, bbox[1] - 0.25, bbox[2] + 0.25, bbox[3] + 0.25)
    water_geometry = intersection(union_all(water_frame.geometry.to_numpy()), water_bounds)
    r8_features, r8_confidence = build_r8_tables(
        inventory,
        support_r8,
        cells,
        graph,
        radius_operator,
        reachable_frame["REACHABLE_WATER_AREA_WITHIN_5KM_M2"].to_numpy(dtype="float64"),
        water_geometry,
        processing,
        equal_area_crs=config.equal_area_crs,
    )
    del graph, cells, support_r8
    gc.collect()
    crosswalk = pd.read_parquet(config.parent_child_path)
    selected_children = set(r8_features["H3_INDEX"].astype(str))
    crosswalk = crosswalk.loc[
        crosswalk["CHILD_H3_INDEX"].astype(str).isin(selected_children)
    ].copy()
    selected_parents = set(crosswalk["PARENT_H3_INDEX"].astype(str))
    support_r6 = load_model_area_support(6, config_path)
    support_r6 = support_r6.loc[support_r6["H3_INDEX"].astype(str).isin(selected_parents)].copy()
    valid_parents = set(support_r6["H3_INDEX"].astype(str))
    crosswalk = crosswalk.loc[crosswalk["PARENT_H3_INDEX"].astype(str).isin(valid_parents)].copy()
    r6_features, r6_confidence = aggregate_r8_to_r6(
        r8_features,
        r8_confidence,
        crosswalk,
        support_r6,
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
    download = load_habitat_download_config(SECTION_NAME, config_path)
    source_records = []
    for name, source in download.sources.items():
        if not bool(source.get("enabled", True)):
            continue
        path = download.raw_dir / str(source["raw_filename"])
        source_records.append(
            {
                "name": name,
                "path": str(path),
                "checksum": _sha256(path),
                "license": source.get("license") or "See authoritative source terms",
                "attribution": source.get("attribution"),
            }
        )
    manifest = build_manifest(
        dataset_family="environment.seascape.anthropogenic",
        run_id=publisher.run_id,
        resolved_config={"surface": asdict(config), "processing": processing},
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=source_records,
        upstream_artifacts=[
            {"path": str(path), "checksum": _sha256(path)}
            for path in (
                config.parent_child_path,
                network_config.radius_sum_operator_path,
                network_config.reachable_water_area_path,
                network_config.manifest_path,
            )
        ],
        attribution=[
            {
                "text": record.get("attribution") or record["name"],
                "license": record["license"],
            }
            for record in source_records
        ],
        source_completeness="partial",
        metadata={
            "radius_operator_lineage": {
                "path": str(network_config.radius_sum_operator_path),
                "checksum": _sha256(network_config.radius_sum_operator_path),
                "radius_m": radius_operator.radius_m,
                "support_hash": radius_operator.support_hash,
                "source_support_hash": radius_operator.source_support_hash,
                "graph_checksum": radius_operator.graph_checksum,
            }
        },
    )
    publisher.publish_manifest(config.manifest_path, manifest)
    return (*paths, config.manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in build_anthropogenic_seascape(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
