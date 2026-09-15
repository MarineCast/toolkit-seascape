"""Product-contract validation for canonical marine support and water graphs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent, get_resolution, grid_disk_set
from seascape.utils.artifacts import (
    validate_manifest as validate_common_manifest,
)

WATER_NETWORK_SCHEMA_VERSION = "3.0.0"

SUPPORT_REQUIRED_COLUMNS = (
    "H3_INDEX",
    "H3_RESOLUTION",
    "PARENT_H3_INDEX",
    "CELL_AREA_M2",
    "WATER_AREA_M2",
    "LAND_AREA_M2",
    "WATER_FRACTION",
    "LAND_FRACTION",
    "HAS_WATER_OVERLAP",
    "IS_HIERARCHY_ONLY_PARENT",
    "IS_FULLY_WATER",
    "IS_PARTIALLY_WATER",
    "INTERSECTS_SHORELINE",
    "IS_AOI_BOUNDARY_CELL",
    "WATER_COMPONENT_ID",
    "WATER_MASK_VERSION",
    "SPATIAL_SUPPORT_VERSION",
    "REPRESENTATIVE_POINT_LONGITUDE",
    "REPRESENTATIVE_POINT_LATITUDE",
    "GRAPH_NODE_ELIGIBLE",
    "GRAPH_DEGREE",
    "GRAPH_CONNECTION_STATUS",
    "CONNECTOR_TARGET_H3_INDEX",
    "CONNECTOR_METHOD",
    "CONNECTOR_DISTANCE_M",
    "CONNECTOR_WATER_PATH_FRACTION",
    "GRAPH_QC_REASON",
)

EDGE_REQUIRED_COLUMNS = (
    "SOURCE_H3_INDEX",
    "TARGET_H3_INDEX",
    "H3_RESOLUTION",
    "EDGE_DISTANCE_M",
    "EDGE_IS_WATER_PASSABLE",
    "PASSABILITY_METHOD",
    "WATER_PATH_FRACTION",
    "SOURCE_WATER_COMPONENT_ID",
    "TARGET_WATER_COMPONENT_ID",
    "WATER_MASK_VERSION",
    "SPATIAL_SUPPORT_VERSION",
)

CONNECTOR_REQUIRED_COLUMNS = (
    "H3_INDEX",
    "TARGET_H3_INDEX",
    "H3_RESOLUTION",
    "CONNECTOR_DISTANCE_M",
    "CONNECTOR_IS_WATER_PASSABLE",
    "CONNECTOR_METHOD",
    "WATER_PATH_FRACTION",
    "WATER_COMPONENT_ID",
    "QC_REASON",
    "WATER_MASK_VERSION",
    "SPATIAL_SUPPORT_VERSION",
)

NEIGHBORHOOD_REQUIRED_COLUMNS = (
    "SOURCE_H3_INDEX",
    "TARGET_H3_INDEX",
    "H3_RESOLUTION",
    "MINIMUM_HOP_COUNT",
    "NETWORK_DISTANCE_M",
    "CONNECTIVITY_STATUS",
    "QC_REASON",
    "WATER_MASK_VERSION",
    "SPATIAL_SUPPORT_VERSION",
)


def _require_columns(frame: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _one_value(frame: pd.DataFrame, column: str, expected: Any, label: str) -> None:
    values = set(frame[column].dropna().tolist())
    if values != {expected}:
        raise ValueError(f"{label}.{column} expected only {expected!r}; found {values!r}.")


def validate_geometry_products(
    full: gpd.GeoDataFrame,
    clipped: gpd.GeoDataFrame,
    resolution: int,
) -> None:
    """Validate one-to-one full-cell and clipped-water geometry products."""

    for frame, label in ((full, "full geometry"), (clipped, "clipped geometry")):
        _require_columns(frame, ("H3_INDEX", "H3_RESOLUTION", "geometry"), label)
        if frame.crs is None or frame.crs.to_epsg() != 4326:
            raise ValueError(f"{label} must use EPSG:4326.")
        if frame.empty or frame["H3_INDEX"].duplicated().any():
            raise ValueError(f"{label} must contain unique, nonempty H3 support.")
        _one_value(frame, "H3_RESOLUTION", resolution, label)
        if frame.geometry.isna().any():
            raise ValueError(f"{label} contains null geometry.")
        if label == "full geometry" and frame.geometry.is_empty.any():
            raise ValueError("Full geometry contains an empty H3 polygon.")
        if label == "clipped geometry" and frame.geometry.is_empty.any():
            if "HAS_WATER_OVERLAP" not in frame.columns:
                raise ValueError("Clipped geometry must identify hierarchy-only empty parents.")
            invalid_empty = frame.geometry.is_empty & frame["HAS_WATER_OVERLAP"].astype(bool)
            if invalid_empty.any():
                raise ValueError("Wet clipped geometry contains an empty polygon.")
    if set(full["H3_INDEX"]) != set(clipped["H3_INDEX"]):
        raise ValueError("Full and clipped marine geometry must contain identical H3 indexes.")


def validate_support(
    frame: pd.DataFrame,
    resolution: int,
    *,
    water_mask_version: str,
    spatial_support_version: str,
    area_tolerance_m2: float,
) -> None:
    """Validate support schema, area arithmetic, H3 lineage, and graph QC."""

    _require_columns(frame, SUPPORT_REQUIRED_COLUMNS, "marine support")
    if frame.empty or frame["H3_INDEX"].duplicated().any():
        raise ValueError("Marine support must contain unique, nonempty H3 indexes.")
    _one_value(frame, "H3_RESOLUTION", resolution, "marine support")
    _one_value(frame, "WATER_MASK_VERSION", water_mask_version, "marine support")
    _one_value(
        frame,
        "SPATIAL_SUPPORT_VERSION",
        spatial_support_version,
        "marine support",
    )
    for cell, parent in frame[["H3_INDEX", "PARENT_H3_INDEX"]].itertuples(index=False):
        if get_resolution(str(cell)) != resolution:
            raise ValueError(f"Unexpected H3 resolution for {cell}.")
        if str(parent) != cell_to_parent(str(cell), resolution - 1):
            raise ValueError(f"Invalid immediate H3 parent for {cell}.")
    cell_area = frame["CELL_AREA_M2"].to_numpy(dtype="float64")
    water_area = frame["WATER_AREA_M2"].to_numpy(dtype="float64")
    land_area = frame["LAND_AREA_M2"].to_numpy(dtype="float64")
    water_fraction = frame["WATER_FRACTION"].to_numpy(dtype="float64")
    land_fraction = frame["LAND_FRACTION"].to_numpy(dtype="float64")
    if not np.isfinite(np.column_stack((cell_area, water_area, land_area))).all():
        raise ValueError("Marine support areas must be finite.")
    hierarchy_only = frame["IS_HIERARCHY_ONLY_PARENT"].astype(bool).to_numpy()
    has_water = frame["HAS_WATER_OVERLAP"].astype(bool).to_numpy()
    if not np.array_equal(has_water, ~hierarchy_only):
        raise ValueError("Water-overlap and hierarchy-only parent flags must be complements.")
    if (cell_area <= 0).any() or (water_area < 0).any() or (land_area < 0).any():
        raise ValueError("Marine support has nonpositive cell or negative water/land area.")
    if (water_area[has_water] <= 0).any() or (water_area[hierarchy_only] != 0).any():
        raise ValueError(
            "Wet support requires positive water; hierarchy-only parents require zero."
        )
    if (water_area > cell_area + area_tolerance_m2).any():
        raise ValueError("Water area exceeds full-cell area beyond tolerance.")
    if not np.allclose(cell_area, water_area + land_area, atol=area_tolerance_m2, rtol=1e-9):
        raise ValueError("Land area is not the complement of water area.")
    if ((water_fraction < 0) | (water_fraction > 1)).any():
        raise ValueError("Water fraction must be in [0, 1].")
    if not np.allclose(water_fraction + land_fraction, 1.0, atol=1e-12, rtol=0):
        raise ValueError("Land fraction must equal one minus water fraction.")
    fully = frame["IS_FULLY_WATER"].astype(bool).to_numpy()
    partial = frame["IS_PARTIALLY_WATER"].astype(bool).to_numpy()
    if (fully & partial).any() or (~(fully | partial) & has_water).any():
        raise ValueError("Every wet cell must be classified as exactly full or partial water.")
    if (fully[hierarchy_only] | partial[hierarchy_only]).any():
        raise ValueError("Hierarchy-only parents cannot be classified as wet cells.")
    degree = frame["GRAPH_DEGREE"].to_numpy(dtype="int64")
    if (degree < 0).any():
        raise ValueError("Graph degree cannot be negative.")
    connected = frame["GRAPH_CONNECTION_STATUS"].isin(("graph_node", "terminal_connector"))
    if frame.loc[connected, "WATER_COMPONENT_ID"].isna().any():
        raise ValueError("Connected support rows must have a water component.")
    if frame.loc[~connected, "GRAPH_QC_REASON"].isna().any():
        raise ValueError("Disconnected support rows must preserve a graph QC reason.")


def validate_edges(
    frame: pd.DataFrame,
    support: pd.DataFrame,
    resolution: int,
) -> None:
    """Validate canonical undirected true-neighbor candidate edges."""

    _require_columns(frame, EDGE_REQUIRED_COLUMNS, "water edge table")
    if frame.empty:
        raise ValueError("Water edge table is empty.")
    _one_value(frame, "H3_RESOLUTION", resolution, "water edge table")
    if (frame["SOURCE_H3_INDEX"] >= frame["TARGET_H3_INDEX"]).any():
        raise ValueError("Undirected edges must be stored with SOURCE < TARGET.")
    if frame.duplicated(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).any():
        raise ValueError("Water edge table contains duplicate edges.")
    support_cells = set(support["H3_INDEX"].astype(str))
    if not set(frame["SOURCE_H3_INDEX"]).issubset(support_cells) or not set(
        frame["TARGET_H3_INDEX"]
    ).issubset(support_cells):
        raise ValueError("Water edge references a cell outside canonical support.")
    for source, target in frame[["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]].itertuples(index=False):
        if str(target) not in grid_disk_set(str(source), 1):
            raise ValueError(f"Water edge is not a true H3 neighbor: {source}, {target}")
    distance = frame["EDGE_DISTANCE_M"].to_numpy(dtype="float64")
    fraction = frame["WATER_PATH_FRACTION"].to_numpy(dtype="float64")
    if not np.isfinite(distance).all() or (distance <= 0).any():
        raise ValueError("Every candidate edge must have a positive finite distance.")
    if not np.isfinite(fraction).all() or ((fraction < 0) | (fraction > 1)).any():
        raise ValueError("Every candidate edge must have a water-path fraction in [0, 1].")


def validate_connectors(
    frame: pd.DataFrame,
    support: pd.DataFrame,
    resolution: int,
) -> None:
    """Validate terminal-only connector records and support denormalization."""

    _require_columns(frame, CONNECTOR_REQUIRED_COLUMNS, "water connector table")
    if frame["H3_INDEX"].duplicated().any():
        raise ValueError("Water connector table must have at most one row per H3 cell.")
    if frame.empty:
        return
    _one_value(frame, "H3_RESOLUTION", resolution, "water connector table")
    if (frame["H3_INDEX"] == frame["TARGET_H3_INDEX"]).any():
        raise ValueError("A terminal connector cannot target itself.")
    accepted = frame["CONNECTOR_IS_WATER_PASSABLE"].astype(bool)
    distance = pd.to_numeric(frame["CONNECTOR_DISTANCE_M"], errors="coerce")
    if distance[accepted].isna().any() or (distance[accepted] <= 0).any():
        raise ValueError("Accepted terminal connectors require positive finite distance.")
    by_cell = support.set_index("H3_INDEX")
    for connector in frame.loc[accepted].itertuples(index=False):
        support_row = by_cell.loc[str(connector.H3_INDEX)]
        if support_row["GRAPH_CONNECTION_STATUS"] != "terminal_connector":
            raise ValueError("Accepted connector is not reflected in support status.")
        if str(support_row["CONNECTOR_TARGET_H3_INDEX"]) != str(connector.TARGET_H3_INDEX):
            raise ValueError("Support and connector target disagree.")


def validate_neighborhoods(
    frame: pd.DataFrame,
    support: pd.DataFrame,
    resolution: int,
    *,
    maximum_hops: int,
) -> None:
    """Validate bounded water-passable neighborhood rows."""

    _require_columns(frame, NEIGHBORHOOD_REQUIRED_COLUMNS, "water neighborhood table")
    if frame.empty:
        raise ValueError("Water neighborhood table is empty.")
    _one_value(frame, "H3_RESOLUTION", resolution, "water neighborhood table")
    if frame.duplicated(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).any():
        raise ValueError("Water neighborhood table contains duplicate source-target rows.")
    support_cells = set(support["H3_INDEX"].astype(str))
    if set(frame["SOURCE_H3_INDEX"].astype(str)) != support_cells:
        raise ValueError("Every support cell must own at least one neighborhood row.")
    if not set(frame["TARGET_H3_INDEX"].astype(str)).issubset(support_cells):
        raise ValueError("Water neighborhood target lies outside canonical support.")
    hops = pd.to_numeric(frame["MINIMUM_HOP_COUNT"], errors="coerce")
    distances = pd.to_numeric(frame["NETWORK_DISTANCE_M"], errors="coerce")
    if hops.isna().any() or ((hops < 0) | (hops > maximum_hops)).any():
        raise ValueError("Water neighborhood hop counts are outside the configured bound.")
    if distances.isna().any() or (~np.isfinite(distances)).any() or (distances < 0).any():
        raise ValueError("Water neighborhood distances must be finite and nonnegative.")
    self_rows = frame["SOURCE_H3_INDEX"].astype(str).eq(frame["TARGET_H3_INDEX"].astype(str))
    if not (hops[self_rows] == 0).all() or not (distances[self_rows] == 0).all():
        raise ValueError("Water neighborhood self rows must use zero hops and distance.")
    self_counts = frame.loc[self_rows, "SOURCE_H3_INDEX"].astype(str).value_counts()
    if set(self_counts.index) != support_cells or not (self_counts == 1).all():
        raise ValueError("Every support cell must have exactly one neighborhood self row.")


def validate_manifest_payload(payload: Mapping[str, Any]) -> None:
    """Validate the minimum manifest contract used by strict loaders."""

    if payload.get("dataset_family") != "environment.seascape.h3_marine_spatial_support":
        raise ValueError("Unexpected water-network dataset family.")
    if str(payload.get("schema_version")) != WATER_NETWORK_SCHEMA_VERSION:
        raise ValueError("Unsupported water-network schema version.")

    validate_common_manifest(payload, project_root=project_root(), verify_artifacts=False)
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("Water-network manifest metadata is missing.")
    for key in ("water_mask_version", "spatial_support_version", "summary"):
        if key not in metadata:
            raise ValueError(f"Water-network manifest metadata is missing {key!r}.")
    for artifact in payload["artifacts"]:
        if not isinstance(artifact, Mapping):
            raise ValueError("Manifest artifact entries must be mappings.")
        for key in ("path", "checksum", "size_bytes", "schema"):
            if key not in artifact:
                raise ValueError(f"Manifest artifact is missing {key!r}.")


def is_finite_or_null(value: Any) -> bool:
    """Return whether a scalar is null or finite."""

    return value is None or pd.isna(value) or math.isfinite(float(value))
