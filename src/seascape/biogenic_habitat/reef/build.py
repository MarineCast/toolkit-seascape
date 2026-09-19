"""Build distinct rocky, biogenic, and deep-coral/sponge H3 habitat layers."""

from __future__ import annotations

import argparse
import gc
import logging
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely import area, intersection, union_all

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.benthic_substrate.bottom_hardness.build import (
    PREFIX as HARDNESS_PREFIX,
)
from seascape.benthic_substrate.bottom_hardness.build import (
    SECTION_NAME as HARDNESS_SECTION,
)
from seascape.benthic_substrate.classification.build import (
    PREFIX as SUBSTRATE_PREFIX,
)
from seascape.benthic_substrate.classification.download import (
    SECTION_NAME as SUBSTRATE_SECTION,
)
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.spatial_support.water_network.load import (
    load_model_area_support,
    load_radius_sum_operator,
    load_water_graph,
)
from seascape.spatial_support.water_network.radius_operator import (
    RadiusSumOperator,
)
from seascape.utils.artifacts import (
    build_manifest,
)
from seascape.utils.artifacts import checksum_artifact as _sha256
from seascape.utils.artifacts import (
    stage_parquet_family,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.config import resolve_project_path as _resolve
from seascape.utils.habitat_acquisition import (
    load_habitat_download_config,
)
from seascape.utils.habitat_configuration import (
    load_cell_geometry,
    load_habitat_surface_config,
    model_bbox_tuple,
)
from seascape.utils.habitat_surface import (
    habitat_network_metrics,
)
from seascape.utils.values import pipe_delimited_union as _pipe_union

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

LOGGER = logging.getLogger(__name__)
PREFIX = "REEF"
INVENTORY_COLUMNS = [
    "RECORD_ID",
    "REEF_SUBTYPE",
    "SOURCE_DATASET",
    "SOURCE_FEATURE_ID",
    "SOURCE_CLASS",
    "EVIDENCE_CLASS",
    "OBSERVED_VS_MODELED",
    "CONFIDENCE_CLASS",
    "geometry",
]


def _reef_processing(config_path: str | Path) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get(SECTION_NAME), SECTION_NAME)
    processing = _mapping(section.get("processing"), f"{SECTION_NAME}.processing")
    base_value = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = base_value if base_value.is_absolute() else project_root() / base_value
    processing["geomorphometry_path"] = _resolve(processing["geomorphometry_path"], base_dir)
    processing["bathymetry_path"] = _resolve(processing["bathymetry_path"], base_dir)
    return processing


def _inventory_frame(
    frame: Any,
    *,
    source_dataset: str,
    feature_id_column: str,
    class_column: str,
    subtype: Any,
) -> Any:
    import geopandas as gpd

    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    subtypes = (
        pd.Series([subtype] * len(frame), index=frame.index)
        if isinstance(subtype, str)
        else pd.Series(subtype, index=frame.index)
    )
    return gpd.GeoDataFrame(
        {
            "RECORD_ID": [
                f"{source_dataset}:{value}:{index}"
                for index, value in enumerate(frame[feature_id_column].astype(str))
            ],
            "REEF_SUBTYPE": subtypes.to_numpy(),
            "SOURCE_DATASET": source_dataset,
            "SOURCE_FEATURE_ID": frame[feature_id_column].astype("string").to_numpy(),
            "SOURCE_CLASS": frame[class_column].astype("string").to_numpy(),
            "EVIDENCE_CLASS": "generalized_mapping",
            "OBSERVED_VS_MODELED": "observed",
            "CONFIDENCE_CLASS": 2,
        },
        geometry=frame.geometry.to_numpy(),
        crs=frame.crs,
    ).loc[:, INVENTORY_COLUMNS]


