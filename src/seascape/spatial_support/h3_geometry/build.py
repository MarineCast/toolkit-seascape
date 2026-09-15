"""Build resolution-specific H3 geometry and identity layers over water."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, List, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from seascape.core.artifacts import ArtifactRef
from seascape.core.config.common_areas import bbox_from_config
from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.distance import haversine_distance_m
from seascape.core.geo.geometry import (
    buffer_meters,
    clip_to_bbox,
    ensure_epsg4326,
    normalize_polygonal_geometry,
    safe_make_valid,
)
from seascape.core.geo.h3 import (
    cell_to_boundary,
    cell_to_latlng,
    latlng_to_cell,
    polygon_to_cells_overlap,
)
from seascape.core.geo.h3 import polygonize_h3_indices as core_polygonize_h3_indices
from seascape.publication import (
    TransactionalSeascapePublisher,
)
from seascape.utils.artifacts import (
    build_manifest,
    capture_staged_parquet_artifact,
    stage_parquet_artifact,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import (
    resolve_project_path as _resolve_project_path,
)

DEFAULT_PROCESSED_OUT_DIR = (
    "data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry"
)
DEFAULT_H3_OUTPUT_DIR = (
    "data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry"
)
DEFAULT_WATER_POLYGON_FILENAME = "TERRITORIAL_WATER_POLYGON.parquet"
DEFAULT_H3_GRID_FILENAME_TEMPLATE = "H3_GRIDS_{res}.parquet"
DEFAULT_H3_CLIPPED_GRID_FILENAME_TEMPLATE = "H3_GRIDS_CLIPPED_{res}.parquet"

# =========================
# Config I/O
# =========================

LOGGER = logging.getLogger(__name__)


def _resolutions(value: Any) -> tuple[int, ...]:
    values = (value,) if isinstance(value, int) else tuple(value)
    resolutions = tuple(dict.fromkeys(int(item) for item in values))
    if not resolutions:
        raise ValueError("h3_geometry.resolutions must contain at least one resolution.")
    invalid = [item for item in resolutions if not 0 <= item <= 15]
    if invalid:
        raise ValueError(f"Invalid H3 resolutions: {invalid}")
    return resolutions


def load_h3_geometry_config(config_path: str | Path) -> dict[str, Any]:
    """Load the water dependency and resolution-specific H3 output settings."""

    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    water_geometry = _mapping(raw.get("water_geometry", {}), "water_geometry")
    h3_config = _mapping(raw.get("h3_geometry", {}), "h3_geometry")
    water_build = _mapping(
        water_geometry.get("build", {}),
        "water_geometry.build",
    )
    base_dir = (project_root() / Path(raw.get("base_directory", ".")).expanduser()).resolve()
    water_dir = _resolve_project_path(
        water_geometry.get(
            "processed_out_dir",
            DEFAULT_PROCESSED_OUT_DIR,
        ),
        base_dir,
    )
    output_dir = _resolve_project_path(
        h3_config.get("output_dir", DEFAULT_H3_OUTPUT_DIR),
        base_dir,
    )
    configured_resolutions = h3_config.get("resolutions", (6,))
    source_water_path = h3_config.get("water_geometry_path")
    if source_water_path:
        water_path = _resolve_project_path(source_water_path, base_dir)
    else:
        water_path = water_dir / str(
            h3_config.get(
                "source_water_filename",
                water_build.get("output_filename", DEFAULT_WATER_POLYGON_FILENAME),
            )
        )
    return {
        "base_dir": base_dir,
        "water_path": water_path,
        "output_dir": output_dir,
        "h3_resolutions": _resolutions(configured_resolutions),
        "bbox": bbox_from_config(h3_config),
        "output_grid_filename_template": str(
            h3_config.get("output_grid_filename_template", DEFAULT_H3_GRID_FILENAME_TEMPLATE)
        ),
        "output_clipped_grid_filename_template": str(
            h3_config.get(
                "output_clipped_grid_filename_template",
                DEFAULT_H3_CLIPPED_GRID_FILENAME_TEMPLATE,
            )
        ),
        "buffer_m": float(h3_config.get("buffer_m", 2000)),
        "fill_simplify_tolerance": float(h3_config.get("fill_simplify_tolerance", 0.0)),
        "clip_simplify_tolerance": float(h3_config.get("clip_simplify_tolerance", 0.003)),
        "max_workers": int(h3_config.get("max_workers", 8)),
        "log_level": str(raw.get("log_level", "INFO")).upper(),
    }


def load_yaml_config(config_path: str | Path) -> dict:
    """Compatibility alias for :func:`load_h3_geometry_config`."""

    return load_h3_geometry_config(config_path)


def _clip_to_bbox(gdf: gpd.GeoDataFrame, bbox: dict[str, float]) -> gpd.GeoDataFrame:
    return clip_to_bbox(gdf, bbox)


# =========================
# Geometry helpers
# =========================


def _normalize_geom(g):
    return normalize_polygonal_geometry(g)


def _ensure_epsg4326(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return ensure_epsg4326(gdf)


def _buffer_meters(gdf: gpd.GeoDataFrame, meters: float) -> gpd.GeoDataFrame:
    """Buffer in meters using Web Mercator and return to EPSG:4326."""
    return buffer_meters(gdf, meters)


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance between two lon/lat pairs in meters."""
    return haversine_distance_m(lat1, lon1, lat2, lon2)


