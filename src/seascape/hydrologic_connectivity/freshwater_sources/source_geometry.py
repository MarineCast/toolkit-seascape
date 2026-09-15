"""Geometry normalization shared by freshwater-source owners."""

from __future__ import annotations

from typing import Any


def line_parts(frame: Any):
    exploded = frame.explode(index_parts=False, ignore_index=True)
    return exploded.loc[exploded.geom_type.eq("LineString")].reset_index(drop=True)


def polygon_parts(frame: Any):
    exploded = frame.explode(index_parts=False, ignore_index=True)
    return exploded.loc[exploded.geom_type.eq("Polygon")].reset_index(drop=True)


__all__ = ["line_parts", "polygon_parts"]