def load_reef_inventory(config_path: str | Path = DEFAULT_CONFIG_PATH):
    """Load oyster/mussel mapping without claiming structural reef confirmation."""

    import geopandas as gpd

    config = load_habitat_download_config(SECTION_NAME, config_path)
    frames = []
    wdfw_path = config.raw_dir / str(config.sources["wa_wdfw_shellfish"]["raw_filename"])
    if wdfw_path.exists():
        wdfw = gpd.read_file(wdfw_path).to_crs("EPSG:4326")
        description = wdfw["shellfish_description"].astype(str).str.lower()
        wdfw = wdfw.loc[description.str.contains("oyster")].copy()
        frames.append(
            _inventory_frame(
                wdfw,
                source_dataset="WA_WDFW_MAPPED_OYSTER_BEDS",
                feature_id_column="OBJECTID",
                class_column="shellfish_description",
                subtype="oyster_bed",
            )
        )
    bc_path = config.raw_dir / str(config.sources["bc_shorezone_bivalves"]["raw_filename"])
    if bc_path.exists():
        bc = gpd.read_file(bc_path).to_crs("EPSG:4326")
        species = bc["SPECIES_NAME"].astype(str).str.lower()
        keep = species.str.contains("mytilus|crassostrea|ostrea", regex=True)
        bc = bc.loc[keep].copy()
        bc["REEF_SUBTYPE"] = np.where(
            bc["SPECIES_NAME"].astype(str).str.lower().str.contains("mytilus"),
            "mussel_bed",
            "oyster_bed",
        )
        bc["_GEOMETRY_KEY"] = bc.geometry.to_wkb(hex=True)
        bc = bc.drop_duplicates(["REEF_SUBTYPE", "_GEOMETRY_KEY"])
        frames.append(
            _inventory_frame(
                bc,
                source_dataset="BC_SHOREZONE_MAPPED_BIVALVES",
                feature_id_column="OBJECTID",
                class_column="SPECIES_NAME",
                subtype=bc["REEF_SUBTYPE"],
            )
        )
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        raise FileNotFoundError(
            "No public bivalve-bed sources are available. Run reef/download.py."
        )
    inventory = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    if inventory["RECORD_ID"].duplicated().any():
        raise ValueError("Normalized reef source record IDs must be unique.")
    return inventory.loc[:, INVENTORY_COLUMNS]