def _estimate_cell_radius_m(target_resolution: int) -> float:
    """Estimate the maximum distance from center to boundary for cells at this resolution."""
    sample_cell = latlng_to_cell(0.0, 0.0, target_resolution)
    center_lat, center_lon = cell_to_latlng(sample_cell)
    boundary = cell_to_boundary(sample_cell)
    radius = max(_haversine_distance(center_lat, center_lon, lat, lon) for lat, lon in boundary)
    LOGGER.debug("Estimated circumradius %.1f m for resolution %d", radius, target_resolution)
    return radius


def _merge_geometries(
    poly_gdf: gpd.GeoDataFrame, simplify_tolerance: float = 0.0
) -> Polygon | MultiPolygon:
    """
    Union all polygons in the GeoDataFrame and optionally simplify the result.
    Ensures H3 receives a single Polygon/MultiPolygon for coverage.
    """
    poly_gdf = _ensure_epsg4326(poly_gdf)
    valid_geoms: List[Polygon | MultiPolygon] = []
    for geom in poly_gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        try:
            normalized = _normalize_geom(geom)
        except (ValueError, TypeError):
            continue
        valid_geoms.append(normalized)

    if not valid_geoms:
        raise ValueError("No valid geometries available for H3 fill.")

    merged = valid_geoms[0] if len(valid_geoms) == 1 else unary_union(valid_geoms)
    merged = safe_make_valid(merged)
    if simplify_tolerance > 0:
        merged = merged.simplify(simplify_tolerance, preserve_topology=True)
    merged = _normalize_geom(merged)  # type: ignore[arg-type]
    LOGGER.debug("Prepared merged geometry with %d parts.", len(valid_geoms))
    return merged


# =========================
# H3 helpers
# =========================


