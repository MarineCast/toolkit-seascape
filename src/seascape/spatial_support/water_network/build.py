"""Build canonical H3 marine support and land-barrier-respecting water graphs."""

from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pyproj import Geod
from shapely import from_wkb, union_all
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.polygon import orient
from shapely.prepared import prep
from shapely.strtree import STRtree

from seascape.core.config.paths import project_root
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.geometry import safe_polygonal_union
from seascape.core.geo.h3 import (
    cell_to_latlng,
    cell_to_parent,
    polygon_to_cells_overlap,
    polygonize_h3_indices,
)
from seascape.publication import (
    TransactionalSeascapePublisher,
)
from seascape.utils.artifacts import (
    build_manifest,
    capture_staged_parquet_artifact,
    default_semantic_contracts,
)
from seascape.utils.spatial import h3_cell_set_hash

from .config import DEFAULT_CONFIG_PATH, WaterNetworkConfig, load_water_network_config
from .graph import (
    _assign_components,
    _build_connectors,
    _build_edges,
    _build_neighborhoods,
    _crosswalk,
)
from .load import _csr
from .radius_operator import RadiusSumOperator
from .validation import (
    SUPPORT_REQUIRED_COLUMNS,
    validate_connectors,
    validate_edges,
    validate_geometry_products,
    validate_neighborhoods,
    validate_support,
)

LOGGER = logging.getLogger(__name__)
GEOD = Geod(ellps="WGS84")


def _geodesic_area_m2(geometry: Any) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    if not isinstance(geometry, Polygon):
        return float(sum(_geodesic_area_m2(part) for part in _polygon_parts(geometry)))
    area, _perimeter = GEOD.geometry_area_perimeter(orient(geometry, sign=1.0))
    return abs(float(area))


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty else []
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if hasattr(geometry, "geoms"):
        return [part for value in geometry.geoms for part in _polygon_parts(value)]
    return []


def _representative_point(geometry: Any):
    parts = _polygon_parts(geometry)
    if not parts:
        raise ValueError("Water-clipped H3 geometry has no polygonal component.")
    ranked = sorted(
        parts,
        key=lambda part: (
            -_geodesic_area_m2(part),
            part.bounds,
            part.wkb_hex,
        ),
    )
    point = ranked[0].representative_point()
    if not ranked[0].covers(point):
        raise ValueError("Representative point is not within clipped water geometry.")
    return point


def _densified_geodesic_polygon(polygon: Polygon, maximum_segment_m: float) -> Polygon:
    """Densify a polygon boundary with points on each geodesic edge."""

    coordinates = list(polygon.exterior.coords)
    densified: list[tuple[float, float]] = []
    for source, target in zip(coordinates, coordinates[1:]):
        densified.append((float(source[0]), float(source[1])))
        _azimuth, _back_azimuth, distance = GEOD.inv(*source, *target)
        interior_count = max(0, int(math.ceil(float(distance) / maximum_segment_m)) - 1)
        if interior_count:
            densified.extend(GEOD.npts(*source, *target, interior_count))
    densified.append((float(coordinates[-1][0]), float(coordinates[-1][1])))
    return Polygon(densified)


def _load_water_geometry(config: WaterNetworkConfig):
    if not config.water_polygon_path.exists():
        raise FileNotFoundError(f"Canonical water geometry not found: {config.water_polygon_path}")
    frame = gpd.read_parquet(config.water_polygon_path)
    if frame.crs is None:
        raise ValueError(f"Canonical water geometry has no CRS: {config.water_polygon_path}")
    frame = frame.to_crs("EPSG:4326")
    bounds = box(
        config.bbox["min_lon"],
        config.bbox["min_lat"],
        config.bbox["max_lon"],
        config.bbox["max_lat"],
    )
    return safe_polygonal_union(frame, clip_geometry=bounds), bounds


