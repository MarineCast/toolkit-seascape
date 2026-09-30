"""Build cross-border H3 substrate composition from dbSEABED grids."""

from __future__ import annotations

import argparse
import gc
import logging
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from seascape.core.config.paths import project_root
from seascape.spatial_support.water_network.load import (
    load_model_area_support,
    load_water_graph,
)
from seascape.utils.artifacts import (
    build_manifest,
    stage_parquet_family,
)
from seascape.utils.artifacts import checksum_artifact as _sha256
from seascape.utils.config import load_processing_config
from seascape.utils.habitat_acquisition import (
    load_habitat_download_config,
)
from seascape.utils.habitat_configuration import (
    load_habitat_surface_config,
    model_bbox_tuple,
)
from seascape.utils.habitat_raster import (
    sample_raster_bilinear,
    validate_percentage,
)
from seascape.utils.habitat_surface import (
    habitat_network_metrics,
)
from seascape.utils.values import pipe_delimited_union as _pipe_union

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

LOGGER = logging.getLogger(__name__)
PREFIX = "SUBSTRATE"
CLASSES = ("ROCK", "BOULDER", "COBBLE", "GRAVEL", "SAND", "MUD", "MIXED")
SEDIMENT_CLASSES = ("GRAVEL", "SAND", "MUD")
DBSEABED_VARIABLES = ("rock", "gravel", "sand", "mud")