def _clip_score(values: pd.Series, maximum: float) -> np.ndarray:
    if maximum <= 0:
        raise ValueError("Rocky-reef score thresholds must be positive.")
    return np.clip(pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64") / maximum, 0, 1)


def _rocky_potential(
    base: pd.DataFrame,
    geomorphometry: pd.DataFrame,
    bathymetry: pd.DataFrame,
    processing: Mapping[str, Any],
) -> np.ndarray:
    terrain = (
        base[["H3_INDEX", "BOTTOM_HARDNESS_INDEX"]]
        .merge(
            geomorphometry[
                [
                    "H3_INDEX",
                    "SLOPE_MEAN_RING_1",
                    "LOCAL_RELIEF_RING_2_M",
                    "VECTOR_RUGGEDNESS_RING_1",
                ]
            ],
            on="H3_INDEX",
            how="left",
            validate="one_to_one",
        )
        .merge(
            bathymetry[["H3_INDEX", "BATHYMETRY_MEDIAN"]],
            on="H3_INDEX",
            how="left",
            validate="one_to_one",
        )
    )
    scores = {
        "hardness": pd.to_numeric(terrain["BOTTOM_HARDNESS_INDEX"], errors="coerce").to_numpy(),
        "slope": _clip_score(
            terrain["SLOPE_MEAN_RING_1"], float(processing["slope_full_score_degrees"])
        ),
        "relief": _clip_score(
            terrain["LOCAL_RELIEF_RING_2_M"], float(processing["relief_full_score_m"])
        ),
        "ruggedness": _clip_score(
            terrain["VECTOR_RUGGEDNESS_RING_1"], float(processing["ruggedness_full_score"])
        ),
    }
    depth = pd.to_numeric(terrain["BATHYMETRY_MEDIAN"], errors="coerce").to_numpy(dtype="float64")
    full_depth = float(processing["depth_full_score_max_m"])
    zero_depth = float(processing["depth_zero_score_m"])
    if zero_depth <= full_depth:
        raise ValueError("Rocky-reef depth zero-score threshold must exceed full-score depth.")
    scores["depth"] = np.clip((zero_depth - depth) / (zero_depth - full_depth), 0, 1)
    weights = {
        key: float(value)
        for key, value in _mapping(processing["potential_weights"], "potential_weights").items()
    }
    if set(weights) != set(scores) or any(value <= 0 for value in weights.values()):
        raise ValueError("Rocky-reef potential weights must be positive for every score family.")
    numerator = np.zeros(len(terrain), dtype="float64")
    denominator = np.zeros(len(terrain), dtype="float64")
    for name, values in scores.items():
        valid = np.isfinite(values)
        numerator[valid] += values[valid] * weights[name]
        denominator[valid] += weights[name]
    return np.divide(
        numerator,
        denominator,
        out=np.full(len(terrain), np.nan, dtype="float64"),
        where=denominator > 0,
    )


def _rocky_fraction(
    base: pd.DataFrame,
    substrate_confidence: pd.DataFrame,
    target_cells: list[str],
) -> tuple[pd.Series, pd.DataFrame]:
    """Return mapped hard-substrate fraction without converting unknown cells to zero."""

    substrate_conf = substrate_confidence.set_index("H3_INDEX").loc[target_cells]
    fraction = pd.to_numeric(base["SUBSTRATE_HARD_SUBSTRATE_FRAC"], errors="coerce").astype(
        "float64"
    )
    unmapped = substrate_conf["SUBSTRATE_UNMAPPED_AREA"].fillna(True).to_numpy(dtype=bool)
    fraction.loc[unmapped] = np.nan
    return fraction, substrate_conf


def _biogenic_metrics(
    inventory: Any,
    cells: Any,
    support: pd.DataFrame,
    graph: Any,
    radius_operator: RadiusSumOperator,
    *,
    equal_area_crs: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    projected_cells = cells.to_crs(equal_area_crs)
    projected_inventory = inventory.to_crs(equal_area_crs)
    target_cells = support["H3_INDEX"].astype(str).tolist()
    water_area = support["WATER_AREA_M2"].to_numpy(dtype="float64")
    subtype_area: dict[str, np.ndarray] = {}
    present_cells: set[str] = set()
    source_sets: list[set[str]] = [set() for _ in target_cells]
    confidence = np.zeros(len(target_cells), dtype="int8")
    for subtype in ("oyster_bed", "mussel_bed"):
        records = projected_inventory.loc[projected_inventory["REEF_SUBTYPE"].eq(subtype)]
        if records.empty:
            subtype_area[subtype] = np.zeros(len(target_cells), dtype="float64")
            continue
        geometry = union_all(records.geometry.to_numpy())
        subtype_area[subtype] = np.asarray(
            area(intersection(projected_cells.geometry.to_numpy(), geometry)),
            dtype="float64",
        )
        hit = np.flatnonzero(subtype_area[subtype] > 0)
        present_cells.update(target_cells[index] for index in hit)
        for index in hit:
            cell_geometry = projected_cells.geometry.iloc[index]
            matching = records.loc[records.geometry.intersects(cell_geometry)]
            source_sets[index].update(matching["SOURCE_DATASET"].astype(str))
            confidence[index] = max(confidence[index], int(matching["CONFIDENCE_CLASS"].max()))
    total_area = np.minimum(
        water_area,
        subtype_area["oyster_bed"] + subtype_area["mussel_bed"],
    )
    area_series = pd.Series(total_area, index=target_cells)
    distance, area_5km, distance_qc = habitat_network_metrics(
        graph, target_cells, present_cells, area_series, radius_operator
    )
    values = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "OYSTER_BED_FRAC": np.clip(
                np.divide(
                    subtype_area["oyster_bed"],
                    water_area,
                    out=np.zeros_like(water_area),
                    where=water_area > 0,
                ),
                0,
                1,
            ),
            "MUSSEL_BED_FRAC": np.clip(
                np.divide(
                    subtype_area["mussel_bed"],
                    water_area,
                    out=np.zeros_like(water_area),
                    where=water_area > 0,
                ),
                0,
                1,
            ),
            "BIOGENIC_REEF_FRAC": np.clip(
                np.divide(
                    total_area,
                    water_area,
                    out=np.zeros_like(water_area),
                    where=water_area > 0,
                ),
                0,
                1,
            ),
            "BIOGENIC_REEF_DISTANCE_M": distance,
            "BIOGENIC_REEF_AREA_WITHIN_5KM_M2": area_5km,
            "BIOGENIC_REEF_DISTANCE_QC_REASON": distance_qc,
        }
    )
    certainty = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "BIOGENIC_REEF_SOURCE_DATASETS": [
                "|".join(sorted(values)) or None for values in source_sets
            ],
            "BIOGENIC_REEF_SOURCE_COUNT": [len(values) for values in source_sets],
            "BIOGENIC_REEF_CONFIDENCE": confidence,
            "BIOGENIC_REEF_OBSERVED_VS_MODELED": np.where(
                confidence > 0, "observed_generalized_bivalve_bed", None
            ),
            "BIOGENIC_REEF_UNMAPPED_AREA": True,
        }
    )
    return values, certainty