def _tiled_water_parts(
    water_geometry: Any,
    *,
    tile_size_degrees: float = 0.5,
) -> list[Polygon]:
    """Partition the exact water mask into bounded polygonal components."""

    min_x, min_y, max_x, max_y = water_geometry.bounds
    x_start = math.floor(min_x / tile_size_degrees) * tile_size_degrees
    y_start = math.floor(min_y / tile_size_degrees) * tile_size_degrees
    x_values = np.arange(x_start, max_x + tile_size_degrees, tile_size_degrees)
    y_values = np.arange(y_start, max_y + tile_size_degrees, tile_size_degrees)
    prepared_water = prep(from_wkb(water_geometry.wkb))
    output: list[Polygon] = []
    seam_overlap_degrees = 1e-9
    for x_value in x_values:
        for y_value in y_values:
            tile = box(
                float(x_value - seam_overlap_degrees),
                float(y_value - seam_overlap_degrees),
                float(x_value + tile_size_degrees + seam_overlap_degrees),
                float(y_value + tile_size_degrees + seam_overlap_degrees),
            )
            if not prepared_water.intersects(tile):
                continue
            clipped_water = water_geometry.intersection(tile)
            output.extend(_polygon_parts(clipped_water))
    return output


def _tiled_overlap_cells(
    water_geometry: Any,
    resolution: int,
    *,
    tile_size_degrees: float = 0.5,
) -> list[str]:
    """Fill exact water-overlap candidates in bounded spatial tiles.

    Intersecting the unsimplified mask with a complete tile partition preserves
    overlap membership while avoiding a single pathological H3 fill over a very
    detailed coastline.
    """

    parts = _tiled_water_parts(
        water_geometry,
        tile_size_degrees=tile_size_degrees,
    )
    cells: set[str] = set()
    for part in parts:
        cells.update(polygon_to_cells_overlap(part, resolution))
    if resolution == 6:
        child_cells: set[str] = set()
        for part in parts:
            child_cells.update(polygon_to_cells_overlap(part, 8))
        cells.update(cell_to_parent(cell, 6) for cell in child_cells)
    return sorted(cells)


