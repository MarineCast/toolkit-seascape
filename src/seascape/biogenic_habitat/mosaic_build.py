"""Optional normalized mapped-habitat mosaic on explicit tidal supports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent
from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.utils.artifacts import build_manifest, checksum_artifact, stage_parquet_family

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


def load_mosaic_config(config_path: str | Path) -> MosaicConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("mapped_habitat_mosaic")
    if not isinstance(section, dict) or not section.get("inventory_path"):
        raise ValueError("Set mapped_habitat_mosaic.inventory_path to a normalized GeoParquet")
    root = project_root()
    network = load_water_network_config(config_path)
    output = root / str(section.get("output_dir", "data/processed/domain/environmental_layer/seascape/biogenic_habitat/mosaic"))
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Habitat mosaic output escapes workspace")
    year = int(section["as_of_year"])
    max_cells = int(section.get("max_cells", 200))
    max_records = int(section.get("max_records", 10_000))
    if year < 1800 or min(max_cells, max_records) < 1:
        raise ValueError("Mosaic year and resource bounds are invalid")
    return MosaicConfig(
        root / str(section["inventory_path"]),
        root / str(section["intertidal_support_path"]) if section.get("intertidal_support_path") else None,
        network.clipped_geometry_path(8), output,
        str(section.get("equal_area_crs", "EPSG:6933")), year,
        max_cells, max_records,
        tuple(str(value) for value in section.get("selected_h3_indices", ())),
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


def build_mapped_habitat_mosaic(config_path: str | Path) -> tuple[Path, ...]:
    config = load_mosaic_config(config_path)
    inventory = gpd.read_parquet(config.inventory_path)
    required = {"RECORD_ID", "HABITAT_TYPE", "SUPPORT_TYPE", "SOURCE_DATASET", "SOURCE_FEATURE_ID", "SOURCE_RIGHTS", "RAW_CLASS"}
    if required - set(inventory) or inventory.crs is None:
        raise ValueError(f"Normalized inventory needs CRS and fields {sorted(required - set(inventory))}")
    if inventory.RECORD_ID.isna().any() or inventory.RECORD_ID.duplicated().any() or len(inventory) > config.max_records:
        raise ValueError("Mosaic record IDs are duplicate/null or record bound exceeded")
    if inventory.SOURCE_RIGHTS.isna().any() or inventory.SOURCE_RIGHTS.astype(str).str.len().eq(0).any():
        raise ValueError("Every mapped habitat source needs explicit rights")
    marine = gpd.read_parquet(config.marine_r8_path)
    marine["H3_RESOLUTION"] = 8
    marine["SUPPORT_TYPE"] = "marine"
    if config.selected_h3_indices:
        missing = set(config.selected_h3_indices) - set(marine.H3_INDEX.astype(str))
        if missing:
            raise KeyError(f"Selected habitat cells missing from canonical R8: {sorted(missing)}")
        marine = marine.loc[marine.H3_INDEX.isin(config.selected_h3_indices)]
    if marine.empty or len(marine) > config.max_cells:
        raise ValueError("Marine habitat support cell bound exceeded or support empty")
    support = [marine[["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "geometry"]]]
    if inventory.SUPPORT_TYPE.eq("intertidal").any():
        if config.intertidal_support_path is None:
            raise ValueError("Intertidal habitat requires separate tidal-frame support")
        intertidal = gpd.read_parquet(config.intertidal_support_path)
        needed = {"H3_INDEX", "H3_RESOLUTION", "TIDAL_FRAME", "VERTICAL_DATUM", "SOURCE_RIGHTS"}
        if needed - set(intertidal) or intertidal.crs is None or not intertidal.H3_RESOLUTION.eq(8).all():
            raise ValueError("Intertidal support needs R8 H3, tidal frame, datum and source rights")
        if config.selected_h3_indices:
            intertidal = intertidal.loc[intertidal.H3_INDEX.isin(config.selected_h3_indices)]
        if len(intertidal) > config.max_cells:
            raise ValueError("Intertidal support cell bound exceeded")
        intertidal["SUPPORT_TYPE"] = "intertidal"
        support.append(intertidal[["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "geometry"]])
    crs = marine.crs
    support_r8 = gpd.GeoDataFrame(pd.concat([item.to_crs(crs) for item in support], ignore_index=True), geometry="geometry", crs=crs)
    support_r6 = _parent_support(support_r8.to_crs(config.equal_area_crs))
    r8 = build_mapped_mosaic(support_r8, inventory, as_of_year=config.as_of_year, equal_area_crs=config.equal_area_crs)
    r6 = build_mapped_mosaic(support_r6, inventory, as_of_year=config.as_of_year, equal_area_crs=config.equal_area_crs)
    outputs = [
        (inventory, config.output_dir / "NORMALIZED_MAPPED_HABITAT_INVENTORY.parquet"),
        (support_r8, config.output_dir / "MAPPED_HABITAT_SUPPORT_RES_8.parquet"),
        (support_r6, config.output_dir / "MAPPED_HABITAT_SUPPORT_RES_6.parquet"),
        (r8, config.output_dir / "MAPPED_HABITAT_MOSAIC_RES_8.parquet"),
        (r6, config.output_dir / "MAPPED_HABITAT_MOSAIC_RES_6.parquet"),
    ]
    publisher = stage_parquet_family(config.output_dir, outputs)
    sources = [config.inventory_path, *(path for path in (config.intertidal_support_path,) if path)]
    manifest = build_manifest(
        dataset_family="environment.seascape.mapped_habitat_mosaic", run_id=publisher.run_id,
        resolved_config=asdict(config), artifacts=publisher.artifacts, project_root=project_root(),
        sources=[{"name": path.name, "path": str(path), "checksum": checksum_artifact(path), "license": "Per-record SOURCE_RIGHTS and tidal support terms"} for path in sources],
        upstream_artifacts=[{"path": str(config.marine_r8_path), "checksum": checksum_artifact(config.marine_r8_path)}],
        attribution=[], source_completeness="partial",
        metadata={"scientific_method_version": "resolved_mapped_habitat_mosaic_v1", "sample_support": "separate marine and tidal-frame source supports; R6 recomputed on R8 child unions; as-of evidence resolver"},
    )
    publisher.publish_manifest(config.output_dir / "mapped_habitat_mosaic_manifest.json", manifest)
    return tuple(path for _frame, path in outputs)
