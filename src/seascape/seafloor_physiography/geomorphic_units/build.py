"""Build resolution-8 H3 seafloor geomorphic units.

The classification follows the multi-scale Bathymetric Position Index approach
used by NOAA's Benthic Terrain Modeler, adapted to the canonical Seascape Toolkit H3
water universe.  It is a modeling-scale terrain classification derived from
GEBCO bathymetry, not an authoritative geological interpretation.
"""

from __future__ import annotations

import argparse
import logging
import math
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.geo.h3 import cell_to_polygon
from seascape.spatial_support.water_network import (
    load_water_neighborhoods,
)
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.spatial import water_neighborhood_lookup

LOGGER = logging.getLogger(__name__)

GEOMORPHIC_UNITS = (
    "SHELF",
    "SHELF_BREAK",
    "SLOPE",
    "BANK_OR_SHOAL",
    "BASIN_OR_DEPRESSION",
    "CANYON_AXIS",
    "CANYON_RIM",
    "CHANNEL",
    "TROUGH",
    "SILL",
    "RIDGE",
    "TERRACE",
    "SEAMOUNT_OR_KNOLL",
)
DIAGNOSTIC_COLUMNS = [
    "BROAD_TERRAIN_POSITION_M",
    "BROAD_TERRAIN_POSITION_Z",
    "DIRECTIONAL_ANISOTROPY",
    "CANYON_DENSITY",
]
DISTANCE_COLUMNS = [f"DISTANCE_TO_{unit}_M" for unit in GEOMORPHIC_UNITS]
PROPORTION_COLUMNS = [f"PROPORTION_{unit}" for unit in GEOMORPHIC_UNITS]
OUTPUT_COLUMNS = [
    "H3_INDEX",
    "GEOMORPHIC_UNIT",
    "CLASSIFICATION_CONFIDENCE",
    "MAPPING_UNIT_CELL_COUNT",
    "MINIMUM_MAPPING_UNIT_CELLS",
    "MEETS_MINIMUM_MAPPING_UNIT",
    *DIAGNOSTIC_COLUMNS,
    *DISTANCE_COLUMNS,
    *PROPORTION_COLUMNS,
]


@dataclass(frozen=True)
class GeomorphicUnitsConfig:
    """Resolved inputs and thresholds for the H3 terrain classification."""

    h3_resolution: int
    bathymetry_path: Path
    geomorphometry_path: Path
    waterbody_morphometry_path: Path
    output_path: Path
    projected_crs: str
    broad_neighborhood_rings: int
    proportion_neighborhood_rings: int
    canyon_density_rings: int
    minimum_mapping_unit_cells: int
    shelf_max_depth_m: float
    flat_slope_degrees: float
    steep_slope_degrees: float
    shelf_break_distance_m: float
    tpi_standard_deviation_break: float
    prominence_min_m: float
    canyon_relief_min_m: float
    bank_max_depth_m: float
    seamount_min_depth_m: float
    channel_max_width_m: float
    sill_max_width_m: float
    sill_min_constriction: float


