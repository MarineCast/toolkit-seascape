"""Optional normalized mapped-habitat mosaic on explicit tidal supports."""

from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent
from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.spatial_support.water_network.graph import target_graph_mapping
from seascape.spatial_support.water_network.load import (
    load_model_area_geometry,
    load_radius_sum_operator,
    load_water_graph,
)
from seascape.spatial_support.water_network.radius_operator import RadiusSumOperator
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)
from seascape.utils.habitat_surface import habitat_network_metrics

from .mosaic import build_mapped_mosaic


@dataclass(frozen=True)
class MosaicConfig:
    inventory_path: Path
    intertidal_support_path: Path | None
    marine_r8_path: Path
    output_dir: Path
    equal_area_crs: str
    as_of_year: int
    max_cells: int
    max_records: int
    selected_h3_indices: tuple[str, ...]
    max_radius_searches: int


def load_mosaic_config(config_path: str | Path) -> MosaicConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("mapped_habitat_mosaic")
    if not isinstance(section, dict) or not section.get("inventory_path"):
        raise ValueError(
            "Set mapped_habitat_mosaic.inventory_path to a normalized GeoParquet"
        )
    root = project_root()
    network = load_water_network_config(config_path)
    output = root / str(
        section.get(
            "output_dir",
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/mosaic",
        )
    )
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Habitat mosaic output escapes workspace")
    year = int(section["as_of_year"])
    max_cells = int(section.get("max_cells", 200))
    max_records = int(section.get("max_records", 10_000))
    max_radius_searches = int(section.get("max_radius_searches", 2000))
    if year < 1800 or min(max_cells, max_records, max_radius_searches) < 1:
        raise ValueError("Mosaic year and resource bounds are invalid")
    return MosaicConfig(
        root / str(section["inventory_path"]),
        root / str(section["intertidal_support_path"])
        if section.get("intertidal_support_path")
        else None,
        network.clipped_geometry_path(8),
        output,
        str(section.get("equal_area_crs", "EPSG:6933")),
        year,
        max_cells,
        max_records,
        tuple(str(value) for value in section.get("selected_h3_indices", ())),
        max_radius_searches,
    )