def polygonize_h3_indices(
    indices: List[str],
    parallel: str = "thread",  # "thread" | "off"
    max_workers: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """
    Turn a list of H3 indices into a GeoDataFrame of hex polygons.
    """
    return core_polygonize_h3_indices(
        indices,
        h3_col="H3_INDEX",
        parallel=parallel,
        max_workers=max_workers,
    )


def get_h3_cells_indices(
    poly_gdf: gpd.GeoDataFrame,
    target_resolution: int,
    simplify_tolerance: float = 0.0,
) -> List[str]:
    """
    Direct H3 fill at target resolution.
    Optionally simplifies the polygon (in degrees) before calling the overlap-aware
    polygon fill so any hex that intersects the water polygon is returned.
    """
    merged_geom = _merge_geometries(poly_gdf, simplify_tolerance=simplify_tolerance)
    return list(polygon_to_cells_overlap(merged_geom, target_resolution))


# =========================
# Water clipping
# =========================


def prepare_water_geometry(
    waters: gpd.GeoDataFrame,
    simplify_tolerance: float = 0.001,
):
    """
    Dissolve, validate, and simplify the water geometry.
    simplify_tolerance is in degrees (~0.001 ≈ ~100 m).
    """
    waters = _ensure_epsg4326(waters)
    water_geom = unary_union(waters.geometry)
    water_geom = safe_make_valid(water_geom)
    if simplify_tolerance > 0:
        water_geom = water_geom.simplify(simplify_tolerance, preserve_topology=True)
    return water_geom


def clip_hexes_to_water(
    gdf_out: gpd.GeoDataFrame,
    waters: gpd.GeoDataFrame,
    simplify_tolerance: float = 0.001,
) -> gpd.GeoDataFrame:
    """
    Intersect each hex with the water polygon and drop land-only cells.
    Uses bbox-intersects to prefilter water instead of full gpd.clip.
    """
    gdf_out = _ensure_epsg4326(gdf_out)
    waters = _ensure_epsg4326(waters)

    # Bounding box of all hexes
    aoi_bbox = gdf_out.geometry.union_all().envelope

    # Cheap prefilter: only keep water features whose bbox intersects AOI
    # (no geometry overlay yet, just bounding boxes)
    if hasattr(waters, "sindex") and waters.sindex is not None:
        # use spatial index if available
        hits = waters.sindex.query(aoi_bbox, predicate="intersects")
        waters_aoi = waters.iloc[hits].copy()
    else:
        # fallback: bbox filter
        waters_aoi = waters[waters.intersects(aoi_bbox)].copy()

    # Dissolve + validate + simplify
    water_geom = unary_union(waters_aoi.geometry)
    water_geom = safe_make_valid(water_geom)
    if simplify_tolerance > 0:
        water_geom = water_geom.simplify(simplify_tolerance, preserve_topology=True)

    # Spatial index prefilter on hexes
    hex_hits = gdf_out.sindex.query(water_geom, predicate="intersects")
    candidates = gdf_out.iloc[hex_hits].copy()

    # Vectorized intersection
    candidates["geometry"] = candidates.geometry.intersection(water_geom)

    clipped = candidates[~candidates.geometry.is_empty].copy()
    clipped.reset_index(drop=True, inplace=True)
    return clipped


def _calculate_area_sq_meters(gdf: gpd.GeoDataFrame) -> float:
    if gdf.empty:
        return 0.0
    return float(gdf.to_crs(3857).geometry.area.sum())


def _log_coverage_stats(waters: gpd.GeoDataFrame, clipped: gpd.GeoDataFrame) -> None:
    water_area = _calculate_area_sq_meters(waters)
    clipped_area = _calculate_area_sq_meters(clipped)
    ratio = clipped_area / water_area if water_area > 0 else 0.0
    LOGGER.info(
        "Water area %.0f m², clipped hex area %.0f m², coverage ratio %.1f%%",
        water_area,
        clipped_area,
        ratio * 100,
    )
    if 0 < ratio < 0.95:
        LOGGER.warning(
            "Clipped hex coverage (%.1f%%) is much lower than the water area; "
            "this may indicate missing H3 cells or a simplify tolerance that is too aggressive.",
            ratio * 100,
        )


# =========================
# Main builder
# =========================


def _build_h3_grid_layer(
    *,
    waters: gpd.GeoDataFrame,
    resolution: int,
    output_dir: Path,
    output_grid_filename_template: str,
    output_clipped_grid_filename_template: str,
    buffer_m: float,
    fill_simplify_tolerance: float,
    clip_simplify_tolerance: float,
    max_workers: int,
    full_path: Path | None = None,
    clipped_path: Path | None = None,
) -> tuple[Path, Path]:
    """Build full-cell and water-clipped geometry layers for one resolution."""

    cell_radius_m = _estimate_cell_radius_m(resolution)
    buffer_extension = max(buffer_m, 0.0)
    fill_buffer_m = cell_radius_m + buffer_extension
    LOGGER.info(
        "Filling H3 resolution %d with %.0f m buffer (base %.0f m + cell radius %.0f m).",
        resolution,
        fill_buffer_m,
        buffer_extension,
        cell_radius_m,
    )
    waters_buffer = _buffer_meters(waters, fill_buffer_m)
    indices = get_h3_cells_indices(
        poly_gdf=waters_buffer,
        target_resolution=resolution,
        simplify_tolerance=fill_simplify_tolerance,
    )
    full_grid = polygonize_h3_indices(
        indices,
        parallel="thread",
        max_workers=max_workers,
    )
    clipped_grid = clip_hexes_to_water(
        gdf_out=full_grid,
        waters=waters,
        simplify_tolerance=clip_simplify_tolerance,
    )
    if clipped_grid.empty:
        raise ValueError(f"Water-clipped H3 grid is empty at resolution {resolution}.")
    _log_coverage_stats(waters, clipped_grid)

    full_grid["H3_RESOLUTION"] = resolution
    clipped_grid["H3_RESOLUTION"] = resolution
    full_grid = full_grid[["H3_INDEX", "H3_RESOLUTION", "geometry"]]
    clipped_grid = clipped_grid[["H3_INDEX", "H3_RESOLUTION", "geometry"]]
    output_dir.mkdir(parents=True, exist_ok=True)
    full_path = full_path or output_dir / output_grid_filename_template.format(res=resolution)
    clipped_path = clipped_path or output_dir / output_clipped_grid_filename_template.format(
        res=resolution
    )
    full_grid.to_parquet(full_path, index=False)
    clipped_grid.to_parquet(clipped_path, index=False)
    return full_path, clipped_path


def build_h3_grid_layers(
    config_path: str | Path = "config/data/project.yaml",
    water_path: str | Path | None = None,
    resolutions: tuple[int, ...] | None = None,
    buffer_m: float | None = None,
    fill_simplify_tolerance: float | None = None,
    clip_simplify_tolerance: float | None = None,
    max_workers: int | None = None,
) -> tuple[tuple[Path, Path], ...]:
    """Build configured H3 geometry layers from the canonical water geometry."""

    cfg = load_h3_geometry_config(config_path)
    selected_resolutions = (
        cfg["h3_resolutions"] if resolutions is None else _resolutions(resolutions)
    )
    source = Path(water_path) if water_path is not None else Path(cfg["water_path"])
    if not source.exists():
        raise FileNotFoundError(
            f"Water geometry not found: {source}. Build water_geometry before h3_geometry."
        )
    waters = _ensure_epsg4326(gpd.read_parquet(source))
    waters = _clip_to_bbox(waters, cfg["bbox"])
    if waters.empty:
        raise ValueError("Water geometry is empty after the configured H3-area clip.")
    waters = waters.dissolve()[["geometry"]]

    configured_buffer = cfg["buffer_m"] if buffer_m is None else float(buffer_m)
    fill_tolerance = (
        cfg["fill_simplify_tolerance"]
        if fill_simplify_tolerance is None
        else float(fill_simplify_tolerance)
    )
    clip_tolerance = (
        cfg["clip_simplify_tolerance"]
        if clip_simplify_tolerance is None
        else float(clip_simplify_tolerance)
    )
    workers = cfg["max_workers"] if max_workers is None else int(max_workers)
    output_dir = Path(cfg["output_dir"])
    results: list[tuple[Path, Path]] = []
    with TransactionalSeascapePublisher(output_dir) as publisher:
        records = []
        for resolution in selected_resolutions:
            full_destination = output_dir / cfg["output_grid_filename_template"].format(
                res=resolution
            )
            clipped_destination = output_dir / cfg["output_clipped_grid_filename_template"].format(
                res=resolution
            )
            _build_h3_grid_layer(
                waters=waters,
                resolution=resolution,
                output_dir=output_dir,
                output_grid_filename_template=cfg["output_grid_filename_template"],
                output_clipped_grid_filename_template=cfg["output_clipped_grid_filename_template"],
                buffer_m=configured_buffer,
                fill_simplify_tolerance=fill_tolerance,
                clip_simplify_tolerance=clip_tolerance,
                max_workers=workers,
                full_path=publisher.stage_path(full_destination),
                clipped_path=publisher.stage_path(clipped_destination),
            )
            records.extend(
                (
                    capture_staged_parquet_artifact(publisher, full_destination),
                    capture_staged_parquet_artifact(publisher, clipped_destination),
                )
            )
            results.append((full_destination, clipped_destination))
        water_checksum = checksum_path(source)
        manifest = build_manifest(
            dataset_family="environment.seascape.h3_water_geometry",
            run_id=publisher.run_id,
            resolved_config={
                **cfg,
                "resolutions": selected_resolutions,
                "buffer_m": configured_buffer,
                "fill_simplify_tolerance": fill_tolerance,
                "clip_simplify_tolerance": clip_tolerance,
                "max_workers": workers,
            },
            artifacts=records,
            project_root=project_root(),
            sources=[
                {
                    "name": "Canonical territorial-water geometry",
                    "license": "Derived source; see water_geometry_manifest.json",
                    "observation_period": "Static configured boundary snapshot",
                    "redistribution_restrictions": (
                        "Follow the upstream territorial-water source terms."
                    ),
                    "source_warning": (
                        "Full and clipped H3 geometry are support products, not observations."
                    ),
                }
            ],
            upstream_artifacts=[{"path": str(source), "checksum": water_checksum}],
            attribution=[
                {
                    "text": "Derived from the canonical territorial-water geometry",
                    "license": "See water_geometry_manifest.json",
                }
            ],
            source_completeness="complete",
            metadata={"geometry_role": "multi-resolution full and water-clipped support"},
        )
        publisher.stage_manifest(output_dir / "h3_geometry_manifest.json", manifest)
        publisher.publish()
    return tuple(results)


def build_full_counting_universes(
    *,
    water_path: Path,
    output_root: Path,
    bbox: tuple[float, float, float, float],
    resolutions: tuple[int, ...] = (4, 5, 6),
    run_id: str = "full-counting-universe",
    force: bool = False,
) -> tuple[ArtifactRef, ...]:
    """Publish identity-only water-cell universes for authoritative counts."""

    selected_resolutions = _resolutions(resolutions)
    if not water_path.exists():
        raise FileNotFoundError(f"Water geometry does not exist: {water_path}")
    waters = gpd.read_parquet(water_path).to_crs(4326).clip(bbox)
    if waters.empty:
        raise ValueError("Water geometry is empty after AOI clipping")
    if output_root.exists() and not force:
        raise FileExistsError(f"Full counting universes exist; pass --force: {output_root}")
    producer = "environment.seascape.spatial_support.h3_geometry.build"
    input_checksum = checksum_path(water_path)
    published_refs: list[ArtifactRef] = []
    with TransactionalSeascapePublisher(output_root, run_id=run_id) as publisher:
        published_records = []
        for resolution in selected_resolutions:
            cells = sorted(set(get_h3_cells_indices(waters, resolution)))
            if not cells:
                raise ValueError(f"Full counting universe is empty at H{resolution}")
            destination = output_root / f"H3_WATER_UNIVERSE_{resolution}.parquet"
            frame = pd.DataFrame({"H3_INDEX": cells, "H3_RESOLUTION": resolution})
            record = stage_parquet_artifact(publisher, frame, destination)
            published_records.append(record)
            published_refs.append(
                ArtifactRef(
                    kind="domain",
                    dataset_id=(f"environment.seascape.h3_full_counting_universe_r{resolution}"),
                    path=destination,
                    producer=producer,
                    schema_version="1",
                    run_id=run_id,
                    checksum=record.checksum,
                    row_count=len(cells),
                    file_count=1,
                    inputs=(input_checksum,),
                )
            )
        manifest = build_manifest(
            dataset_family="environment.seascape.h3_full_counting_universe",
            run_id=run_id,
            resolved_config={"bbox": bbox, "resolutions": selected_resolutions},
            artifacts=published_records,
            project_root=project_root(),
            sources=[
                {
                    "name": "Canonical territorial-water geometry",
                    "license": "Derived source; see water_geometry_manifest.json",
                    "observation_period": "Static configured boundary snapshot",
                    "redistribution_restrictions": (
                        "Follow the upstream territorial-water source terms."
                    ),
                    "source_warning": (
                        "This is an identity universe, not model-area support or habitat evidence."
                    ),
                }
            ],
            upstream_artifacts=[{"path": str(water_path), "checksum": input_checksum}],
            attribution=[
                {
                    "text": "Derived from the canonical territorial-water geometry",
                    "license": "See water_geometry_manifest.json",
                }
            ],
            source_completeness="complete",
            metadata={"bbox": list(bbox), "identity_only": True},
        )
        publisher.stage_manifest(output_root / "_dataset_manifest.json", manifest)
        publisher.publish()
    return tuple(published_refs)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Build H3 grid layers from config.")
    parser.add_argument(
        "--config",
        type=str,
        default="config/data/project.yaml",
        help="Path to YAML config file.",
    )
    parser.add_argument(
        "--water-path",
        "--water_path",
        type=str,
        default=None,
        help="Optional override path to water polygon parquet.",
    )
    parser.add_argument(
        "--resolution",
        dest="resolutions",
        action="append",
        type=int,
        help="Override configured H3 resolutions; repeat for multiple values.",
    )
    parser.add_argument(
        "--buffer_m",
        type=float,
        default=None,
        help="Override configured buffer distance in meters for AOI expansion.",
    )
    parser.add_argument(
        "--fill_simplify_tolerance",
        type=float,
        default=None,
        help="Override configured simplification tolerance (degrees) before H3 fill.",
    )
    parser.add_argument(
        "--clip_simplify_tolerance",
        type=float,
        default=None,
        help="Override configured simplification tolerance (degrees) during clipping.",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=None,
        help="Override configured max thread workers for H3 polygonization.",
    )

    args = parser.parse_args()

    build_h3_grid_layers(
        config_path=args.config,
        water_path=args.water_path,
        resolutions=tuple(args.resolutions) if args.resolutions else None,
        buffer_m=args.buffer_m,
        fill_simplify_tolerance=args.fill_simplify_tolerance,
        clip_simplify_tolerance=args.clip_simplify_tolerance,
        max_workers=args.max_workers,
    )
