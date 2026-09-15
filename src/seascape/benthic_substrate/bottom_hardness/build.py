"""Derive bounded bottom-hardness indices from modeled dbSEABED composition."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from seascape.core.config.paths import project_root
from seascape.benthic_substrate.classification.build import (
    PREFIX as SUBSTRATE_PREFIX,
)
from seascape.benthic_substrate.classification.download import (
    SECTION_NAME as SUBSTRATE_SECTION,
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

SECTION_NAME = "bottom_hardness"
PREFIX = "BOTTOM_HARDNESS"
CLASS_WEIGHTS = {
    "ROCK": 1.00,
    "BOULDER": 0.90,
    "COBBLE": 0.75,
    "GRAVEL": 0.45,
    "SAND": 0.20,
    "MUD": 0.05,
    "MIXED": 0.40,
}


def _derive(features: pd.DataFrame, confidence: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    evidence_total = sum(
        pd.to_numeric(features[f"{SUBSTRATE_PREFIX}_{name}_FRAC"], errors="raise")
        for name in CLASS_WEIGHTS
    )
    index = sum(
        pd.to_numeric(features[f"{SUBSTRATE_PREFIX}_{name}_FRAC"], errors="raise") * weight
        for name, weight in CLASS_WEIGHTS.items()
    )
    index = index.where(evidence_total > 0)
    consolidated = sum(
        pd.to_numeric(features[f"{SUBSTRATE_PREFIX}_{name}_FRAC"], errors="raise")
        for name in ("ROCK", "BOULDER", "COBBLE")
    ).where(evidence_total > 0)
    output = pd.DataFrame(
        {
            "H3_INDEX": features["H3_INDEX"].astype("string"),
            "H3_RESOLUTION": features["H3_RESOLUTION"].astype("int8"),
            "BOTTOM_HARDNESS_INDEX": index,
            "CONSOLIDATED_SUBSTRATE_FRAC": consolidated,
            "EXPOSED_ROCK_FRAC": pd.to_numeric(
                features[f"{SUBSTRATE_PREFIX}_ROCK_FRAC"], errors="raise"
            ).where(evidence_total > 0),
            "MODELED_HARD_SUBSTRATE_FRAC": features[
                f"{SUBSTRATE_PREFIX}_HARD_SUBSTRATE_FRAC"
            ].to_numpy(),
            "DISTANCE_TO_MODELED_HARD_SUBSTRATE_M": features[
                f"{SUBSTRATE_PREFIX}_DISTANCE_TO_HARD_SUBSTRATE_M"
            ].to_numpy(),
            "DERIVATION_METHOD": "fixed documented weights on dbSEABED composition",
        }
    )
    for column in (
        "WATER_COMPONENT_ID",
        "NETWORK_CONNECTOR_METHOD",
        "NETWORK_CONNECTOR_DISTANCE_M",
        "NETWORK_DISTANCE_QC_REASON",
    ):
        output[column] = features[column].to_numpy()
    if (
        output["BOTTOM_HARDNESS_INDEX"].dropna().lt(0).any()
        or output["BOTTOM_HARDNESS_INDEX"].dropna().gt(1).any()
    ):
        raise ValueError("Derived bottom-hardness index must remain in [0, 1].")
    renamed = confidence.rename(
        columns={
            column: column.replace("SUBSTRATE_", "BOTTOM_HARDNESS_", 1)
            for column in confidence.columns
            if column.startswith("SUBSTRATE_")
        }
    ).copy()
    renamed["BOTTOM_HARDNESS_OBSERVED_VS_MODELED"] = np.where(
        renamed["BOTTOM_HARDNESS_CONFIDENCE"] > 0,
        "derived_from_modeled_dbseabed_substrate",
        None,
    )
    return output, renamed


def build_bottom_hardness(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path, Path]:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    substrate = load_habitat_surface_config(SUBSTRATE_SECTION, SUBSTRATE_PREFIX, config_path)
    input_paths = [
        substrate.feature_path(8),
        substrate.confidence_path(8),
        substrate.feature_path(6),
        substrate.confidence_path(6),
    ]
    missing = [path for path in input_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Substrate classification inputs are missing; run classification/build.py first: "
            + ", ".join(map(str, missing))
        )
    r8_features, r8_confidence = _derive(
        pd.read_parquet(input_paths[0]), pd.read_parquet(input_paths[1])
    )
    r6_features, r6_confidence = _derive(
        pd.read_parquet(input_paths[2]), pd.read_parquet(input_paths[3])
    )
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
    substrate_manifest = substrate.manifest_path
    manifest = build_manifest(
        dataset_family="environment.seascape.bottom_hardness",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[
            {
                "name": "Derived dbSEABED substrate composition",
                "path": str(substrate_manifest),
                "checksum": _sha256(substrate_manifest),
                "license": "Inherited dbSEABED source terms; see substrate manifest",
            }
        ],
        upstream_artifacts=[{"path": str(path), "checksum": _sha256(path)} for path in input_paths],
        attribution=[
            {
                "text": "Derived from dbSEABED interpolated substrate composition",
                "license": "Inherited dbSEABED source terms; see substrate manifest",
            }
        ],
        source_completeness="complete",
    )
    publisher.publish_manifest(config.manifest_path, manifest)
    return (*paths, config.manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    for path in build_bottom_hardness(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