def _build_geometry_and_base_support(
    water_geometry: Any,
    aoi: Any,
    resolution: int,
    config: WaterNetworkConfig,
    *,
    cells: list[str] | None = None,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame]:
    stage_started = time.perf_counter()
    cells = _tiled_overlap_cells(water_geometry, resolution) if cells is None else sorted(cells)
    if not cells:
        raise ValueError(f"No H3 r{resolution} cells overlap canonical water geometry.")
    LOGGER.info(
        "Filled H3 r%d overlap support (%d candidates) in %.1fs",
        resolution,
        len(cells),
        time.perf_counter() - stage_started,
    )
    stage_started = time.perf_counter()
    full = polygonize_h3_indices(
        cells,
        h3_col="H3_INDEX",
        parallel="thread",
        max_workers=config.max_workers,
    )
    full["H3_RESOLUTION"] = resolution
    LOGGER.info(
        "Polygonized H3 r%d support in %.1fs",
        resolution,
        time.perf_counter() - stage_started,
    )
    stage_started = time.perf_counter()
    water_parts = _tiled_water_parts(water_geometry)
    water_tree = STRtree(water_parts)
    clipped_rows: list[dict[str, Any]] = []
    for h3_index, cell_geometry in zip(full["H3_INDEX"], full.geometry):
        candidates = water_tree.query(cell_geometry, predicate="intersects")
        if not len(candidates):
            continue
        candidate_geometries = [water_parts[int(index)] for index in candidates]
        local_water = (
            candidate_geometries[0]
            if len(candidate_geometries) == 1
            else union_all(candidate_geometries)
        )
        intersection = cell_geometry.intersection(local_water)
        polygon_parts = _polygon_parts(intersection)
        if not polygon_parts:
            continue
        clipped_rows.append(
            {
                "H3_INDEX": h3_index,
                "H3_RESOLUTION": resolution,
                "geometry": (
                    polygon_parts[0] if len(polygon_parts) == 1 else union_all(polygon_parts)
                ),
            }
        )
    clipped = gpd.GeoDataFrame(clipped_rows, crs="EPSG:4326")
    full = full.loc[full["H3_INDEX"].isin(clipped["H3_INDEX"])].copy()
    full = full.sort_values("H3_INDEX").reset_index(drop=True)
    clipped = clipped.sort_values("H3_INDEX").reset_index(drop=True)
    keep = ~clipped.geometry.is_empty & clipped.geometry.notna()
    full = full.loc[keep].reset_index(drop=True)
    clipped = clipped.loc[keep].reset_index(drop=True)
    if not full["H3_INDEX"].equals(clipped["H3_INDEX"]):
        raise ValueError("Full and clipped H3 geometry identifiers are misaligned.")
    cells = full["H3_INDEX"].astype(str).tolist()
    LOGGER.info(
        "Clipped H3 r%d support to exact water geometry in %.1fs",
        resolution,
        time.perf_counter() - stage_started,
    )
    stage_started = time.perf_counter()
    cell_area = np.asarray([_geodesic_area_m2(value) for value in full.geometry])
    water_area = np.asarray([_geodesic_area_m2(value) for value in clipped.geometry])
    if (water_area <= 0.0).any():
        raise ValueError("A retained marine-support cell has nonpositive water area.")
    raw_fraction = water_area / cell_area
    invalid = (water_area < -config.area_tolerance_m2) | (
        water_area > cell_area + config.area_tolerance_m2
    )
    # Intersections can insert planar vertices along a canonical H3 edge, which
    # perturbs Geod's segment interpretation.  For an apparent overshoot only,
    # ask the original unsplit mask whether the whole cell is water.  The
    # unprepared predicate is intentional: prepared ``covers`` is unreliable for
    # this highly detailed source geometry in current Shapely releases.
    normalized_full_cells = 0
    densified_partial_cells = 0
    for index in np.flatnonzero(invalid & (raw_fraction > 1.0)):
        if water_geometry.covers(full.geometry.iloc[index]):
            clipped.at[index, "geometry"] = full.geometry.iloc[index]
            water_area[index] = cell_area[index]
            normalized_full_cells += 1
            continue
        segment_sizes = [config.geodesic_segment_max_m]
        segment_sizes.extend(
            value for value in (10.0, 1.0) if value < config.geodesic_segment_max_m
        )
        for segment_size in segment_sizes:
            densified_cell = _densified_geodesic_polygon(
                full.geometry.iloc[index],
                segment_size,
            )
            exact_intersection = densified_cell.intersection(water_geometry)
            exact_parts = _polygon_parts(exact_intersection)
            if not exact_parts:
                continue
            clipped.at[index, "geometry"] = (
                exact_parts[0] if len(exact_parts) == 1 else union_all(exact_parts)
            )
            water_area[index] = _geodesic_area_m2(clipped.geometry.iloc[index])
            if water_area[index] <= cell_area[index] + config.area_tolerance_m2:
                break
        densified_partial_cells += 1
    if invalid.any():
        LOGGER.info(
            "Resolved %d full-water and %d partial-cell geodesic-area overshoots out of %d",
            normalized_full_cells,
            densified_partial_cells,
            int(invalid.sum()),
        )
    raw_fraction = water_area / cell_area
    invalid = (water_area < -config.area_tolerance_m2) | (
        water_area > cell_area + config.area_tolerance_m2
    )
    complement_corrected_cells = 0
    for index in np.flatnonzero(invalid & (water_area > cell_area)):
        land_geometry = full.geometry.iloc[index].difference(water_geometry)
        direct_land_area = _geodesic_area_m2(land_geometry)
        if 0.0 <= direct_land_area < cell_area[index]:
            water_area[index] = cell_area[index] - direct_land_area
            complement_corrected_cells += 1
    if complement_corrected_cells:
        LOGGER.info(
            "Applied geodesic partition-complement correction to %d partial cells",
            complement_corrected_cells,
        )
    raw_fraction = water_area / cell_area
    invalid = (water_area < -config.area_tolerance_m2) | (
        water_area > cell_area + config.area_tolerance_m2
    )
    if invalid.any():
        examples = [
            {
                "h3": cells[index],
                "cell_area_m2": float(cell_area[index]),
                "water_area_m2": float(water_area[index]),
                "fraction": float(raw_fraction[index]),
                "missing_area_m2": _geodesic_area_m2(
                    full.geometry.iloc[index].difference(clipped.geometry.iloc[index])
                ),
            }
            for index in np.flatnonzero(invalid)[:5]
        ]
        raise ValueError(f"Water fraction is outside numerical tolerance: {examples}")
    water_fraction = np.clip(raw_fraction, 0.0, 1.0)
    land_area = np.maximum(0.0, cell_area - water_area)
    land_fraction = 1.0 - water_fraction
    representative_points = [_representative_point(value) for value in clipped.geometry]
    is_full = land_area <= config.area_tolerance_m2
    shoreline = water_geometry.boundary
    prepared_shoreline = prep(from_wkb(shoreline.wkb))
    prepared_aoi_boundary = prep(from_wkb(aoi.boundary.wkb))
    base = pd.DataFrame(
        {
            "H3_INDEX": cells,
            "H3_RESOLUTION": resolution,
            "PARENT_H3_INDEX": [cell_to_parent(cell, resolution - 1) for cell in cells],
            "CELL_AREA_M2": cell_area,
            "WATER_AREA_M2": water_area,
            "LAND_AREA_M2": land_area,
            "WATER_FRACTION": water_fraction,
            "LAND_FRACTION": land_fraction,
            "HAS_WATER_OVERLAP": True,
            "IS_HIERARCHY_ONLY_PARENT": False,
            "IS_FULLY_WATER": is_full,
            "IS_PARTIALLY_WATER": ~is_full,
            "INTERSECTS_SHORELINE": [
                bool(prepared_shoreline.intersects(value)) for value in full.geometry
            ],
            "IS_AOI_BOUNDARY_CELL": [
                bool(prepared_aoi_boundary.intersects(value)) for value in full.geometry
            ],
            "WATER_COMPONENT_ID": pd.Series([None] * len(cells), dtype="string"),
            "WATER_MASK_VERSION": config.water_mask_version,
            "SPATIAL_SUPPORT_VERSION": config.spatial_support_version,
            "REPRESENTATIVE_POINT_LONGITUDE": [point.x for point in representative_points],
            "REPRESENTATIVE_POINT_LATITUDE": [point.y for point in representative_points],
            "GRAPH_NODE_ELIGIBLE": (
                (water_fraction >= config.minimum_water_fraction)
                & (water_area >= config.minimum_water_area_m2)
            ),
            "GRAPH_DEGREE": np.zeros(len(cells), dtype=np.int32),
            "GRAPH_CONNECTION_STATUS": "disconnected",
            "CONNECTOR_TARGET_H3_INDEX": pd.Series([None] * len(cells), dtype="string"),
            "CONNECTOR_METHOD": pd.Series([None] * len(cells), dtype="string"),
            "CONNECTOR_DISTANCE_M": np.full(len(cells), np.nan),
            "CONNECTOR_WATER_PATH_FRACTION": np.full(len(cells), np.nan),
            "GRAPH_QC_REASON": pd.Series([None] * len(cells), dtype="string"),
        }
    )
    LOGGER.info(
        "Calculated H3 r%d geodesic areas/flags in %.1fs",
        resolution,
        time.perf_counter() - stage_started,
    )
    return (
        full.assign(HAS_WATER_OVERLAP=True)[
            ["H3_INDEX", "H3_RESOLUTION", "HAS_WATER_OVERLAP", "geometry"]
        ],
        clipped.assign(HAS_WATER_OVERLAP=True)[
            ["H3_INDEX", "H3_RESOLUTION", "HAS_WATER_OVERLAP", "geometry"]
        ],
        base,
    )


