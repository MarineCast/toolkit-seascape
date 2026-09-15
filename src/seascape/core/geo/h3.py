from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, box, mapping


def _load_h3() -> Any:
    try:
        import h3  # type: ignore
    except Exception as e:
        raise ImportError("Install h3-py (pip install h3) to use H3 operations.") from e
    return h3


def cell_to_parent(cell: str, parent_res: int) -> str:
    h3 = _load_h3()
    if hasattr(h3, "cell_to_parent"):
        return str(h3.cell_to_parent(str(cell), int(parent_res)))
    if hasattr(h3, "h3_to_parent"):
        return str(h3.h3_to_parent(str(cell), int(parent_res)))
    raise ImportError("Unknown h3 API: expected cell_to_parent or h3_to_parent")


def cell_to_children(cell: str, child_res: int) -> list[str]:
    h3 = _load_h3()
    if hasattr(h3, "cell_to_children"):
        return [str(x) for x in h3.cell_to_children(str(cell), int(child_res))]
    if hasattr(h3, "h3_to_children"):
        return [str(x) for x in h3.h3_to_children(str(cell), int(child_res))]
    raise ImportError("Unknown h3 API: expected cell_to_children or h3_to_children")


def cell_to_boundary(cell: str) -> list[tuple[float, float]]:
    h3 = _load_h3()
    if hasattr(h3, "cell_to_boundary"):
        boundary = h3.cell_to_boundary(str(cell))
    elif hasattr(h3, "h3_to_geo_boundary"):
        boundary = h3.h3_to_geo_boundary(str(cell))
    else:
        raise ImportError("Unknown h3 API: expected cell_to_boundary or h3_to_geo_boundary")
    return [(float(lat), float(lng)) for lat, lng in boundary]


def cell_to_polygon(cell: str) -> Polygon:
    """Convert an H3 cell to a WGS84 Shapely polygon."""
    latlon = cell_to_boundary(str(cell))
    return Polygon([(lng, lat) for lat, lng in latlon])


def cell_to_latlng(cell: str) -> tuple[float, float]:
    h3 = _load_h3()
    if hasattr(h3, "cell_to_latlng"):
        lat, lng = h3.cell_to_latlng(str(cell))
        return float(lat), float(lng)
    if hasattr(h3, "h3_to_geo"):
        lat, lng = h3.h3_to_geo(str(cell))
        return float(lat), float(lng)
    raise ImportError("Unknown h3 API: expected cell_to_latlng or h3_to_geo")


def get_resolution(cell: str) -> int:
    h3 = _load_h3()
    if hasattr(h3, "get_resolution"):
        return int(h3.get_resolution(str(cell)))
    if hasattr(h3, "h3_get_resolution"):
        return int(h3.h3_get_resolution(str(cell)))
    raise ImportError("Unknown h3 API: expected get_resolution or h3_get_resolution")


def grid_disk(cell: str, k_ring: int) -> list[str]:
    h3 = _load_h3()
    if hasattr(h3, "grid_disk"):
        return [str(x) for x in h3.grid_disk(str(cell), int(k_ring))]
    if hasattr(h3, "k_ring"):
        return [str(x) for x in h3.k_ring(str(cell), int(k_ring))]
    raise ImportError("Unknown h3 API: expected grid_disk or k_ring")


def grid_disk_set(cell: str, k_ring: int) -> set[str]:
    return set(grid_disk(cell, k_ring))


def grid_disk_distances(cell: str, k_ring: int) -> dict[int, list[str]]:
    h3 = _load_h3()
    if hasattr(h3, "grid_disk_distances"):
        rings = h3.grid_disk_distances(str(cell), int(k_ring))
        return {int(d): [str(x) for x in rings[d]] for d in range(len(rings))}
    if hasattr(h3, "k_ring_distances"):
        dd = h3.k_ring_distances(str(cell), int(k_ring))
        return {int(d): [str(x) for x in vals] for d, vals in dd.items()}
    if hasattr(h3, "grid_ring"):
        return {0: [str(cell)]} | {
            int(d): [str(x) for x in h3.grid_ring(str(cell), int(d))]
            for d in range(1, int(k_ring) + 1)
        }
    if hasattr(h3, "hex_ring"):
        return {0: [str(cell)]} | {
            int(d): [str(x) for x in h3.hex_ring(str(cell), int(d))]
            for d in range(1, int(k_ring) + 1)
        }

    out: dict[int, list[str]] = {0: [str(cell)]}
    prev_disk = {str(cell)}
    for d in range(1, int(k_ring) + 1):
        cur_disk = set(grid_disk(str(cell), int(d)))
        out[int(d)] = list(cur_disk - prev_disk)
        prev_disk = cur_disk
    return out


