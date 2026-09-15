"""Geometry-only operations for territorial-water source assembly."""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.ops import linemerge, polygonize, snap, unary_union


def line_to_polygon_if_closed(geometry: Any):
    """Convert a closed LineString to a Polygon and preserve other geometry."""

    if isinstance(geometry, LineString) and geometry.is_ring:
        return Polygon(geometry)
    return geometry


def clean_connected_lines(
    frame: gpd.GeoDataFrame,
    tolerance: float = 0.0001,
    *,
    drop_polygons: bool = True,
    find_polygons: bool = True,
) -> gpd.GeoDataFrame:
    """Snap and merge linework while optionally removing discovered rings."""

    merged = linemerge(snap(unary_union(frame.geometry), unary_union(frame.geometry), tolerance))
    if merged.geom_type == "LineString":
        geometries = [merged]
    elif merged.geom_type == "MultiLineString":
        geometries = list(merged.geoms)
    else:
        raise ValueError("Unexpected geometry type after line merge.")
    result = gpd.GeoDataFrame(geometry=geometries, crs=frame.crs)
    if find_polygons:
        result["geometry"] = result.geometry.map(line_to_polygon_if_closed)
        if drop_polygons:
            result = result.loc[result.geom_type.ne("Polygon")]
    return result.reset_index(drop=True)


def round_geometry_coordinates(geometry: Any, precision: int = 4):
    """Round coordinates for supported Shapely geometry types."""

    if geometry.is_empty:
        return geometry

    def rounded(coordinates: Any) -> list[tuple[float, ...]]:
        return [
            tuple(round(value, precision) for value in coordinate) for coordinate in coordinates
        ]

    if geometry.geom_type == "Point":
        return Point(*rounded([geometry.coords[0]])[0])
    if geometry.geom_type == "LineString":
        return LineString(rounded(geometry.coords))
    if geometry.geom_type == "Polygon":
        return Polygon(
            rounded(geometry.exterior.coords),
            [rounded(ring.coords) for ring in geometry.interiors],
        )
    if geometry.geom_type == "MultiPoint":
        return MultiPoint(
            [Point(*value) for value in rounded([p.coords[0] for p in geometry.geoms])]
        )
    if geometry.geom_type == "MultiLineString":
        return MultiLineString([LineString(rounded(part.coords)) for part in geometry.geoms])
    if geometry.geom_type == "MultiPolygon":
        return MultiPolygon(
            [
                Polygon(
                    rounded(part.exterior.coords),
                    [rounded(ring.coords) for ring in part.interiors],
                )
                for part in geometry.geoms
            ]
        )
    raise ValueError(f"Geometry type {geometry.geom_type} not supported.")


def extract_endpoints(line: LineString) -> tuple[Point, Point]:
    coordinates = list(line.coords)
    return Point(coordinates[0]), Point(coordinates[-1])


def round_point(point: Point, decimals: int = 4) -> Point:
    return Point(round(point.x, decimals), round(point.y, decimals))


def connect_lines_by_endpoints(
    frame: gpd.GeoDataFrame,
    endpoint_column: str = "endpoints",
    tolerance: float = 0.0001,
) -> gpd.GeoDataFrame:
    """Merge line components whose endpoints fall within a configured tolerance."""

    records = [
        (index, point.x, point.y)
        for index, endpoints in frame[endpoint_column].items()
        for point in endpoints
    ]
    points = pd.DataFrame(records, columns=["line_index", "x", "y"])
    graph = nx.Graph()
    graph.add_nodes_from(frame.index)
    for left, right in cKDTree(points[["x", "y"]].to_numpy()).query_pairs(r=tolerance):
        left_index = points.loc[left, "line_index"]
        right_index = points.loc[right, "line_index"]
        if left_index != right_index:
            graph.add_edge(left_index, right_index)
    merged_lines = []
    for component in nx.connected_components(graph):
        merged = linemerge(unary_union(frame.loc[list(component), "geometry"]))
        merged_lines.extend(merged.geoms if merged.geom_type == "MultiLineString" else [merged])
    return gpd.GeoDataFrame(geometry=merged_lines, crs=frame.crs).reset_index(drop=True)


def smooth_coastline(frame: gpd.GeoDataFrame, tolerance: float = 0.001) -> gpd.GeoDataFrame:
    """Round, connect, and measure coastline components deterministically."""

    result = frame.copy()
    result["geometry"] = result.geometry.map(
        lambda geometry: round_geometry_coordinates(geometry, precision=5)
    )
    result = result.explode(index_parts=False).dissolve()
    result["geometry"] = linemerge(unary_union(result.geometry))
    result = result.explode(index_parts=False)
    result["endpoints"] = result.geometry.map(extract_endpoints).map(
        lambda endpoints: tuple(round_point(point) for point in endpoints)
    )
    result = connect_lines_by_endpoints(result, tolerance=tolerance)
    result = result.dissolve().explode(index_parts=False).reset_index(drop=True)
    projected = result.to_crs("EPSG:5070")
    projected["length"] = projected.length
    return projected.to_crs("EPSG:4326")


