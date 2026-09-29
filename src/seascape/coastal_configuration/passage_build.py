"""Optional reviewed-passage geometry candidate with bounded cross sections."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from shapely import wkt
from shapely.ops import transform, unary_union

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent
from seascape.seafloor_physiography.bathymetry.pipeline import load_bathymetry_config
from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)

from .passage_sections import measure_passage_section, sill_candidates


@dataclass(frozen=True)
class PassageConfig:
    registry_path: Path
    mapped_sills_path: Path | None
    water_path: Path
    clipped_r8_path: Path
    depth_raster_path: Path
    output_dir: Path
    projected_crs: str
    section_spacing_m: float
    half_length_m: float
    sample_step_m: float
    threshold_m: float
    tangent_scale_m: float
    minimum_sill_relief_m: float
    max_passages: int
    max_sections: int
    max_cells: int
    max_sills: int


def load_passage_config(config_path: str | Path) -> PassageConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("passage_sections")
    if not isinstance(section, dict) or not section.get("registry_path"):
        raise ValueError("Set passage_sections.registry_path to a reviewed passage GeoParquet")
    network = load_water_network_config(config_path)
    bathymetry = load_bathymetry_config(config_path)
    root = project_root()
    output = root / str(section.get("output_dir", "data/processed/domain/environmental_layer/seascape/coastal_configuration/passage_sections"))
    registry = root / str(section["registry_path"])
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Passage output escapes workspace")
    scales = {key: float(section[key]) for key in (
        "section_spacing_m", "half_length_m", "sample_step_m", "threshold_m",
        "tangent_scale_m", "minimum_sill_relief_m",
    )}
    if scales["threshold_m"] < 0 or any(value <= 0 for key, value in scales.items() if key != "threshold_m"):
        raise ValueError("Passage scales must be positive and threshold nonnegative")
    bounds = {key: int(section.get(key, default)) for key, default in (
        ("max_passages", 2), ("max_sections", 100), ("max_cells", 200),
        ("max_sills", 100),
    )}
    if min(bounds.values()) < 1:
        raise ValueError("Passage resource bounds must be positive")
    return PassageConfig(
        registry,
        root / str(section["mapped_sills_path"]) if section.get("mapped_sills_path") else None,
        network.water_polygon_path, network.clipped_geometry_path(8),
        bathymetry.raw_path, output, str(section.get("projected_crs", "EPSG:32610")),
        **scales, **bounds,
    )


def normalize_mapped_sills(
    mapped: gpd.GeoDataFrame, passages: gpd.GeoDataFrame, *, max_sills: int
) -> gpd.GeoDataFrame:
    """Validate separately sourced crests; mapped is distinct from validated."""

    required = {
        "SILL_ID", "PASSAGE_ID", "MAPPED_SILL_CREST_DEPTH_M", "SOURCE_ID",
        "SOURCE_VERSION", "RIGHTS", "VERTICAL_DATUM", "VALIDATION_STATUS",
    }
    if required - set(mapped) or mapped.crs is None:
        raise ValueError(f"Mapped sill registry needs CRS and fields {sorted(required - set(mapped))}")
    if len(mapped) > max_sills or mapped.SILL_ID.isna().any() or mapped.SILL_ID.duplicated().any():
        raise ValueError("Mapped sill IDs must be unique, nonnull and within the configured bound")
    text_fields = list(required - {"MAPPED_SILL_CREST_DEPTH_M"})
    if mapped[text_fields].isna().any().any() or mapped[text_fields].astype(str).apply(
        lambda column: column.str.strip().eq("").any()
    ).any():
        raise ValueError("Mapped sill identity, rights, datum and validation status are required")
    depth = pd.to_numeric(mapped.MAPPED_SILL_CREST_DEPTH_M, errors="coerce")
    if depth.isna().any() or not np.isfinite(depth).all() or depth.lt(0).any():
        raise ValueError("Mapped sill crest depth must be finite and positive down")
    if not set(mapped.VALIDATION_STATUS.astype(str)) <= {"mapped", "validated"}:
        raise ValueError("Sill validation status must be mapped or validated")
    if set(mapped.PASSAGE_ID.astype(str)) - set(passages.PASSAGE_ID.astype(str)):
        raise ValueError("Mapped sill references unknown passage")
    projected = mapped.to_crs(passages.crs).copy()
    projected["PASSAGE_ID"] = projected.PASSAGE_ID.astype(str)
    projected["SILL_ID"] = projected.SILL_ID.astype(str)
    passage_geometry = passages.set_index("PASSAGE_ID").geometry
    passage_datums = passages.set_index("PASSAGE_ID").VERTICAL_DATUM.astype(str)
    for sill in projected.itertuples(index=False):
        if sill.geometry.is_empty or not sill.geometry.is_valid or not passage_geometry.loc[sill.PASSAGE_ID].covers(sill.geometry):
            raise ValueError("Mapped sill geometry must be valid and within its reviewed passage")
        if str(sill.VERTICAL_DATUM) != passage_datums.loc[sill.PASSAGE_ID]:
            raise ValueError("Mapped sill and passage vertical datums disagree")
    projected["CONFIRMED_SILL_CREST_DEPTH_M"] = depth.where(
        projected.VALIDATION_STATUS.eq("validated")
    ).to_numpy()
    return projected.sort_values("SILL_ID").reset_index(drop=True)


def build_passage_sections(config_path: str | Path) -> tuple[Path, ...]:
    config = load_passage_config(config_path)
    passages = gpd.read_parquet(config.registry_path)
    required = {"PASSAGE_ID", "CENTERLINE_WKT", "SOURCE_ID", "SOURCE_VERSION", "RIGHTS", "VERTICAL_DATUM"}
    if required - set(passages) or passages.crs is None:
        raise ValueError(f"Passage registry needs CRS and fields {sorted(required - set(passages))}")
    if passages.PASSAGE_ID.isna().any() or passages.PASSAGE_ID.duplicated().any() or len(passages) > config.max_passages:
        raise ValueError("Passage IDs must be unique and within configured bound")
    for field in required - {"CENTERLINE_WKT"}:
        if passages[field].isna().any() or passages[field].astype(str).str.len().eq(0).any():
            raise ValueError(f"Passage registry {field} is required")
    source_crs = passages.crs
    passages = passages.to_crs(config.projected_crs).sort_values("PASSAGE_ID").reset_index(drop=True)
    passages["PASSAGE_ID"] = passages.PASSAGE_ID.astype(str)
    to_metric = Transformer.from_crs(source_crs, config.projected_crs, always_xy=True).transform
    centers = [transform(to_metric, wkt.loads(value)) for value in passages.CENTERLINE_WKT]
    if any(center.geom_type != "LineString" or not passage.geometry.covers(center) for center, passage in zip(centers, passages.itertuples(), strict=True)):
        raise ValueError("Passage centerline must be an ordered line inside its bounded polygon")
    water = gpd.read_parquet(config.water_path).to_crs(config.projected_crs).geometry.union_all()
    cells = gpd.read_parquet(config.clipped_r8_path).to_crs(config.projected_crs)
    interest = unary_union(list(passages.geometry)).buffer(config.half_length_m)
    cells = cells.loc[cells.geometry.intersects(interest)].sort_values("H3_INDEX")
    if cells.empty or len(cells) > config.max_cells:
        raise ValueError("Passage H3 association cell bound exceeded or no cells intersect")
    section_rows = []
    associations = []
    with rasterio.open(config.depth_raster_path) as source:
        with WarpedVRT(source, crs=config.projected_crs, resampling=Resampling.nearest) as depth:
            effective_resolution = max(abs(depth.transform.a), abs(depth.transform.e))

            def depth_at(x: float, y: float) -> float | None:
                value = next(depth.sample([(x, y)], masked=True))[0]
                if np.ma.is_masked(value) or pd.isna(value) or (depth.nodata is not None and value == depth.nodata):
                    return None
                return -float(value) if float(value) < 0 else None

            for passage, center in zip(passages.itertuples(index=False), centers, strict=True):
                count = max(1, math.ceil(center.length / config.section_spacing_m))
                if len(section_rows) + count > config.max_sections:
                    raise ValueError("Passage section budget exceeded")
                for index in range(count):
                    position = min(center.length, (index + 0.5) * config.section_spacing_m)
                    measured = measure_passage_section(
                        str(passage.PASSAGE_ID), passage.geometry, center, water, depth_at,
                        along_axis_m=position, half_length_m=config.half_length_m,
                        sample_step_m=config.sample_step_m, depth_threshold_m=config.threshold_m,
                        tangent_scale_m=config.tangent_scale_m,
                    )
                    section_rows.append({
                        "SECTION_ID": f"{passage.PASSAGE_ID}:{position:.3f}m",
                        "PASSAGE_ID": str(passage.PASSAGE_ID),
                        "ALONG_AXIS_M": position,
                        "WET_WIDTH_M": measured.wet_width_m,
                        "CROSS_SECTION_AREA_M2": measured.cross_section_area_m2,
                        "VALID_INTEGRAL_AREA_M2": measured.valid_integral_area_m2,
                        "MAX_DEPTH_M": measured.max_depth_m,
                        "WIDTH_AT_DEPTH_THRESHOLD_M": measured.width_at_depth_threshold_m,
                        "MAX_CONTIGUOUS_WIDTH_AT_DEPTH_THRESHOLD_M": measured.max_contiguous_width_at_depth_threshold_m,
                        "DEPTH_THRESHOLD_M": config.threshold_m,
                        "BANK_STATUS": measured.bank_status,
                        "BATHYMETRY_STATUS": measured.bathymetry_status if config.sample_step_m >= effective_resolution else "unresolved_resolution",
                        "EFFECTIVE_RASTER_RESOLUTION_M": effective_resolution,
                        "WET_INTERVAL_COUNT": measured.wet_intervals,
                        "VERTICAL_DATUM": passage.VERTICAL_DATUM,
                        "geometry": measured.section,
                    })
            supports = {8: cells}
            parent_rows = [
                {"H3_INDEX": parent, "geometry": unary_union(list(rows.geometry))}
                for parent, rows in cells.assign(PARENT=cells.H3_INDEX.map(lambda value: cell_to_parent(str(value), 6))).groupby("PARENT")
            ]
            supports[6] = gpd.GeoDataFrame(parent_rows, geometry="geometry", crs=cells.crs)
            for resolution, frame in supports.items():
                for cell in frame.itertuples(index=False):
                    for passage in passages.itertuples(index=False):
                        overlap = cell.geometry.intersection(passage.geometry).intersection(water).area
                        if overlap <= 0:
                            continue
                        associations.append({
                            "H3_INDEX": str(cell.H3_INDEX), "H3_RESOLUTION": resolution,
                            "PASSAGE_ID": str(passage.PASSAGE_ID),
                            "PASSAGE_OVERLAP_AREA_M2": overlap,
                            "PASSAGE_FRAC_OF_WATER_SUPPORT": overlap / cell.geometry.area,
                            "SPATIAL_SUPPORT": "water_clipped_r8" if resolution == 8 else "hierarchical_r8_child_union",
                        })
    sections = gpd.GeoDataFrame(section_rows, geometry="geometry", crs=config.projected_crs)
    candidate_input = pd.DataFrame(sections.drop(columns="geometry"))
    candidates = sill_candidates(candidate_input, min_relief_m=config.minimum_sill_relief_m)
    if candidates.empty:
        candidates = pd.DataFrame(columns=[
            "SILL_CANDIDATE_ID", "PASSAGE_ID", "ALONG_AXIS_M", "SILL_CANDIDATE_DEPTH_M",
            "RELIEF_LEFT_M", "RELIEF_RIGHT_M", "SUPPORTING_SECTION_POSITIONS_M", "METHOD", "QC",
        ])
    association_frame = pd.DataFrame(associations)
    if association_frame.empty:
        raise ValueError("No reviewed passage overlaps selected canonical water support")
    if association_frame.duplicated(["H3_INDEX", "H3_RESOLUTION", "PASSAGE_ID"]).any():
        raise ValueError("Duplicate H3-to-passage association")
    outputs = [
        (passages, config.output_dir / "PASSAGE_INVENTORY.parquet"),
        (sections, config.output_dir / "PASSAGE_CROSS_SECTIONS.parquet"),
        (candidates, config.output_dir / "SILL_CANDIDATES.parquet"),
        *(
            (association_frame.loc[association_frame.H3_RESOLUTION.eq(res)].reset_index(drop=True), config.output_dir / f"H3_PASSAGE_ASSOCIATIONS_RES_{res}.parquet")
            for res in (8, 6)
        ),
    ]
    if config.mapped_sills_path is not None:
        mapped_sills = normalize_mapped_sills(
            gpd.read_parquet(config.mapped_sills_path), passages, max_sills=config.max_sills
        )
        outputs.append((mapped_sills, config.output_dir / "MAPPED_SILLS.parquet"))
    publisher = stage_parquet_family(config.output_dir, outputs)
    manifest = build_manifest(
        dataset_family="environment.seascape.passage_sections", run_id=publisher.run_id,
        resolved_config=asdict(config), artifacts=publisher.artifacts, project_root=project_root(),
        sources=[
            {"name": path.name, "path": str(path), "checksum": checksum_artifact(path), "license": "Per-registry RIGHTS field"}
            for path in (config.registry_path, config.mapped_sills_path) if path is not None
        ],
        upstream_artifacts=[{"path": str(path), "checksum": checksum_artifact(path)} for path in (config.water_path, config.clipped_r8_path, config.depth_raster_path)],
        attribution=[], source_completeness="partial",
        metadata={"scientific_method_version": "passage_cross_section_shoal_candidate_v1", "sample_support": "source passage polygon and ordered centerline; virtual projected native raster; bounded R8 child-union R6 associations"},
    )
    publisher.publish_manifest(config.output_dir / "passage_sections_manifest.json", manifest)
    return tuple(path for _frame, path in outputs)