def load_geomorphic_units_config(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> GeomorphicUnitsConfig:
    """Load and validate geomorphic-unit settings and input paths."""

    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    from seascape.seafloor_physiography.depth import require_positive_down_config

    require_positive_down_config(raw)
    section = _mapping(raw.get("geomorphic_units"), "geomorphic_units")
    processing = _mapping(section.get("processing"), "geomorphic_units.processing")
    classification = _mapping(section.get("classification", {}), "geomorphic_units.classification")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()

    resolution = int(processing.get("h3_resolution", 8))
    if resolution != 8:
        raise ValueError("geomorphic_units.processing.h3_resolution must be 8.")
    broad_rings = int(classification.get("broad_neighborhood_rings", 4))
    proportion_rings = int(classification.get("proportion_neighborhood_rings", 3))
    canyon_rings = int(classification.get("canyon_density_rings", 4))
    minimum_cells = int(classification.get("minimum_mapping_unit_cells", 3))
    flat_slope = float(classification.get("flat_slope_degrees", 5.0))
    steep_slope = float(classification.get("steep_slope_degrees", 15.0))
    shelf_depth = float(classification.get("shelf_max_depth_m", 200.0))
    bank_depth = float(classification.get("bank_max_depth_m", 150.0))
    seamount_depth = float(classification.get("seamount_min_depth_m", 200.0))
    tpi_break = float(classification.get("tpi_standard_deviation_break", 1.0))
    prominence = float(classification.get("prominence_min_m", 10.0))
    canyon_relief = float(classification.get("canyon_relief_min_m", 20.0))
    channel_width = float(classification.get("channel_max_width_m", 6_000.0))
    sill_width = float(classification.get("sill_max_width_m", 15_000.0))
    sill_constriction = float(classification.get("sill_min_constriction", 0.05))

    if min(broad_rings, proportion_rings, canyon_rings, minimum_cells) < 1:
        raise ValueError("Geomorphic-unit H3 ring and mapping-unit settings must be positive.")
    if not 0.0 < flat_slope < steep_slope:
        raise ValueError("flat_slope_degrees must be positive and below steep_slope_degrees.")
    if min(shelf_depth, bank_depth, seamount_depth, tpi_break, prominence, canyon_relief) <= 0:
        raise ValueError(
            "Geomorphic-unit depth, TPI, prominence, and relief thresholds must be positive."
        )
    if min(channel_width, sill_width) <= 0.0:
        raise ValueError("Channel and sill width thresholds must be positive.")
    if not 0.0 <= sill_constriction <= 1.0:
        raise ValueError("sill_min_constriction must be in [0, 1].")

    return GeomorphicUnitsConfig(
        h3_resolution=resolution,
        bathymetry_path=_resolve(processing["bathymetry_path"], base_dir),
        geomorphometry_path=_resolve(processing["geomorphometry_path"], base_dir),
        waterbody_morphometry_path=_resolve(processing["waterbody_morphometry_path"], base_dir),
        output_path=_resolve(processing["processed_path"], base_dir),
        projected_crs=str(processing.get("projected_crs", "EPSG:32610")),
        broad_neighborhood_rings=broad_rings,
        proportion_neighborhood_rings=proportion_rings,
        canyon_density_rings=canyon_rings,
        minimum_mapping_unit_cells=minimum_cells,
        shelf_max_depth_m=shelf_depth,
        flat_slope_degrees=flat_slope,
        steep_slope_degrees=steep_slope,
        shelf_break_distance_m=float(classification.get("shelf_break_distance_m", 2_500.0)),
        tpi_standard_deviation_break=tpi_break,
        prominence_min_m=prominence,
        canyon_relief_min_m=canyon_relief,
        bank_max_depth_m=bank_depth,
        seamount_min_depth_m=seamount_depth,
        channel_max_width_m=channel_width,
        sill_max_width_m=sill_width,
        sill_min_constriction=sill_constriction,
    )


def _read_unique(path: Path, required: set[str], name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{name} Parquet not found: {path}")
    frame = pd.read_parquet(path)
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{name} Parquet is missing columns: {missing}")
    if frame["H3_INDEX"].isna().any() or not frame["H3_INDEX"].is_unique:
        raise ValueError(f"{name} must contain one non-null row per H3_INDEX.")
    frame = frame.copy()
    frame["H3_INDEX"] = frame["H3_INDEX"].astype(str)
    return frame


def _load_inputs(config: GeomorphicUnitsConfig) -> pd.DataFrame:
    bathymetry_columns = {
        "H3_INDEX",
        "BATHYMETRY",
        "DISTANCE_TO_ISOBATH_200_M",
    }
    geomorphometry_columns = {
        "H3_INDEX",
        "SLOPE",
        "TERRAIN_POSITION",
        "CURVATURE",
        "RELIEF",
        "RUGGEDNESS",
    }
    morphometry_columns = {
        "H3_INDEX",
        "LOCAL_WATERBODY_WIDTH_M",
        "CONSTRICTION_INDEX",
        "DISTANCE_TO_SILL_CANDIDATE_M",
    }
    bathymetry = _read_unique(config.bathymetry_path, bathymetry_columns, "Bathymetry")
    geomorphometry = _read_unique(
        config.geomorphometry_path, geomorphometry_columns, "Geomorphometry"
    )
    morphometry = _read_unique(
        config.waterbody_morphometry_path,
        morphometry_columns,
        "Waterbody morphometry",
    )
    from seascape.seafloor_physiography.depth import validate_positive_depth

    validate_positive_depth(bathymetry["BATHYMETRY"])
    reference = set(bathymetry["H3_INDEX"])
    for name, frame in (
        ("Geomorphometry", geomorphometry),
        ("Waterbody morphometry", morphometry),
    ):
        if set(frame["H3_INDEX"]) != reference:
            raise ValueError(f"{name} does not use the same H3 universe as bathymetry.")
    merged = bathymetry[list(bathymetry_columns)].merge(
        geomorphometry[list(geomorphometry_columns)],
        on="H3_INDEX",
        validate="one_to_one",
    )
    merged = merged.merge(
        morphometry[list(morphometry_columns)],
        on="H3_INDEX",
        validate="one_to_one",
    )
    return merged.sort_values("H3_INDEX").reset_index(drop=True)


def _projected_centers(cells: pd.Series, crs: str) -> np.ndarray:
    import geopandas as gpd

    polygons = cells.astype(str).map(cell_to_polygon)
    frame = gpd.GeoDataFrame(
        {"H3_INDEX": cells.astype(str)}, geometry=polygons, crs="EPSG:4326"
    ).to_crs(crs)
    centers = frame.geometry.centroid
    return np.column_stack((centers.x.to_numpy(), centers.y.to_numpy())).astype("float64")


def _terrain_context(
    frame: pd.DataFrame,
    centers: np.ndarray,
    config: GeomorphicUnitsConfig,
    neighborhood_lookups: Mapping[int, Mapping[str, tuple[str, ...]]],
) -> dict[str, np.ndarray]:
    cells = frame["H3_INDEX"].astype(str).tolist()
    index = {cell: offset for offset, cell in enumerate(cells)}
    depth = pd.to_numeric(frame["BATHYMETRY"], errors="coerce").to_numpy("float64")
    slope = pd.to_numeric(frame["SLOPE"], errors="coerce").to_numpy("float64")
    local_tpi = pd.to_numeric(frame["TERRAIN_POSITION"], errors="coerce").to_numpy("float64")
    broad_tpi = np.full(len(cells), np.nan)
    broad_z = np.full(len(cells), np.nan)
    slope_context = np.full(len(cells), np.nan)
    directional_anisotropy = np.zeros(len(cells), dtype="float64")
    crosses_shelf_depth = np.zeros(len(cells), dtype="float64")

    for offset, cell in enumerate(cells):
        if not math.isfinite(depth[offset]):
            continue
        broad_indices = [
            index[neighbor]
            for neighbor in neighborhood_lookups[config.broad_neighborhood_rings].get(cell, ())
            if neighbor in index and neighbor != cell and math.isfinite(depth[index[neighbor]])
        ]
        if broad_indices:
            values = depth[broad_indices]
            mean = float(np.mean(values))
            standard_deviation = float(np.std(values))
            broad_tpi[offset] = mean - depth[offset]
            broad_z[offset] = (
                broad_tpi[offset] / standard_deviation if standard_deviation > 1e-9 else 0.0
            )
            valid_slopes = slope[broad_indices]
            valid_slopes = valid_slopes[np.isfinite(valid_slopes)]
            if len(valid_slopes):
                slope_context[offset] = float(np.mean(valid_slopes))
            combined = np.concatenate(([depth[offset]], values))
            crosses_shelf_depth[offset] = float(
                np.nanmin(combined) <= config.shelf_max_depth_m
                and np.nanmax(combined) > config.shelf_max_depth_m
            )

        immediate = [
            index[neighbor]
            for neighbor in neighborhood_lookups[1].get(cell, ())
            if neighbor in index and neighbor != cell and math.isfinite(depth[index[neighbor]])
        ]
        if immediate and not math.isfinite(local_tpi[offset]):
            local_tpi[offset] = float(np.mean(depth[immediate]) - depth[offset])
        if len(immediate) >= 3:
            vectors = centers[immediate] - centers[offset]
            lengths = np.linalg.norm(vectors, axis=1)
            keep = lengths > 0.0
            vectors = vectors[keep] / lengths[keep, None]
            weights = np.abs(depth[np.asarray(immediate)[keep]] - depth[offset])
            if float(weights.sum()) > 1e-9:
                covariance = (vectors * weights[:, None]).T @ vectors / weights.sum()
                eigenvalues = np.linalg.eigvalsh(covariance)
                directional_anisotropy[offset] = float(
                    (eigenvalues[-1] - eigenvalues[0])
                    / max(eigenvalues[-1] + eigenvalues[0], 1e-12)
                )

    return {
        "DEPTH": depth,
        "SLOPE": slope,
        "LOCAL_TPI": local_tpi,
        "BROAD_TPI": broad_tpi,
        "BROAD_Z": broad_z,
        "SLOPE_CONTEXT": slope_context,
        "DIRECTIONAL_ANISOTROPY": directional_anisotropy,
        "CROSSES_SHELF_DEPTH": crosses_shelf_depth,
    }


def _rise(values: np.ndarray, low: float, high: float) -> np.ndarray:
    span = max(high - low, 1e-12)
    return np.clip((np.nan_to_num(values, nan=low) - low) / span, 0.0, 1.0)


def _fall(values: np.ndarray, low: float, high: float) -> np.ndarray:
    return 1.0 - _rise(values, low, high)


def _classification_scores(
    frame: pd.DataFrame,
    terrain: Mapping[str, np.ndarray],
    config: GeomorphicUnitsConfig,
) -> dict[str, np.ndarray]:
    depth = terrain["DEPTH"]
    slope = terrain["SLOPE"]
    local_tpi = terrain["LOCAL_TPI"]
    broad_z = terrain["BROAD_Z"]
    slope_context = terrain["SLOPE_CONTEXT"]
    anisotropy = terrain["DIRECTIONAL_ANISOTROPY"]
    relief = pd.to_numeric(frame["RELIEF"], errors="coerce").to_numpy("float64")
    width = pd.to_numeric(frame["LOCAL_WATERBODY_WIDTH_M"], errors="coerce").to_numpy("float64")
    constriction = pd.to_numeric(frame["CONSTRICTION_INDEX"], errors="coerce").to_numpy("float64")
    distance_sill = pd.to_numeric(frame["DISTANCE_TO_SILL_CANDIDATE_M"], errors="coerce").to_numpy(
        "float64"
    )
    distance_200 = pd.to_numeric(frame["DISTANCE_TO_ISOBATH_200_M"], errors="coerce").to_numpy(
        "float64"
    )

    flat = _fall(slope, config.flat_slope_degrees * 0.4, config.flat_slope_degrees)
    steep = _rise(slope, config.flat_slope_degrees, config.steep_slope_degrees)
    steep_context = _rise(slope_context, config.flat_slope_degrees, config.steep_slope_degrees)
    shelf_depth = _fall(depth, config.shelf_max_depth_m, config.shelf_max_depth_m * 1.5)
    shallow_bank = _fall(depth, config.bank_max_depth_m, config.shelf_max_depth_m)
    deep = _rise(depth, config.seamount_min_depth_m * 0.75, config.seamount_min_depth_m * 2.0)
    positive_broad = _rise(
        broad_z,
        config.tpi_standard_deviation_break * 0.5,
        config.tpi_standard_deviation_break * 1.5,
    )
    negative_broad = _rise(
        -broad_z,
        config.tpi_standard_deviation_break * 0.5,
        config.tpi_standard_deviation_break * 1.5,
    )
    positive_local = _rise(local_tpi, config.prominence_min_m, config.prominence_min_m * 3.0)
    negative_local = _rise(-local_tpi, config.prominence_min_m, config.prominence_min_m * 3.0)
    crest = np.maximum(positive_broad, positive_local)
    valley = np.maximum(negative_broad, negative_local)
    strong_relief = _rise(relief, config.canyon_relief_min_m, config.canyon_relief_min_m * 4.0)
    linear = _rise(anisotropy, 0.25, 0.75)
    radial = _fall(anisotropy, 0.20, 0.65)
    narrow_channel = _fall(width, config.channel_max_width_m * 0.4, config.channel_max_width_m)
    narrow_sill = _fall(width, config.sill_max_width_m * 0.4, config.sill_max_width_m)
    constrained = _rise(
        constriction,
        config.sill_min_constriction,
        min(1.0, config.sill_min_constriction + 0.30),
    )
    near_sill = _fall(distance_sill, 0.0, 5_000.0)
    near_shelf_break = np.maximum(
        _fall(distance_200, 0.0, config.shelf_break_distance_m),
        terrain["CROSSES_SHELF_DEPTH"],
    )
    neutral_bpi = _fall(
        np.abs(broad_z),
        config.tpi_standard_deviation_break * 0.25,
        config.tpi_standard_deviation_break,
    )

    scores: dict[str, np.ndarray] = {}
    # Broad background classes are deliberately down-weighted so that strong
    # local structures are not swallowed by a shelf or slope default.
    scores["SHELF"] = 0.75 * (0.50 * shelf_depth + 0.30 * flat + 0.20 * neutral_bpi)
    scores["SHELF_BREAK"] = near_shelf_break * (0.60 + 0.40 * steep)
    scores["SLOPE"] = 1.20 * (0.70 * steep + 0.20 * deep + 0.10 * neutral_bpi)
    scores["BANK_OR_SHOAL"] = (
        0.50 * crest + 0.25 * shallow_bank + 0.15 * flat + 0.10 * strong_relief
    ) * (crest > 0.10)
    scores["BASIN_OR_DEPRESSION"] = (0.55 * valley + 0.25 * deep + 0.20 * flat) * (valley > 0.10)
    scores["CANYON_AXIS"] = (
        (0.35 * valley + 0.25 * linear + 0.25 * strong_relief + 0.15 * steep_context)
        * (valley > 0.25)
        * (strong_relief > 0.10)
    )
    scores["CHANNEL"] = (
        (0.30 * valley + 0.25 * linear + 0.25 * narrow_channel + 0.20 * constrained)
        * (valley > 0.10)
        * (narrow_channel > 0.10)
    )
    scores["TROUGH"] = (0.45 * negative_broad + 0.25 * linear + 0.20 * flat + 0.10 * deep) * (
        negative_broad > 0.10
    )
    scores["SILL"] = (
        (0.35 * crest + 0.20 * narrow_sill + 0.25 * constrained + 0.20 * near_sill)
        * (crest > 0.10)
        * (narrow_sill > 0.10)
    )
    scores["RIDGE"] = (
        1.40
        * (0.45 * crest + 0.30 * linear + 0.15 * strong_relief + 0.10 * deep)
        * (crest > 0.10)
        * (linear > 0.10)
    )
    scores["TERRACE"] = (
        2.00
        * (0.45 * flat + 0.35 * steep_context + 0.20 * neutral_bpi)
        * (flat > 0.25)
        * (steep_context > 0.10)
    )
    scores["SEAMOUNT_OR_KNOLL"] = (
        (0.45 * crest + 0.25 * radial + 0.20 * deep + 0.10 * strong_relief)
        * (crest > 0.20)
        * (deep > 0.10)
    )
    scores["CANYON_RIM"] = np.zeros(len(frame), dtype="float64")
    return scores


def _add_canyon_rim_scores(
    cells: list[str],
    scores: dict[str, np.ndarray],
    terrain: Mapping[str, np.ndarray],
    immediate_neighbors: Mapping[str, tuple[str, ...]],
) -> None:
    index = {cell: offset for offset, cell in enumerate(cells)}
    axis_candidates = np.flatnonzero(scores["CANYON_AXIS"] >= 0.52)
    for axis_index in axis_candidates:
        axis_cell = cells[int(axis_index)]
        axis_depth = terrain["DEPTH"][axis_index]
        for neighbor in immediate_neighbors.get(axis_cell, ()):
            neighbor_index = index.get(neighbor)
            if neighbor_index is None or neighbor_index == axis_index:
                continue
            depth_difference = axis_depth - terrain["DEPTH"][neighbor_index]
            shallower = float(np.clip(depth_difference / 40.0, 0.0, 1.0))
            slope = float(_rise(np.asarray([terrain["SLOPE"][neighbor_index]]), 2.0, 10.0)[0])
            scores["CANYON_RIM"][neighbor_index] = max(
                scores["CANYON_RIM"][neighbor_index],
                0.70 * (0.45 + 0.30 * shallower + 0.25 * slope),
            )


def _select_labels(
    frame: pd.DataFrame,
    scores: Mapping[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    priority = (
        "CANYON_AXIS",
        "CANYON_RIM",
        "SILL",
        "CHANNEL",
        "SEAMOUNT_OR_KNOLL",
        "RIDGE",
        "BANK_OR_SHOAL",
        "SHELF_BREAK",
        "TROUGH",
        "BASIN_OR_DEPRESSION",
        "TERRACE",
        "SLOPE",
        "SHELF",
    )
    matrix = np.column_stack([scores[unit] for unit in priority])
    selected = np.argmax(matrix, axis=1)
    labels = np.asarray([priority[index] for index in selected], dtype=object)
    valid_depth = np.isfinite(
        pd.to_numeric(frame["BATHYMETRY"], errors="coerce").to_numpy("float64")
    )
    labels[~valid_depth] = "UNCLASSIFIED"
    top = matrix[np.arange(len(frame)), selected]
    second = np.partition(matrix, -2, axis=1)[:, -2]
    confidence = np.clip(0.55 * top + 0.45 * np.maximum(top - second, 0.0), 0.0, 1.0)
    confidence[~valid_depth] = 0.0
    return labels, confidence


def _component_sizes(
    cells: list[str],
    labels: np.ndarray,
    immediate_neighbors: Mapping[str, tuple[str, ...]],
) -> np.ndarray:
    index = {cell: offset for offset, cell in enumerate(cells)}
    sizes = np.zeros(len(cells), dtype="int32")
    visited: set[int] = set()
    for start in range(len(cells)):
        if start in visited or labels[start] == "UNCLASSIFIED":
            continue
        label = labels[start]
        component: list[int] = []
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in immediate_neighbors.get(cells[current], ()):
                neighbor_index = index.get(neighbor)
                if (
                    neighbor_index is not None
                    and neighbor_index not in visited
                    and labels[neighbor_index] == label
                ):
                    visited.add(neighbor_index)
                    queue.append(neighbor_index)
        sizes[component] = len(component)
    return sizes


def _apply_minimum_mapping_unit(
    cells: list[str],
    labels: np.ndarray,
    scores: Mapping[str, np.ndarray],
    minimum_cells: int,
    immediate_neighbors: Mapping[str, tuple[str, ...]],
) -> tuple[np.ndarray, np.ndarray]:
    index = {cell: offset for offset, cell in enumerate(cells)}
    revised = labels.copy()
    for _pass in range(3):
        sizes = _component_sizes(cells, revised, immediate_neighbors)
        small = np.flatnonzero((sizes > 0) & (sizes < minimum_cells) & (revised != "UNCLASSIFIED"))
        if not len(small):
            break
        changes: dict[int, str] = {}
        for offset in small:
            neighbor_labels = [
                str(revised[index[neighbor]])
                for neighbor in immediate_neighbors.get(cells[int(offset)], ())
                if neighbor in index
                and index[neighbor] != offset
                and revised[index[neighbor]] not in {revised[offset], "UNCLASSIFIED"}
            ]
            if not neighbor_labels:
                continue
            counts = Counter(neighbor_labels)
            best_count = max(counts.values())
            candidates = [label for label, count in counts.items() if count == best_count]
            changes[int(offset)] = max(candidates, key=lambda label: float(scores[label][offset]))
        if not changes:
            break
        for offset, label in changes.items():
            revised[offset] = label
    return revised, _component_sizes(cells, revised, immediate_neighbors)


def _distance_and_proportion_metrics(
    cells: list[str],
    labels: np.ndarray,
    centers: np.ndarray,
    neighborhood_lookup: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    index = {cell: offset for offset, cell in enumerate(cells)}
    distances: dict[str, np.ndarray] = {}
    proportions = {unit: np.zeros(len(cells), dtype="float64") for unit in GEOMORPHIC_UNITS}
    for unit in GEOMORPHIC_UNITS:
        targets = np.flatnonzero(labels == unit)
        distances[unit] = (
            cKDTree(centers[targets]).query(centers, workers=-1)[0].astype("float64")
            if len(targets)
            else np.full(len(cells), np.nan)
        )
    for offset, cell in enumerate(cells):
        neighborhood = [
            offset,
            *[
                index[neighbor]
                for neighbor in neighborhood_lookup.get(cell, ())
                if neighbor in index
            ],
        ]
        if not neighborhood:
            continue
        counts = Counter(str(labels[item]) for item in neighborhood)
        denominator = float(len(neighborhood))
        for unit in GEOMORPHIC_UNITS:
            proportions[unit][offset] = counts.get(unit, 0) / denominator
    return distances, proportions


def _canyon_density(
    cells: list[str],
    labels: np.ndarray,
    neighborhood_lookup: Mapping[str, tuple[str, ...]],
) -> np.ndarray:
    index = {cell: offset for offset, cell in enumerate(cells)}
    canyon_units = {"CANYON_AXIS", "CANYON_RIM"}
    density = np.zeros(len(cells), dtype="float64")
    for offset, cell in enumerate(cells):
        neighborhood = [
            offset,
            *[
                index[neighbor]
                for neighbor in neighborhood_lookup.get(cell, ())
                if neighbor in index
            ],
        ]
        if neighborhood:
            density[offset] = sum(labels[item] in canyon_units for item in neighborhood) / len(
                neighborhood
            )
    return density


def _build_output(
    frame: pd.DataFrame,
    terrain: Mapping[str, np.ndarray],
    labels: np.ndarray,
    confidence: np.ndarray,
    component_sizes: np.ndarray,
    distances: Mapping[str, np.ndarray],
    proportions: Mapping[str, np.ndarray],
    canyon_density: np.ndarray,
    minimum_cells: int,
) -> pd.DataFrame:
    data: dict[str, Any] = {
        "H3_INDEX": frame["H3_INDEX"].astype(str),
        "GEOMORPHIC_UNIT": labels,
        "CLASSIFICATION_CONFIDENCE": confidence,
        "MAPPING_UNIT_CELL_COUNT": component_sizes,
        "MINIMUM_MAPPING_UNIT_CELLS": np.full(len(frame), minimum_cells),
        "MEETS_MINIMUM_MAPPING_UNIT": (component_sizes >= minimum_cells)
        & (labels != "UNCLASSIFIED"),
        "BROAD_TERRAIN_POSITION_M": terrain["BROAD_TPI"],
        "BROAD_TERRAIN_POSITION_Z": terrain["BROAD_Z"],
        "DIRECTIONAL_ANISOTROPY": terrain["DIRECTIONAL_ANISOTROPY"],
        "CANYON_DENSITY": canyon_density,
    }
    for unit in GEOMORPHIC_UNITS:
        data[f"DISTANCE_TO_{unit}_M"] = distances[unit]
        data[f"PROPORTION_{unit}"] = proportions[unit]
    output = pd.DataFrame(data, columns=OUTPUT_COLUMNS).sort_values("H3_INDEX")
    output["MAPPING_UNIT_CELL_COUNT"] = output["MAPPING_UNIT_CELL_COUNT"].astype("int32")
    output["MINIMUM_MAPPING_UNIT_CELLS"] = output["MINIMUM_MAPPING_UNIT_CELLS"].astype("int16")
    return output.reset_index(drop=True)


def build_geomorphic_units(
    config_path: str | Path = "config/data/environment_seascape.yaml",
) -> Path:
    """Classify, summarize, and save the configured H3 geomorphic units."""

    config = load_geomorphic_units_config(config_path)
    frame = _load_inputs(config)
    centers = _projected_centers(frame["H3_INDEX"], config.projected_crs)
    required_hops = sorted(
        {
            1,
            config.broad_neighborhood_rings,
            config.proportion_neighborhood_rings,
            config.canyon_density_rings,
        }
    )
    neighborhoods = load_water_neighborhoods(
        config.h3_resolution,
        max(required_hops),
        config_path,
    )
    neighborhood_lookups = {
        hops: water_neighborhood_lookup(neighborhoods, maximum_hops=hops) for hops in required_hops
    }
    terrain = _terrain_context(frame, centers, config, neighborhood_lookups)
    scores = _classification_scores(frame, terrain, config)
    cells = frame["H3_INDEX"].astype(str).tolist()
    _add_canyon_rim_scores(cells, scores, terrain, neighborhood_lookups[1])
    raw_labels, confidence = _select_labels(frame, scores)
    labels, component_sizes = _apply_minimum_mapping_unit(
        cells,
        raw_labels,
        scores,
        config.minimum_mapping_unit_cells,
        neighborhood_lookups[1],
    )
    changed = labels != raw_labels
    confidence[changed] *= 0.75
    confidence *= np.minimum(
        1.0,
        np.maximum(component_sizes, 1) / float(config.minimum_mapping_unit_cells),
    )
    distances, proportions = _distance_and_proportion_metrics(
        cells,
        labels,
        centers,
        neighborhood_lookups[config.proportion_neighborhood_rings],
    )
    canyon_density = _canyon_density(
        cells,
        labels,
        neighborhood_lookups[config.canyon_density_rings],
    )
    output = _build_output(
        frame,
        terrain,
        labels,
        confidence,
        component_sizes,
        distances,
        proportions,
        canyon_density,
        config.minimum_mapping_unit_cells,
    )
    if output["H3_INDEX"].nunique() != len(output):
        raise ValueError("Geomorphic-unit output contains duplicate H3_INDEX values.")
    if list(output.columns) != OUTPUT_COLUMNS:
        raise ValueError("Geomorphic-unit output schema does not match OUTPUT_COLUMNS.")
    unexpected_units = set(output["GEOMORPHIC_UNIT"]) - {
        *GEOMORPHIC_UNITS,
        "UNCLASSIFIED",
    }
    if unexpected_units:
        raise ValueError(f"Unexpected geomorphic units: {sorted(unexpected_units)}")
    publisher = stage_parquet_family(
        config.output_path.parent,
        ((output, config.output_path),),
    )
    network = load_water_network_config(config_path)
    neighborhood_path = network.neighborhood_path(config.h3_resolution)
    manifest = build_manifest(
        dataset_family="environment.seascape.geomorphic_units",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "GEBCO-derived Seascape Toolkit bathymetry and geomorphometry",
                "license": "GEBCO terms of use",
            }
        ],
        upstream_artifacts=[
            {"path": str(path), "checksum": checksum_artifact(path)}
            for path in (
                config.bathymetry_path,
                config.geomorphometry_path,
                config.waterbody_morphometry_path,
                neighborhood_path,
            )
        ],
        attribution=[
            {
                "text": "GEBCO Compilation Group; derived terrain classification by Seascape Toolkit",
                "license": "GEBCO terms of use",
            }
        ],
        source_completeness="complete",
        metadata={
            "classification_warning": (
                "Modeling-scale terrain classification; not an authoritative geological map."
            ),
            "neighborhood_semantics": "water-passable graph neighborhoods",
        },
    )
    publisher.publish_manifest(
        config.output_path.parent / "geomorphic_units_manifest.json",
        manifest,
    )
    counts = output["GEOMORPHIC_UNIT"].value_counts().sort_index().to_dict()
    LOGGER.info("Geomorphic-unit counts: %s", counts)
    LOGGER.info("Saved resolution-8 geomorphic units: %s", config.output_path)
    return config.output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(build_geomorphic_units(args.config))
    return 0


__all__ = [
    "DISTANCE_COLUMNS",
    "GEOMORPHIC_UNITS",
    "OUTPUT_COLUMNS",
    "PROPORTION_COLUMNS",
    "build_geomorphic_units",
    "load_geomorphic_units_config",
]


if __name__ == "__main__":
    raise SystemExit(main())