def closed_lines(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a copy of closed LineStrings."""

    return frame.loc[frame.geometry.map(lambda geometry: geometry.is_ring)].copy()


def connect_lines_to_polygon(line1: LineString, line2: LineString, tolerance: float = 1e-9):
    """Connect two oriented lines when one orientation forms a closed ring."""

    first = list(line1.coords)
    second = list(line2.coords)
    options = (
        first + second[1:],
        first + second[::-1][1:],
        second + first[1:],
        second[::-1] + first[1:],
    )
    for coordinates in options:
        if Point(coordinates[0]).distance(Point(coordinates[-1])) < tolerance:
            return Polygon(coordinates)
    raise ValueError("Cannot connect lines into a closed polygon.")


def linestrings_to_polygons_if_closed(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = frame.copy()
    result["geometry"] = result.geometry.map(line_to_polygon_if_closed)
    return result


def close_linestring_as_polygon(line: LineString, tolerance: float = 1e-9) -> Polygon:
    coordinates = list(line.coords)
    if Point(coordinates[0]).distance(Point(coordinates[-1])) > tolerance:
        coordinates.append(coordinates[0])
    return Polygon(coordinates)


def polygonize_boundary_cycle(
    lines: gpd.GeoDataFrame,
    *,
    snap_tolerance_m: float,
    projected_crs: str = "EPSG:3338",
) -> Polygon:
    """Build the dominant closed boundary cycle without source row-order dependence."""

    if lines.empty or lines.crs is None:
        raise ValueError("Boundary linework must be nonempty and have a CRS.")
    if snap_tolerance_m <= 0:
        raise ValueError("Boundary snap tolerance must be positive.")
    projected = lines.to_crs(projected_crs).explode(index_parts=False).reset_index(drop=True)
    projected = projected.loc[
        projected.geometry.notna()
        & ~projected.geometry.is_empty
        & projected.geom_type.eq("LineString")
    ].copy()
    if projected.empty:
        raise ValueError("Boundary linework has no nonempty LineString geometry.")
    endpoints = [
        Point(coordinate)
        for geometry in projected.geometry
        for coordinate in (geometry.coords[0], geometry.coords[-1])
    ]
    coordinates = [(point.x, point.y) for point in endpoints]
    parent = list(range(len(endpoints)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left, right in cKDTree(coordinates).query_pairs(r=snap_tolerance_m):
        union(int(left), int(right))
    clusters: dict[int, list[int]] = {}
    for index in range(len(endpoints)):
        clusters.setdefault(find(index), []).append(index)
    cluster_point = {
        root: tuple(np.mean([coordinates[index] for index in members], axis=0))
        for root, members in clusters.items()
    }
    graph = nx.MultiGraph()
    for line_index, geometry in enumerate(projected.geometry):
        source_root, target_root = find(2 * line_index), find(2 * line_index + 1)
        if source_root != target_root:
            graph.add_edge(
                source_root,
                target_root,
                key=line_index,
                line_index=line_index,
                length_m=float(geometry.length),
            )
    if graph.number_of_edges() == 0:
        raise ValueError("Boundary linework has no connectable endpoint graph.")
    core = graph.copy()
    queue = [node for node, degree in core.degree() if degree < 2]
    while queue:
        node = queue.pop()
        if node not in core or core.degree(node) >= 2:
            continue
        neighbors = list(core.neighbors(node))
        core.remove_node(node)
        queue.extend(neighbor for neighbor in neighbors if neighbor in core)
    if core.number_of_edges() == 0:
        raise ValueError(
            "Boundary endpoint graph has no closed cycle within the configured tolerance."
        )
    scored = sorted(
        (
            (
                sum(
                    float(data["length_m"])
                    for left, right, data in core.edges(data=True)
                    if left in nodes and right in nodes
                ),
                min(nodes),
                nodes,
            )
            for nodes in nx.connected_components(nx.Graph(core))
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if len(scored) > 1 and scored[1][0] >= scored[0][0] * 0.5:
        raise ValueError("Boundary linework produced multiple comparable closed cycles.")
    component = scored[0][2]
    selected = sorted(
        int(data["line_index"])
        for left, right, data in core.edges(data=True)
        if left in component and right in component
    )
    snapped_lines = []
    for line_index in selected:
        line_coordinates = list(projected.geometry.iloc[line_index].coords)
        line_coordinates[0] = cluster_point[find(2 * line_index)]
        line_coordinates[-1] = cluster_point[find(2 * line_index + 1)]
        snapped_lines.append(LineString(line_coordinates))
    candidates = [
        candidate for candidate in polygonize(unary_union(snapped_lines)) if candidate.is_valid
    ]
    if not candidates:
        raise ValueError("Closed boundary graph could not be polygonized.")
    candidates.sort(key=lambda candidate: (-candidate.area, candidate.bounds, candidate.wkb_hex))
    if len(candidates) > 1 and candidates[1].area >= candidates[0].area * 0.5:
        raise ValueError("Boundary linework produced multiple comparable polygons.")
    polygon = gpd.GeoSeries([candidates[0]], crs=projected_crs).to_crs(lines.crs).iloc[0]
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError("Polygonized boundary is empty or invalid after reprojection.")
    return polygon


__all__ = [
    "clean_connected_lines",
    "close_linestring_as_polygon",
    "closed_lines",
    "connect_lines_by_endpoints",
    "connect_lines_to_polygon",
    "extract_endpoints",
    "linestrings_to_polygons_if_closed",
    "polygonize_boundary_cycle",
    "round_geometry_coordinates",
    "round_point",
    "smooth_coastline",
]
