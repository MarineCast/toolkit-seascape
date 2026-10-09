"""Exact local water-piece unions for bounded calls to unchanged science primitives."""

from collections import OrderedDict, defaultdict
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import shapely
from shapely.geometry import box
from shapely.prepared import prep

from seascape.core.geo.h3 import cell_to_polygon
from seascape.spatial_support.water_network.build import (
    _build_geometry_and_base_support,
    _tiled_water_parts,
)
from seascape.spatial_support.water_network.geometry import (
    _densified_geodesic_line,
    water_path_metrics,
)


class LocalSourceWater:
    def __init__(self, path: Path, check=lambda: None):
        frame = gpd.read_file(path, layer="water_area")
        if not frame.crs.to_epsg() == 4326:
            raise ValueError("Scientific validation failed")
        self.parts = []
        for piece in frame.geometry:
            self.parts.extend(_tiled_water_parts(piece, tile_size_degrees=0.5))
            check()
        self.parts = np.asarray(self.parts, dtype=object)
        self.tree = shapely.STRtree(self.parts)
        self.cache = OrderedDict()
        self.check = check

    def local_water(self, bounds):
        west, south, east, north = bounds
        envelope = box(west - 1e-07, south - 1e-07, east + 1e-07, north + 1e-07)
        indexes = tuple(
            sorted((int(i) for i in self.tree.query(envelope, predicate="intersects")))
        )
        if not indexes:
            return (shapely.GeometryCollection(), None)
        cached = self.cache.get(indexes)
        if cached is None:
            water = (
                self.parts[indexes[0]]
                if len(indexes) == 1
                else shapely.union_all(self.parts[list(indexes)])
            )
            cached = (water, prep(shapely.from_wkb(water.wkb)))
            self.cache[indexes] = cached
            if len(self.cache) > 16:
                self.cache.popitem(last=False)
            self.check()
        else:
            self.cache.move_to_end(indexes)
        return cached

    def path_metrics(self, source_lon, source_lat, target_lon, target_lat):
        line, _ = _densified_geodesic_line(
            source_lon, source_lat, target_lon, target_lat, 100
        )
        water, prepared = self.local_water(line.bounds)
        return water_path_metrics(
            source_lon,
            source_lat,
            target_lon,
            target_lat,
            water,
            maximum_segment_m=100,
            outside_tolerance_m=1,
            prepared_water=prepared,
        )

    def geometry_batches(self, cells, resolution, config, aoi, batch_size=256):
        groups = defaultdict(list)
        for cell in cells:
            latitude, longitude = h3.cell_to_latlng(cell)
            groups[int(np.floor(longitude * 4)), int(np.floor(latitude * 4))].append(
                cell
            )
        for tile in sorted(groups):
            values = sorted(groups[tile])
            for first in range(0, len(values), batch_size):
                selected = values[first : first + batch_size]
                polygons = [cell_to_polygon(cell) for cell in selected]
                water, _ = self.local_water(shapely.total_bounds(polygons))
                if water.is_empty:
                    continue
                wet = [
                    cell
                    for cell, polygon in zip(selected, polygons, strict=True)
                    if polygon.intersection(water).area > 0
                ]
                if not wet:
                    continue
                yield _build_geometry_and_base_support(
                    water, aoi, resolution, config, cells=wet
                )
                self.check()