def load_substrate_inventory(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> pd.DataFrame:
    """Validate and inventory the four dbSEABED percentage rasters."""

    import rasterio

    config = load_habitat_download_config(SECTION_NAME, config_path)
    rows = []
    for variable in DBSEABED_VARIABLES:
        source_name = f"dbseabed_{variable}"
        source = config.sources[source_name]
        path = config.raw_dir / str(source["raw_filename"])
        if not path.exists():
            raise FileNotFoundError(
                f"Missing dbSEABED {variable} raster: {path}. Run the substrate "
                "download stage before building."
            )
        if path.stat().st_size <= 0:
            raise ValueError(f"dbSEABED raster is empty: {path}")
        with rasterio.open(path) as raster:
            if raster.crs is None:
                raise ValueError(f"dbSEABED raster has no CRS: {path}")
            rows.append(
                {
                    "SOURCE_DATASET": "DBSEABED_GLOBAL_INTERPOLATED_GRID_VER202512",
                    "VARIABLE": variable,
                    "UNITS": str(source.get("units", "percent")),
                    "EVIDENCE_BASIS": "interpolated_raster",
                    "OBSERVED_VS_MODELED": "modeled",
                    "SOURCE_URL": str(
                        source.get("dataset_url", "https://dbseabed.com/")
                    ),
                    "PATH": str(path),
                    "SHA256": _sha256(path),
                    "CRS": raster.crs.to_string(),
                    "RASTER_WIDTH": raster.width,
                    "RASTER_HEIGHT": raster.height,
                    "PIXEL_SIZE_X": abs(float(raster.transform.a)),
                    "PIXEL_SIZE_Y": abs(float(raster.transform.e)),
                    "GRID_TRANSFORM": ",".join(
                        format(float(value), ".12g") for value in raster.transform
                    ),
                }
            )
    inventory = pd.DataFrame(rows)
    if set(inventory["VARIABLE"]) != set(DBSEABED_VARIABLES):
        raise ValueError("dbSEABED inventory must contain rock, gravel, sand, and mud.")
    if not inventory["UNITS"].str.lower().eq("percent").all():
        raise ValueError("dbSEABED input rasters must be configured in percent units.")
    grid_columns = [
        "CRS",
        "RASTER_WIDTH",
        "RASTER_HEIGHT",
        "PIXEL_SIZE_X",
        "PIXEL_SIZE_Y",
        "GRID_TRANSFORM",
    ]
    if any(inventory[column].nunique(dropna=False) != 1 for column in grid_columns):
        raise ValueError(
            "dbSEABED rock, gravel, sand, and mud rasters must share one grid."
        )
    return inventory


def _close_composition(
    rock: np.ndarray,
    gravel: np.ndarray,
    sand: np.ndarray,
    mud: np.ndarray,
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Keep rock presence separate from source sediment texture fractions."""

    valid = (
        np.isfinite(rock) & np.isfinite(gravel) & np.isfinite(sand) & np.isfinite(mud)
    )
    for name, values in (
        ("rock", rock),
        ("gravel", gravel),
        ("sand", sand),
        ("mud", mud),
    ):
        finite = values[np.isfinite(values)]
        if finite.size and (finite.min() < 0 or finite.max() > 1):
            raise ValueError(f"dbSEABED {name} fraction must be within [0, 1].")
    classes = {name: np.full(rock.shape, np.nan, dtype="float64") for name in CLASSES}
    classes["ROCK"] = rock.astype("float64", copy=True)
    classes["GRAVEL"] = gravel.astype("float64", copy=True)
    classes["SAND"] = sand.astype("float64", copy=True)
    classes["MUD"] = mud.astype("float64", copy=True)
    return classes, valid


def _entropy(classes: dict[str, np.ndarray]) -> np.ndarray:
    probabilities = np.column_stack([classes[name] for name in SEDIMENT_CLASSES])
    total = probabilities.sum(axis=1)
    supported = np.isfinite(probabilities).all(axis=1) & np.isclose(
        total, 1.0, atol=1e-3
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(probabilities > 0, probabilities * np.log(probabilities), 0.0)
    values = -terms.sum(axis=1) / math.log(len(SEDIMENT_CLASSES))
    values[~supported] = np.nan
    return values


def _sediment_texture_status(classes: dict[str, np.ndarray]) -> np.ndarray:
    values = np.column_stack([classes[name] for name in SEDIMENT_CLASSES])
    valid = np.isfinite(values).all(axis=1)
    total = np.where(valid, values.sum(axis=1), np.nan)
    return np.where(
        ~valid,
        "source_texture_unavailable",
        np.where(
            np.isclose(total, 1.0, atol=1e-3),
            "closed_sediment_texture",
            np.where(
                total == 0, "no_sediment_texture_mass", "source_texture_not_closed"
            ),
        ),
    )


def _r8_tables(
    inventory: pd.DataFrame,
    support: pd.DataFrame,
    graph: Any,
    *,
    hard_seed_min_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not 0 < hard_seed_min_fraction <= 1:
        raise ValueError("Hard-substrate seed fraction must be in (0, 1].")
    target_cells = support["H3_INDEX"].astype(str).tolist()
    longitudes = support["REPRESENTATIVE_POINT_LONGITUDE"].to_numpy(dtype="float64")
    latitudes = support["REPRESENTATIVE_POINT_LATITUDE"].to_numpy(dtype="float64")
    sampled: dict[str, np.ndarray] = {}
    validity: dict[str, np.ndarray] = {}
    for row in inventory.itertuples(index=False):
        values, valid = sample_raster_bilinear(Path(row.PATH), longitudes, latitudes)
        sampled[str(row.VARIABLE)] = validate_percentage(values, str(row.VARIABLE))
        validity[str(row.VARIABLE)] = valid
    classes, valid = _close_composition(
        sampled["rock"], sampled["gravel"], sampled["sand"], sampled["mud"]
    )
    valid &= np.logical_and.reduce([validity[name] for name in DBSEABED_VARIABLES])
    water_area = support["WATER_AREA_M2"].to_numpy(dtype="float64")
    hard_fraction = classes["ROCK"].copy()
    # Presence is a modeled source score, not surveyed areal rock cover.
    hard_area = np.zeros_like(water_area)
    hard_cells = {
        cell
        for cell, fraction in zip(target_cells, hard_fraction, strict=True)
        if np.isfinite(fraction) and fraction >= hard_seed_min_fraction
    }
    distance, _, distance_qc = habitat_network_metrics(
        graph,
        target_cells,
        hard_cells,
        pd.Series(hard_area, index=target_cells),
        None,
    )
    lineage = support.set_index("H3_INDEX").loc[target_cells]
    features = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "H3_RESOLUTION": 8,
            **{f"SUBSTRATE_{name}_FRAC": classes[name] for name in CLASSES},
            "SUBSTRATE_INTERPOLATED_COVERAGE_FRAC": np.full(len(valid), np.nan),
            "SUBSTRATE_POINT_SAMPLE_AVAILABLE": valid,
            "SUBSTRATE_HARD_SUBSTRATE_FRAC": np.full(len(valid), np.nan),
            "SUBSTRATE_MODELED_ROCK_PRESENCE_SCORE": hard_fraction,
            "SUBSTRATE_HETEROGENEITY": _entropy(classes),
            "SUBSTRATE_SEDIMENT_TEXTURE_STATUS": _sediment_texture_status(classes),
            "SUBSTRATE_DISTANCE_TO_HARD_SUBSTRATE_M": np.full(len(valid), np.nan),
            "SUBSTRATE_MODELED_ROCK_PRESENCE_DISTANCE_M": distance,
            "SUBSTRATE_MODELED_ROCK_PRESENCE_DISTANCE_QC_REASON": distance_qc,
            "WATER_COMPONENT_ID": lineage["WATER_COMPONENT_ID"].to_numpy(),
            "NETWORK_CONNECTOR_METHOD": lineage["CONNECTOR_METHOD"].to_numpy(),
            "NETWORK_CONNECTOR_DISTANCE_M": lineage["CONNECTOR_DISTANCE_M"].to_numpy(),
            "NETWORK_DISTANCE_QC_REASON": np.full(
                len(valid), "hard_substrate_fraction_unverified", dtype=object
            ),
        }
    )
    confidence = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "H3_RESOLUTION": 8,
            "SUBSTRATE_SOURCE_DATASETS": np.where(
                valid, "DBSEABED_GLOBAL_INTERPOLATED_GRID_VER202512", None
            ),
            "SUBSTRATE_SOURCE_COUNT": valid.astype("int8"),
            "SUBSTRATE_EVIDENCE_BASIS": np.where(valid, "interpolated_raster", None),
            "SUBSTRATE_OBSERVED_VS_MODELED": np.where(valid, "modeled", None),
            "SUBSTRATE_CONFIDENCE": valid.astype("int8"),
            "SUBSTRATE_UNMAPPED_AREA": np.ones(len(valid), dtype=bool),
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
    feature_rows: list[dict[str, Any]] = []
    confidence_rows: list[dict[str, Any]] = []
    for parent, rows in child.groupby("PARENT_H3_INDEX", sort=True):
        weights = rows["CHILD_WATER_AREA_M2"].astype("float64")
        valid = rows["SUBSTRATE_POINT_SAMPLE_AVAILABLE"].astype(bool)
        parent_area = float(weights.sum())
        class_values: dict[str, float] = {}
        for name in CLASSES:
            values = rows[f"SUBSTRATE_{name}_FRAC"]
            class_values[name] = (
                float(
                    np.average(
                        values.loc[valid].astype(float), weights=weights.loc[valid]
                    )
                )
                if valid.any()
                else np.nan
            )
        hard_fraction = np.nan
        feature_rows.append(
            {
                "H3_INDEX": str(parent),
                "H3_RESOLUTION": 6,
                "NATIVE_CHILD_WATER_AREA_M2": parent_area,
                **{f"SUBSTRATE_{name}_FRAC": class_values[name] for name in CLASSES},
                "SUBSTRATE_INTERPOLATED_COVERAGE_FRAC": np.nan,
                "SUBSTRATE_POINT_SAMPLE_AVAILABLE": bool(valid.any()),
                "SUBSTRATE_HARD_SUBSTRATE_FRAC": hard_fraction,
                "SUBSTRATE_MODELED_ROCK_PRESENCE_SCORE": class_values["ROCK"],
                "SUBSTRATE_HETEROGENEITY": (
                    _entropy(
                        {
                            name: np.asarray([class_values[name]], dtype="float64")
                            for name in CLASSES
                        }
                    )[0]
                    if valid.any()
                    else np.nan
                ),
                "SUBSTRATE_SEDIMENT_TEXTURE_STATUS": _sediment_texture_status(
                    {
                        name: np.asarray([class_values[name]], dtype="float64")
                        for name in CLASSES
                    }
                )[0],
                "SUBSTRATE_DISTANCE_TO_HARD_SUBSTRATE_M": rows[
                    "SUBSTRATE_DISTANCE_TO_HARD_SUBSTRATE_M"
                ].min(skipna=True),
                "SUBSTRATE_MODELED_ROCK_PRESENCE_DISTANCE_M": rows[
                    "SUBSTRATE_MODELED_ROCK_PRESENCE_DISTANCE_M"
                ].min(skipna=True),
                "SUBSTRATE_MODELED_ROCK_PRESENCE_DISTANCE_QC_REASON": (
                    None
                    if rows["SUBSTRATE_MODELED_ROCK_PRESENCE_DISTANCE_M"].notna().any()
                    else "no_child_with_reachable_modeled_rock_presence"
                ),
                "WATER_COMPONENT_ID": support.loc[str(parent), "WATER_COMPONENT_ID"],
                "NETWORK_CONNECTOR_METHOD": support.loc[
                    str(parent), "CONNECTOR_METHOD"
                ],
                "NETWORK_CONNECTOR_DISTANCE_M": support.loc[
                    str(parent), "CONNECTOR_DISTANCE_M"
                ],
                "NETWORK_DISTANCE_QC_REASON": "hard_substrate_fraction_unverified",
            }
        )
    for parent, rows in child_conf.groupby("PARENT_H3_INDEX", sort=True):
        sources = _pipe_union(rows["SUBSTRATE_SOURCE_DATASETS"])
        confidence_rows.append(
            {
                "H3_INDEX": str(parent),
                "H3_RESOLUTION": 6,
                "SUBSTRATE_SOURCE_DATASETS": sources,
                "SUBSTRATE_SOURCE_COUNT": 1 if sources else 0,
                "SUBSTRATE_EVIDENCE_BASIS": _pipe_union(
                    rows["SUBSTRATE_EVIDENCE_BASIS"]
                ),
                "SUBSTRATE_OBSERVED_VS_MODELED": _pipe_union(
                    rows["SUBSTRATE_OBSERVED_VS_MODELED"]
                ),
                "SUBSTRATE_CONFIDENCE": int(rows["SUBSTRATE_CONFIDENCE"].max()),
                "SUBSTRATE_UNMAPPED_AREA": True,
            }
        )
    return pd.DataFrame(feature_rows), pd.DataFrame(confidence_rows)


def build_substrate_classification(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    processing = load_processing_config(config_path, SECTION_NAME)
    resampling = str(processing.get("raster_resampling", "bilinear")).strip().lower()
    if resampling != "bilinear":
        raise ValueError(
            "dbSEABED raster_resampling currently supports only 'bilinear'."
        )
    inventory = load_substrate_inventory(config_path)
    bbox = model_bbox_tuple(config)
    support_r8 = load_model_area_support(8, config_path)
    graph = load_water_graph(8, config_path, bbox=bbox, bbox_buffer_m=35_000.0)
    r8_features, r8_confidence = _r8_tables(
        inventory,
        support_r8,
        graph,
        hard_seed_min_fraction=float(
            processing.get("hard_substrate_seed_min_fraction", 0.5)
        ),
    )
    del graph, support_r8
    gc.collect()
    crosswalk = pd.read_parquet(config.parent_child_path)
    crosswalk = crosswalk.loc[
        crosswalk["CHILD_H3_INDEX"].astype(str).isin(set(r8_features["H3_INDEX"]))
    ].copy()
    parents = set(crosswalk["PARENT_H3_INDEX"].astype(str))
    support_r6 = load_model_area_support(6, config_path)
    support_r6 = support_r6.loc[support_r6["H3_INDEX"].astype(str).isin(parents)].copy()
    crosswalk = crosswalk.loc[
        crosswalk["PARENT_H3_INDEX"]
        .astype(str)
        .isin(set(support_r6["H3_INDEX"].astype(str)))
    ].copy()
    r6_features, r6_confidence = _r6_tables(
        r8_features, r8_confidence, crosswalk, support_r6
    )
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
    source_by_variable = {
        str(source.get("variable", "")).upper(): (name, source)
        for name, source in download.sources.items()
    }
    source_records = []
    for row in inventory.itertuples(index=False):
        name, source = source_by_variable[str(row.VARIABLE).upper()]
        source_records.append(
            {
                "name": name,
                "path": str(row.PATH),
                "checksum": str(row.SHA256),
                "license": source.get("license") or "License not documented by source",
                "attribution": source.get("attribution"),
                "dataset_version": source.get("dataset_version"),
            }
        )
    manifest = build_manifest(
        dataset_family="environment.seascape.benthic_substrate_classification",
        run_id=publisher.run_id,
        resolved_config={"surface": asdict(config), "processing": processing},
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=source_records,
        upstream_artifacts=[
            {
                "path": str(config.parent_child_path),
                "checksum": _sha256(config.parent_child_path),
            }
        ],
        attribution=[
            {
                "text": record.get("attribution") or record["name"],
                "license": record["license"],
            }
            for record in source_records
        ],
        source_completeness="complete",
        metadata={
            "scientific_method_version": "separate_rock_presence_sediment_texture_v2",
            "sample_support": "bilinear representative-point sample from native 0.1-degree modeled grid",
            "rock_measurement": "modeled rock-presence score; not an areal cover fraction",
            "sediment_measurement": "source gravel, sand, and mud texture percentages kept separately from rock",
            "joint_composition_status": "unverified; no four-part closure or physical hardness index",
            "unsupported_classes": ["BOULDER", "COBBLE", "MIXED"],
        },
    )
    publisher.publish_manifest(config.manifest_path, manifest)
    return (*paths, config.manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in build_substrate_classification(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