def latlng_to_cell(lat: float, lng: float, resolution: int) -> str:
    h3 = _load_h3()
    if hasattr(h3, "latlng_to_cell"):
        return str(h3.latlng_to_cell(float(lat), float(lng), int(resolution)))
    if hasattr(h3, "geo_to_h3"):
        return str(h3.geo_to_h3(float(lat), float(lng), int(resolution)))
    raise ImportError("Unknown h3 API: expected latlng_to_cell or geo_to_h3")


def h3_cells_within_distance(
    lat: float,
    lon: float,
    resolution: int,
    distance_km: float,
    *,
    max_cells: int | None = None,
) -> list[str]:
    """Return H3 cells whose centers are within a geodesic radius.

    Results are ordered nearest-first, with the H3 index used as a stable
    tie-breaker. Cell-center inclusion is intentional: a cell whose polygon
    merely touches the radius is not included unless its center is also within
    ``distance_km``.
    """

    latitude = float(lat)
    longitude = float(lon)
    h3_resolution = int(resolution)
    radius_km = float(distance_km)
    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"Latitude must be between -90 and 90 degrees; got {lat!r}.")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError(f"Longitude must be between -180 and 180 degrees; got {lon!r}.")
    if not 0 <= h3_resolution <= 15:
        raise ValueError(f"H3 resolution must be between 0 and 15; got {resolution!r}.")
    if not math.isfinite(radius_km) or radius_km < 0.0:
        raise ValueError(f"distance_km must be a finite non-negative value; got {distance_km!r}.")
    if max_cells is not None and int(max_cells) < 0:
        raise ValueError(f"max_cells must be non-negative when provided; got {max_cells!r}.")

    h3 = _load_h3()
    if hasattr(h3, "average_hexagon_edge_length"):
        edge_km = float(h3.average_hexagon_edge_length(h3_resolution, unit="km"))
    elif hasattr(h3, "edge_length"):
        edge_km = float(h3.edge_length(h3_resolution, unit="km"))
    else:
        raise ImportError("Unknown h3 API: expected average_hexagon_edge_length or edge_length")

    try:
        from pyproj import Geod
    except Exception as exc:
        raise ImportError("Install pyproj to select H3 cells by geodesic distance.") from exc

    center_cell = latlng_to_cell(latitude, longitude, h3_resolution)
    candidate_k = int(math.ceil(radius_km / edge_km)) + 2
    candidates = grid_disk(center_cell, candidate_k)
    geod = Geod(ellps="WGS84")
    maximum_distance_m = radius_km * 1_000.0
    cells_and_distances: list[tuple[float, str]] = []
    for cell in candidates:
        cell_lat, cell_lon = cell_to_latlng(cell)
        _, _, distance_m = geod.inv(longitude, latitude, cell_lon, cell_lat)
        if float(distance_m) <= maximum_distance_m + 1e-6:
            cells_and_distances.append((float(distance_m), str(cell)))

    cells_and_distances.sort(key=lambda item: (item[0], item[1]))
    if max_cells is not None:
        cells_and_distances = cells_and_distances[: int(max_cells)]
    return [cell for _, cell in cells_and_distances]


def polygon_to_cells(geometry: Any, resolution: int) -> set[str]:
    """Return cells covering a polygon across h3-py v3/v4 APIs."""
    h3 = _load_h3()
    if hasattr(geometry, "geoms") and geometry.geom_type == "MultiPolygon":
        cells: set[str] = set()
        for part in geometry.geoms:
            cells.update(polygon_to_cells(part, resolution))
        return cells

    if hasattr(h3, "geo_to_cells"):
        try:
            return {str(x) for x in h3.geo_to_cells(geometry, int(resolution))}
        except TypeError:
            return {str(x) for x in h3.geo_to_cells(geometry.__geo_interface__, int(resolution))}

    geojson = mapping(geometry)
    if hasattr(h3, "polyfill_geojson"):
        return {str(x) for x in h3.polyfill_geojson(geojson, int(resolution))}
    if hasattr(h3, "polyfill"):
        return {
            str(x)
            for x in h3.polyfill(
                geojson,
                int(resolution),
                geo_json_conformant=True,
            )
        }
    raise ImportError("Unknown h3 API: expected geo_to_cells or polyfill")


