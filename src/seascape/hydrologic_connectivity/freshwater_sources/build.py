"""Build river systems, marine mouths, widths, distance, and mapped-mouth pressure."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point, box

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.geometry import safe_polygonal_union
from seascape.spatial_support.water_network import (
    load_model_area_support,
)
from seascape.utils.artifacts import (
    build_manifest,
    stage_parquet_family,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.spatial import (
    align_to_model_support,
    project_h3_centers,
)
from seascape.utils.values import clean_optional_text

from .download import DEFAULT_CONFIG_PATH, load_freshwater_download_config
from .h3_publication import river_mouth_pressure as _river_mouth_pressure
from .mouth_morphometry import apply_mouth_widths as _apply_mouth_widths
from .river_system_aggregation import build_river_systems as _build_river_systems
from .source_classification import bc_stream_mask as _bc_stream_mask
from .source_classification import nhd_flowline_mask as _nhd_flowline_mask
from .source_classification import source_classification as _source_classification
from .source_geometry import line_parts as _line_parts

LOGGER = logging.getLogger(__name__)

H3_BASE_OUTPUT_COLUMNS = [
    "H3_INDEX",
    "DISTANCE_TO_RIVER_MOUTH_M",
    "NEAREST_RIVER_MOUTH_ID",
    "NEAREST_RIVER_MOUTH_WIDTH_M",
]


@dataclass(frozen=True)
class RiverMouthBuildConfig:
    """Resolved inputs, width settings, and durable output paths."""

    bbox: dict[str, float]
    context_bbox: dict[str, float]
    h3_resolution: int
    projected_crs: str
    water_polygon_path: Path
    raw_paths: Mapping[str, Path]
    hydrorivers_extract_dir: Path
    processed_dir: Path
    river_mouths_path: Path
    river_systems_path: Path
    feature_path: Path
    mouth_coast_tolerance_m: float
    hydrorivers_match_distance_m: float
    mouth_width_sample_distances_m: tuple[float, ...]
    mouth_width_cross_section_length_m: float
    mouth_width_polygon_match_distance_m: float
    default_stream_mouth_width_m: float
    river_mouth_pressure_decay_km: int


def load_river_mouth_build_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> RiverMouthBuildConfig:
    """Load and validate the narrowed river-mouth build contract."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get("freshwater_sources"), "freshwater_sources")
    processing = _mapping(section.get("processing"), "freshwater_sources.processing")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    download = load_freshwater_download_config(path)
    processed_dir = _resolve(processing["processed_directory"], base_dir)
    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("freshwater_sources.processing.h3_resolution must be 8.")

    positive = {
        "mouth_coast_tolerance_m": float(processing.get("mouth_coast_tolerance_m", 1_500)),
        "hydrorivers_match_distance_m": float(
            processing.get("hydrorivers_match_distance_m", 5_000)
        ),
        "mouth_width_cross_section_length_m": float(
            processing.get("mouth_width_cross_section_length_m", 5_000)
        ),
        "mouth_width_polygon_match_distance_m": float(
            processing.get("mouth_width_polygon_match_distance_m", 300)
        ),
        "default_stream_mouth_width_m": float(processing.get("default_stream_mouth_width_m", 2)),
        "river_mouth_pressure_decay_km": float(processing.get("river_mouth_pressure_decay_km", 5)),
    }
    if any(value <= 0 for value in positive.values()):
        raise ValueError("River-mouth distance and width settings must be positive.")
    sample_distances = tuple(
        sorted({float(value) for value in processing.get("mouth_width_sample_distances_m", ())})
    )
    if not sample_distances or any(value <= 0 for value in sample_distances):
        raise ValueError("mouth_width_sample_distances_m must contain positive distances.")
    pressure_decay_km = positive["river_mouth_pressure_decay_km"]
    if not pressure_decay_km.is_integer():
        raise ValueError("river_mouth_pressure_decay_km must be a positive whole kilometer.")

    raw_paths = {source.name: source.raw_path for source in download.arcgis_sources}
    return RiverMouthBuildConfig(
        bbox=download.bbox,
        context_bbox=download.context_bbox,
        h3_resolution=resolution,
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        water_polygon_path=_resolve(processing["water_polygon_path"], base_dir),
        raw_paths=raw_paths,
        hydrorivers_extract_dir=download.hydrorivers_extract_dir,
        processed_dir=processed_dir,
        river_mouths_path=processed_dir / str(processing["river_mouths_filename"]),
        river_systems_path=processed_dir / str(processing["river_systems_filename"]),
        feature_path=processed_dir / str(processing["feature_filename"]),
        mouth_coast_tolerance_m=positive["mouth_coast_tolerance_m"],
        hydrorivers_match_distance_m=positive["hydrorivers_match_distance_m"],
        mouth_width_sample_distances_m=sample_distances,
        mouth_width_cross_section_length_m=positive["mouth_width_cross_section_length_m"],
        mouth_width_polygon_match_distance_m=positive["mouth_width_polygon_match_distance_m"],
        default_stream_mouth_width_m=positive["default_stream_mouth_width_m"],
        river_mouth_pressure_decay_km=int(pressure_decay_km),
    )


