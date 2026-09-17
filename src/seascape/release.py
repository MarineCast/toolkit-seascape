"""Validate the materialized seascape release against its public contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from seascape.core.artifacts import atomic_write_json
from seascape.core.config.paths import project_root
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.code_identity import package_code_identity
from seascape.core.data.registry import DATASETS
from seascape.governance.feature_eligibility import (
    seascape_catalog_subset,
)
from seascape.publication import (
    SEASCAPE_RELEASE_MANIFEST,
    SeascapeReleasePublisher,
    SeascapeSnapshot,
)
from seascape.spatial_support.water_network.radius_operator import (
    RadiusSumOperator,
)
from seascape.utils.artifacts import (
    SEASCAPE_MANIFEST_SCHEMA_VERSION,
    load_manifest,
    validate_manifest,
)

DEFAULT_CATALOG_PATH = Path("config/feature_catalog.yaml")
DEFAULT_OUTPUT_PATH = Path(
    "outputs/domains/environmental_layer/seascape/p0_p2_catalog_release_audit.json"
)
PROCESSED_ROOT = Path("data/processed/domain/environmental_layer/seascape")
SUPPORTED_SEASCAPE_RESOLUTIONS = frozenset({6, 8})
EXPECTED_FAMILY_MANIFESTS = frozenset(
    {
        "anthropogenic/anthropogenic_manifest.json",
        "benthic_substrate/bottom_hardness/bottom_hardness_manifest.json",
        "benthic_substrate/classification/benthic_substrate_classification_manifest.json",
        "biogenic_habitat/composite/benthic_habitat_composite_manifest.json",
        "biogenic_habitat/kelp/kelp_habitat_manifest.json",
        "biogenic_habitat/reef/reef_habitat_manifest.json",
        "biogenic_habitat/seagrass/seagrass_habitat_manifest.json",
        "coastal_configuration/exposure_and_enclosure/exposure_and_enclosure_manifest.json",
        "coastal_configuration/shoreline_characterization/shoreline_characterization_manifest.json",
        "coastal_configuration/shoreline_proximity/shoreline_proximity_manifest.json",
        "coastal_configuration/waterbody_morphometry/waterbody_morphometry_manifest.json",
        "hydrologic_connectivity/estuarine_connectivity/estuarine_connectivity_manifest.json",
        "hydrologic_connectivity/fluvial_barriers/fluvial_barriers_manifest.json",
        "hydrologic_connectivity/fluvial_connectivity/fluvial_connectivity_manifest.json",
        "hydrologic_connectivity/freshwater_sources/river_mouths_manifest.json",
        "seafloor_physiography/bathymetry/bathymetry_manifest.json",
        "seafloor_physiography/geomorphic_units/geomorphic_units_manifest.json",
        "seafloor_physiography/geomorphometry/geomorphometry_manifest.json",
        "spatial_support/h3_geometry/h3_geometry_manifest.json",
        "spatial_support/water_geometry/water_geometry_manifest.json",
        "spatial_support/water_network/_dataset_manifest.json",
    }
)
RADIUS_OPERATOR_FAMILIES = frozenset(
    {
        "environment.seascape.anthropogenic",
        "environment.seascape.kelp_habitat",
        "environment.seascape.reef_habitat",
        "environment.seascape.seagrass_habitat",
    }
)


def _seascape_products(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return only catalog products governed by the seascape release contract."""

    products = catalog.get("products")
    if not isinstance(products, dict):
        raise ValueError("Environment feature catalog has no products mapping.")
    return {
        str(product_id): product
        for product_id, product in products.items()
        if isinstance(product, dict) and product.get("metric_family") == "seascape"
    }