def polygon_to_cells_overlap(geometry: Polygon | MultiPolygon, resolution: int) -> set[str]:
    """Return cells overlapping a polygon using h3-py v4 when available.

    Falls back to center-contained polygon fill for older h3-py versions.
    """
    h3 = _load_h3()
    if not hasattr(h3, "polygon_to_cells_experimental"):
        return polygon_to_cells(geometry, resolution)

    # H3's experimental overlap fill can become pathologically slow when a large
    # MultiPolygon is converted to one LatLngMultiPoly.  Components are independent
    # for overlap membership, so fill them separately and union the deterministic
    # cell sets.  Polygon holes remain attached to their containing component.
    if isinstance(geometry, MultiPolygon):
        cells: set[str] = set()
        for part in geometry.geoms:
            if not part.is_empty:
                cells.update(polygon_to_cells_overlap(part, resolution))
        return cells

    vertex_count = len(geometry.exterior.coords) + sum(
        len(interior.coords) for interior in geometry.interiors
    )
    min_x, min_y, max_x, max_y = geometry.bounds
    if vertex_count > 5_000 and max(max_x - min_x, max_y - min_y) > 1.0:
        tile_size = 0.5
        seam_overlap = 1e-9
        x_value = math.floor(min_x / tile_size) * tile_size
        cells: set[str] = set()
        while x_value <= max_x:
            y_value = math.floor(min_y / tile_size) * tile_size
            while y_value <= max_y:
                tile = box(
                    x_value - seam_overlap,
                    y_value - seam_overlap,
                    x_value + tile_size + seam_overlap,
                    y_value + tile_size + seam_overlap,
                )
                if geometry.intersects(tile):
                    clipped = geometry.intersection(tile)
                    if isinstance(clipped, Polygon) and not clipped.is_empty:
                        cells.update(polygon_to_cells_overlap(clipped, resolution))
                    elif hasattr(clipped, "geoms"):
                        for part in clipped.geoms:
                            if isinstance(part, Polygon) and not part.is_empty:
                                cells.update(polygon_to_cells_overlap(part, resolution))
                y_value += tile_size
            x_value += tile_size
        return cells

    h3_shape = geom_to_h3shape(geometry)
    return {
        str(x)
        for x in h3.polygon_to_cells_experimental(
            h3_shape,
            int(resolution),
            contain="overlap",
        )
    }


def ring_to_latlng_coords(ring: Any) -> list[tuple[float, float]]:
    coords = list(ring.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 3:
        return []
    return [(lat, lon) for lon, lat in coords]


def polygon_to_h3shape(poly: Polygon) -> Any:
    h3 = _load_h3()
    outer = ring_to_latlng_coords(poly.exterior)
    holes = []
    for interior in poly.interiors:
        hole_coords = ring_to_latlng_coords(interior)
        if hole_coords:
            holes.append(hole_coords)
    if not outer:
        raise ValueError("Polygon provided to H3 shape conversion has too few vertices.")
    if not hasattr(h3, "LatLngPoly"):
        raise ImportError("h3-py version does not expose LatLngPoly.")
    return h3.LatLngPoly(outer, *holes)


def geom_to_h3shape(geom: Polygon | MultiPolygon) -> Any:
    h3 = _load_h3()
    if isinstance(geom, Polygon):
        return polygon_to_h3shape(geom)
    polys = []
    for poly in geom.geoms:
        if poly is not None and not poly.is_empty:
            polys.append(polygon_to_h3shape(poly))
    if not polys:
        raise ValueError("Geometry yielded no polygons.")
    if len(polys) == 1:
        return polys[0]
    if not hasattr(h3, "LatLngMultiPoly"):
        raise ImportError("h3-py version does not expose LatLngMultiPoly.")
    return h3.LatLngMultiPoly(*polys)


def polygonize_h3_indices(
    indices: list[str],
    *,
    h3_col: str = "h3_index",
    parallel: str = "thread",
    max_workers: int | None = None,
) -> Any:
    """Turn H3 cells into an EPSG:4326 GeoDataFrame of polygons."""
    import geopandas as gpd

    if not indices:
        return gpd.GeoDataFrame({h3_col: []}, geometry=[], crs="EPSG:4326")
    if parallel == "thread":
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            geoms = list(ex.map(cell_to_polygon, indices))
    elif parallel == "off":
        geoms = [cell_to_polygon(h) for h in indices]
    else:
        raise ValueError(f"Unknown parallel mode: {parallel}")
    return gpd.GeoDataFrame({h3_col: indices}, geometry=geoms, crs="EPSG:4326")


def bbox_h3_cells(
    bbox_wgs84: tuple[float, float, float, float],
    resolution: int,
    *,
    buffer_rings: int = 1,
    strict_intersection: bool = True,
) -> list[str]:
    bbox_polygon = box(*bbox_wgs84)
    base_cells = polygon_to_cells(bbox_polygon, int(resolution))

    cells = set(base_cells)
    if buffer_rings > 0:
        for cell in list(base_cells):
            cells.update(grid_disk(cell, int(buffer_rings)))

    if strict_intersection:
        cells = {cell for cell in cells if cell_to_polygon(cell).intersects(bbox_polygon)}

    if not cells:
        raise ValueError(f"No H3 cells generated for bbox={bbox_wgs84} at resolution={resolution}.")

    return sorted(cells)


to_parent = cell_to_parent
to_children = cell_to_children
to_boundary = cell_to_boundary
to_latlng = cell_to_latlng
to_polygon = cell_to_polygon