def pressure_columns(config: RiverMouthBuildConfig) -> tuple[str, str]:
    """Return pressure column names carrying their configured e-folding scale."""

    suffix = f"{config.river_mouth_pressure_decay_km}KM"
    return (
        f"MAPPED_RIVER_MOUTH_PRESSURE_{suffix}",
        f"MAPPED_WIDTH_WEIGHTED_RIVER_MOUTH_PRESSURE_{suffix}",
    )


def output_columns(config: RiverMouthBuildConfig) -> list[str]:
    """Return the deterministic H3 product schema."""

    return [*H3_BASE_OUTPUT_COLUMNS, *pressure_columns(config)]


def _read_vector(path: Path, *, bbox_value: Mapping[str, float] | None = None):
    import geopandas as gpd

    if not path.exists():
        raise FileNotFoundError(f"River source not found: {path}. Run download.py first.")
    read_bbox = None
    if bbox_value is not None:
        read_bbox = tuple(bbox_value[key] for key in ("min_lon", "min_lat", "max_lon", "max_lat"))
    frame = gpd.read_file(path, bbox=read_bbox)
    if frame.crs is None:
        raise ValueError(f"River source has no CRS: {path}")
    frame = frame.to_crs("EPSG:4326")
    frame.columns = [
        str(column).upper() if column != frame.geometry.name else column for column in frame
    ]
    if frame.geometry.name != "geometry":
        frame = frame.rename_geometry("geometry")
    return frame


def _hydrorivers_path(config: RiverMouthBuildConfig) -> Path:
    paths = sorted(config.hydrorivers_extract_dir.rglob("*.shp"))
    if len(paths) != 1:
        raise FileNotFoundError(
            "Expected exactly one HydroRIVERS Shapefile beneath "
            f"{config.hydrorivers_extract_dir}; found {len(paths)}."
        )
    return paths[0]


def _clip_context(frame: Any, bbox_value: Mapping[str, float]):
    import geopandas as gpd

    context = box(
        bbox_value["min_lon"],
        bbox_value["min_lat"],
        bbox_value["max_lon"],
        bbox_value["max_lat"],
    )
    valid = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if valid.empty:
        return valid
    return gpd.clip(valid, context, keep_geom_type=True).reset_index(drop=True)


def _load_water(config: RiverMouthBuildConfig):
    import geopandas as gpd

    if not config.water_polygon_path.exists():
        raise FileNotFoundError(
            f"Canonical marine-water geometry not found: {config.water_polygon_path}"
        )
    water = gpd.read_parquet(config.water_polygon_path)
    if water.crs is None:
        raise ValueError(f"Canonical marine-water geometry has no CRS: {config.water_polygon_path}")
    model_box = box(
        config.bbox["min_lon"],
        config.bbox["min_lat"],
        config.bbox["max_lon"],
        config.bbox["max_lat"],
    )
    target = safe_polygonal_union(water.to_crs("EPSG:4326"), clip_geometry=model_box)
    if target.is_empty:
        raise ValueError("Canonical marine-water geometry is empty in the model area.")
    projected = gpd.GeoSeries([target], crs="EPSG:4326").to_crs(config.projected_crs).iloc[0]
    return target, projected


