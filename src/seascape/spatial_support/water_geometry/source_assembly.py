"""Source-specific assembly for canonical territorial-water geometry."""

from __future__ import annotations

from typing import Any

import geopandas as gpd
from shapely.geometry import box


def build_us_waters_boundary(us_waters: Any):
    """Select and clip the configured U.S. Pacific territorial-water boundary."""

    selected = us_waters[
        (us_waters.REGION.isin(["Alaska", "US-Canada", "Pacific Coast"]))
        & (
            (us_waters.TS == 1)
            | (us_waters.REGION == "US-Canada")
            | us_waters.NOTE.astype(str).str.contains("Georgia")
        )
    ][["geometry"]].dissolve()
    bounds = selected.total_bounds
    clip = gpd.GeoDataFrame(
        geometry=[box(bounds[0], bounds[1], -116.5, bounds[3])],
        crs=selected.crs,
    )
    return gpd.overlay(selected, clip, how="intersection")


def build_us_coastline(us_coastline: Any):
    """Select and dissolve the configured Census Pacific coastline."""

    return (
        us_coastline[(us_coastline.NAME == "Pacific") & (us_coastline.MTFCC == "L4150")]
        .set_crs(4326, allow_override=True)[["geometry"]]
        .dissolve()
    )


def clip_us_water_lines(us_waters_line: Any, area_zone: str):
    """Clip Pacific boundary linework to contiguous-U.S. or Alaska context."""

    bounds = us_waters_line.total_bounds
    if area_zone == "CONTIGUOUS":
        clip_geometry = box(-140.5, bounds[1], -115.0, 50.0)
    elif area_zone == "ALASKA":
        clip_geometry = box(bounds[0], 50.0, bounds[2], bounds[3])
    else:
        raise ValueError(f"Unsupported U.S. water area zone: {area_zone}")
    clip = gpd.GeoDataFrame(geometry=[clip_geometry], crs=us_waters_line.crs)
    return gpd.overlay(us_waters_line, clip, how="intersection")


__all__ = ["build_us_coastline", "build_us_waters_boundary", "clip_us_water_lines"]
