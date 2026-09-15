"""Build physical shoreline fractions and straight/network class distances."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import points
from shapely.strtree import STRtree

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.h3 import cell_to_parent
from seascape.publication import (
    TransactionalSeascapePublisher,
)
from seascape.spatial_support.water_network import (
    load_model_area_support,
    load_water_graph,
)
from seascape.spatial_support.water_network.graph import (
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    multi_source_shortest_paths,
)
from seascape.utils.artifacts import (
    build_manifest,
    capture_staged_parquet_artifact,
)
from seascape.utils.config import (
    require_mapping,
    resolve_project_path,
)
from seascape.utils.spatial import align_to_model_support

from .download import DEFAULT_CONFIG_PATH, resolve_shoreline_sources

LOGGER = logging.getLogger(__name__)

CLASS_TOKENS = (
    "ROCKY",
    "SANDY",
    "GRAVEL",
    "CLIFF",
    "BLUFF",
    "DELTAIC",
    "ESTUARINE",
)

SHORELINE_LENGTH_COLUMNS = (
    "SHORELINE_TOTAL_MAPPED_LENGTH_M",
    "SHORELINE_CLASSIFIED_LENGTH_M",
    *(f"{token}_SHORE_LENGTH_M" for token in CLASS_TOKENS),
)


@dataclass(frozen=True)
class ShorelineConfig:
    resolutions: tuple[int, ...]
    projected_crs: str
    output_dir: Path
    inventory_path: Path
    feature_filename_template: str
    full_geometry_path_template: str
    sources: dict[str, dict[str, Any]]

    def feature_path(self, resolution: int) -> Path:
        return self.output_dir / self.feature_filename_template.format(res=resolution)

    def full_geometry_path(self, resolution: int) -> Path:
        return Path(self.full_geometry_path_template.format(res=resolution))

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "shoreline_characterization_manifest.json"


def load_shoreline_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> ShorelineConfig:
    """Load the shoreline product contract."""

    raw = load_data_config(resolve_config_path(config_path), domains="SEASCAPE_LAYER")
    section = require_mapping(
        raw.get("shoreline_characterization"),
        "shoreline_characterization",
    )
    processing = require_mapping(
        section.get("processing"),
        "shoreline_characterization.processing",
    )
    sources = require_mapping(section.get("sources"), "shoreline_characterization.sources")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    resolutions = tuple(
        dict.fromkeys(int(value) for value in processing.get("resolutions", [6, 8]))
    )
    if set(resolutions) != {6, 8}:
        raise ValueError("Shoreline characterization requires exactly H3 resolutions 6 and 8.")
    output_dir = resolve_project_path(processing["output_dir"], base_dir)
    inventory_filename = str(processing.get("inventory_filename", "SHORELINE_SEGMENTS.parquet"))
    return ShorelineConfig(
        resolutions=resolutions,
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        output_dir=output_dir,
        inventory_path=output_dir / inventory_filename,
        feature_filename_template=str(
            processing.get(
                "feature_filename_template",
                "SHORELINE_CHARACTERIZATION_RES_{res}.parquet",
            )
        ),
        full_geometry_path_template=str(
            resolve_project_path(processing["full_geometry_path_template"], base_dir)
        ),
        sources={
            name: require_mapping(value, f"shoreline source {name}")
            for name, value in sources.items()
        },
    )


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _segment_record(
    *,
    segment_id: str,
    source_segment_id: str,
    source_name: str,
    jurisdiction: str,
    observation_date: str | None,
    valid_from_date: str | None,
    valid_to_date: str | None,
    raw_classification: str,
    classified: bool,
    flags: Mapping[str, bool],
    geometry: Any,
) -> dict[str, Any]:
    return {
        "SEGMENT_ID": segment_id,
        "SOURCE_SEGMENT_ID": source_segment_id,
        "SOURCE_DATASET": source_name,
        "JURISDICTION": jurisdiction,
        "OBSERVATION_DATE": observation_date,
        "VALID_FROM_DATE": valid_from_date,
        "VALID_TO_DATE": valid_to_date,
        "RAW_CLASSIFICATION": raw_classification,
        "IS_PHYSICALLY_CLASSIFIED": bool(classified),
        "MAPPING_STATUS": "classified" if classified else "unmapped_or_unsupported",
        **{f"IS_{token}_SHORE": bool(flags.get(token, False)) for token in CLASS_TOKENS},
        "geometry": geometry,
    }


def _normalize_wa(
    path: Path,
    source_name: str,
    source: Mapping[str, Any],
) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path).to_crs("EPSG:4326")
    required = {"Seg_ID", "GeoUnit", "GeoClass", "DeltaPres", "geometry"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"WA shoreline source is missing fields: {missing}")
    rows = []
    for item in frame.itertuples(index=False):
        geometry = item.geometry
        if geometry is None or geometry.is_empty:
            continue
        unit = _text(item.GeoUnit)
        class_name = _text(item.GeoClass)
        labels = f"{class_name} | {unit}".casefold()
        modified = class_name.casefold() == "modified"
        flags = {
            "ROCKY": "rock" in labels,
            "SANDY": "sand" in labels,
            "GRAVEL": "gravel" in labels,
            "CLIFF": "cliff" in labels or "plunging rocky shoreline" in labels,
            "BLUFF": "bluff" in labels,
            "DELTAIC": _text(item.DeltaPres) in {"1", "1.0"} or "delta" in labels,
            "ESTUARINE": any(value in labels for value in ("estuary", "lagoon", "marsh")),
        }
        rows.append(
            _segment_record(
                segment_id=f"{source_name}:{_text(item.Seg_ID)}",
                source_segment_id=_text(item.Seg_ID),
                source_name=source_name,
                jurisdiction="WA",
                observation_date=_text(source.get("observation_date")) or None,
                valid_from_date=_text(source.get("valid_from_date")) or None,
                valid_to_date=_text(source.get("valid_to_date")) or None,
                raw_classification=f"GeoClass={class_name}; GeoUnit={unit}",
                classified=bool(class_name and not modified),
                flags=flags,
                geometry=geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_bc(
    path: Path,
    source_name: str,
    source: Mapping[str, Any],
) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path).to_crs("EPSG:4326")
    required = {
        "PHYIDENT",
        "PROJECT_CODE",
        "REP_TYPE_NAME",
        "COASTAL_CLASS_NAME",
        "FORM",
        "MATERIAL",
        "geometry",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"BC shoreline source is missing fields: {missing}")
    rows = []
    for position, item in enumerate(frame.itertuples(index=False)):
        geometry = item.geometry
        if geometry is None or geometry.is_empty:
            continue
        representative = _text(item.REP_TYPE_NAME)
        coastal_class = _text(item.COASTAL_CLASS_NAME)
        labels = f"{representative} | {coastal_class}".casefold()
        classified = _text(
            item.PROJECT_CODE
        ).upper() != "UNMAPD" and representative.casefold() not in {
            "",
            "- none -",
            "undefined",
            "man-made",
        }
        flags = {
            "ROCKY": "rock" in labels,
            "SANDY": "sand" in labels,
            "GRAVEL": "gravel" in labels,
            "CLIFF": "cliff" in labels,
            "BLUFF": "bluff" in labels,
            "DELTAIC": "delta" in labels,
            "ESTUARINE": any(value in labels for value in ("estuary", "lagoon", "marsh")),
        }
        source_id = _text(item.PHYIDENT) or str(position)
        rows.append(
            _segment_record(
                segment_id=f"{source_name}:{source_id}:{position:08d}",
                source_segment_id=source_id,
                source_name=source_name,
                jurisdiction="BC",
                observation_date=_text(source.get("observation_date")) or None,
                valid_from_date=_text(source.get("valid_from_date")) or None,
                valid_to_date=_text(source.get("valid_to_date")) or None,
                raw_classification=(
                    f"REP_TYPE_NAME={representative}; COASTAL_CLASS_NAME={coastal_class}; "
                    f"FORM={_text(item.FORM)}; MATERIAL={_text(item.MATERIAL)}"
                ),
                classified=classified,
                flags=flags,
                geometry=geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def normalize_inventory(
    sources: Mapping[str, tuple[Path, Mapping[str, Any]]],
) -> gpd.GeoDataFrame:
    """Normalize jurisdictional classifications while retaining raw labels."""

    normalizers = {"wa_physical": _normalize_wa, "bc_shorezone": _normalize_bc}
    frames = []
    for name, (path, source) in sorted(sources.items()):
        normalizer_name = str(source.get("normalizer", ""))
        if normalizer_name not in normalizers:
            raise ValueError(f"Unsupported shoreline normalizer {normalizer_name!r} for {name}.")
        frames.append(normalizers[normalizer_name](path, name, source))
    inventory = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326",
    )
    if inventory.empty or inventory["SEGMENT_ID"].duplicated().any():
        raise ValueError("Normalized shoreline inventory must be nonempty with unique IDs.")
    return inventory.sort_values("SEGMENT_ID").reset_index(drop=True)


def _aggregate_lengths(
    inventory: gpd.GeoDataFrame,
    cell_geometry: gpd.GeoDataFrame,
    support: pd.DataFrame,
    *,
    projected_crs: str,
) -> pd.DataFrame:
    cells = cell_geometry[["H3_INDEX", "geometry"]].to_crs(projected_crs)
    shore = inventory.to_crs(projected_crs)
    cell_values = list(cells.geometry)
    tree = STRtree(cell_values)
    positions = {str(cell): index for index, cell in enumerate(cells["H3_INDEX"])}
    total = np.zeros(len(cells), dtype="float64")
    classified = np.zeros(len(cells), dtype="float64")
    class_lengths = {token: np.zeros(len(cells), dtype="float64") for token in CLASS_TOKENS}
    for item in shore.itertuples(index=False):
        for candidate in tree.query(item.geometry, predicate="intersects"):
            candidate = int(candidate)
            shared = item.geometry.intersection(cell_values[candidate])
            shared_length = float(shared.length)
            if shared_length <= 0:
                continue
            total[candidate] += shared_length
            if item.IS_PHYSICALLY_CLASSIFIED:
                classified[candidate] += shared_length
                for token in CLASS_TOKENS:
                    if getattr(item, f"IS_{token}_SHORE"):
                        class_lengths[token][candidate] += shared_length
    values = pd.DataFrame(
        {
            "H3_INDEX": cells["H3_INDEX"].astype(str),
            "SHORELINE_TOTAL_MAPPED_LENGTH_M": total,
            "SHORELINE_CLASSIFIED_LENGTH_M": classified,
            "SHORELINE_CLASSIFIED_COVERAGE_FRAC": np.divide(
                classified,
                total,
                out=np.full(len(cells), np.nan),
                where=total > 0,
            ),
        }
    )
    for token in CLASS_TOKENS:
        values[f"{token}_SHORE_LENGTH_M"] = class_lengths[token]
        values[f"{token}_SHORE_FRAC"] = np.divide(
            class_lengths[token],
            classified,
            out=np.full(len(cells), np.nan),
            where=classified > 0,
        )
    if set(positions) != set(values["H3_INDEX"]):
        raise ValueError("Shoreline geometry and support identifiers are misaligned.")
    return align_to_model_support(support, values, feature_label="shoreline length metrics")


def _straight_distances(
    support: pd.DataFrame,
    class_segments: gpd.GeoDataFrame,
    *,
    projected_crs: str,
) -> np.ndarray:
    if class_segments.empty:
        return np.full(len(support), np.nan)
    points_frame = gpd.GeoSeries(
        points(
            support["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(),
            support["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(),
        ),
        crs="EPSG:4326",
    ).to_crs(projected_crs)
    projected_class = class_segments.to_crs(projected_crs).geometry.explode(
        index_parts=False, ignore_index=True
    )
    tree = STRtree(projected_class.to_numpy())
    indexes, nearest_distances = tree.query_nearest(
        points_frame.to_numpy(),
        return_distance=True,
        all_matches=False,
    )
    output = np.full(len(points_frame), np.nan)
    output[np.asarray(indexes[0], dtype="int64")] = np.asarray(
        nearest_distances,
        dtype="float64",
    )
    return output


def recompute_parent_shoreline_lengths(
    child: pd.DataFrame,
    parent: pd.DataFrame,
    *,
    parent_resolution: int,
) -> pd.DataFrame:
    """Recompute R6 shoreline fractions from summed canonical R8 lengths."""

    required = {"H3_INDEX", *SHORELINE_LENGTH_COLUMNS}
    for name, frame in (("child", child), ("parent", parent)):
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise ValueError(f"Shoreline {name} table is missing columns: {missing}")
    values = child.loc[:, ["H3_INDEX", *SHORELINE_LENGTH_COLUMNS]].copy()
    values["H3_INDEX"] = (
        values["H3_INDEX"].astype(str).map(lambda cell: cell_to_parent(cell, parent_resolution))
    )
    grouped = values.groupby("H3_INDEX", sort=True, observed=True)[
        list(SHORELINE_LENGTH_COLUMNS)
    ].sum(min_count=1)
    output = parent.copy()
    output["H3_INDEX"] = output["H3_INDEX"].astype(str)
    output = output.set_index("H3_INDEX")
    unknown = sorted(set(grouped.index).difference(output.index))
    if unknown:
        raise ValueError(f"R8 shoreline cells map outside canonical R6 support: {unknown[:5]}")
    output.loc[grouped.index, list(SHORELINE_LENGTH_COLUMNS)] = grouped
    total = output["SHORELINE_TOTAL_MAPPED_LENGTH_M"]
    classified = output["SHORELINE_CLASSIFIED_LENGTH_M"]
    output["SHORELINE_CLASSIFIED_COVERAGE_FRAC"] = classified.div(total.where(total > 0))
    for token in CLASS_TOKENS:
        output[f"{token}_SHORE_FRAC"] = output[f"{token}_SHORE_LENGTH_M"].div(
            classified.where(classified > 0)
        )
    return output.reset_index()


def _network_distances(
    graph: Any,
    support: pd.DataFrame,
    source_cells: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    distances = np.full(len(support), np.nan)
    reasons = np.full(len(support), "shoreline_class_not_mapped", dtype=object)
    if not source_cells:
        return distances, reasons
    source_positions, source_connectors, _source_reasons = target_graph_mapping(graph, source_cells)
    seeds: list[tuple[str, float, int]] = []
    for owner, (position, connector) in enumerate(
        zip(source_positions, source_connectors, strict=True)
    ):
        if position >= 0 and np.isfinite(connector):
            seeds.append((str(graph.cells[position]), float(connector), owner))
    if not seeds:
        reasons[:] = "shoreline_class_has_no_reachable_graph_seed"
        return distances, reasons
    graph_distances, _owners = multi_source_shortest_paths(graph, seeds)
    target_positions, target_connectors, target_reasons = target_graph_mapping(
        graph,
        support["H3_INDEX"].astype(str).tolist(),
    )
    for index, (position, connector) in enumerate(
        zip(target_positions, target_connectors, strict=True)
    ):
        if position >= 0 and np.isfinite(connector) and np.isfinite(graph_distances[position]):
            distances[index] = float(graph_distances[position] + connector)
            reasons[index] = target_reasons[index]
        else:
            reasons[index] = target_reasons[index] or "shoreline_class_graph_disconnected"
    return distances, reasons


def _build_resolution(
    config_path: str | Path,
    config: ShorelineConfig,
    inventory: gpd.GeoDataFrame,
    resolution: int,
    child_lengths: pd.DataFrame | None = None,
) -> pd.DataFrame:
    support = load_model_area_support(resolution, config_path)
    geometry_path = config.full_geometry_path(resolution)
    if not geometry_path.exists():
        raise FileNotFoundError(f"Canonical full-cell geometry not found: {geometry_path}")
    cell_geometry = gpd.read_parquet(geometry_path)
    support_cells = set(support["H3_INDEX"].astype(str))
    cell_geometry = cell_geometry.loc[
        cell_geometry["H3_INDEX"].astype(str).isin(support_cells)
    ].copy()
    if set(cell_geometry["H3_INDEX"].astype(str)) != support_cells:
        raise ValueError(f"H3 r{resolution} full geometry does not match canonical support.")
    output = _aggregate_lengths(
        inventory,
        cell_geometry,
        support,
        projected_crs=config.projected_crs,
    )
    if child_lengths is not None:
        output = recompute_parent_shoreline_lengths(
            child_lengths,
            output,
            parent_resolution=resolution,
        )
    graph = load_water_graph(resolution, config_path)
    for token in CLASS_TOKENS:
        selected = inventory.loc[
            inventory["IS_PHYSICALLY_CLASSIFIED"] & inventory[f"IS_{token}_SHORE"]
        ]
        output[f"STRAIGHT_DISTANCE_TO_{token}_SHORE_M"] = _straight_distances(
            support,
            selected,
            projected_crs=config.projected_crs,
        )
        source_cells = (
            output.loc[
                output[f"{token}_SHORE_LENGTH_M"].gt(0),
                "H3_INDEX",
            ]
            .astype(str)
            .tolist()
        )
        network_distance, reasons = _network_distances(
            graph,
            support,
            source_cells,
        )
        output[f"WATER_NETWORK_DISTANCE_TO_{token}_SHORE_M"] = network_distance
        output[f"{token}_SHORE_NETWORK_DISTANCE_QC_REASON"] = pd.Series(
            reasons,
            dtype="string",
        )
    return output


def build_shoreline_characterization(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, ...]:
    """Build normalized inventory and both canonical H3 feature resolutions."""

    config = load_shoreline_config(config_path)
    resolved_sources = resolve_shoreline_sources(config_path)
    inventory = normalize_inventory(resolved_sources)
    with TransactionalSeascapePublisher(config.output_dir) as publisher:
        staged_inventory = publisher.stage_path(config.inventory_path)
        inventory.to_parquet(staged_inventory, index=False)
        destinations = [config.inventory_path]
        by_resolution: dict[int, pd.DataFrame] = {}
        for resolution in sorted(config.resolutions, reverse=True):
            destination = config.feature_path(resolution)
            frame = _build_resolution(
                config_path,
                config,
                inventory,
                resolution,
                child_lengths=by_resolution.get(8) if resolution == 6 else None,
            )
            frame.to_parquet(publisher.stage_path(destination), index=False)
            by_resolution[resolution] = frame
            destinations.append(destination)
        artifacts = [
            capture_staged_parquet_artifact(publisher, destination) for destination in destinations
        ]
        source_records = []
        for name, (path, source) in resolved_sources.items():
            source_records.append(
                {
                    "name": name,
                    "path": str(path),
                    "checksum": checksum_path(path),
                    "license": source.get("license"),
                    "attribution": source.get("attribution"),
                    "observation_date": source.get("observation_date"),
                    "source_completeness_warning": source.get("source_completeness_warning"),
                    "redistribution_restrictions": source.get("redistribution_restrictions"),
                }
            )
        manifest = build_manifest(
            dataset_family="environment.seascape.shoreline_characterization",
            run_id=publisher.run_id,
            resolved_config=asdict(config),
            artifacts=artifacts,
            project_root=project_root(),
            sources=source_records,
            upstream_artifacts=[
                {
                    "path": str(config.full_geometry_path(resolution)),
                    "checksum": checksum_path(config.full_geometry_path(resolution)),
                }
                for resolution in config.resolutions
            ],
            attribution=[
                {"text": source.get("attribution"), "license": source.get("license")}
                for source in config.sources.values()
            ],
            source_completeness="partial",
            metadata={
                "fraction_denominator": "physically_classified_shoreline_length_m",
                "overlapping_classes_may_sum_above_one": True,
                "distance_semantics": ["straight_projected", "water_network"],
                "h3_resolutions": list(config.resolutions),
            },
        )
        publisher.stage_manifest(config.manifest_path, manifest)
        publisher.publish()
    return tuple([*destinations, config.manifest_path])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(
        json.dumps([str(path) for path in build_shoreline_characterization(args.config)], indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