def _r8_tables(
    inventory: Any,
    support: pd.DataFrame,
    cells: Any,
    graph: Any,
    radius_operator: RadiusSumOperator,
    processing: Mapping[str, Any],
    substrate_features: pd.DataFrame,
    substrate_confidence: pd.DataFrame,
    hardness_features: pd.DataFrame,
    geomorphometry: pd.DataFrame,
    bathymetry: pd.DataFrame,
    *,
    equal_area_crs: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_cells = support["H3_INDEX"].astype(str).tolist()
    base = (
        pd.DataFrame({"H3_INDEX": target_cells})
        .merge(
            substrate_features,
            on="H3_INDEX",
            how="left",
            validate="one_to_one",
        )
        .merge(
            hardness_features[["H3_INDEX", "BOTTOM_HARDNESS_INDEX"]],
            on="H3_INDEX",
            how="left",
            validate="one_to_one",
        )
    )
    rocky_fraction, substrate_conf = _rocky_fraction(base, substrate_confidence, target_cells)
    rocky_area = rocky_fraction.fillna(0.0).to_numpy() * support["WATER_AREA_M2"].to_numpy(
        dtype="float64"
    )
    rocky_area_5km = radius_operator.apply(
        rocky_area,
        eligible_sources=np.isfinite(rocky_area) & (rocky_area > 0),
    )
    potential = _rocky_potential(base, geomorphometry, bathymetry, processing)
    biogenic, biogenic_confidence = _biogenic_metrics(
        inventory,
        cells,
        support,
        graph,
        radius_operator,
        equal_area_crs=equal_area_crs,
    )
    lineage = support.set_index("H3_INDEX").loc[target_cells]
    features = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "H3_RESOLUTION": 8,
            "ROCKY_REEF_FRAC": rocky_fraction.to_numpy(),
            "ROCKY_REEF_DISTANCE_M": base["SUBSTRATE_DISTANCE_TO_HARD_SUBSTRATE_M"].to_numpy(),
            "ROCKY_REEF_AREA_WITHIN_5KM_M2": rocky_area_5km,
            "POTENTIAL_ROCKY_REEF_SUITABILITY": potential,
            "BIOGENIC_REEF_FRAC": biogenic["BIOGENIC_REEF_FRAC"].to_numpy(),
            "BIOGENIC_REEF_DISTANCE_M": biogenic["BIOGENIC_REEF_DISTANCE_M"].to_numpy(),
            "BIOGENIC_REEF_AREA_WITHIN_5KM_M2": biogenic[
                "BIOGENIC_REEF_AREA_WITHIN_5KM_M2"
            ].to_numpy(),
            "OYSTER_BED_FRAC": biogenic["OYSTER_BED_FRAC"].to_numpy(),
            "MUSSEL_BED_FRAC": biogenic["MUSSEL_BED_FRAC"].to_numpy(),
            "DEEP_CORAL_SPONGE_FRAC": np.nan,
            "DEEP_CORAL_SPONGE_DISTANCE_M": np.nan,
            "DEEP_CORAL_SPONGE_AREA_WITHIN_5KM_M2": np.nan,
            "WATER_COMPONENT_ID": lineage["WATER_COMPONENT_ID"].to_numpy(),
            "NETWORK_CONNECTOR_METHOD": lineage["CONNECTOR_METHOD"].to_numpy(),
            "NETWORK_CONNECTOR_DISTANCE_M": lineage["CONNECTOR_DISTANCE_M"].to_numpy(),
            "NETWORK_DISTANCE_QC_REASON": base["NETWORK_DISTANCE_QC_REASON"].to_numpy(),
        }
    )
    rocky_confidence = np.where(
        rocky_fraction.fillna(0.0).to_numpy() > 0,
        substrate_conf["SUBSTRATE_CONFIDENCE"].to_numpy(dtype="int8"),
        np.where(np.isfinite(potential), 1, 0),
    )
    confidence = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "H3_RESOLUTION": 8,
            "ROCKY_REEF_CONFIDENCE": rocky_confidence,
            "ROCKY_REEF_OBSERVED_VS_MODELED": np.where(
                rocky_fraction.fillna(0.0).to_numpy() > 0,
                "modeled_dbseabed_substrate_plus_modeled_potential",
                np.where(np.isfinite(potential), "modeled_potential", None),
            ),
            "ROCKY_REEF_UNMAPPED_AREA": substrate_conf["SUBSTRATE_UNMAPPED_AREA"].to_numpy(),
            "BIOGENIC_REEF_SOURCE_DATASETS": biogenic_confidence[
                "BIOGENIC_REEF_SOURCE_DATASETS"
            ].to_numpy(),
            "BIOGENIC_REEF_SOURCE_COUNT": biogenic_confidence[
                "BIOGENIC_REEF_SOURCE_COUNT"
            ].to_numpy(),
            "BIOGENIC_REEF_CONFIDENCE": biogenic_confidence["BIOGENIC_REEF_CONFIDENCE"].to_numpy(),
            "BIOGENIC_REEF_OBSERVED_VS_MODELED": biogenic_confidence[
                "BIOGENIC_REEF_OBSERVED_VS_MODELED"
            ].to_numpy(),
            "BIOGENIC_REEF_UNMAPPED_AREA": True,
            "DEEP_CORAL_SPONGE_CONFIDENCE": 0,
            "DEEP_CORAL_SPONGE_DATA_AVAILABILITY": "no_public_export_in_current_pipeline",
            "DEEP_CORAL_SPONGE_UNMAPPED_AREA": True,
            "REEF_CONFIDENCE": np.maximum(
                rocky_confidence,
                biogenic_confidence["BIOGENIC_REEF_CONFIDENCE"].to_numpy(dtype="int8"),
            ),
            "REEF_UNMAPPED_AREA": True,
        }
    )
    return features, confidence


