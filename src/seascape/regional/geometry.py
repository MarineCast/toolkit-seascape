"""Validated full native cells and source-relative representative points."""

import geopandas as gpd
import h3
import numpy as np
import shapely

from .contract import RegionalError
from .projection import qualify_projected_geometries
from .subdivision import subdivide_water


def cells(keys):
    return gpd.GeoDataFrame(
        {"H3_INDEX": keys},
        geometry=[
            shapely.Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(k)])
            for k in keys
        ],
        crs=4326,
    )


def points(job, keys):
    frame = (
        job.table("support").to_pandas().set_index("H3_INDEX", verify_integrity=True)
    )
    if not set(keys) <= set(frame.index):
        raise RegionalError("Support misses reporting cells")
    frame = frame.loc[keys].reset_index()
    for field in ("HAS_WATER_OVERLAP",):
        if field not in frame or not frame[field].eq(True).all():
            raise RegionalError("Representative points require positive water overlap")
    if (
        "IS_HIERARCHY_ONLY_PARENT" not in frame
        or frame.IS_HIERARCHY_ONLY_PARENT.ne(False).any()
    ):
        raise RegionalError("Hierarchy-only points cannot be used")
    lon = frame.REPRESENTATIVE_POINT_LONGITUDE.to_numpy(dtype=float)
    lat = frame.REPRESENTATIVE_POINT_LATITUDE.to_numpy(dtype=float)
    if (
        not np.isfinite(lon).all()
        or not np.isfinite(lat).all()
        or not all(
            g.covers(shapely.Point(x, y))
            for g, x, y in zip(cells(keys).geometry, lon, lat, strict=True)
        )
    ):
        raise RegionalError(
            "Representative point must be finite and inside focal H3 cell"
        )
    return frame


def inventory(job, name="inventory", *, allow_invalid=False, layer=None):
    path = job.source(name)
    if path.suffix == ".parquet":
        frame = gpd.read_parquet(path)
    else:
        frame = gpd.read_file(
            path,
            layer=layer if layer is not None else job.settings.get(name + "_layer"),
        )
    if (
        frame.crs is None
        or frame.empty
        or frame.geometry.isna().any()
        or frame.geometry.is_empty.any()
        or (not allow_invalid and not frame.geometry.is_valid.all())
    ):
        raise RegionalError(f"Invalid, empty or unregistered native geometry: {name}")
    return frame


def projected(job, name="inventory", crs=6933, subdivide=False):
    native = inventory(job, name)
    plane = native.to_crs(crs)
    values, evidence = qualify_projected_geometries(
        native.geometry.to_numpy(), plane.geometry.to_numpy()
    )
    plane = plane.set_geometry(values)
    if subdivide:
        values, closure = subdivide_water(values, job.guard)
        return np.asarray(values, dtype=object), {
            "projection": evidence,
            "subdivision": closure,
        }
    return plane, {"projection": evidence}