_text = clean_optional_text


def _bc_terminal_segments(frame: Any):
    candidate = _line_parts(frame)
    candidate = candidate.loc[_bc_stream_mask(candidate)].copy()
    if candidate.empty:
        return candidate
    route = candidate.get("BLUE_LINE_KEY", candidate.get("OBJECTID")).astype("string")
    fallback = pd.Series(candidate.index.astype(str), index=candidate.index, dtype="string")
    candidate["_ROUTE"] = route.fillna(fallback)
    measure = pd.to_numeric(candidate.get("DOWNSTREAM_ROUTE_MEASURE"), errors="coerce")
    candidate["_MEASURE"] = measure.fillna(np.inf)
    return (
        candidate.sort_values(["_ROUTE", "_MEASURE"])
        .drop_duplicates("_ROUTE", keep="first")
        .drop(columns=["_ROUTE", "_MEASURE"])
        .reset_index(drop=True)
    )


def _outlet_points(lines: Any, projected_water: Any, config: RiverMouthBuildConfig):
    """Retain terminal line orientation while selecting its marine-nearest endpoint."""

    import geopandas as gpd

    projected = _line_parts(lines).to_crs(config.projected_crs)
    if projected.empty:
        return projected
    projected["_TERMINAL_LINE"] = projected.geometry.copy()
    starts = gpd.GeoSeries(
        [Point(geometry.coords[0]) for geometry in projected.geometry],
        index=projected.index,
        crs=config.projected_crs,
    )
    ends = gpd.GeoSeries(
        [Point(geometry.coords[-1]) for geometry in projected.geometry],
        index=projected.index,
        crs=config.projected_crs,
    )
    start_distance = starts.distance(projected_water).to_numpy(dtype="float64")
    end_distance = ends.distance(projected_water).to_numpy(dtype="float64")
    mouth_at_end = end_distance <= start_distance
    projected["_MOUTH_AT_END"] = mouth_at_end
    projected["COAST_DISTANCE_M"] = np.where(mouth_at_end, end_distance, start_distance)
    projected.geometry = gpd.GeoSeries(
        [ends.iloc[i] if mouth_at_end[i] else starts.iloc[i] for i in range(len(projected))],
        index=projected.index,
        crs=config.projected_crs,
    )
    return projected.loc[
        projected["COAST_DISTANCE_M"] <= config.mouth_coast_tolerance_m
    ].reset_index(drop=True)