def _append_hierarchy_only_parents(
    full: gpd.GeoDataFrame,
    clipped: gpd.GeoDataFrame,
    support: pd.DataFrame,
    required_cells: set[str],
    *,
    resolution: int,
    water_geometry: Any,
    aoi: Any,
    config: WaterNetworkConfig,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame]:
    """Retain dry geometric parents required by the exact H3 hierarchy contract."""

    missing = sorted(required_cells.difference(support["H3_INDEX"].astype(str)))
    if not missing:
        return full, clipped, support
    parent_full = polygonize_h3_indices(missing, h3_col="H3_INDEX")
    parent_full["H3_RESOLUTION"] = resolution
    parent_full["HAS_WATER_OVERLAP"] = False
    parent_clipped = parent_full.copy()
    parent_clipped["geometry"] = [Polygon() for _ in missing]
    cell_area = np.asarray([_geodesic_area_m2(value) for value in parent_full.geometry])
    centers = [cell_to_latlng(cell) for cell in missing]
    parent_support = pd.DataFrame(
        {
            "H3_INDEX": missing,
            "H3_RESOLUTION": resolution,
            "PARENT_H3_INDEX": [cell_to_parent(cell, resolution - 1) for cell in missing],
            "CELL_AREA_M2": cell_area,
            "WATER_AREA_M2": np.zeros(len(missing)),
            "LAND_AREA_M2": cell_area,
            "WATER_FRACTION": np.zeros(len(missing)),
            "LAND_FRACTION": np.ones(len(missing)),
            "HAS_WATER_OVERLAP": False,
            "IS_HIERARCHY_ONLY_PARENT": True,
            "IS_FULLY_WATER": False,
            "IS_PARTIALLY_WATER": False,
            "INTERSECTS_SHORELINE": [
                bool(water_geometry.boundary.intersects(value)) for value in parent_full.geometry
            ],
            "IS_AOI_BOUNDARY_CELL": [
                bool(aoi.boundary.intersects(value)) for value in parent_full.geometry
            ],
            "WATER_COMPONENT_ID": pd.Series([None] * len(missing), dtype="string"),
            "WATER_MASK_VERSION": config.water_mask_version,
            "SPATIAL_SUPPORT_VERSION": config.spatial_support_version,
            "REPRESENTATIVE_POINT_LONGITUDE": [longitude for latitude, longitude in centers],
            "REPRESENTATIVE_POINT_LATITUDE": [latitude for latitude, longitude in centers],
            "GRAPH_NODE_ELIGIBLE": False,
            "GRAPH_DEGREE": np.zeros(len(missing), dtype=np.int32),
            "GRAPH_CONNECTION_STATUS": "disconnected",
            "CONNECTOR_TARGET_H3_INDEX": pd.Series([None] * len(missing), dtype="string"),
            "CONNECTOR_METHOD": pd.Series([None] * len(missing), dtype="string"),
            "CONNECTOR_DISTANCE_M": np.full(len(missing), np.nan),
            "CONNECTOR_WATER_PATH_FRACTION": np.full(len(missing), np.nan),
            "GRAPH_QC_REASON": "hierarchy_parent_without_geometric_water_overlap",
        }
    )
    LOGGER.warning(
        "Retaining %d H3 r%d hierarchy-only parents with zero geometric water overlap",
        len(missing),
        resolution,
    )
    return (
        gpd.GeoDataFrame(pd.concat([full, parent_full], ignore_index=True), crs=full.crs)
        .sort_values("H3_INDEX")
        .reset_index(drop=True),
        gpd.GeoDataFrame(pd.concat([clipped, parent_clipped], ignore_index=True), crs=clipped.crs)
        .sort_values("H3_INDEX")
        .reset_index(drop=True),
        pd.concat([support, parent_support], ignore_index=True)
        .sort_values("H3_INDEX")
        .reset_index(drop=True),
    )


