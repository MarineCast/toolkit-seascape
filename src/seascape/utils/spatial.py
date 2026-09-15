"""Canonical H3 support and feature-alignment helpers."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from shapely.geometry import box

from seascape.core.geo.geometry import normalize_polygonal_geometry, safe_polygonal_union


def expanded_bbox_polygon(bbox: Mapping[str, float], distance_km: float):
    """Return a WGS84 bbox polygon expanded by an approximate geodesic distance."""

    if distance_km < 0:
        raise ValueError("Bounding-box expansion distance must be nonnegative.")
    middle_latitude = (float(bbox["min_lat"]) + float(bbox["max_lat"])) / 2.0
    latitude_padding = float(distance_km) / 110.574
    longitude_padding = float(distance_km) / (
        111.320 * max(math.cos(math.radians(middle_latitude)), 0.1)
    )
    return box(
        float(bbox["min_lon"]) - longitude_padding,
        float(bbox["min_lat"]) - latitude_padding,
        float(bbox["max_lon"]) + longitude_padding,
        float(bbox["max_lat"]) + latitude_padding,
    )


def load_polygon_layer(path: str | Path, *, target_crs: str = "EPSG:4326"):
    """Load a vector polygon source with explicit existence and CRS checks."""

    import geopandas as gpd

    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Polygon source not found: {source}")
    frame = (
        gpd.read_parquet(source)
        if source.suffix.lower() in {".parquet", ".geoparquet"}
        else gpd.read_file(source)
    )
    if frame.crs is None:
        raise ValueError(f"Polygon source has no CRS: {source}")
    return frame.to_crs(target_crs)


def project_h3_centers(
    cells: Iterable[str], projected_crs: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return latitude, longitude, projected x, and projected y arrays for H3 cells."""

    import h3
    from pyproj import Transformer

    normalized = [str(cell) for cell in cells]
    latitudes = np.empty(len(normalized), dtype="float64")
    longitudes = np.empty(len(normalized), dtype="float64")
    for index, cell in enumerate(normalized):
        latitude, longitude = h3.cell_to_latlng(cell)
        latitudes[index] = float(latitude)
        longitudes[index] = float(longitude)
    transformer = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    x_values, y_values = transformer.transform(longitudes, latitudes)
    return (
        latitudes,
        longitudes,
        np.asarray(x_values, dtype="float64"),
        np.asarray(y_values, dtype="float64"),
    )


def prepare_water_land_context(
    *,
    water_path: str | Path,
    land_path: str | Path,
    bbox: Mapping[str, float],
    context_buffer_km: float,
    guard_buffer_km: float = 10.0,
) -> dict[str, Any]:
    """Prepare guarded target/context water and land geometry without filling gaps."""

    water = load_polygon_layer(water_path)
    land = load_polygon_layer(land_path)
    target_box = box(
        float(bbox["min_lon"]),
        float(bbox["min_lat"]),
        float(bbox["max_lon"]),
        float(bbox["max_lat"]),
    )
    context_box = expanded_bbox_polygon(bbox, context_buffer_km)
    guard_box = expanded_bbox_polygon(bbox, context_buffer_km + guard_buffer_km)
    target_water = safe_polygonal_union(water, clip_geometry=target_box)
    context_water = safe_polygonal_union(water, clip_geometry=context_box)
    guarded_land = safe_polygonal_union(land, clip_geometry=guard_box)
    context_land = normalize_polygonal_geometry(guarded_land.intersection(context_box))
    return {
        "target_box": target_box,
        "context_box": context_box,
        "target_water": target_water,
        "context_water": context_water,
        "context_land": context_land,
        "guarded_land": guarded_land,
    }


def h3_cell_set_hash(values: Iterable[object]) -> str:
    """Hash a unique, sorted H3 identifier set for manifest comparisons."""

    normalized = sorted({str(value) for value in values if pd.notna(value)})
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()


def validate_unique_h3(frame: pd.DataFrame, *, label: str) -> None:
    """Validate the one-row-per-cell contract used by feature products."""

    if "H3_INDEX" not in frame.columns:
        raise ValueError(f"{label} must contain H3_INDEX.")
    if frame["H3_INDEX"].isna().any():
        raise ValueError(f"{label} contains null H3_INDEX values.")
    duplicated = frame["H3_INDEX"].astype(str).duplicated(keep=False)
    if duplicated.any():
        examples = sorted(frame.loc[duplicated, "H3_INDEX"].astype(str).unique())[:5]
        raise ValueError(f"{label} contains duplicate H3 cells: {examples}")


def align_to_model_support(
    support: pd.DataFrame,
    features: pd.DataFrame,
    *,
    feature_label: str,
    support_columns: tuple[str, ...] = ("H3_INDEX",),
) -> pd.DataFrame:
    """Left-align a feature table to canonical support without inventing zeroes."""

    validate_unique_h3(support, label="canonical model support")
    validate_unique_h3(features, label=feature_label)
    missing_support_columns = sorted(set(support_columns).difference(support.columns))
    if missing_support_columns:
        raise ValueError(
            f"Canonical model support is missing requested columns: {missing_support_columns}"
        )
    unknown = sorted(
        set(features["H3_INDEX"].astype(str)).difference(support["H3_INDEX"].astype(str))
    )
    if unknown:
        raise ValueError(
            f"{feature_label} contains cells outside canonical model support: {unknown[:5]}"
        )
    left = support.loc[:, list(support_columns)].copy()
    left["H3_INDEX"] = left["H3_INDEX"].astype(str)
    right = features.copy()
    right["H3_INDEX"] = right["H3_INDEX"].astype(str)
    output = left.merge(right, on="H3_INDEX", how="left", validate="one_to_one")
    if h3_cell_set_hash(output["H3_INDEX"]) != h3_cell_set_hash(support["H3_INDEX"]):
        raise ValueError(f"{feature_label} alignment changed the canonical H3 cell set.")
    return output


def water_neighborhood_lookup(
    neighborhoods: pd.DataFrame,
    *,
    maximum_hops: int,
) -> dict[str, tuple[str, ...]]:
    """Return deterministic water-passable targets for each source cell.

    Materialized neighborhood tables include the source at hop zero. Callers
    receive only other cells through the requested inclusive hop bound.
    """

    required = {"SOURCE_H3_INDEX", "TARGET_H3_INDEX", "MINIMUM_HOP_COUNT"}
    missing = sorted(required.difference(neighborhoods.columns))
    if missing:
        raise ValueError(f"Water-neighborhood table is missing columns: {missing}")
    if maximum_hops < 1:
        raise ValueError("maximum_hops must be positive.")
    hops = pd.to_numeric(neighborhoods["MINIMUM_HOP_COUNT"], errors="coerce")
    selected = neighborhoods.loc[
        hops.between(1, maximum_hops),
        ["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "MINIMUM_HOP_COUNT"],
    ].copy()
    selected["SOURCE_H3_INDEX"] = selected["SOURCE_H3_INDEX"].astype(str)
    selected["TARGET_H3_INDEX"] = selected["TARGET_H3_INDEX"].astype(str)
    selected = selected.sort_values(["SOURCE_H3_INDEX", "MINIMUM_HOP_COUNT", "TARGET_H3_INDEX"])
    return {
        str(source): tuple(group["TARGET_H3_INDEX"].astype(str))
        for source, group in selected.groupby("SOURCE_H3_INDEX", sort=True)
    }
