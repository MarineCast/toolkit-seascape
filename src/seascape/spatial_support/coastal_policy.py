"""Explicit source-scale coastal-plus-inland reporting masks and native H3 membership."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import h3
import numpy as np
import shapely
from pyproj import CRS, Geod, Transformer
from shapely.geometry import LineString, Polygon, box, mapping
from shapely.ops import transform

GEOD = Geod(ellps="WGS84")
INLAND_TYPES = {"strait", "sound", "bay", "inlet", "estuary", "marine_channel"}
SOURCE_COLUMNS = {"SOURCE_ID", "SOURCE_VERSION", "RIGHTS"}


@dataclass(frozen=True)
class CoastalMask:
    geometry: Any
    report: dict[str, Any]


def _validate_frame(frame: gpd.GeoDataFrame, kinds: set[str], name: str) -> Any:
    if (
        not isinstance(frame, gpd.GeoDataFrame)
        or frame.crs is None
        or frame.crs.to_epsg() != 4326
    ):
        raise ValueError(f"{name} requires explicit EPSG:4326")
    if frame.empty or SOURCE_COLUMNS - set(frame):
        raise ValueError(f"{name} requires nonempty source-identified geometry")
    if (
        frame[list(SOURCE_COLUMNS)].isna().any().any()
        or frame[list(SOURCE_COLUMNS)]
        .astype(str)
        .apply(lambda s: s.str.strip().eq("").any())
        .any()
    ):
        raise ValueError(f"{name} requires source identity, version and rights")
    if (
        frame.geometry.isna().any()
        or frame.geometry.is_empty.any()
        or not frame.geometry.is_valid.all()
        or not frame.geometry.geom_type.isin(kinds).all()
    ):
        raise ValueError(f"{name} has invalid or unsupported geometry")
    bounds = frame.total_bounds
    if (
        not np.isfinite(bounds).all()
        or bounds[2] - bounds[0] > 30
        or bounds[3] - bounds[1] > 30
        or max(abs(bounds[1]), abs(bounds[3])) > 80
    ):
        raise ValueError(f"{name} must be finite regional non-polar geometry")
    return shapely.union_all(frame.geometry.to_numpy())


def _source_hash(frame: gpd.GeoDataFrame) -> str:
    columns = sorted(set(frame.columns) - {frame.geometry.name})
    records = [
        (tuple((c, str(row[c])) for c in columns), row.geometry.wkb_hex)
        for _, row in frame.iterrows()
    ]
    return hashlib.sha256(
        json.dumps(sorted(records), separators=(",", ":")).encode()
    ).hexdigest()


def _lines(geometry: Any) -> list[Any]:
    if geometry.geom_type in {"LineString", "LinearRing"}:
        return [LineString(geometry.coords)]
    return [line for part in geometry.geoms for line in _lines(part)]


def _polygons(geometry: Any) -> list[Any]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [polygon for part in geometry.geoms for polygon in _polygons(part)]
    return []


def geodesic_coastal_corridor(
    coast: Any,
    *,
    distance_m: float = 22224,
    tolerance_m: float = 5,
    max_vertices: int = 2_000_000,
) -> tuple[Any, dict[str, Any]]:
    """Construct and check an ellipsoidal corridor relative to source cartography."""
    if (
        not math.isfinite(distance_m)
        or not math.isfinite(tolerance_m)
        or distance_m <= 0
        or not 0 < tolerance_m <= 10
        or max_vertices < 1
    ):
        raise ValueError("Coastal distance, tolerance and resource bounds are invalid")
    west, south, east, north = coast.bounds
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={(south + north) / 2} +lon_0={(west + east) / 2} +datum=WGS84 +units=m"
    )
    to_metric = Transformer.from_crs(4326, crs, always_xy=True)
    to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
    source = transform(to_metric.transform, shapely.segmentize(coast, 0.001))
    chunks: list[Any] = []
    for line in _lines(source):
        coordinates = np.asarray(line.coords)
        chunks.extend(
            LineString(coordinates[i : min(i + 65, len(coordinates))])
            for i in range(0, len(coordinates) - 1, 64)
        )
    if not chunks or sum(shapely.get_num_coordinates(chunks)) > max_vertices:
        raise ValueError("Source coastline vertex bound exceeded or empty")
    chunks_array: Any = np.asarray(chunks, dtype=object)
    tree = shapely.STRtree(chunks_array)

    def nearest(coordinates: Any) -> tuple[Any, Any, Any, Any]:
        # A projected nearest coast can differ from the ellipsoidal nearest coast.
        # Evaluate all chunks within a conservative 500 m projection margin.
        results = []
        for offset in range(0, len(coordinates), 512):
            batch = coordinates[offset : offset + 512]
            points = shapely.points(batch)
            closest = tree.nearest(points)
            distance = shapely.distance(chunks_array[closest], points)
            pairs = tree.query(points, predicate="dwithin", distance=distance + 500)
            if pairs.shape[1] > 4_000_000:
                raise ValueError("Nearest-coast candidate pair bound exceeded")
            connectors = shapely.shortest_line(chunks_array[pairs[1]], points[pairs[0]])
            xy = shapely.get_coordinates(shapely.get_point(connectors, 0))
            lon, lat = to_geo.transform(xy[:, 0], xy[:, 1])
            target_lon, target_lat = to_geo.transform(
                batch[pairs[0], 0], batch[pairs[0], 1]
            )
            azimuth, _, ellipsoidal = GEOD.inv(lon, lat, target_lon, target_lat)
            order = np.lexsort((ellipsoidal, pairs[0]))
            _, positions = np.unique(pairs[0, order], return_index=True)
            chosen = order[positions]
            results.append(np.column_stack((lon, lat, azimuth, ellipsoidal))[chosen])
        joined = np.concatenate(results)
        return joined[:, 0], joined[:, 1], joined[:, 2], joined[:, 3]

    corridor = shapely.segmentize(
        source.buffer(distance_m + tolerance_m / 2, quad_segs=32), 250
    )
    if shapely.get_num_coordinates(corridor) > max_vertices:
        raise ValueError("Corridor vertex bound exceeded")
    repair_events = 0
    for _ in range(3):
        coordinates = shapely.get_coordinates(corridor)
        lon, lat, azimuth, _ = nearest(coordinates)
        xlon, ylat, _ = GEOD.fwd(
            lon, lat, azimuth, np.full(len(lon), distance_m + tolerance_m / 2)
        )
        x, y = to_metric.transform(xlon, ylat)
        corridor = shapely.set_coordinates(corridor, np.column_stack((x, y)))
        if not corridor.is_valid:
            corridor = shapely.union_all(_polygons(shapely.make_valid(corridor)))
            repair_events += 1
            if corridor.is_empty or not corridor.is_valid:
                raise ValueError("Corrected geodesic corridor has invalid topology")
    corridor = shapely.segmentize(corridor, 250)
    checks: list[Any] = []
    for ring in _lines(corridor.boundary):
        coords = np.asarray(ring.coords)
        checks.extend((coords, (coords[:-1] + coords[1:]) / 2))
    _, _, _, distances = nearest(np.concatenate(checks))
    minimum, maximum = float(distances.min()), float(distances.max())
    if minimum < distance_m - 1e-4 or maximum > distance_m + tolerance_m + 1e-4:
        raise ValueError(f"Geodesic corridor envelope failed: {minimum}, {maximum}")
    if not corridor.covers(source):
        raise ValueError("Corrected corridor does not cover its source coastline")
    return transform(to_geo.transform, corridor), {
        "method": "aeqd_initial_wgs84_ellipsoidal_vertex_corrected_v1",
        "distance_m": distance_m,
        "numerical_tolerance_m": tolerance_m,
        "maximum_boundary_edge_m": 250,
        "boundary_check_points": len(distances),
        "minimum_checked_geodesic_distance_m": minimum,
        "maximum_checked_geodesic_distance_m": maximum,
        "source_position_accuracy_established": False,
        "computational_buffer_topology_repairs": repair_events,
        "topology_repair_scope": "Constructed buffer only; source coastline unchanged; final geodesic envelope rechecked",
    }


def build_coastal_mask(
    coastline: gpd.GeoDataFrame,
    marine_water: gpd.GeoDataFrame,
    inland_water: gpd.GeoDataFrame,
    source_context: gpd.GeoDataFrame,
    *,
    distance_m: float = 22224,
    tolerance_m: float = 5,
    max_vertices: int = 2_000_000,
) -> CoastalMask:
    coast = _validate_frame(coastline, {"LineString", "MultiLineString"}, "Coastline")
    marine = _validate_frame(marine_water, {"Polygon", "MultiPolygon"}, "Marine water")
    inland = _validate_frame(inland_water, {"Polygon", "MultiPolygon"}, "Inland water")
    context = _validate_frame(
        source_context, {"Polygon", "MultiPolygon"}, "Source context"
    )
    if (
        "WATERBODY_TYPE" not in inland_water
        or not inland_water.WATERBODY_TYPE.isin(INLAND_TYPES).all()
        or "WATERBODY_ID" not in inland_water
        or inland_water.WATERBODY_ID.isna().any()
        or inland_water.WATERBODY_ID.duplicated().any()
    ):
        raise ValueError(
            "Inland water requires unique IDs and explicit marine waterbody types"
        )
    corridor, report = geodesic_coastal_corridor(
        coast, distance_m=distance_m, tolerance_m=tolerance_m, max_vertices=max_vertices
    )
    if not context.covers(corridor) or not context.covers(inland):
        raise ValueError("Source context truncates requested coastal/inland geometry")
    result = shapely.intersection(shapely.union_all([corridor, inland]), marine)
    if (
        result.is_empty
        or not result.is_valid
        or result.geom_type not in {"Polygon", "MultiPolygon"}
    ):
        raise ValueError("Coastal-plus-inland mask is empty or invalid")
    sources = {
        name: _source_hash(frame)
        for name, frame in (
            ("coastline", coastline),
            ("marine_water", marine_water),
            ("inland_water", inland_water),
            ("context", source_context),
        )
    }
    return CoastalMask(
        result,
        {
            **report,
            "source_hashes": sources,
            "mask_geometry_sha256": hashlib.sha256(result.wkb).hexdigest(),
            "inland_waterbody_ids": sorted(inland_water.WATERBODY_ID.astype(str)),
            "membership": "positive_area_intersection",
            "crs": "EPSG:4326",
            "acquisition_bbox_used_as_reporting_selector": False,
            "source_temporal_support": "static_cartographic_reference_not_historical_water_levels",
            "physical_full_catalog_qualified": False,
        },
    )


def native_mask_membership(
    mask: CoastalMask, resolution: int, *, max_cells: int = 1_000_000
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return exact positive polygon-area members; do not threshold water fraction."""
    if not 0 <= resolution <= 15 or max_cells < 1:
        raise ValueError("Invalid native resolution or cell bound")
    west, south, east, north = mask.geometry.bounds
    boxes = [
        box(x, y, x + 0.5, y + 0.5)
        for x in np.arange(math.floor(west * 2) / 2, east, 0.5)
        for y in np.arange(math.floor(south * 2) / 2, north, 0.5)
    ]
    if len(boxes) > 10000:
        raise ValueError("Native mask tile bound exceeded")
    shapely.prepare(mask.geometry)
    pieces = [
        part
        for tile in boxes
        if mask.geometry.intersects(tile)
        for part in _polygons(mask.geometry.intersection(tile))
    ]
    candidate_set: set[str] = set()
    for part in pieces:
        candidate_set.update(
            h3.h3shape_to_cells_experimental(
                h3.geo_to_h3shape(mapping(part)), resolution, contain="bbox_overlap"
            )
        )
        if len(candidate_set) > max_cells:
            raise ValueError("Native mask cell bound exceeded")
    candidates = sorted(candidate_set)
    full = gpd.GeoDataFrame(
        {"H3_INDEX": candidates, "H3_RESOLUTION": resolution},
        geometry=[
            Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(key)])
            for key in candidates
        ],
        crs=4326,
    )
    clipped = full.copy()
    tree = shapely.STRtree(pieces)
    to_area = Transformer.from_crs(4326, 6933, always_xy=True).transform
    projected_pieces = [
        transform(to_area, shapely.segmentize(g, 0.001)) for g in pieces
    ]
    projected_cells = [
        transform(to_area, shapely.segmentize(g, 0.001)) for g in full.geometry
    ]
    intersections = []
    areas = []
    for cell, projected in zip(full.geometry, projected_cells, strict=True):
        indexes = tree.query(cell, predicate="intersects")
        local = shapely.union_all([projected_pieces[int(i)] for i in indexes])
        intersection = shapely.union_all(_polygons(projected.intersection(local)))
        areas.append(intersection.area)
        intersections.append(intersection)
    full = full.set_geometry(gpd.GeoSeries(projected_cells, index=full.index, crs=6933))
    clipped = clipped.set_geometry(
        gpd.GeoSeries(intersections, index=clipped.index, crs=6933)
    )
    area = np.asarray(areas)
    keep = area > 0
    full = full.loc[keep].reset_index(drop=True)
    clipped = clipped.loc[keep].reset_index(drop=True)
    full_area = shapely.area(projected_cells)[keep]
    if np.any(area[keep] > full_area * (1 + 1e-8) + 0.001):
        raise ValueError("Native water area exceeds full cell support")
    for frame in (full, clipped):
        frame["WATER_AREA_M2"] = area[keep]
        frame["FULL_CELL_AREA_M2"] = full_area
        frame["WATER_FRACTION"] = area[keep] / full_area
        frame["MASK_SHA256"] = mask.report["mask_geometry_sha256"]
        frame["MEMBERSHIP_METHOD"] = "positive_polygon_area_epsg6933_no_fraction_cutoff"
    return full, clipped
