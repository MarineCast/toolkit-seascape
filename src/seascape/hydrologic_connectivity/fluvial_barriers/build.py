"""Build sourced fluvial-barrier and passage-status features at H3 r8 and r6."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely import intersection, union_all
from shapely.geometry import box

from seascape.core.config.paths import project_root
from seascape.spatial_support.water_network.graph import (
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    attach_points_to_graph,
    load_model_area_support,
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
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.surface import (
    load_surface_config as load_habitat_surface_config,
)
from seascape.utils.values import iter_frame_records

from .aggregation import aggregate_r8_to_r6
from .download import DEFAULT_CONFIG_PATH, SECTION_NAME
from .sources import (
    BARRIER_TYPES,
    INVENTORY_COLUMNS,
    NETWORK_COLUMNS,
    PREFIX,
    _processing,
    deduplicate_inventory,
    load_source_inventory,
    validate_feature_table,
)

LOGGER = logging.getLogger(__name__)


def attach_barriers_to_network(
    barriers: Any,
    segments: Any,
    mouths: Any,
    *,
    projected_crs: str,
    max_distance_m: float,
):
    """Attach canonical points to the operational HydroRIVERS topology."""

    import geopandas as gpd

    canonical = barriers.loc[barriers["IS_CANONICAL"].astype(bool)].copy()
    if canonical.empty:
        raise ValueError("No canonical barrier records remain after deduplication.")
    if segments.crs is None or mouths.crs is None:
        raise ValueError("Fluvial network products must retain CRS metadata.")
    point_columns = [column for column in canonical.columns if column != "geometry"]
    segment_columns = [
        "FLUVIAL_SEGMENT_ID",
        "RIVER_BASIN_ID",
        "SUBBASIN_ID",
        "ALONG_NETWORK_DISTANCE_TO_OUTLET_KM",
        "SEGMENT_LENGTH_KM",
        "geometry",
    ]
    joined = gpd.sjoin_nearest(
        canonical[point_columns + ["geometry"]].to_crs(projected_crs),
        segments[segment_columns].to_crs(projected_crs),
        how="left",
        max_distance=float(max_distance_m),
        distance_col="NETWORK_SNAP_DISTANCE_M",
    )
    joined = joined.sort_values(
        ["SOURCE_RECORD_ID", "NETWORK_SNAP_DISTANCE_M", "FLUVIAL_SEGMENT_ID"],
        na_position="last",
    ).drop_duplicates("SOURCE_RECORD_ID", keep="first")
    mouths_lookup = mouths[
        ["FLUVIAL_MOUTH_ID", "RIVER_BASIN_ID", "OUTLET_SUBBASIN_ID"]
    ].drop_duplicates("RIVER_BASIN_ID")
    joined = joined.merge(mouths_lookup, on="RIVER_BASIN_ID", how="left", suffixes=("", "_MOUTH"))
    joined["OUTLET_SUBBASIN_ID"] = joined["OUTLET_SUBBASIN_ID"]
    attached = joined["FLUVIAL_SEGMENT_ID"].notna() & joined["FLUVIAL_MOUTH_ID"].notna()
    joined["NETWORK_SNAP_STATUS"] = np.where(attached, "ATTACHED", "UNATTACHED")
    joined["NETWORK_SOURCE"] = "HYDRORIVERS_V10_OPERATIONAL_FALLBACK"
    joined["ALONG_RIVER_DISTANCE_TO_MOUTH_KM"] = np.where(
        attached,
        pd.to_numeric(joined["ALONG_NETWORK_DISTANCE_TO_OUTLET_KM"], errors="coerce")
        + 0.5 * pd.to_numeric(joined["SEGMENT_LENGTH_KM"], errors="coerce"),
        np.nan,
    )
    joined["NETWORK_QC_REASON"] = np.where(
        attached,
        "nearest_hydrorivers_segment_midpoint_distance_approximation",
        "no_hydrorivers_segment_and_mouth_within_snap_tolerance",
    )
    joined = joined.drop(columns=["index_right"], errors="ignore").to_crs("EPSG:4326")
    return joined


def _positive_or_null(value: int | float) -> float:
    return float(value) if value > 0 else np.nan


def summarize_mouths(attached: Any, mouths: Any) -> pd.DataFrame:
    """Summarize mapped upstream evidence without converting missing to absence."""

    source = attached.loc[attached["NETWORK_SNAP_STATUS"].eq("ATTACHED")].copy()
    rows = []
    for _, mouth in iter_frame_records(mouths.sort_values("FLUVIAL_MOUTH_ID")):
        records = source.loc[source["FLUVIAL_MOUTH_ID"].eq(mouth["FLUVIAL_MOUTH_ID"])]
        physical = records.loc[records["BARRIER_TYPE"].isin(BARRIER_TYPES)]
        assessed = records.loc[~records["PASSAGE_STATUS"].eq("NOT_ASSESSED")]
        mapped_count = len(physical)
        if mapped_count:
            state = "MAPPED_BARRIERS_PRESENT"
        elif len(assessed):
            state = "ASSESSED_SITES_WITHOUT_MAPPED_TARGET_BARRIER"
        else:
            state = "NO_MAPPED_BARRIER_RECORDS"
        values: dict[str, Any] = {
            "FLUVIAL_MOUTH_ID": mouth["FLUVIAL_MOUTH_ID"],
            "RIVER_BASIN_ID": mouth["RIVER_BASIN_ID"],
            "OUTLET_SUBBASIN_ID": mouth["OUTLET_SUBBASIN_ID"],
            "BARRIER_INVENTORY_STATE": state,
            "MAPPED_UPSTREAM_BARRIER_PRESENT": 1.0 if mapped_count else np.nan,
            "MAPPED_UPSTREAM_BARRIER_COUNT": _positive_or_null(mapped_count),
            "MAPPED_UPSTREAM_DAM_COUNT": _positive_or_null(
                int(physical["BARRIER_TYPE"].eq("DAM").sum())
            ),
            "MAPPED_UPSTREAM_CULVERT_COUNT": _positive_or_null(
                int(physical["BARRIER_TYPE"].eq("CULVERT").sum())
            ),
            "MAPPED_UPSTREAM_WATERFALL_COUNT": _positive_or_null(
                int(physical["BARRIER_TYPE"].eq("WATERFALL").sum())
            ),
            "MAPPED_UPSTREAM_TIDE_GATE_COUNT": _positive_or_null(
                int(physical["BARRIER_TYPE"].eq("TIDE_GATE").sum())
            ),
            "MAPPED_ASSESSED_SITE_COUNT": _positive_or_null(len(assessed)),
            "MAPPED_BLOCKED_COUNT": _positive_or_null(
                int(records["PASSAGE_STATUS"].eq("BLOCKED").sum())
            ),
            "MAPPED_PARTIAL_COUNT": _positive_or_null(
                int(records["PASSAGE_STATUS"].eq("PARTIAL").sum())
            ),
            "MAPPED_PASSABLE_COUNT": _positive_or_null(
                int(records["PASSAGE_STATUS"].eq("PASSABLE").sum())
            ),
            "MAPPED_POTENTIAL_BARRIER_COUNT": _positive_or_null(
                int(records["PASSAGE_STATUS"].eq("POTENTIAL_BARRIER").sum())
            ),
            "MAPPED_UNKNOWN_STATUS_COUNT": _positive_or_null(
                int(records["PASSAGE_STATUS"].eq("UNKNOWN").sum())
            ),
            "NEAREST_MAPPED_BARRIER_FROM_MOUTH_KM": (
                physical["ALONG_RIVER_DISTANCE_TO_MOUTH_KM"].min() if mapped_count else np.nan
            ),
            "NEAREST_MAPPED_BLOCKING_BARRIER_FROM_MOUTH_KM": records.loc[
                records["PASSAGE_STATUS"].isin({"BLOCKED", "PARTIAL", "POTENTIAL_BARRIER"}),
                "ALONG_RIVER_DISTANCE_TO_MOUTH_KM",
            ].min(),
            "PASSAGE_STATUS_COVERAGE_FRAC": (
                float(len(assessed) / len(records)) if len(records) else np.nan
            ),
            "BARRIER_SOURCE_DATASETS": "|".join(sorted(set(records["SOURCE_DATASET"].astype(str))))
            or None,
            "BARRIER_LATEST_ASSESSMENT_YEAR": (
                pd.to_datetime(records["ASSESSMENT_DATE"], errors="coerce").dt.year.max()
                if len(records)
                else np.nan
            ),
            "BARRIER_EVIDENCE_CONFIDENCE": (
                int(records["CONFIDENCE_CLASS"].max()) if len(records) else 0
            ),
        }
        rows.append(values)
    summary = pd.DataFrame(rows)
    if len(summary) != len(mouths) or not summary["FLUVIAL_MOUTH_ID"].is_unique:
        raise ValueError("Mouth barrier summary must retain exactly one row per fluvial mouth.")
    return summary


def _water_geometry(path: Path, bbox_values: Mapping[str, float]):
    import geopandas as gpd

    frame = gpd.read_parquet(path).to_crs("EPSG:4326")
    bounds = box(
        float(bbox_values["min_lon"]) - 0.25,
        float(bbox_values["min_lat"]) - 0.25,
        float(bbox_values["max_lon"]) + 0.25,
        float(bbox_values["max_lat"]) + 0.25,
    )
    return intersection(union_all(frame.geometry.to_numpy()), bounds)


def build_r8_features(
    crosswalk: pd.DataFrame,
    mouth_summary: pd.DataFrame,
    mouths: Any,
    *,
    config_path: str | Path,
    bbox_values: Mapping[str, float],
    water_geometry: Any,
    processing: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Join river-basin evidence and marine distance on canonical r8 support."""

    import geopandas as gpd

    graph = load_water_graph(
        8,
        config_path,
        bbox=tuple(float(bbox_values[key]) for key in ("min_lon", "min_lat", "max_lon", "max_lat")),
    )
    affected = mouth_summary.loc[mouth_summary["MAPPED_UPSTREAM_BARRIER_PRESENT"].eq(1.0)].merge(
        mouths[["FLUVIAL_MOUTH_ID", "geometry"]], on="FLUVIAL_MOUTH_ID", how="left"
    )
    affected = gpd.GeoDataFrame(affected, geometry="geometry", crs=mouths.crs).to_crs("EPSG:4326")
    nearest_by_cell: dict[str, tuple[float, str]] = {}
    if len(affected):
        attachment = attach_points_to_graph(
            graph,
            affected.geometry.x.to_numpy(dtype="float64"),
            affected.geometry.y.to_numpy(dtype="float64"),
            water_geometry,
            source_water_max_distance_m=float(processing["source_water_max_distance_m"]),
            graph_connector_max_distance_m=float(processing["graph_connector_max_distance_m"]),
            candidate_limit=int(processing["graph_connector_candidate_limit"]),
        )
        sources = [
            (
                str(row.GRAPH_H3_INDEX),
                float(row.SOURCE_TO_WATER_DISTANCE_M) + float(row.GRAPH_CONNECTOR_DISTANCE_M),
                int(row.SOURCE_POSITION),
            )
            for row in attachment.itertuples(index=False)
            if bool(row.IS_CONNECTED)
        ]
        if sources:
            distances, owners = multi_source_shortest_paths(graph, sources)
            target_cells = crosswalk["H3_INDEX"].astype(str).tolist()
            positions, connectors, _reasons = target_graph_mapping(graph, target_cells)
            for cell, position, connector in zip(target_cells, positions, connectors, strict=True):
                if position < 0 or owners[position] < 0 or not np.isfinite(distances[position]):
                    continue
                mouth_id = str(affected.iloc[int(owners[position])]["FLUVIAL_MOUTH_ID"])
                nearest_by_cell[cell] = (float(distances[position] + connector), mouth_id)
    output = crosswalk.copy()
    output["H3_INDEX"] = output["H3_INDEX"].astype("string")
    output["H3_RESOLUTION"] = 8
    output = output.rename(
        columns={
            "FLUVIAL_MOUTH_ID": "NEAREST_FLUVIAL_MOUTH_ID",
            "RIVER_BASIN_ID": "NEAREST_RIVER_BASIN_ID",
            "OUTLET_SUBBASIN_ID": "NEAREST_OUTLET_SUBBASIN_ID",
            "WATER_NETWORK_DISTANCE_M": "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M",
        }
    )
    output = output.merge(
        mouth_summary.rename(columns={"FLUVIAL_MOUTH_ID": "NEAREST_FLUVIAL_MOUTH_ID"}).drop(
            columns=["RIVER_BASIN_ID", "OUTLET_SUBBASIN_ID"]
        ),
        on="NEAREST_FLUVIAL_MOUTH_ID",
        how="left",
        validate="many_to_one",
    )
    output["WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M"] = output["H3_INDEX"].map(
        lambda value: nearest_by_cell.get(str(value), (np.nan, None))[0]
    )
    output["NEAREST_BARRIER_AFFECTED_FLUVIAL_MOUTH_ID"] = output["H3_INDEX"].map(
        lambda value: nearest_by_cell.get(str(value), (np.nan, None))[1]
    )
    confidence = pd.DataFrame(
        {
            "H3_INDEX": output["H3_INDEX"],
            "H3_RESOLUTION": 8,
            f"{PREFIX}_CONFIDENCE": output["BARRIER_EVIDENCE_CONFIDENCE"].fillna(0).astype("int8"),
            f"{PREFIX}_UNMAPPED_AREA": output["BARRIER_INVENTORY_STATE"].eq(
                "NO_MAPPED_BARRIER_RECORDS"
            ),
            f"{PREFIX}_SOURCE_DATASETS": output["BARRIER_SOURCE_DATASETS"],
            f"{PREFIX}_EVIDENCE_BASIS": "authoritative mapped inventory; HydroRIVERS topology fallback",
            f"{PREFIX}_LATEST_SURVEY_YEAR": output["BARRIER_LATEST_ASSESSMENT_YEAR"],
        }
    )
    validate_feature_table(output, 8)
    return output, confidence