def _r6_tables(
    features: pd.DataFrame,
    confidence: pd.DataFrame,
    crosswalk: pd.DataFrame,
    parent_support: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    child = features.merge(
        crosswalk[["CHILD_H3_INDEX", "PARENT_H3_INDEX", "CHILD_WATER_AREA_M2"]],
        left_on="H3_INDEX",
        right_on="CHILD_H3_INDEX",
        how="left",
        validate="one_to_one",
    )
    child_conf = confidence.merge(
        crosswalk[["CHILD_H3_INDEX", "PARENT_H3_INDEX"]],
        left_on="H3_INDEX",
        right_on="CHILD_H3_INDEX",
        how="left",
        validate="one_to_one",
    )
    support = parent_support.set_index("H3_INDEX")
    fraction_columns = [
        "ROCKY_REEF_FRAC",
        "BIOGENIC_REEF_FRAC",
        "OYSTER_BED_FRAC",
        "MUSSEL_BED_FRAC",
        "DEEP_CORAL_SPONGE_FRAC",
    ]
    mean_columns = [
        "ROCKY_REEF_AREA_WITHIN_5KM_M2",
        "POTENTIAL_ROCKY_REEF_SUITABILITY",
        "BIOGENIC_REEF_AREA_WITHIN_5KM_M2",
        "DEEP_CORAL_SPONGE_AREA_WITHIN_5KM_M2",
    ]
    distance_columns = [
        "ROCKY_REEF_DISTANCE_M",
        "BIOGENIC_REEF_DISTANCE_M",
        "DEEP_CORAL_SPONGE_DISTANCE_M",
    ]
    feature_rows = []
    confidence_rows = []
    for parent, rows in child.groupby("PARENT_H3_INDEX", sort=True):
        weights = rows["CHILD_WATER_AREA_M2"].astype(float)
        parent_area = float(weights.sum())
        row: dict[str, Any] = {
            "H3_INDEX": str(parent),
            "H3_RESOLUTION": 6,
            "NATIVE_CHILD_WATER_AREA_M2": parent_area,
        }
        for column in fraction_columns:
            valid = rows[column].notna()
            row[column] = (
                float((rows.loc[valid, column].astype(float) * weights.loc[valid]).sum())
                / parent_area
                if valid.all()
                else np.nan
            )
        for column in mean_columns:
            valid = rows[column].notna()
            row[column] = (
                float(np.average(rows.loc[valid, column].astype(float), weights=weights.loc[valid]))
                if valid.any()
                else np.nan
            )
        for column in distance_columns:
            row[column] = rows[column].min(skipna=True)
        row.update(
            {
                "WATER_COMPONENT_ID": support.loc[str(parent), "WATER_COMPONENT_ID"],
                "NETWORK_CONNECTOR_METHOD": support.loc[str(parent), "CONNECTOR_METHOD"],
                "NETWORK_CONNECTOR_DISTANCE_M": support.loc[str(parent), "CONNECTOR_DISTANCE_M"],
                "NETWORK_DISTANCE_QC_REASON": (
                    None
                    if rows["ROCKY_REEF_DISTANCE_M"].notna().any()
                    else "no_child_with_reachable_modeled_rocky_reef"
                ),
            }
        )
        feature_rows.append(row)
    for parent, rows in child_conf.groupby("PARENT_H3_INDEX", sort=True):
        confidence_rows.append(
            {
                "H3_INDEX": str(parent),
                "H3_RESOLUTION": 6,
                "ROCKY_REEF_CONFIDENCE": int(rows["ROCKY_REEF_CONFIDENCE"].max()),
                "ROCKY_REEF_OBSERVED_VS_MODELED": _pipe_union(
                    rows["ROCKY_REEF_OBSERVED_VS_MODELED"]
                ),
                "ROCKY_REEF_UNMAPPED_AREA": bool(rows["ROCKY_REEF_UNMAPPED_AREA"].any()),
                "BIOGENIC_REEF_SOURCE_DATASETS": _pipe_union(rows["BIOGENIC_REEF_SOURCE_DATASETS"]),
                "BIOGENIC_REEF_SOURCE_COUNT": (
                    len((_pipe_union(rows["BIOGENIC_REEF_SOURCE_DATASETS"]) or "").split("|"))
                    if _pipe_union(rows["BIOGENIC_REEF_SOURCE_DATASETS"])
                    else 0
                ),
                "BIOGENIC_REEF_CONFIDENCE": int(rows["BIOGENIC_REEF_CONFIDENCE"].max()),
                "BIOGENIC_REEF_OBSERVED_VS_MODELED": _pipe_union(
                    rows["BIOGENIC_REEF_OBSERVED_VS_MODELED"]
                ),
                "BIOGENIC_REEF_UNMAPPED_AREA": True,
                "DEEP_CORAL_SPONGE_CONFIDENCE": 0,
                "DEEP_CORAL_SPONGE_DATA_AVAILABILITY": "no_public_export_in_current_pipeline",
                "DEEP_CORAL_SPONGE_UNMAPPED_AREA": True,
                "REEF_CONFIDENCE": int(rows["REEF_CONFIDENCE"].max()),
                "REEF_UNMAPPED_AREA": True,
            }
        )
    return pd.DataFrame(feature_rows), pd.DataFrame(confidence_rows)


def build_reef_habitat(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    processing = _reef_processing(config_path)
    inventory = load_reef_inventory(config_path)
    bbox = model_bbox_tuple(config)
    support_r8 = load_model_area_support(8, config_path)
    cells = load_cell_geometry(config, support_r8)
    graph = load_water_graph(8, config_path, bbox=bbox, bbox_buffer_m=35_000.0)
    radius_operator = load_radius_sum_operator(config_path)
    network = load_water_network_config(config_path)
    substrate = load_habitat_surface_config(SUBSTRATE_SECTION, SUBSTRATE_PREFIX, config_path)
    hardness = load_habitat_surface_config(HARDNESS_SECTION, HARDNESS_PREFIX, config_path)
    required = [
        substrate.feature_path(8),
        substrate.confidence_path(8),
        hardness.feature_path(8),
        Path(processing["geomorphometry_path"]),
        Path(processing["bathymetry_path"]),
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Reef inputs are missing; build substrate, hardness, bathymetry, and "
            "geomorphometry first: " + ", ".join(map(str, missing))
        )
    r8_features, r8_confidence = _r8_tables(
        inventory,
        support_r8,
        cells,
        graph,
        radius_operator,
        processing,
        pd.read_parquet(required[0]),
        pd.read_parquet(required[1]),
        pd.read_parquet(required[2]),
        pd.read_parquet(required[3]),
        pd.read_parquet(required[4]),
        equal_area_crs=config.equal_area_crs,
    )
    del graph, cells, support_r8
    gc.collect()
    crosswalk = pd.read_parquet(config.parent_child_path)
    crosswalk = crosswalk.loc[
        crosswalk["CHILD_H3_INDEX"].astype(str).isin(set(r8_features["H3_INDEX"]))
    ].copy()
    parents = set(crosswalk["PARENT_H3_INDEX"].astype(str))
    support_r6 = load_model_area_support(6, config_path)
    support_r6 = support_r6.loc[support_r6["H3_INDEX"].astype(str).isin(parents)].copy()
    crosswalk = crosswalk.loc[
        crosswalk["PARENT_H3_INDEX"].astype(str).isin(set(support_r6["H3_INDEX"].astype(str)))
    ].copy()
    r6_features, r6_confidence = _r6_tables(r8_features, r8_confidence, crosswalk, support_r6)
    paths = (
        config.inventory_path,
        config.feature_path(8),
        config.confidence_path(8),
        config.feature_path(6),
        config.confidence_path(6),
    )
    publisher = stage_parquet_family(
        config.processed_dir,
        tuple(
            zip(
                (inventory, r8_features, r8_confidence, r6_features, r6_confidence),
                paths,
                strict=True,
            )
        ),
    )
    download = load_habitat_download_config(SECTION_NAME, config_path)
    sources: list[dict[str, Any]] = []
    for name, source in download.sources.items():
        raw_filename = source.get("raw_filename")
        raw_path = download.raw_dir / str(raw_filename) if raw_filename else None
        record: dict[str, Any] = {
            "name": name,
            "license": source.get("license") or "See authoritative source terms",
            "attribution": source.get("attribution") or name,
            "status": "disabled" if not bool(source.get("enabled", True)) else "configured",
            "source_url": source.get("url", source.get("layer_url", source.get("dataset_url"))),
        }
        if raw_path is not None:
            record["path"] = str(raw_path)
            if raw_path.exists():
                record["checksum"] = _sha256(raw_path)
                record["status"] = "available"
            elif bool(source.get("enabled", True)):
                record["status"] = "not_materialized"
        sources.append(record)
    manifest = build_manifest(
        dataset_family="environment.seascape.reef_habitat",
        run_id=publisher.run_id,
        resolved_config={"surface": asdict(config), "processing": processing},
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=sources,
        upstream_artifacts=[
            {"path": str(path), "checksum": _sha256(path)}
            for path in [
                *required,
                config.clipped_geometry_path,
                config.parent_child_path,
                network.radius_sum_operator_path,
                network.manifest_path,
            ]
        ],
        attribution=[
            {"text": source["attribution"], "license": source["license"]} for source in sources
        ],
        source_completeness="partial",
        metadata={
            "radius_operator_lineage": {
                "path": str(network.radius_sum_operator_path),
                "checksum": _sha256(network.radius_sum_operator_path),
                "radius_m": radius_operator.radius_m,
                "support_hash": radius_operator.support_hash,
                "source_support_hash": radius_operator.source_support_hash,
                "graph_checksum": radius_operator.graph_checksum,
            },
            "source_warning": (
                "B.C. sponge-reef data are access-only; deep coral and sponge values remain "
                "explicitly unavailable rather than being treated as absence."
            ),
        },
    )
    publisher.publish_manifest(config.manifest_path, manifest)
    return (*paths, config.manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in build_reef_habitat(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