def build_marine_spatial_support(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    resolutions: tuple[int, ...] | None = None,
    overwrite: bool = False,
    run_id: str | None = None,
) -> tuple[Path, ...]:
    """Build, validate, and publish configured marine support and water graphs."""

    config = load_water_network_config(config_path)
    selected_request = config.resolutions if resolutions is None else tuple(resolutions)
    if set(selected_request) != set(config.resolutions):
        raise ValueError(
            "Canonical publication requires every configured resolution in one build; "
            f"configured={config.resolutions}, requested={selected_request}."
        )
    selected = tuple(sorted(config.resolutions, reverse=True))
    destinations: list[Path] = []
    for resolution in selected:
        destinations.extend(
            (
                config.support_path(resolution),
                config.model_support_path(resolution),
                config.full_geometry_path(resolution),
                config.clipped_geometry_path(resolution),
                config.edge_path(resolution),
                config.connector_path(resolution),
                config.neighborhood_path(resolution),
            )
        )
    if {6, 8}.issubset(selected):
        destinations.append(config.parent_child_path)
    destinations.extend((config.radius_sum_operator_path, config.reachable_water_area_path))
    existing = [path for path in destinations if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Marine support artifacts exist; pass --overwrite: {existing[0]}")
    water_geometry, aoi = _load_water_geometry(config)
    water_checksum = checksum_path(config.water_polygon_path)
    run = run_id or f"marine-spatial-support-{uuid.uuid4().hex[:12]}"
    transaction_root = Path(
        os.path.commonpath([str(path.parent.resolve()) for path in destinations])
    )
    publisher = TransactionalSeascapePublisher(transaction_root, run_id=run)
    publisher.__enter__()
    support_by_resolution: dict[int, pd.DataFrame] = {}
    model_support_by_resolution: dict[int, pd.DataFrame] = {}
    model_cells_by_resolution: dict[int, set[str]] = {}
    edges_by_resolution: dict[int, pd.DataFrame] = {}
    staged: dict[Path, Path] = {}
    try:
        for resolution in selected:
            LOGGER.info("Building canonical H3 r%d marine support", resolution)
            stage_started = time.perf_counter()
            candidate_cells = None
            if resolution == 6 and 8 in model_cells_by_resolution:
                required_parents = {
                    cell_to_parent(cell, 6) for cell in model_cells_by_resolution[8]
                }
                candidate_cells = sorted(
                    set(_tiled_overlap_cells(water_geometry, resolution)).union(required_parents)
                )
            full, clipped, support = _build_geometry_and_base_support(
                water_geometry,
                aoi,
                resolution,
                config,
                cells=candidate_cells,
            )
            if resolution == 6 and 8 in model_cells_by_resolution:
                full, clipped, support = _append_hierarchy_only_parents(
                    full,
                    clipped,
                    support,
                    {cell_to_parent(cell, 6) for cell in model_cells_by_resolution[8]},
                    resolution=resolution,
                    water_geometry=water_geometry,
                    aoi=aoi,
                    config=config,
                )
            LOGGER.info(
                "Built H3 r%d geometry/support base (%d wet cells) in %.1fs",
                resolution,
                len(support),
                time.perf_counter() - stage_started,
            )
            validate_geometry_products(full, clipped, resolution)
            if resolution == 8:
                model_bounds = (
                    gpd.GeoSeries(
                        [
                            box(
                                config.model_bbox["min_lon"],
                                config.model_bbox["min_lat"],
                                config.model_bbox["max_lon"],
                                config.model_bbox["max_lat"],
                            )
                        ],
                        crs="EPSG:4326",
                    )
                    .to_crs("EPSG:6933")
                    .iloc[0]
                )
                projected_clipped = clipped.to_crs("EPSG:6933")
                positive_overlap = projected_clipped.geometry.intersection(model_bounds).area.gt(0)
                model_cells_by_resolution[8] = set(
                    clipped.loc[positive_overlap.to_numpy(), "H3_INDEX"].astype(str)
                )
            elif resolution == 6:
                if 8 not in model_cells_by_resolution:
                    raise ValueError("R8 model support must be derived before R6 support.")
                model_cells_by_resolution[6] = {
                    cell_to_parent(cell, 6) for cell in model_cells_by_resolution[8]
                }
            for destination, frame in (
                (config.full_geometry_path(resolution), full.sort_values("H3_INDEX")),
                (config.clipped_geometry_path(resolution), clipped.sort_values("H3_INDEX")),
            ):
                candidate = publisher.stage_path(destination)
                frame.to_parquet(candidate, index=False)
                staged[destination] = candidate
            del full, clipped
            gc.collect()
            stage_started = time.perf_counter()
            edges = _build_edges(support, water_geometry, resolution, config)
            LOGGER.info(
                "Evaluated H3 r%d neighbor passability (%d candidates) in %.1fs",
                resolution,
                len(edges),
                time.perf_counter() - stage_started,
            )
            stage_started = time.perf_counter()
            _assign_components(support, edges)
            connectors = _build_connectors(support, water_geometry, resolution, config)
            LOGGER.info(
                "Assigned H3 r%d components/connectors (%d connectors) in %.1fs",
                resolution,
                len(connectors),
                time.perf_counter() - stage_started,
            )
            support = support.loc[:, SUPPORT_REQUIRED_COLUMNS].sort_values("H3_INDEX")
            edges = edges.sort_values(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"])
            connectors = connectors.sort_values("H3_INDEX").reset_index(drop=True)
            validate_support(
                support,
                resolution,
                water_mask_version=config.water_mask_version,
                spatial_support_version=config.spatial_support_version,
                area_tolerance_m2=config.area_tolerance_m2,
            )
            validate_edges(edges, support, resolution)
            validate_connectors(connectors, support, resolution)
            model_support = support.loc[
                support["H3_INDEX"].astype(str).isin(model_cells_by_resolution[resolution])
            ].copy()
            if set(model_support["H3_INDEX"].astype(str)) != model_cells_by_resolution[resolution]:
                missing = sorted(
                    model_cells_by_resolution[resolution].difference(
                        model_support["H3_INDEX"].astype(str)
                    )
                )[:5]
                raise ValueError(
                    f"Model-area H3 r{resolution} parents are absent from full support: {missing}"
                )
            validate_support(
                model_support,
                resolution,
                water_mask_version=config.water_mask_version,
                spatial_support_version=config.spatial_support_version,
                area_tolerance_m2=config.area_tolerance_m2,
            )
            neighborhoods = _build_neighborhoods(
                model_support,
                edges,
                connectors,
                resolution,
                config,
            )
            validate_neighborhoods(
                neighborhoods,
                model_support,
                resolution,
                maximum_hops=config.maximum_neighborhood_hops,
            )
            support_by_resolution[resolution] = support
            model_support_by_resolution[resolution] = model_support
            edges_by_resolution[resolution] = edges
            products: tuple[tuple[Path, Any], ...] = (
                (config.support_path(resolution), support),
                (config.model_support_path(resolution), model_support),
                (config.edge_path(resolution), edges),
                (config.connector_path(resolution), connectors),
                (config.neighborhood_path(resolution), neighborhoods),
            )
            for destination, frame in products:
                candidate = publisher.stage_path(destination)
                frame.to_parquet(candidate, index=False)
                staged[destination] = candidate
        crosswalk = _crosswalk(support_by_resolution, config)
        if crosswalk is not None:
            candidate = publisher.stage_path(config.parent_child_path)
            crosswalk.to_parquet(candidate, index=False)
            staged[config.parent_child_path] = candidate
        model_r8 = model_support_by_resolution[8].sort_values("H3_INDEX").reset_index(drop=True)
        passable_r8 = edges_by_resolution[8].loc[
            edges_by_resolution[8]["EDGE_IS_WATER_PASSABLE"].astype(bool)
        ]
        graph_r8 = _csr(support_by_resolution[8], passable_r8, 8)
        edge_candidate = staged[config.edge_path(8)]
        operator = RadiusSumOperator.build(
            graph_r8,
            model_r8["H3_INDEX"].astype(str).tolist(),
            radius_m=config.canonical_radius_m,
            graph_checksum=checksum_path(
                edge_candidate,
                logical_name=config.edge_path(8).name,
            ),
            source_cells=support_by_resolution[8]["H3_INDEX"].astype(str).tolist(),
        )
        operator_candidate = publisher.stage_path(config.radius_sum_operator_path)
        operator.save(operator_candidate)
        staged[config.radius_sum_operator_path] = operator_candidate
        water_area = model_r8["WATER_AREA_M2"].to_numpy(dtype="float64")
        reachable = operator.apply(
            water_area,
            eligible_sources=np.isfinite(water_area),
        )
        reachable_frame = pd.DataFrame(
            {
                "H3_INDEX": model_r8["H3_INDEX"].astype(str),
                "H3_RESOLUTION": 8,
                "REACHABLE_WATER_AREA_WITHIN_5KM_M2": reachable,
                "RADIUS_OPERATOR_SUPPORT_HASH": operator.support_hash,
                "RADIUS_OPERATOR_SOURCE_SUPPORT_HASH": operator.source_support_hash,
                "RADIUS_OPERATOR_GRAPH_CHECKSUM": operator.graph_checksum,
                "GRAPH_CONNECTION_STATUS": model_r8["GRAPH_CONNECTION_STATUS"],
                "GRAPH_QC_REASON": model_r8["GRAPH_QC_REASON"],
            }
        )
        reachable_candidate = publisher.stage_path(config.reachable_water_area_path)
        reachable_frame.to_parquet(reachable_candidate, index=False)
        staged[config.reachable_water_area_path] = reachable_candidate
        artifacts = [
            (
                capture_staged_parquet_artifact(publisher, destination)
                if destination.suffix == ".parquet"
                else publisher.staged_artifact(
                    destination,
                    schema=(
                        {"name": "cells", "type": "string[]", "nullable": False},
                        {"name": "source_cells", "type": "string[]", "nullable": False},
                        {
                            "name": "target_source_indices",
                            "type": "int64[]",
                            "nullable": False,
                        },
                        {"name": "offsets", "type": "int64[]", "nullable": False},
                        {"name": "indices", "type": "int64[]", "nullable": False},
                        {"name": "metadata", "type": "json", "nullable": False},
                    ),
                )
            )
            for destination in sorted(staged)
        ]
        summary = {
            str(resolution): {
                "support_rows": len(support),
                "model_support_rows": len(model_support_by_resolution[resolution]),
                "graph_nodes": int((support["GRAPH_DEGREE"] > 0).sum()),
                "terminal_connectors": int(
                    (support["GRAPH_CONNECTION_STATUS"] == "terminal_connector").sum()
                ),
                "disconnected_cells": int(
                    (support["GRAPH_CONNECTION_STATUS"] == "disconnected").sum()
                ),
                "components": int(support["WATER_COMPONENT_ID"].nunique(dropna=True)),
                "full_h3_cell_set_hash": h3_cell_set_hash(support["H3_INDEX"]),
                "model_h3_cell_set_hash": h3_cell_set_hash(
                    model_support_by_resolution[resolution]["H3_INDEX"]
                ),
                "neighborhood_rows": int(
                    pq.ParquetFile(staged[config.neighborhood_path(resolution)]).metadata.num_rows
                ),
                "candidate_edges": int(
                    pq.ParquetFile(staged[config.edge_path(resolution)]).metadata.num_rows
                ),
            }
            for resolution, support in support_by_resolution.items()
        }
        payload = build_manifest(
            dataset_family="environment.seascape.h3_marine_spatial_support",
            run_id=run,
            resolved_config=asdict(config),
            artifacts=artifacts,
            project_root=project_root(),
            sources=[
                {
                    "name": "Canonical Seascape Toolkit territorial-water geometry",
                    "path": str(config.water_polygon_path),
                    "checksum": water_checksum,
                    "license": "See water_geometry source manifest and seascape documentation",
                    "observation_period": "Static configured territorial-water source generation.",
                    "redistribution_restrictions": (
                        "Follow the licenses in the upstream water-geometry manifest."
                    ),
                    "source_warning": (
                        "Territorial-water geometry is a modeling support mask, not legal advice."
                    ),
                }
            ],
            upstream_artifacts=[
                {"path": str(config.water_polygon_path), "checksum": water_checksum}
            ],
            attribution=[
                {
                    "text": "Canonical Seascape Toolkit territorial-water geometry",
                    "license": "See water_geometry source manifest and seascape documentation",
                }
            ],
            source_completeness="complete",
            semantic_contracts=default_semantic_contracts(
                aggregation=(
                    "The 5 km radius operator uses exact water-network distance with terminal "
                    "connectors and direct self-support for disconnected cells."
                )
            ),
            metadata={
                "water_mask_version": config.water_mask_version,
                "spatial_support_version": config.spatial_support_version,
                "summary": summary,
                "radius_operator_lineage": {
                    "path": str(config.radius_sum_operator_path),
                    "checksum": next(
                        item.checksum
                        for item in artifacts
                        if item.path == config.radius_sum_operator_path
                    ),
                    "radius_m": operator.radius_m,
                    "support_hash": operator.support_hash,
                    "source_support_hash": operator.source_support_hash,
                    "graph_checksum": operator.graph_checksum,
                },
            },
        )
        publisher.stage_manifest(config.manifest_path, payload)
        publisher.publish()
        destinations.append(config.manifest_path)
        LOGGER.info("Published canonical marine support manifest: %s", config.manifest_path)
        return tuple(destinations)
    finally:
        publisher.__exit__(None, None, None)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--resolution", action="append", type=int, dest="resolutions")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--run-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    outputs = build_marine_spatial_support(
        args.config,
        resolutions=tuple(args.resolutions) if args.resolutions else None,
        overwrite=args.overwrite,
        run_id=args.run_id,
    )
    print(json.dumps([str(path) for path in outputs], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