def _parent_support(children: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows = [
        {
            "H3_INDEX": parent,
            "H3_RESOLUTION": 6,
            "SUPPORT_TYPE": support_type,
            "geometry": unary_union(list(group.geometry)),
        }
        for (parent, support_type), group in children.assign(
            PARENT=children.H3_INDEX.map(lambda cell: cell_to_parent(str(cell), 6))
        ).groupby(["PARENT", "SUPPORT_TYPE"], sort=True)
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=children.crs)


def _radius_area(
    graph, cell: str, sources: list[tuple[str, int, float, float]], radius_m: float
) -> float | None:
    positions, connectors, _reasons = target_graph_mapping(graph, [cell])
    if positions[0] < 0:
        return None
    start = int(positions[0])
    queue = [(float(connectors[0]), start)]
    best = {start: float(connectors[0])}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > best[node] + 1e-9 or distance > radius_m:
            continue
        neighbors, weights = graph.neighbors_of(node)
        for target, weight in zip(neighbors, weights, strict=True):
            target = int(target)
            candidate = distance + float(weight)
            if candidate <= radius_m and candidate < best.get(target, math.inf):
                best[target] = candidate
                heapq.heappush(queue, (candidate, target))
    return sum(
        area
        for source_cell, node, connector, area in sources
        if source_cell == cell or best.get(node, math.inf) + connector <= radius_m
    )


def _network_mosaic_metrics(
    frame: pd.DataFrame, resolution: int, config_path: str | Path, max_searches: int
) -> pd.DataFrame:
    frame = frame.copy()
    frame["NEAREST_MAPPED_HABITAT_M"] = float("nan")
    frame["MAPPED_AREA_WITHIN_5KM_OF_SELECTED_SUPPORT_M2"] = float("nan")
    frame["NETWORK_QC"] = "intertidal_requires_reviewed_marine_attachment"
    marine = frame.loc[frame.SUPPORT_TYPE.eq("marine")]
    if marine.empty:
        return frame
    graph = load_water_graph(resolution, config_path)
    groups = list(marine.groupby("HABITAT_TYPE", sort=True))
    targets = sorted(set(marine.H3_INDEX.astype(str)))
    if resolution == 8:
        operator = load_radius_sum_operator(config_path)
        if operator.radius_m != 5000:
            raise ValueError(
                "Habitat mosaic requires the canonical 5000 m radius operator"
            )
    else:
        if len(targets) > max_searches:
            raise ValueError("Habitat radius-search budget exceeded")
        network = load_water_network_config(config_path)
        operator = RadiusSumOperator.build(
            graph,
            targets,
            radius_m=5000,
            graph_checksum=checksum_artifact(network.edge_path(resolution)),
            source_cells=sorted(graph.support.H3_INDEX.astype(str)),
        )
    for habitat_type, group in groups:
        cells = group.H3_INDEX.astype(str).tolist()
        area = group.set_index("H3_INDEX").MAPPED_AREA_M2.astype(float)
        present = set(area.loc[area.gt(0)].index.astype(str))
        distance, _unused_area, qc = habitat_network_metrics(
            graph, cells, present, area, None
        )
        radius = _operator_mapped_area(operator, area, cells)
        positions, _connectors, _reasons = target_graph_mapping(graph, cells)
        radius[positions < 0] = np.nan
        frame.loc[group.index, "NEAREST_MAPPED_HABITAT_M"] = distance
        frame.loc[group.index, "MAPPED_AREA_WITHIN_5KM_OF_SELECTED_SUPPORT_M2"] = radius
        frame.loc[group.index, "NETWORK_QC"] = [
            str(value)
            if value is not None and not pd.isna(value)
            else "mapped_habitat_graph_v1_selected_support_censored"
            for value in qc
        ]
    return frame


def _operator_mapped_area(operator, area, cells):
    values = area.reindex(operator.source_cells.astype(str)).to_numpy(dtype=float)
    summed = operator.apply(values, eligible_sources=np.isfinite(values) & (values > 0))
    return (
        pd.Series(summed, index=operator.cells.astype(str))
        .reindex(cells)
        .to_numpy(dtype=float, copy=True)
    )


def _validate_tidal_support(intertidal):
    required = {
        "H3_INDEX",
        "H3_RESOLUTION",
        "TIDAL_FRAME",
        "VERTICAL_DATUM",
        "SOURCE_RIGHTS",
        "SOURCE_ID",
        "SOURCE_VERSION",
        "INDEPENDENT_TIDAL_SUPPORT",
    }
    if required - set(intertidal) or intertidal.crs is None or intertidal.empty:
        raise ValueError(
            "Intertidal support needs R8 H3, independent source identity, tidal frame, datum and rights"
        )
    if (
        not intertidal.H3_RESOLUTION.eq(8).all()
        or intertidal.H3_INDEX.duplicated().any()
        or not intertidal.INDEPENDENT_TIDAL_SUPPORT.eq(True).all()
    ):
        raise ValueError(
            "Intertidal support needs unique R8 identities and an independent tidal source"
        )
    for name in (
        "TIDAL_FRAME",
        "VERTICAL_DATUM",
        "SOURCE_RIGHTS",
        "SOURCE_ID",
        "SOURCE_VERSION",
    ):
        if (
            intertidal[name].isna().any()
            or intertidal[name]
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin(
                {"", "unknown", "unspecified", "none", "nan", "null", "not_available"}
            )
            .any()
        ):
            raise ValueError(f"Intertidal support {name} is unqualified")
    if (
        intertidal.geometry.isna().any()
        or not intertidal.geometry.is_valid.all()
        or intertidal.geometry.is_empty.any()
        or intertidal.to_crs(6933).geometry.area.le(0).any()
    ):
        raise ValueError("Intertidal support must have valid positive-area geometry")


def build_mapped_habitat_mosaic(config_path: str | Path) -> tuple[Path, ...]:
    config = load_mosaic_config(config_path)
    inventory = gpd.read_parquet(config.inventory_path)
    required = {
        "RECORD_ID",
        "HABITAT_TYPE",
        "SUPPORT_TYPE",
        "SOURCE_DATASET",
        "SOURCE_FEATURE_ID",
        "SOURCE_RIGHTS",
        "RAW_CLASS",
    }
    if required - set(inventory) or inventory.crs is None:
        raise ValueError(
            f"Normalized inventory needs CRS and fields {sorted(required - set(inventory))}"
        )
    if (
        inventory.RECORD_ID.isna().any()
        or inventory.RECORD_ID.duplicated().any()
        or len(inventory) > config.max_records
    ):
        raise ValueError(
            "Mosaic record IDs are duplicate/null or record bound exceeded"
        )
    if (
        inventory.SOURCE_RIGHTS.isna().any()
        or inventory.SOURCE_RIGHTS.astype(str).str.len().eq(0).any()
    ):
        raise ValueError("Every mapped habitat source needs explicit rights")
    marine = load_model_area_geometry(8, config_path)
    marine["H3_RESOLUTION"] = 8
    marine["SUPPORT_TYPE"] = "marine"
    if config.selected_h3_indices:
        missing = set(config.selected_h3_indices) - set(marine.H3_INDEX.astype(str))
        if missing:
            raise KeyError(
                f"Selected habitat cells missing from canonical R8: {sorted(missing)}"
            )
        marine = marine.loc[marine.H3_INDEX.isin(config.selected_h3_indices)]
    if marine.empty or len(marine) > config.max_cells:
        raise ValueError("Marine habitat support cell bound exceeded or support empty")
    support = [marine[["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "geometry"]]]
    if inventory.SUPPORT_TYPE.eq("intertidal").any():
        if config.intertidal_support_path is None:
            raise ValueError("Intertidal habitat requires separate tidal-frame support")
        intertidal = gpd.read_parquet(config.intertidal_support_path)
        _validate_tidal_support(intertidal)
        if config.selected_h3_indices:
            intertidal = intertidal.loc[
                intertidal.H3_INDEX.isin(config.selected_h3_indices)
            ]
        if len(intertidal) > config.max_cells:
            raise ValueError("Intertidal support cell bound exceeded")
        intertidal["SUPPORT_TYPE"] = "intertidal"
        support.append(
            intertidal[["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "geometry"]]
        )
    crs = marine.crs
    support_r8 = gpd.GeoDataFrame(
        pd.concat([item.to_crs(crs) for item in support], ignore_index=True),
        geometry="geometry",
        crs=crs,
    )
    support_r6 = _parent_support(support_r8.to_crs(config.equal_area_crs))
    r8 = build_mapped_mosaic(
        support_r8,
        inventory,
        as_of_year=config.as_of_year,
        equal_area_crs=config.equal_area_crs,
    )
    r6 = build_mapped_mosaic(
        support_r6,
        inventory,
        as_of_year=config.as_of_year,
        equal_area_crs=config.equal_area_crs,
    )
    r8 = _network_mosaic_metrics(r8, 8, config_path, config.max_radius_searches)
    r6 = _network_mosaic_metrics(r6, 6, config_path, config.max_radius_searches)
    outputs = [
        (inventory, config.output_dir / "NORMALIZED_MAPPED_HABITAT_INVENTORY.parquet"),
        (support_r8, config.output_dir / "MAPPED_HABITAT_SUPPORT_RES_8.parquet"),
        (support_r6, config.output_dir / "MAPPED_HABITAT_SUPPORT_RES_6.parquet"),
        (r8, config.output_dir / "MAPPED_HABITAT_MOSAIC_RES_8.parquet"),
        (r6, config.output_dir / "MAPPED_HABITAT_MOSAIC_RES_6.parquet"),
    ]
    publisher = stage_parquet_family(config.output_dir, outputs)
    sources = [
        config.inventory_path,
        *(path for path in (config.intertidal_support_path,) if path),
    ]
    manifest = build_manifest(
        dataset_family="environment.seascape.mapped_habitat_mosaic",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": path.name,
                "path": str(path),
                "checksum": checksum_artifact(path),
                "license": "Per-record SOURCE_RIGHTS and tidal support terms",
            }
            for path in sources
        ],
        upstream_artifacts=[
            {
                "path": str(config.marine_r8_path),
                "checksum": checksum_artifact(config.marine_r8_path),
            }
        ],
        attribution=[
            {"text": str(source_id), "license": str(rights)}
            for source_id, rights in inventory[["SOURCE_DATASET", "SOURCE_RIGHTS"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        ],
        source_completeness="partial",
        metadata={
            "scientific_method_version": "resolved_mapped_habitat_mosaic_v1",
            "sample_support": "separate marine and tidal-frame source supports; R6 recomputed on R8 child unions; as-of evidence resolver",
        },
    )
    publisher.publish_manifest(
        config.output_dir / "mapped_habitat_mosaic_manifest.json", manifest
    )
    return tuple(path for _frame, path in outputs)