def _mouth_frame(
    lines: Any,
    *,
    dataset: str,
    id_column: str,
    name_column: str | None,
    width_key_column: str | None,
    projected_water: Any,
    config: RiverMouthBuildConfig,
):
    import geopandas as gpd

    candidates = _outlet_points(lines, projected_water, config)
    records = []
    for position, row in enumerate(candidates.to_dict("records")):
        identifier = _text(row.get(id_column)) or str(position)
        classification = _source_classification(dataset, row)
        records.append(
            {
                "RIVER_MOUTH_ID": f"{dataset}_{identifier}",
                "SOURCE_DATASET": dataset,
                "RIVER_NAME": _text(row.get(name_column)) if name_column else None,
                "MOUTH_WIDTH_M": config.default_stream_mouth_width_m,
                "MOUTH_WIDTH_SOURCE_DATASET": "CONFIGURED_DEFAULT",
                "MOUTH_WIDTH_METHOD": "configured_default_line_only_width",
                "COAST_DISTANCE_M": float(row["COAST_DISTANCE_M"]),
                **classification,
                "_WIDTH_KEY": _text(row.get(width_key_column)) if width_key_column else None,
                "_TERMINAL_LINE": row["_TERMINAL_LINE"],
                "_MOUTH_AT_END": bool(row["_MOUTH_AT_END"]),
                "geometry": row["geometry"],
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=config.projected_crs)


def _deduplicate_hydrorivers(mouths: Any, config: RiverMouthBuildConfig):
    hydro_mask = mouths["SOURCE_DATASET"].eq("HYDRORIVERS_V10")
    hydro = mouths.loc[hydro_mask]
    local = mouths.loc[~hydro_mask]
    if hydro.empty or local.empty:
        return mouths
    local_xy = np.column_stack((local.geometry.x, local.geometry.y))
    hydro_xy = np.column_stack((hydro.geometry.x, hydro.geometry.y))
    distance, _ = cKDTree(local_xy).query(hydro_xy)
    drop_indices = hydro.index[distance <= config.hydrorivers_match_distance_m]
    return mouths.drop(index=drop_indices).reset_index(drop=True)


def _build_mouths(
    frames: Mapping[str, Any],
    projected_water: Any,
    config: RiverMouthBuildConfig,
):
    import geopandas as gpd

    bc = _mouth_frame(
        _bc_terminal_segments(frames["bc_stream_network"]),
        dataset="BC_FWA_STREAM_NETWORK",
        id_column="BLUE_LINE_KEY",
        name_column="GNIS_NAME",
        width_key_column="BLUE_LINE_KEY",
        projected_water=projected_water,
        config=config,
    )
    us_flowlines = frames["us_network_flowlines"]
    terminal = pd.to_numeric(us_flowlines.get("TERMINALFL"), errors="coerce").eq(1)
    us = _mouth_frame(
        us_flowlines.loc[_nhd_flowline_mask(us_flowlines) & terminal],
        dataset="US_NHD_SMALL_SCALE",
        id_column="COMID",
        name_column="GNIS_NAME",
        width_key_column=None,
        projected_water=projected_water,
        config=config,
    )
    hydrorivers = frames["hydrorivers"]
    hydro_terminal = pd.to_numeric(hydrorivers.get("NEXT_DOWN"), errors="coerce").eq(0)
    hydro_exorheic = pd.to_numeric(hydrorivers.get("ENDORHEIC"), errors="coerce").fillna(0).eq(0)
    hydro = _mouth_frame(
        hydrorivers.loc[hydro_terminal & hydro_exorheic],
        dataset="HYDRORIVERS_V10",
        id_column="HYRIV_ID",
        name_column=None,
        width_key_column=None,
        projected_water=projected_water,
        config=config,
    )
    mouths = gpd.GeoDataFrame(
        pd.concat([bc, us, hydro], ignore_index=True),
        geometry="geometry",
        crs=config.projected_crs,
    )
    if mouths.empty:
        raise ValueError("No river mouths were found next to the canonical marine water.")
    mouths = _deduplicate_hydrorivers(mouths, config)
    mouths = _apply_mouth_widths(
        mouths,
        frames["bc_river_polygons"],
        frames["us_river_polygons"],
        config,
    )
    return mouths.sort_values(["SOURCE_DATASET", "RIVER_MOUTH_ID"]).reset_index(drop=True)


def _build_h3_features(
    target_water: Any,
    mouths: Any,
    config: RiverMouthBuildConfig,
    support: pd.DataFrame,
) -> pd.DataFrame:
    import h3

    cells = support["H3_INDEX"].astype(str).sort_values().tolist()
    if not cells:
        raise ValueError("No H3 cells overlap canonical marine water in the model area.")
    if any(h3.get_resolution(cell) != config.h3_resolution for cell in cells):
        raise ValueError("River-mouth target support contains an unexpected H3 resolution.")
    _, _, target_x, target_y = project_h3_centers(cells, config.projected_crs)
    target_xy = np.column_stack((target_x, target_y))
    projected_mouths = mouths.to_crs(config.projected_crs).reset_index(drop=True)
    mouth_xy = np.column_stack((projected_mouths.geometry.x, projected_mouths.geometry.y))
    distance, nearest_position = cKDTree(mouth_xy).query(target_xy)
    nearest = projected_mouths.iloc[nearest_position].reset_index(drop=True)
    pressure_column, weighted_pressure_column = pressure_columns(config)
    unweighted_pressure, width_weighted_pressure = _river_mouth_pressure(
        target_xy,
        mouth_xy,
        pd.to_numeric(projected_mouths["MOUTH_WIDTH_M"], errors="coerce").to_numpy(),
        decay_distance_m=config.river_mouth_pressure_decay_km * 1_000.0,
        width_reference_m=config.default_stream_mouth_width_m,
    )
    features = pd.DataFrame(
        {
            "H3_INDEX": cells,
            "DISTANCE_TO_RIVER_MOUTH_M": distance,
            "NEAREST_RIVER_MOUTH_ID": nearest["RIVER_MOUTH_ID"].astype("string"),
            "NEAREST_RIVER_MOUTH_WIDTH_M": pd.to_numeric(nearest["MOUTH_WIDTH_M"], errors="coerce"),
            pressure_column: unweighted_pressure,
            weighted_pressure_column: width_weighted_pressure,
        }
    ).loc[:, output_columns(config)]
    if not features["H3_INDEX"].is_unique:
        raise ValueError("River-mouth H3 product contains duplicate H3_INDEX values.")
    if not np.isfinite(features["DISTANCE_TO_RIVER_MOUTH_M"]).all():
        raise ValueError("Nearest river-mouth distance contains non-finite values.")
    pressure_values = features[[pressure_column, weighted_pressure_column]].to_numpy(
        dtype="float64"
    )
    if not np.isfinite(pressure_values).all() or np.any(pressure_values < 0):
        raise ValueError("Mapped river-mouth pressure must be finite and nonnegative.")
    if np.any(width_weighted_pressure + 1e-12 < unweighted_pressure):
        raise ValueError("Width-weighted pressure cannot be lower than unweighted pressure.")
    return (
        align_to_model_support(
            support,
            features,
            feature_label="river-mouth H3 features",
        )
        .sort_values("H3_INDEX")
        .reset_index(drop=True)
    )


def _load_source_frames(config: RiverMouthBuildConfig):
    frames = {
        name: _clip_context(_read_vector(path), config.context_bbox)
        for name, path in config.raw_paths.items()
    }
    frames["hydrorivers"] = _clip_context(
        _read_vector(_hydrorivers_path(config), bbox_value=config.context_bbox),
        config.context_bbox,
    )
    required = (
        "bc_stream_network",
        "bc_river_polygons",
        "us_network_flowlines",
        "hydrorivers",
    )
    empty = [name for name in required if frames[name].empty]
    if empty:
        raise ValueError(f"Required river source extracts are empty: {empty}")
    return frames


def _numeric_summary(values: pd.Series) -> dict[str, float]:
    """Return compact deterministic distribution diagnostics for a manifest."""

    numeric = pd.to_numeric(values, errors="raise").to_numpy(dtype="float64")
    quantiles = np.quantile(numeric, [0.0, 0.1, 0.5, 0.9, 0.99, 1.0])
    return {
        label: float(value)
        for label, value in zip(
            ("minimum", "p10", "median", "p90", "p99", "maximum"),
            quantiles,
            strict=True,
        )
    }


def build_river_mouths(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path]:
    """Build river mouths, systems, and H3 distance/pressure features."""

    config = load_river_mouth_build_config(config_path)
    target_water, projected_water = _load_water(config)
    frames = _load_source_frames(config)
    mouths = _build_mouths(frames, projected_water, config)
    systems = _build_river_systems(frames)
    support = load_model_area_support(config.h3_resolution, config_path)
    features = _build_h3_features(target_water, mouths, config, support)

    private_columns = [column for column in mouths.columns if column.startswith("_")]
    mouths = mouths.drop(columns=private_columns).to_crs("EPSG:4326")
    publisher = stage_parquet_family(
        config.processed_dir,
        (
            (mouths, config.river_mouths_path),
            (systems, config.river_systems_path),
            (features, config.feature_path),
        ),
    )

    measured_width_mask = mouths["MOUTH_WIDTH_SOURCE_DATASET"].ne("CONFIGURED_DEFAULT")
    measured_width_count = int(measured_width_mask.sum())
    default_width_count = int((~measured_width_mask).sum())
    pressure_column, weighted_pressure_column = pressure_columns(config)
    detailed_metadata = {
        "h3_resolution": config.h3_resolution,
        "h3_cell_count": len(features),
        "river_mouth_count": len(mouths),
        "river_segment_count": len(systems),
        "mapped_mouth_width_count": measured_width_count,
        "default_mouth_width_count": default_width_count,
        "mapped_mouth_width_coverage_fraction": measured_width_count / len(mouths),
        "default_stream_mouth_width_m": config.default_stream_mouth_width_m,
        "mapped_entrypoint_pressure": {
            "interpretation": "effective nearby mapped river mouths",
            "mouth_inventory": "current mixed-source mapped mouth inventory",
            "decay_distance_km": config.river_mouth_pressure_decay_km,
            "unweighted_formula": "sum(exp(-distance_m / decay_distance_m))",
            "width_weighted_formula": (
                "sum(sqrt(mouth_width_m / default_stream_mouth_width_m) "
                "* exp(-distance_m / decay_distance_m))"
            ),
            "width_transform": "square_root",
            "width_reference_m": config.default_stream_mouth_width_m,
            "width_weighted_is_experimental": True,
            "coverage_warning": (
                "Mapped-mouth pressure is not physical discharge, plume extent, or complete "
                "river density; B.C. and U.S. mouth sources have different spatial resolution."
            ),
            "summaries": {
                pressure_column: _numeric_summary(features[pressure_column]),
                weighted_pressure_column: _numeric_summary(features[weighted_pressure_column]),
            },
        },
        "source_counts": {
            str(key): int(value)
            for key, value in mouths["SOURCE_DATASET"].value_counts().sort_index().items()
        },
        "h3_columns": output_columns(config),
    }
    manifest_path = config.processed_dir / "river_mouths_manifest.json"
    source_paths = {**config.raw_paths, "hydrorivers": _hydrorivers_path(config)}
    source_attribution = {
        "bc_stream_network": (
            "British Columbia Freshwater Atlas",
            "Open Government Licence - British Columbia",
        ),
        "bc_river_polygons": (
            "British Columbia Freshwater Atlas",
            "Open Government Licence - British Columbia",
        ),
        "us_network_flowlines": (
            "United States Geological Survey National Hydrography Dataset",
            "United States Government work",
        ),
        "us_river_polygons": (
            "United States Geological Survey NHDPlus HR",
            "United States Government work",
        ),
        "hydrorivers": ("HydroRIVERS v1.0", "HydroSHEDS licence terms"),
    }
    manifest = build_manifest(
        dataset_family="environment.seascape.freshwater_sources",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": name,
                "path": str(path),
                "checksum": checksum_path(path),
                "attribution": source_attribution[name][0],
                "license": source_attribution[name][1],
            }
            for name, path in source_paths.items()
        ],
        upstream_artifacts=[
            {
                "path": str(config.water_polygon_path),
                "checksum": checksum_path(config.water_polygon_path),
            }
        ],
        attribution=[
            {"text": attribution, "license": license_name}
            for attribution, license_name in source_attribution.values()
        ],
        source_completeness="complete",
        metadata=detailed_metadata,
    )
    publisher.publish_manifest(manifest_path, manifest)
    LOGGER.info(
        "Saved %d river mouths (%d mapped widths), %d river segments, and %d H3 cells in %s",
        len(mouths),
        measured_width_count,
        len(systems),
        len(features),
        config.processed_dir,
    )
    return config.river_mouths_path, config.river_systems_path, config.feature_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for path in build_river_mouths(args.config):
        print(path)
    return 0


__all__ = [
    "RiverMouthBuildConfig",
    "build_river_mouths",
    "load_river_mouth_build_config",
    "output_columns",
    "pressure_columns",
]


if __name__ == "__main__":
    raise SystemExit(main())
