"""Retain declared water-mask lineage in downstream support manifests."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from seascape.core.artifacts.checksums import checksum_path
from seascape.utils.artifacts import load_manifest, validate_manifest


def water_geometry_provenance(water_path: Path, root: Path) -> dict[str, Any] | None:
    """Verify an available upstream manifest; preserve legacy absence behavior.

    This reads metadata, never changes the mask or determines its authority from
    a filename. Invalid or mismatched declared provenance fails before publication.
    """
    manifest_path = water_path.with_name("water_geometry_manifest.json")
    if not manifest_path.exists():
        if water_path.exists() and "AREA" in pq.read_schema(water_path).names:
            areas = (
                pq.read_table(water_path, columns=["AREA"]).column("AREA").to_pylist()
            )
            if any(str(area).startswith("SAN_JUAN_EXPLORATORY_") for area in areas):
                raise ValueError(
                    "Exploratory San Juan mask requires water_geometry_manifest.json; "
                    "rebuild it in an approved disposable workspace to retain source lineage."
                )
        return None
    manifest_root = Path(os.environ.get("SEASCAPE_CANDIDATE_ROOT", root)).resolve()
    payload = load_manifest(manifest_path)
    validate_manifest(payload, project_root=manifest_root, verify_artifacts=True)
    if payload["dataset_family"] not in {
        "environment.seascape.territorial_water_geometry",
        "environment.seascape.exploratory_water_geometry",
    }:
        raise ValueError("Unexpected upstream water-geometry dataset family.")
    if not payload["sources"]:
        raise ValueError("Water-geometry manifest must retain its source records.")
    paths = {(manifest_root / item["path"]).resolve() for item in payload["artifacts"]}
    if water_path.resolve() not in paths:
        raise ValueError("Water-geometry manifest does not identify the selected mask.")
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("Water-geometry manifest metadata must be an object.")
    if payload["dataset_family"] == "environment.seascape.exploratory_water_geometry":
        if (
            metadata.get("support_kind") != "exploratory"
            or metadata.get("model_eligible") is not False
        ):
            raise ValueError(
                "Exploratory water-geometry provenance must declare exploratory, model-ineligible support."
            )
    sources = [dict(item) for item in payload["sources"]]
    for item in sources:
        if item.get("path"):
            item["path"] = str((manifest_root / item["path"]).resolve())
    return {
        "sources": sources,
        "attribution": payload["attribution"],
        "source_completeness": payload["source_completeness"],
        "upstream": {
            "path": str(manifest_path),
            "checksum": checksum_path(manifest_path),
        },
        "metadata": {
            key: metadata[key]
            for key in (
                "support_kind",
                "model_eligible",
                "mask_method",
                "cartographic_scale",
            )
            if key in metadata
        },
    }