def _catalog_table_audit(root: Path, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    support = {
        resolution: set(
            pd.read_parquet(
                root
                / PROCESSED_ROOT
                / "spatial_support/h3_geometry"
                / f"H3_MODEL_AREA_SUPPORT_RES_{resolution}.parquet",
                columns=["H3_INDEX"],
            )["H3_INDEX"].astype(str)
        )
        for resolution in (6, 8)
    }
    results = []
    for product_id, product in _seascape_products(catalog).items():
        for raw_resolution, relative_path in product["collection"]["paths"].items():
            resolution = int(raw_resolution)
            if resolution not in SUPPORTED_SEASCAPE_RESOLUTIONS:
                raise ValueError(
                    f"Unexpected seascape catalog resolution R{resolution} for {product_id}; "
                    "the canonical seascape contract supports only R6 and R8."
                )
            frame = pd.read_parquet(root / relative_path)
            cells = frame["H3_INDEX"].astype(str)
            numeric = frame.select_dtypes(include=[np.number]).to_numpy(
                dtype="float64", copy=False
            )
            state_prefixes = {
                column.removesuffix("_OBSERVED_PRESENCE")
                for column in frame
                if column.endswith("_OBSERVED_PRESENCE")
            }
            invalid_state_rows = 0
            for prefix in state_prefixes:
                columns = [
                    f"{prefix}_OBSERVED_PRESENCE",
                    f"{prefix}_OBSERVED_ABSENCE",
                    f"{prefix}_UNSURVEYED",
                ]
                if all(column in frame for column in columns):
                    invalid_state_rows += int(
                        frame[columns]
                        .fillna(False)
                        .astype(bool)
                        .sum(axis=1)
                        .ne(1)
                        .sum()
                    )
            fraction_columns = [column for column in frame if column.endswith("_FRAC")]
            invalid_fraction_values = sum(
                int(
                    (
                        ~pd.to_numeric(frame[column], errors="coerce")
                        .dropna()
                        .between(0.0, 1.0)
                    ).sum()
                )
                for column in fraction_columns
            )
            qc_columns = [column for column in frame if column.endswith("QC_REASON")]
            empty_qc_values = sum(
                int(frame[column].dropna().astype(str).str.strip().eq("").sum())
                for column in qc_columns
            )
            result = {
                "product": product_id,
                "resolution": resolution,
                "path": str(relative_path),
                "rows": int(len(frame)),
                "unique_h3": bool(cells.is_unique and cells.notna().all()),
                "exact_canonical_support": set(cells) == support[resolution],
                "infinite_numeric_values": int(np.isinf(numeric).sum()),
                "invalid_missingness_state_rows": invalid_state_rows,
                "invalid_fraction_values": invalid_fraction_values,
                "empty_qc_values": empty_qc_values,
            }
            if (
                not result["unique_h3"]
                or not result["exact_canonical_support"]
                or result["infinite_numeric_values"]
                or result["invalid_missingness_state_rows"]
                or result["invalid_fraction_values"]
                or result["empty_qc_values"]
            ):
                raise ValueError(
                    f"Seascape catalog-table release gate failed: {result}"
                )
            results.append(result)
    return results


def _manifest_audit(root: Path) -> dict[str, Any]:
    current = []
    superseded = []
    operator_path = (
        root
        / PROCESSED_ROOT
        / "spatial_support/water_network/H3_WATER_RADIUS_OPERATOR_RES_8_5000M.npz"
    )
    operator = RadiusSumOperator.load(operator_path)
    processed_root = root / PROCESSED_ROOT
    for path in sorted(processed_root.rglob("*manifest*.json")):
        if path.name == SEASCAPE_RELEASE_MANIFEST:
            continue
        payload = load_manifest(path)
        relative = str(path.relative_to(root))
        if payload.get("schema_version") == SEASCAPE_MANIFEST_SCHEMA_VERSION:
            validate_manifest(payload, project_root=root, verify_artifacts=True)
            for upstream in payload.get("upstream_artifacts", []):
                upstream_path = Path(str(upstream["path"]))
                resolved = (
                    upstream_path
                    if upstream_path.is_absolute()
                    else root / upstream_path
                )
                if not resolved.exists() or checksum_path(resolved) != upstream.get(
                    "checksum"
                ):
                    raise ValueError(
                        f"Manifest has a stale upstream checksum: {relative}"
                    )
            if payload.get("dataset_family") in RADIUS_OPERATOR_FAMILIES:
                lineage = payload.get("metadata", {}).get("radius_operator_lineage")
                expected = {
                    "checksum": checksum_path(operator_path),
                    "radius_m": operator.radius_m,
                    "support_hash": operator.support_hash,
                    "source_support_hash": operator.source_support_hash,
                    "graph_checksum": operator.graph_checksum,
                }
                if not isinstance(lineage, dict) or any(
                    lineage.get(key) != value for key, value in expected.items()
                ):
                    raise ValueError(
                        f"Manifest radius-operator lineage is missing or stale: {relative}"
                    )
            current.append(relative)
        elif "/eelgrass/" in f"/{relative}":
            superseded.append(relative)
        else:
            raise ValueError(
                f"Current seascape manifest uses a legacy schema: {relative}"
            )
    if not current:
        raise ValueError("No current common-schema seascape manifests were found.")
    current_family_paths = {
        str(Path(path).relative_to(PROCESSED_ROOT)) for path in current
    }
    missing = sorted(EXPECTED_FAMILY_MANIFESTS.difference(current_family_paths))
    if missing:
        raise ValueError(
            "Required seascape family manifests are missing: " + ", ".join(missing)
        )
    return {
        "current_common_schema_count": len(current),
        "current_common_schema_paths": current,
        "superseded_legacy_paths": superseded,
        "required_family_manifests": sorted(EXPECTED_FAMILY_MANIFESTS),
    }


def _governance_audit(root: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    eligibility_path = root / "config/feature_eligibility.yaml"
    readme_path = root / "docs/products.md"
    if not eligibility_path.exists() or not readme_path.exists():
        raise FileNotFoundError(
            "Candidate seascape eligibility metadata and README are required release artifacts."
        )
    eligibility = yaml.safe_load(eligibility_path.read_text(encoding="utf-8"))
    _subset, expected_catalog_checksum = seascape_catalog_subset(catalog)
    if eligibility.get("feature_catalog_checksum") != expected_catalog_checksum:
        raise ValueError("Seascape catalog and feature-eligibility checksums disagree.")
    included_invalid = [
        f"{record['product']}.{record['column']}"
        for record in eligibility.get("features", [])
        if record.get("eligible")
        and record.get("materialization_status")
        in {"all_null", "unavailable", "all_null_or_unavailable"}
    ]
    if included_invalid:
        raise ValueError(
            "All-null or unavailable features are marked eligible: "
            + ", ".join(included_invalid[:10])
        )
    alternatives = eligibility.get("alternate_scale_groups", {})
    docs_namespace = runpy.run_module("seascape.maintenance.update_seascape_docs")
    current_readme = readme_path.read_text(encoding="utf-8")
    expected_readme = docs_namespace["update_readme"](
        current_readme,
        docs_namespace["render_product_index"](catalog),
    )
    if current_readme != expected_readme:
        raise ValueError("Candidate seascape README product index is stale.")
    return {
        "catalog_checksum": checksum_path(root / DEFAULT_CATALOG_PATH),
        "feature_eligibility_checksum": checksum_path(eligibility_path),
        "readme_checksum": checksum_path(readme_path),
        "included_invalid_features": included_invalid,
        "alternate_scale_groups": alternatives,
        "feature_eligibility_complete": True,
    }


def _radius_operator_audit(root: Path) -> dict[str, Any]:
    directory = root / PROCESSED_ROOT / "spatial_support/water_network"
    support_path = (
        root
        / PROCESSED_ROOT
        / "spatial_support/h3_geometry/H3_MODEL_AREA_SUPPORT_RES_8.parquet"
    )
    source_support_path = (
        root
        / PROCESSED_ROOT
        / "spatial_support/h3_geometry/H3_MARINE_SUPPORT_RES_8.parquet"
    )
    edge_path = directory / "H3_WATER_PASSABLE_EDGES_RES_8.parquet"
    operator_path = directory / "H3_WATER_RADIUS_OPERATOR_RES_8_5000M.npz"
    reachable_path = directory / "H3_REACHABLE_WATER_AREA_RES_8_5000M.parquet"
    operator = RadiusSumOperator.load(operator_path)
    cells = (
        pd.read_parquet(support_path, columns=["H3_INDEX"])["H3_INDEX"]
        .astype(str)
        .tolist()
    )
    source_cells = (
        pd.read_parquet(source_support_path, columns=["H3_INDEX"])["H3_INDEX"]
        .astype(str)
        .tolist()
    )
    operator.validate_lineage(
        graph_path=edge_path,
        support_cells=cells,
        source_support_cells=source_cells,
    )
    reachable = pd.read_parquet(reachable_path)
    if reachable["H3_INDEX"].astype(str).tolist() != cells:
        raise ValueError(
            "Reachable-water-area derivative has noncanonical support order."
        )
    lineage_hashes = set(reachable["RADIUS_OPERATOR_SUPPORT_HASH"].astype(str))
    graph_hashes = set(reachable["RADIUS_OPERATOR_GRAPH_CHECKSUM"].astype(str))
    if lineage_hashes != {operator.support_hash} or graph_hashes != {
        operator.graph_checksum
    }:
        raise ValueError("Reachable-water-area radius-operator lineage is stale.")
    return {
        "path": str(operator_path.relative_to(root)),
        "checksum": checksum_path(operator_path),
        "radius_m": operator.radius_m,
        "graph_checksum": operator.graph_checksum,
        "support_hash": operator.support_hash,
        "source_support_hash": operator.source_support_hash,
        "nonzero_memberships": int(len(operator.indices)),
    }


def _depth_band_audit(root: Path) -> list[dict[str, Any]]:
    directory = root / PROCESSED_ROOT / "seafloor_physiography/bathymetry"
    results = []
    for resolution, name in (
        (8, "BATHYMETRY.parquet"),
        (6, "BATHYMETRY_RES_6.parquet"),
    ):
        frame = pd.read_parquet(directory / name)
        fractions = [
            column for column in frame if column.startswith("BATHYMETRY_FRAC_")
        ]
        counts = [
            column for column in frame if column.startswith("BATHYMETRY_PIXEL_COUNT_")
        ]
        valid = frame["BATHYMETRY_PIXEL_COUNT"].fillna(0).gt(0)
        fraction_error = float(
            (frame.loc[valid, fractions].sum(axis=1) - 1.0).abs().max()
        )
        count_error = float(
            (
                frame.loc[valid, counts].sum(axis=1)
                - frame.loc[valid, "BATHYMETRY_PIXEL_COUNT"]
            )
            .abs()
            .max()
        )
        if len(fractions) != 6 or fraction_error > 1e-9 or count_error > 0:
            raise ValueError(f"Bathymetry depth-band contract failed at R{resolution}.")
        results.append(
            {
                "resolution": resolution,
                "band_count": len(fractions),
                "maximum_fraction_sum_error": fraction_error,
                "maximum_pixel_count_error": count_error,
            }
        )
    return results


def _shoreline_audit(root: Path) -> list[dict[str, Any]]:
    directory = (
        root / PROCESSED_ROOT / "coastal_configuration/shoreline_characterization"
    )
    results = []
    for resolution in (6, 8):
        frame = pd.read_parquet(
            directory / f"SHORELINE_CHARACTERIZATION_RES_{resolution}.parquet"
        )
        fractions = [column for column in frame if column.endswith("_SHORE_FRAC")]
        classified = frame["SHORELINE_CLASSIFIED_LENGTH_M"].gt(0)
        fraction_contract = all(
            frame.loc[classified, column].between(0.0, 1.0).all()
            and frame.loc[~classified, column].isna().all()
            for column in fractions
        )
        coverage_contract = bool(
            frame["SHORELINE_CLASSIFIED_COVERAGE_FRAC"].dropna().between(0.0, 1.0).all()
        )
        if not fraction_contract or not coverage_contract:
            raise ValueError(f"Shoreline denominator contract failed at R{resolution}.")
        results.append(
            {
                "resolution": resolution,
                "class_fraction_count": len(fractions),
                "classified_denominator_contract": fraction_contract,
                "coverage_contract": coverage_contract,
            }
        )
    return results


def build_release_audit(root: Path, catalog_path: Path) -> dict[str, Any]:
    """Build a fail-closed audit of current product, manifest, and denominator contracts."""

    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    products = _seascape_products(catalog)
    if not products:
        raise ValueError("Environment feature catalog contains no seascape products.")
    tables = _catalog_table_audit(root, catalog)
    governance = _governance_audit(root, catalog)
    return {
        "schema_version": 2,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "catalog_path": str(catalog_path.relative_to(root)),
        "catalog_product_count": len(products),
        "catalog_feature_entry_count": sum(
            int(product.get("feature_count", len(product.get("features", {}))))
            for product in products.values()
        ),
        "catalog_table_count": len(tables),
        "catalog_tables": tables,
        "manifests": _manifest_audit(root),
        "bathymetry_depth_bands": _depth_band_audit(root),
        "shoreline_denominators": _shoreline_audit(root),
        "radius_operator": _radius_operator_audit(root),
        "governance": governance,
        "artifact_release_passed": True,
        "feature_eligibility_complete": governance["feature_eligibility_complete"],
        "release_gate_passed": True,
    }


def _product_release_records(
    candidate: Path,
    *,
    artifact_checksums: dict[str, str],
    code_identity: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Describe every registry product materialized into the candidate release."""

    manifest_metadata: dict[str, dict[str, Any]] = {}
    for manifest_path in sorted((candidate / PROCESSED_ROOT).rglob("*manifest*.json")):
        if manifest_path.name == SEASCAPE_RELEASE_MANIFEST:
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_relative = str(manifest_path.relative_to(candidate))
        for artifact in payload.get("artifacts", []):
            relative = str(artifact.get("path", ""))
            if not relative:
                continue
            manifest_metadata[relative] = {
                "manifest_path": manifest_relative,
                "source_completeness": payload.get("source_completeness"),
                "coverage": {
                    "h3_resolutions": payload.get("h3_resolutions", []),
                    "spatial_bounds_wgs84": payload.get("spatial_bounds_wgs84"),
                },
                "source_vintage": [
                    {
                        "name": source.get("name"),
                        "version": source.get("version"),
                        "observation_period": source.get("observation_period"),
                        "retrieved_at_utc": source.get("retrieved_at_utc"),
                    }
                    for source in payload.get("sources", [])
                ],
                "rights": {
                    "licensing": payload.get("licensing", []),
                    "attribution": payload.get("attribution", []),
                },
            }

    records: dict[str, dict[str, Any]] = {}
    for spec in DATASETS:
        path = spec.path(
            data_root=candidate / "data",
            artifact_root=candidate / "artifacts",
            output_root=candidate / "outputs",
        )
        if not path.is_file():
            continue
        relative = str(path.relative_to(candidate))
        checksum = artifact_checksums.get(relative)
        if checksum is None:
            continue
        dataset_id = str(spec.dataset_id)
        suffix = dataset_id.removeprefix("environment.seascape.")
        match = re.fullmatch(r"(?P<product>.+)_r(?P<resolution>\d+)", suffix)
        product_id = match.group("product") if match else suffix
        resolution = int(match.group("resolution")) if match else None
        metadata = manifest_metadata.get(relative, {})
        records[dataset_id] = {
            "product_id": product_id,
            "dataset_id": dataset_id,
            "path": relative,
            "checksum": checksum,
            "checksum_algorithm": "sha256",
            "schema_version": spec.schema_version,
            "producer": spec.producer,
            "producer_code_identity": code_identity,
            "resolution": resolution,
            "grain": list(spec.primary_key),
            "spatial_support": (
                {"kind": "h3", "resolution": resolution}
                if resolution is not None
                else {"kind": "native_or_non_h3"}
            ),
            **metadata,
        }
    return records


def publish_candidate_release(
    *,
    canonical_project_root: Path,
    candidate_project_root: Path,
) -> Path:
    """Promote one audited project-mirrored environment candidate in a global transaction."""

    canonical = canonical_project_root.resolve()
    candidate = candidate_project_root.resolve()
    audit_path = (
        candidate
        / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not audit.get("artifact_release_passed"):
        raise ValueError("Candidate seascape release audit has not passed.")
    processed = candidate / PROCESSED_ROOT
    family_manifests = {
        str(path.relative_to(candidate)): checksum_path(path)
        for path in sorted(processed.rglob("*manifest*.json"))
        if path.name != SEASCAPE_RELEASE_MANIFEST
        and "biogenic_habitat/eelgrass" not in str(path)
    }
    governed = {
        "catalog": "config/feature_catalog.yaml",
        "feature_eligibility": "config/feature_eligibility.yaml",
        "readme": "docs/products.md",
        "release_audit": str(audit_path.relative_to(candidate)),
        "seascape_config": "config/data/environment_seascape.yaml",
    }
    governed_checksums = {
        name: {
            "path": path,
            "checksum": (
                checksum_path(candidate / path)
                if (candidate / path).exists()
                else checksum_path(canonical / path)
            ),
        }
        for name, path in governed.items()
    }
    artifact_checksums = {
        str(path.relative_to(candidate)): checksum_path(path)
        for path in sorted(processed.rglob("*"))
        if path.is_file() and path.name != SEASCAPE_RELEASE_MANIFEST
    }
    code_identity = package_code_identity(canonical)
    products = _product_release_records(
        candidate,
        artifact_checksums=artifact_checksums,
        code_identity=code_identity,
    )
    release_identity_payload = {
        "artifact_checksums": artifact_checksums,
        "governed_artifacts": governed_checksums,
        "code_identity": code_identity,
    }
    release_id = hashlib.sha256(
        json.dumps(
            release_identity_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    release_relative = PROCESSED_ROOT / SEASCAPE_RELEASE_MANIFEST
    release_path = candidate / release_relative
    release_payload = {
        "schema_version": 2,
        "release_id": release_id,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "artifact_release_passed": True,
        "feature_eligibility_complete": bool(
            audit.get("feature_eligibility_complete")
        ),
        "family_manifest_checksums": family_manifests,
        "governed_artifacts": governed_checksums,
        "artifact_checksums": artifact_checksums,
        "products": products,
        "code_identity": code_identity,
        "code_revision": code_identity.get("git_revision"),
    }
    atomic_write_json(release_path, release_payload, overwrite=True)
    roots = (
        PROCESSED_ROOT,
        Path("config/feature_catalog.yaml"),
        Path("config/feature_eligibility.yaml"),
        Path("docs/products.md"),
        Path(
            "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
        ),
    )
    relative_files: set[Path] = {release_relative}
    for relative_root in roots:
        path = candidate / relative_root
        if path.is_file():
            relative_files.add(relative_root)
        elif path.is_dir():
            relative_files.update(
                item.relative_to(candidate)
                for item in path.rglob("*")
                if item.is_file()
                and "/.staging/" not in f"/{item.relative_to(candidate)}"
            )
    with SeascapeReleasePublisher(canonical, candidate) as publisher:
        for relative in sorted(relative_files, key=str):
            publisher.stage_candidate(relative, manifest=relative == release_relative)
        publisher.publish()
    return canonical / release_relative


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    args = parser.parse_args()
    root = project_root()
    catalog_path = (root / args.catalog).resolve()
    output_path = (root / args.output).resolve()
    with SeascapeSnapshot(root):
        audit = build_release_audit(root, catalog_path)
    atomic_write_json(output_path, audit, overwrite=True)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "tables": audit["catalog_table_count"],
                "manifests": audit["manifests"]["current_common_schema_count"],
                "passed": audit["release_gate_passed"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
