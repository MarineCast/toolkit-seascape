"""Build the model-ready benthic panel without collapsing habitat families."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from seascape.core.config.paths import project_root
from seascape.benthic_substrate.classification.build import (
    PREFIX as SUBSTRATE_PREFIX,
)
from seascape.benthic_substrate.classification.download import (
    SECTION_NAME as SUBSTRATE_SECTION,
)
from seascape.biogenic_habitat.kelp.build import PREFIX as KELP_PREFIX
from seascape.biogenic_habitat.kelp.download import (
    SECTION_NAME as KELP_SECTION,
)
from seascape.biogenic_habitat.reef.build import PREFIX as REEF_PREFIX
from seascape.biogenic_habitat.reef.download import (
    SECTION_NAME as REEF_SECTION,
)
from seascape.biogenic_habitat.seagrass.build import (
    PREFIX as SEAGRASS_PREFIX,
)
from seascape.biogenic_habitat.seagrass.download import (
    SECTION_NAME as SEAGRASS_SECTION,
)
from seascape.utils.artifacts import (
    build_manifest,
)
from seascape.utils.artifacts import checksum_artifact as _sha256
from seascape.utils.artifacts import (
    stage_parquet_family,
)
from seascape.utils.habitat_configuration import (
    load_habitat_surface_config,
)

from .download import DEFAULT_CONFIG_PATH

SECTION_NAME = "benthic_habitat_composite"
PREFIX = "BENTHIC_HABITAT"
CORE_FEATURES = [
    "SEAGRASS_FRAC",
    "SEAGRASS_MAX_LOCAL_FRAC",
    "SEAGRASS_DISTANCE_M",
    "SEAGRASS_AREA_WITHIN_5KM_M2",
    "KELP_FRAC",
    "KELP_MAX_LOCAL_FRAC",
    "KELP_DISTANCE_M",
    "KELP_AREA_WITHIN_5KM_M2",
    "KELP_PERSISTENCE_RATIO",
    "ROCKY_REEF_FRAC",
    "ROCKY_REEF_DISTANCE_M",
    "ROCKY_REEF_AREA_WITHIN_5KM_M2",
]


def _family_configs(config_path: str | Path) -> dict[str, Any]:
    return {
        "seagrass": load_habitat_surface_config(SEAGRASS_SECTION, SEAGRASS_PREFIX, config_path),
        "kelp": load_habitat_surface_config(KELP_SECTION, KELP_PREFIX, config_path),
        "reef": load_habitat_surface_config(REEF_SECTION, REEF_PREFIX, config_path),
        "substrate": load_habitat_surface_config(SUBSTRATE_SECTION, SUBSTRATE_PREFIX, config_path),
    }


def _coverage_gated_richness(
    values: pd.DataFrame,
    confidence: pd.DataFrame,
) -> pd.Series:
    """Return habitat-family richness only where every family is mapped."""

    minimum_richness = sum(
        pd.to_numeric(values[column], errors="coerce").fillna(0).gt(0).astype("int8")
        for column in (
            "SEAGRASS_FRAC",
            "KELP_FRAC",
            "ROCKY_REEF_FRAC",
            "BIOGENIC_REEF_FRAC",
        )
    )
    complete = ~(
        confidence["SEAGRASS_UNMAPPED_AREA"].astype(bool)
        | confidence["KELP_UNMAPPED_AREA"].astype(bool)
        | confidence["ROCKY_REEF_UNMAPPED_AREA"].astype(bool)
        | confidence["BIOGENIC_REEF_UNMAPPED_AREA"].astype(bool)
    )
    return minimum_richness.astype("float64").where(complete, np.nan)


def _build_resolution(
    configs: dict[str, Any], resolution: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    seagrass = pd.read_parquet(configs["seagrass"].feature_path(resolution))
    kelp = pd.read_parquet(configs["kelp"].feature_path(resolution))
    reef = pd.read_parquet(configs["reef"].feature_path(resolution))
    seagrass_conf = pd.read_parquet(configs["seagrass"].confidence_path(resolution))
    kelp_conf = pd.read_parquet(configs["kelp"].confidence_path(resolution))
    reef_conf = pd.read_parquet(configs["reef"].confidence_path(resolution))
    substrate_conf = pd.read_parquet(configs["substrate"].confidence_path(resolution))
    keys = ["H3_INDEX", "H3_RESOLUTION"]
    values = seagrass.merge(
        kelp, on=keys, how="inner", validate="one_to_one", suffixes=("", "_KELP")
    )
    duplicate_lineage = [
        column
        for column in values
        if column.endswith("_KELP") and column.removesuffix("_KELP") in values
    ]
    values = values.drop(columns=duplicate_lineage)
    values = values.merge(
        reef,
        on=keys,
        how="inner",
        validate="one_to_one",
        suffixes=("", "_REEF"),
    )
    duplicate_lineage = [
        column
        for column in values
        if column.endswith("_REEF") and column.removesuffix("_REEF") in values
    ]
    values = values.drop(columns=duplicate_lineage)
    missing_core = sorted(set(CORE_FEATURES).difference(values.columns))
    if missing_core:
        raise ValueError(f"Benthic composite is missing core features: {missing_core}")
    output = values.loc[:, [*keys, *CORE_FEATURES]].copy()
    confidence = seagrass_conf.merge(kelp_conf, on=keys, how="inner", validate="one_to_one").merge(
        reef_conf, on=keys, how="inner", validate="one_to_one"
    )
    confidence = confidence.merge(
        substrate_conf[
            [
                *keys,
                "SUBSTRATE_CONFIDENCE",
                "SUBSTRATE_UNMAPPED_AREA",
            ]
        ],
        on=keys,
        how="inner",
        validate="one_to_one",
    )
    output["BENTHIC_HABITAT_RICHNESS"] = _coverage_gated_richness(values, confidence)
    edge_density = pd.to_numeric(values["SEAGRASS_EDGE_DENSITY_M_PER_KM2"], errors="coerce").fillna(
        0
    ) + pd.to_numeric(values["KELP_EDGE_DENSITY_M_PER_KM2"], errors="coerce").fillna(0)
    edge_coverage_complete = ~(
        confidence["SEAGRASS_UNMAPPED_AREA"].astype(bool)
        | confidence["KELP_UNMAPPED_AREA"].astype(bool)
    )
    output["BENTHIC_EDGE_DENSITY_M_PER_KM2"] = edge_density.where(edge_coverage_complete, np.nan)
    rocky_observed_confidence = np.where(
        output["ROCKY_REEF_FRAC"].fillna(0).to_numpy() > 0,
        confidence["SUBSTRATE_CONFIDENCE"].to_numpy(dtype="float64"),
        0.0,
    )
    survey_matrix = np.column_stack(
        [
            confidence["SEAGRASS_CONFIDENCE"].to_numpy(dtype="float64"),
            confidence["KELP_CONFIDENCE"].to_numpy(dtype="float64"),
            rocky_observed_confidence,
            confidence["BIOGENIC_REEF_CONFIDENCE"].to_numpy(dtype="float64"),
        ]
    )
    composite_confidence = pd.DataFrame(
        {
            "H3_INDEX": confidence["H3_INDEX"].astype("string"),
            "H3_RESOLUTION": resolution,
            "SEAGRASS_CONFIDENCE": confidence["SEAGRASS_CONFIDENCE"].to_numpy(),
            "SEAGRASS_SURVEY_COVERAGE": confidence["SEAGRASS_SURVEYED_AREA_FRAC"].to_numpy(),
            "KELP_CONFIDENCE": confidence["KELP_CONFIDENCE"].to_numpy(),
            "KELP_SURVEY_COVERAGE": confidence["KELP_SURVEYED_AREA_FRAC"].to_numpy(),
            "ROCKY_REEF_CONFIDENCE": confidence["ROCKY_REEF_CONFIDENCE"].to_numpy(),
            "BIOGENIC_REEF_CONFIDENCE": confidence["BIOGENIC_REEF_CONFIDENCE"].to_numpy(),
            "DEEP_CORAL_SPONGE_CONFIDENCE": confidence["DEEP_CORAL_SPONGE_CONFIDENCE"].to_numpy(),
            "BENTHIC_SURVEY_CONFIDENCE": survey_matrix.mean(axis=1),
            "BENTHIC_HABITAT_CONFIDENCE": np.max(survey_matrix, axis=1),
            "BENTHIC_HABITAT_UNMAPPED_AREA": (
                confidence["SEAGRASS_UNMAPPED_AREA"].astype(bool)
                | confidence["KELP_UNMAPPED_AREA"].astype(bool)
                | confidence["SUBSTRATE_UNMAPPED_AREA"].astype(bool)
                | confidence["BIOGENIC_REEF_UNMAPPED_AREA"].astype(bool)
            ).to_numpy(),
        }
    )
    return output, composite_confidence


def build_benthic_habitat_composite(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path, Path]:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    families = _family_configs(config_path)
    input_paths = [
        path
        for family in families.values()
        for resolution in (8, 6)
        for path in (family.feature_path(resolution), family.confidence_path(resolution))
    ]
    missing = [path for path in input_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Benthic family products are missing; build substrate, seagrass, kelp, and reef "
            "first: " + ", ".join(map(str, missing))
        )
    r8_features, r8_confidence = _build_resolution(families, 8)
    r6_features, r6_confidence = _build_resolution(families, 6)
    paths = (
        config.feature_path(8),
        config.confidence_path(8),
        config.feature_path(6),
        config.confidence_path(6),
    )
    publisher = stage_parquet_family(
        config.processed_dir,
        tuple(
            zip(
                (r8_features, r8_confidence, r6_features, r6_confidence),
                paths,
                strict=True,
            )
        ),
    )
    family_manifest_paths = [family.manifest_path for family in families.values()]
    manifest = build_manifest(
        dataset_family="environment.seascape.benthic_habitat_composite",
        run_id=publisher.run_id,
        resolved_config={
            "composite": asdict(config),
            "families": {name: asdict(family) for name, family in families.items()},
        },
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": f"{name} family manifest",
                "path": str(family.manifest_path),
                "checksum": _sha256(family.manifest_path),
                "license": "Inherited source terms; see family manifest",
            }
            for name, family in families.items()
        ],
        upstream_artifacts=[
            {"path": str(path), "checksum": _sha256(path)}
            for path in [*input_paths, *family_manifest_paths]
        ],
        attribution=[
            {
                "text": "Composite of separately attributed seascape habitat families",
                "license": "Inherited source terms; see family manifests",
            }
        ],
        source_completeness="partial",
    )
    publisher.publish_manifest(config.manifest_path, manifest)
    return (*paths, config.manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    for path in build_benthic_habitat_composite(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
