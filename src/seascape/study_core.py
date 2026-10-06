"""Executable synthetic core orchestration; regional production stays unavailable.

This local fixture input format is provisional pending owner contract review.
It is deliberately distinct from regional audit/publication and retained resolvers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from seascape._study_contract import canonical_bytes, unique_object
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.code_identity import package_code_identity
from seascape.study import StudyConfig, StudyConfigError, load_study_config
from seascape.study_routes import PinnedInput, route_bathymetry, route_geomorphometry
from seascape.study_support import MembershipArtifact, _read_pinned, load_study_support
from seascape.utils.artifacts import build_manifest, validate_manifest

SCOPE = "synthetic_software_acceptance"
MANDATORY = {"bathymetry_r6", "bathymetry_native_r8"}
SUPPORTED = MANDATORY | {"geomorphometry_native_r8"}
EXCLUDED_FAMILIES = (
    "shoreline_characterization",
    "shoreline_proximity",
    "exposure_and_enclosure",
    "waterbody_morphometry",
    "geomorphic_units",
    "freshwater_sources",
    "fluvial_connectivity",
    "selected_outlets",
    "fluvial_barriers",
    "estuarine_connectivity",
    "nearshore_transitions",
    "passage_sections",
    "geographic_gateways",
    "coast_complexity",
    "mapped_habitat_mosaic",
    "substrate_classification",
    "bottom_hardness",
    "seagrass",
    "kelp",
    "reef",
    "benthic_composite",
    "anthropogenic",
    "gebco_tid",
)


def _json(raw: bytes) -> Any:
    return json.loads(
        raw,
        object_pairs_hook=unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value))


def _plan(raw: bytes, study: StudyConfig) -> dict[str, Any]:
    plan = _json(raw)
    keys = {
        "interface_version",
        "validation_scope",
        "study_config_sha256",
        "selected_capabilities",
        "mask_relative_path",
        "compute_memberships",
        "raster",
        "graphs",
        "scientific_settings",
    }
    if (
        not isinstance(plan, dict)
        or set(plan) != keys
        or type(plan["interface_version"]) is not int
        or plan["interface_version"] != 1
    ):
        raise StudyConfigError("Invalid provisional core fixture input manifest.")
    capabilities = plan["selected_capabilities"]
    if (
        plan["validation_scope"] != SCOPE
        or plan["study_config_sha256"] != study.config_sha256
        or not isinstance(capabilities, list)
        or any(type(v) is not str for v in capabilities)
        or len(set(capabilities)) != len(capabilities)
        or not MANDATORY.issubset(capabilities)
        or set(capabilities).difference(SUPPORTED)
    ):
        raise StudyConfigError(
            "Fixture scope, config or explicit core capabilities are invalid."
        )
    if study.payload["storage"]["data_root"] != "../Data":
        raise StudyConfigError(
            "Provisional fixture snapshot requires the config/../Data layout."
        )
    if not isinstance(plan["graphs"], dict) or set(plan["graphs"]) != {"6", "8"}:
        raise StudyConfigError("Fixture core requires separate pinned R6/R8 graphs.")
    for graph in plan["graphs"].values():
        if (
            not isinstance(graph, dict)
            or set(graph) != {"input", "maximum_hops"}
            or type(graph["maximum_hops"]) is not int
            or not 1 <= graph["maximum_hops"] <= 64
        ):
            raise StudyConfigError("Fixture graph descriptor/hop bound is invalid.")
    settings = plan["scientific_settings"]
    wanted = {"bathymetry"} | (
        {"geomorphometry"} if "geomorphometry_native_r8" in capabilities else set()
    )
    if not isinstance(settings, dict) or set(settings) != wanted:
        raise StudyConfigError(
            "Fixture scientific settings must match selected capabilities."
        )
    bathy = settings["bathymetry"]
    fields = {
        "bathymetry_sign",
        "depth_quantiles",
        "local_depth_anomaly_neighborhood_rings",
        "isobath_levels_m",
        "isobath_distance_projected_crs",
    }
    if (
        not isinstance(bathy, dict)
        or set(bathy) != fields
        or bathy["bathymetry_sign"] != "positive_down"
    ):
        raise StudyConfigError(
            "Fixture core requires explicit positive-down bathymetry settings."
        )
    for key in ("depth_quantiles", "isobath_levels_m"):
        values = bathy[key]
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 32
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                for v in values
            )
            or len(set(values)) != len(values)
        ):
            raise StudyConfigError(
                "Fixture depth quantiles/contour levels are invalid."
            )
    if any(v >= 1 or v == 0.5 for v in bathy["depth_quantiles"]):
        raise StudyConfigError(
            "Fixture depth quantiles must be within (0,1), excluding median."
        )
    if (
        type(bathy["local_depth_anomaly_neighborhood_rings"]) is not int
        or not 1 <= bathy["local_depth_anomaly_neighborhood_rings"] <= 64
    ):
        raise StudyConfigError("Fixture anomaly ring bound is invalid.")
    if "geomorphometry" in settings:
        terrain = settings["geomorphometry"]
        required = {
            "native_resolution_arc_seconds",
            "projected_crs",
            "neighbor_ring",
            "neighborhood_rings",
            "minimum_neighbors",
            "ruggedness_algorithm",
            "slope_upper_quantile",
            "openness_radius_rings",
            "openness_bearing_sectors",
            "curvature_index_scale_per_m",
        }
        if not isinstance(terrain, dict) or set(terrain) != required:
            raise StudyConfigError("Fixture native R8 terrain settings are incomplete.")
        if any(
            type(terrain[key]) is not int or not 1 <= terrain[key] <= 64
            for key in (
                "neighbor_ring",
                "minimum_neighbors",
                "openness_radius_rings",
                "openness_bearing_sectors",
            )
        ):
            raise StudyConfigError("Fixture terrain neighborhood bounds are invalid.")
        if (
            not isinstance(terrain["neighborhood_rings"], list)
            or not terrain["neighborhood_rings"]
            or any(
                type(v) is not int or not 1 <= v <= 64
                for v in terrain["neighborhood_rings"]
            )
        ):
            raise StudyConfigError("Fixture terrain rings are invalid.")
    for source in (
        plan["raster"],
        *(record["input"] for record in plan["graphs"].values()),
    ):
        _pin(source)
    return plan


def _pin(record: dict[str, Any]) -> PinnedInput:
    if set(record) != {"relative_path", "sha256", "metadata"}:
        raise StudyConfigError("Fixture inputs require path, raw hash and metadata.")
    metadata = record["metadata"]
    if (
        not isinstance(metadata, dict)
        or metadata.get("evidence_type") != "synthetic software acceptance"
    ):
        raise StudyConfigError(
            "Core fixture command refuses non-synthetic source evidence."
        )
    return PinnedInput(
        record["relative_path"], record["sha256"], canonical_bytes(metadata).decode()
    )


def _membership_specs(
    plan: dict[str, Any],
) -> tuple[MembershipArtifact, MembershipArtifact]:
    specs = tuple(MembershipArtifact(**entry) for entry in plan["compute_memberships"])
    if len(specs) != 2:
        raise StudyConfigError("Core fixture requires explicit R6/R8 compute context.")
    return specs[0], specs[1]


def _inventory(root: Path) -> dict[str, str]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path not in {root / "audit.json", root / "software_release.json"}
    )
    for path in files:
        if not path.resolve().is_relative_to(root.resolve()):
            raise StudyConfigError("Fixture candidate contains escaping symlinks.")
    return {str(path.relative_to(root)): checksum_path(path) for path in files}


def _validate_candidate(root: Path) -> dict[str, Any]:
    inputs = _inventory(root)
    study = load_study_config(root / "inputs/config/study.v1.json")
    assert study is not None
    plan = _plan((root / "inputs/input-manifest.json").read_bytes(), study)
    support = load_study_support(
        study,
        producer="bathymetry",
        mask_relative_path=plan["mask_relative_path"],
        compute_memberships=_membership_specs(plan),
    )
    caps = _json((root / "capabilities.json").read_bytes())
    if set(caps["materialized"]) != set(plan["selected_capabilities"]):
        raise StudyConfigError("Fixture capability set differs from its pinned plan.")
    checks = []
    for capability in plan["selected_capabilities"]:
        entry = caps["materialized"][capability]
        path = root / entry["path"]
        resolution = entry["resolution"]
        frame = pd.read_parquet(path)
        if (
            frame.H3_INDEX.tolist() != list(support.cells(resolution, role="reporting"))
            or not frame.H3_RESOLUTION.eq(resolution).all()
            or np.isinf(
                frame.select_dtypes(include=[np.number]).to_numpy(dtype="float64")
            ).any()
        ):
            raise StudyConfigError(
                "Fixture reporting key/resolution/finite-value audit failed."
            )
        provenance = _json(
            pq.ParquetFile(path).metadata.metadata[b"marinecast_study_route"]
        )
        if (
            provenance["artifact_role"] != "reporting"
            or provenance["study"]["config_sha256"] != study.config_sha256
            or provenance["support"]["reporting_mask_sha256"] != support.mask_sha256
            or provenance["production_ready"] is not False
            or provenance["release_eligible"] is not False
        ):
            raise StudyConfigError(
                "Fixture provenance identity or qualification audit failed."
            )
        if capability.startswith("bathymetry"):
            valid = frame.BATHYMETRY_PIXEL_COUNT.notna()
            counts = [c for c in frame if c.startswith("BATHYMETRY_PIXEL_COUNT_")]
            fractions = [c for c in frame if c.startswith("BATHYMETRY_FRAC_")]
            if (
                len(counts) != 6
                or len(fractions) != 6
                or not frame.loc[valid, counts]
                .sum(axis=1)
                .eq(frame.loc[valid, "BATHYMETRY_PIXEL_COUNT"])
                .all()
                or not np.allclose(frame.loc[valid, fractions].sum(axis=1), 1)
                or frame.loc[~valid, "BATHYMETRY"].notna().any()
            ):
                raise StudyConfigError(
                    "Fixture bathymetry pixel/band/missingness audit failed."
                )
        manifest = _json((root / entry["manifest"]).read_bytes())
        validate_manifest(manifest, project_root=root, verify_artifacts=True)
        for upstream in manifest["upstream_artifacts"]:
            if checksum_path(root / upstream["path"]) != upstream["checksum"]:
                raise StudyConfigError("Fixture upstream bytes changed.")
        checks.append(
            {
                "capability": capability,
                "rows": len(frame),
                "checksum": checksum_path(path),
                "passed": True,
            }
        )
    if _inventory(root) != inputs:
        raise StudyConfigError("Fixture candidate changed during audit.")
    return {
        "schema_version": 3,
        "validation_scope": SCOPE,
        "audited_inputs": inputs,
        "checksum_algorithm": "toolkit_sha256_filename_and_bytes",
        "selected_capabilities": plan["selected_capabilities"],
        "checks": checks,
        "software_release_passed": True,
        "artifact_release_passed": False,
        "regional_release_eligible": False,
        "production_ready": False,
    }


def verify_core_fixture_release(root: str | Path) -> dict[str, Any]:
    """Recheck a retained software generation independently of its old workspace."""
    generation = Path(root).resolve()
    audit = _json((generation / "audit.json").read_bytes())
    release = _json((generation / "software_release.json").read_bytes())
    if _inventory(generation) != audit.get("audited_inputs"):
        raise StudyConfigError(
            "Retained fixture bytes differ from their bound audit inventory."
        )
    fresh = _validate_candidate(generation)
    if (
        audit != fresh
        or type(audit.get("schema_version")) is not int
        or audit["schema_version"] != 3
        or audit.get("software_release_passed") is not True
        or audit.get("artifact_release_passed") is not False
        or type(release.get("schema_version")) is not int
        or release["schema_version"] != 3
        or release.get("software_release_passed") is not True
        or release.get("artifact_release_passed") is not False
        or release.get("production_ready") is not False
        or release.get("selected_capabilities") != fresh["selected_capabilities"]
        or release["validation_scope"] != SCOPE
        or release["regional_release_eligible"] is not False
        or release["audit_checksum"] != checksum_path(generation / "audit.json")
        or release["release_id"] != hashlib.sha256(canonical_bytes(audit)).hexdigest()
    ):
        raise StudyConfigError(
            "Retained fixture differs from its bound schema3 software audit."
        )
    return release


def run_core_fixture(
    study: StudyConfig, input_manifest: Path, workspace: Path
) -> dict[str, Any]:
    """Config -> verified support -> scientific core -> audited retained software generation."""
    with input_manifest.open("rb") as stream:
        raw_plan = stream.read(1024 * 1024 + 1)
    if len(raw_plan) > 1024 * 1024:
        raise StudyConfigError("Fixture input manifest exceeds 1MiB.")
    plan = _plan(raw_plan, study)
    specs = _membership_specs(plan)
    support = load_study_support(
        study,
        producer="bathymetry",
        mask_relative_path=plan["mask_relative_path"],
        compute_memberships=specs,
    )
    owner = (workspace.resolve() / ".seascape/study-core-fixtures").resolve()
    if not owner.is_relative_to(workspace.resolve()):
        raise StudyConfigError("Fixture namespace escapes explicit workspace.")
    owner.mkdir(parents=True, exist_ok=True)
    with (owner / ".writer.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidate = owner / f"candidate-{uuid.uuid4().hex}"
        candidate.mkdir()
        code_identity = package_code_identity(workspace)
        _write(candidate / "code_identity.json", code_identity)
        config_raw = study.source.read_bytes()
        if hashlib.sha256(config_raw).hexdigest() != study.raw_file_sha256:
            raise StudyConfigError("Selected config changed before fixture snapshot.")
        config_copy = candidate / "inputs/config/study.v1.json"
        config_copy.parent.mkdir(parents=True)
        config_copy.write_bytes(config_raw)
        (candidate / "inputs/input-manifest.json").write_bytes(raw_plan)
        records = [
            dict(relative_path=plan["mask_relative_path"], sha256=support.mask_sha256),
            *[vars(spec) for spec in specs],
            *study.payload["grid_registry"]["memberships"],
            plan["raster"],
            *(record["input"] for record in plan["graphs"].values()),
        ]
        snapshots = []
        for record in records:
            raw = _read_pinned(
                study.source.parent,
                study.data_root,
                record["relative_path"],
                record["sha256"],
                16 * 1024 * 1024,
            )
            destination = (config_copy.parent / record["relative_path"]).resolve()
            if not destination.is_relative_to((candidate / "inputs/Data").resolve()):
                raise StudyConfigError(
                    "Fixture snapshot path escapes retained Data root."
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.read_bytes() != raw:
                    raise StudyConfigError("Conflicting snapshot paths.")
            else:
                destination.write_bytes(raw)
            snapshots.append(
                {
                    "path": str(destination),
                    "checksum": checksum_path(destination),
                }
            )
        # Compute exclusively from retained snapshots, not mutable original files.
        local = load_study_config(config_copy)
        assert local is not None
        support = load_study_support(
            local,
            producer="bathymetry",
            mask_relative_path=plan["mask_relative_path"],
            compute_memberships=specs,
        )
        materialized: dict[str, dict[str, Any]] = {}
        products = candidate / "products"
        products.mkdir()
        for resolution, capability in (
            (6, "bathymetry_r6"),
            (8, "bathymetry_native_r8"),
        ):
            graph = plan["graphs"][str(resolution)]
            settings = SimpleNamespace(
                **plan["scientific_settings"]["bathymetry"], h3_resolution=resolution
            )
            result = route_bathymetry(
                settings,
                local,
                support,
                raster=_pin(plan["raster"]),
                neighborhoods=_pin(graph["input"]),
                maximum_graph_hops=graph["maximum_hops"],
            )
            result.write_reporting(products / f"{capability}.parquet")
            result.write_compute(products / f"compute_bathymetry_r{resolution}.parquet")
            materialized[capability] = {
                "path": f"products/{capability}.parquet",
                "resolution": resolution,
                "producer": "bathymetry",
                "status": "materialized_synthetic",
                "manifest": f"manifests/{capability}.json",
            }
        if "geomorphometry_native_r8" in plan["selected_capabilities"]:
            terrain_support = load_study_support(
                local,
                producer="geomorphometry",
                mask_relative_path=plan["mask_relative_path"],
                compute_memberships=specs,
            )
            path = products / "compute_bathymetry_r8.parquet"
            depth_metadata = {
                "version": "synthetic-routed-compute",
                "observation_period": "none: synthetic fixture",
                "license": "Apache-2.0 synthetic fixture",
                "evidence_type": "synthetic software acceptance",
            }
            # Config-relative source lies outside Data; retain this upstream in Data before routing.
            upstream = candidate / "inputs/Data/routed-compute-bathymetry-r8.parquet"
            upstream.write_bytes(path.read_bytes())
            result = route_geomorphometry(
                SimpleNamespace(
                    **plan["scientific_settings"]["geomorphometry"], h3_resolution=8
                ),
                local,
                terrain_support,
                bathymetry=PinnedInput(
                    "../Data/routed-compute-bathymetry-r8.parquet",
                    hashlib.sha256(upstream.read_bytes()).hexdigest(),
                    canonical_bytes(depth_metadata).decode(),
                ),
                raster=_pin(plan["raster"]),
                neighborhoods=_pin(plan["graphs"]["8"]["input"]),
                maximum_graph_hops=plan["graphs"]["8"]["maximum_hops"],
            )
            result.write_reporting(products / "geomorphometry_native_r8.parquet")
            result.write_compute(products / "compute_geomorphometry_r8.parquet")
            materialized["geomorphometry_native_r8"] = {
                "path": "products/geomorphometry_native_r8.parquet",
                "resolution": 8,
                "producer": "geomorphometry",
                "status": "materialized_synthetic",
                "manifest": "manifests/geomorphometry_native_r8.json",
            }
        excluded = {
            family: "not_selected_unqualified_optional" for family in EXCLUDED_FAMILIES
        }
        if "geomorphometry_native_r8" not in materialized:
            excluded["geomorphometry_native_r8"] = "not_selected_optional"
        _write(
            candidate / "capabilities.json",
            {
                "validation_scope": SCOPE,
                "materialized": materialized,
                "excluded": excluded,
            },
        )
        previous_candidate = os.environ.get("SEASCAPE_CANDIDATE_ROOT")
        os.environ["SEASCAPE_CANDIDATE_ROOT"] = str(candidate)
        try:
            for capability, entry in materialized.items():
                artifact = candidate / entry["path"]
                manifest = build_manifest(
                    dataset_family=f"environment.seascape.{entry['producer']}",
                    run_id=candidate.name,
                    resolved_config=plan,
                    artifacts=[artifact],
                    project_root=candidate,
                    sources=[
                        {
                            "name": "pinned synthetic native inputs",
                            "license": "Apache-2.0 synthetic fixtures",
                            "evidence_type": "synthetic software acceptance",
                        }
                    ],
                    upstream_artifacts=snapshots,
                    attribution=[
                        {
                            "text": "Synthetic software fixture; no survey observations",
                            "license": "Apache-2.0",
                        }
                    ],
                    source_completeness="partial",
                    metadata={
                        "validation_scope": SCOPE,
                        "production_ready": False,
                        "regional_release_eligible": False,
                        "selected_capability": capability,
                        "study_config_sha256": study.config_sha256,
                    },
                )
                _write(candidate / entry["manifest"], manifest)
        finally:
            if previous_candidate is None:
                os.environ.pop("SEASCAPE_CANDIDATE_ROOT", None)
            else:
                os.environ["SEASCAPE_CANDIDATE_ROOT"] = previous_candidate
        audit = _validate_candidate(candidate)
        if package_code_identity(workspace) != code_identity:
            raise StudyConfigError(
                "Package code changed during fixture computation; candidate retained."
            )
        _write(candidate / "audit.json", audit)
        release_id = hashlib.sha256(canonical_bytes(audit)).hexdigest()
        _write(
            candidate / "software_release.json",
            {
                "schema_version": 3,
                "release_id": release_id,
                "validation_scope": SCOPE,
                "software_release_passed": True,
                "regional_release_eligible": False,
                "artifact_release_passed": False,
                "production_ready": False,
                "audit_checksum": checksum_path(candidate / "audit.json"),
                "selected_capabilities": plan["selected_capabilities"],
            },
        )
        verify_core_fixture_release(candidate)
        generation = owner / "releases" / release_id
        generation.parent.mkdir(exist_ok=True)
        if generation.exists():
            raise StudyConfigError(
                "Software release generation already exists; retained candidate unchanged."
            )
        os.rename(candidate, generation)
        verify_core_fixture_release(generation)
        return {
            "status": "software_release_validated",
            "validation_scope": SCOPE,
            "release_id": release_id,
            "generation": str(generation),
            "audit": str(generation / "audit.json"),
            "selected_capabilities": plan["selected_capabilities"],
            "regional_release_eligible": False,
            "production_ready": False,
        }