def build_fluvial_barriers(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, ...]:
    """Build inventory, lineage, topology, mouth, H3, confidence, and manifest products."""

    import geopandas as gpd

    surface = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    processing, base_dir = _processing(config_path)
    processed_dir = surface.processed_dir
    paths = {
        "inventory": surface.inventory_path,
        "lineage": processed_dir / str(processing["lineage_filename"]),
        "barriers": processed_dir / str(processing["barriers_filename"]),
        "mouth_summary": processed_dir / str(processing["mouth_summary_filename"]),
        "r8": surface.feature_path(8),
        "c8": surface.confidence_path(8),
        "r6": surface.feature_path(6),
        "c6": surface.confidence_path(6),
    }
    inventory = load_source_inventory(config_path)
    inventory, lineage = deduplicate_inventory(
        inventory, float(processing["deduplication_tolerance_m"])
    )
    segments_path = _resolve(processing["fluvial_segments_path"], base_dir)
    mouths_path = _resolve(processing["fluvial_mouths_path"], base_dir)
    crosswalk_path = _resolve(processing["watershed_crosswalk_path"], base_dir)
    for path in (segments_path, mouths_path, crosswalk_path):
        if not path.exists():
            raise FileNotFoundError(
                f"Required fluvial-connectivity product is missing: {path}. Rebuild fluvial_connectivity."
            )
    segments = gpd.read_parquet(segments_path)
    mouths = gpd.read_parquet(mouths_path).to_crs("EPSG:4326")
    attached = attach_barriers_to_network(
        inventory,
        segments,
        mouths,
        projected_crs=str(processing["projected_crs"]),
        max_distance_m=float(processing["river_network_snap_max_m"]),
    )
    barriers = attached.loc[:, [*INVENTORY_COLUMNS, *NETWORK_COLUMNS]].copy()
    summary = summarize_mouths(attached, mouths)
    crosswalk = pd.read_parquet(crosswalk_path)
    water_path = _resolve(processing["water_polygon_path"], base_dir)
    water = _water_geometry(water_path, surface.bbox)
    r8, c8 = build_r8_features(
        crosswalk,
        summary,
        mouths,
        config_path=config_path,
        bbox_values=surface.bbox,
        water_geometry=water,
        processing=processing,
    )
    parent_child = pd.read_parquet(surface.parent_child_path)
    support_r6 = load_model_area_support(6, config_path)
    r6, c6 = aggregate_r8_to_r6(r8, c8, parent_child, support_r6)
    frames = {
        "inventory": inventory,
        "lineage": lineage,
        "barriers": barriers,
        "mouth_summary": summary,
        "r8": r8,
        "c8": c8,
        "r6": r6,
        "c6": c6,
    }
    publisher = stage_parquet_family(
        surface.processed_dir,
        tuple((frames[key], path) for key, path in paths.items()),
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
        dataset_family="environment.seascape.fluvial_barriers",
        run_id=publisher.run_id,
        resolved_config={"surface": asdict(surface), "processing": processing},
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=source_records,
        upstream_artifacts=[
            {"path": str(path), "checksum": _sha256(path)}
            for path in (
                segments_path,
                mouths_path,
                crosswalk_path,
                surface.parent_child_path,
                water_path,
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
    )
    publisher.publish_manifest(surface.manifest_path, manifest)
    return (*paths.values(), surface.manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in build_fluvial_barriers(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
