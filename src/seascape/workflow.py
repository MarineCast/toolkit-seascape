"""Explicit domain-layer build orchestration for Seascape Toolkit."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shutil
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

import yaml

from seascape.core.config.data import DOMAIN_CONFIG_KEYS
from seascape.core.config.paths import (
    project_root,
    resolve_config_include,
    resolve_config_path,
)
from seascape.core.artifacts.checksums import checksum_path

StageRunner = Callable[["DomainBuildContext"], Any]


@dataclass(frozen=True)
class DomainBuildContext:
    config_path: Path
    source_config_path: Path
    candidate_root: Path
    canonical_root: Path
    overwrite: bool = False
    continue_on_error: bool = False
    resume: bool = False
    publish: bool = True


@dataclass(frozen=True)
class DomainBuildStage:
    name: str
    description: str
    runner: StageRunner
    dependencies: tuple[str, ...] = ()
    declared_outputs: tuple[str, ...] = ()
    declared_manifests: tuple[str, ...] = ()
    terminal_action: bool = False


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    elapsed_seconds: float = 0.0
    error: str | None = None


@contextmanager
def _patched_argv(program: str, args: Sequence[str]):
    original = sys.argv[:]
    sys.argv = [program, *list(args)]
    try:
        yield
    finally:
        sys.argv = original


@contextmanager
def _candidate_environment(candidate_root: Path):
    previous = os.environ.get("SEASCAPE_CANDIDATE_ROOT")
    os.environ["SEASCAPE_CANDIDATE_ROOT"] = str(candidate_root)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SEASCAPE_CANDIDATE_ROOT", None)
        else:
            os.environ["SEASCAPE_CANDIDATE_ROOT"] = previous


def _run_seascape_water_geometry(ctx: DomainBuildContext) -> None:
    from seascape.spatial_support.water_geometry.build import (
        build_water_geometry,
    )

    build_water_geometry(config_path=ctx.config_path, skip_download=True)


def _run_h3_water_universe(ctx: DomainBuildContext) -> None:
    from seascape.spatial_support.h3_geometry.build import (
        build_h3_grid_layers,
    )

    build_h3_grid_layers(config_path=ctx.config_path)


def _run_h3_marine_spatial_support(ctx: DomainBuildContext) -> None:
    from seascape.spatial_support.water_network.build import (
        build_marine_spatial_support,
    )

    build_marine_spatial_support(
        config_path=ctx.config_path,
        overwrite=ctx.overwrite,
    )


def _run_seascape_bathymetry(ctx: DomainBuildContext) -> None:
    from seascape.seafloor_physiography.bathymetry import (
        run_pipeline,
    )

    run_pipeline(
        config_path=ctx.config_path,
        skip_download=True,
        skip_map=True,
    )


def _run_seascape_shoreline_characterization(ctx: DomainBuildContext) -> None:
    from seascape.coastal_configuration.shoreline_characterization import (
        build_shoreline_characterization,
    )

    build_shoreline_characterization(config_path=ctx.config_path)


def _run_seascape_geomorphometry(ctx: DomainBuildContext) -> None:
    from seascape.seafloor_physiography.geomorphometry.build import (
        build_geomorphometry,
    )

    build_geomorphometry(config_path=ctx.config_path)


def _run_seascape_shoreline_proximity(ctx: DomainBuildContext) -> None:
    from seascape.coastal_configuration.shoreline_proximity.build import (
        build_shoreline_proximity,
    )

    build_shoreline_proximity(config_path=ctx.config_path)


def _run_seascape_exposure_and_enclosure(ctx: DomainBuildContext) -> None:
    from seascape.coastal_configuration.exposure_and_enclosure.build import (
        build_exposure_and_enclosure,
    )

    build_exposure_and_enclosure(config_path=ctx.config_path)


def _run_seascape_waterbody_morphometry(ctx: DomainBuildContext) -> None:
    from seascape.coastal_configuration.waterbody_morphometry.build import (
        build_waterbody_morphometry,
    )

    build_waterbody_morphometry(config_path=ctx.config_path)


def _run_seascape_geomorphic_units(ctx: DomainBuildContext) -> None:
    from seascape.seafloor_physiography.geomorphic_units.build import (
        build_geomorphic_units,
    )

    build_geomorphic_units(config_path=ctx.config_path)


def _run_seascape_freshwater_sources(ctx: DomainBuildContext) -> None:
    from seascape.hydrologic_connectivity.freshwater_sources.build import (
        build_river_mouths,
    )

    build_river_mouths(config_path=ctx.config_path)


def _run_seascape_fluvial_connectivity(ctx: DomainBuildContext) -> None:
    from seascape.hydrologic_connectivity.fluvial_connectivity.build import (
        build_fluvial_connectivity,
    )

    build_fluvial_connectivity(config_path=ctx.config_path)


def _run_seascape_estuarine_connectivity(ctx: DomainBuildContext) -> None:
    from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
        build_estuarine_connectivity,
    )

    build_estuarine_connectivity(config_path=ctx.config_path)


def _run_seascape_fluvial_barriers(ctx: DomainBuildContext) -> None:
    from seascape.hydrologic_connectivity.fluvial_barriers.build import (
        build_fluvial_barriers,
    )

    build_fluvial_barriers(config_path=ctx.config_path)


def _run_seascape_substrate_classification(ctx: DomainBuildContext) -> None:
    from seascape.benthic_substrate.classification.build import (
        build_substrate_classification,
    )

    build_substrate_classification(config_path=ctx.config_path)


def _run_seascape_bottom_hardness(ctx: DomainBuildContext) -> None:
    from seascape.benthic_substrate.bottom_hardness.build import (
        build_bottom_hardness,
    )

    build_bottom_hardness(config_path=ctx.config_path)


def _run_seascape_seagrass_habitat(ctx: DomainBuildContext) -> None:
    from seascape.biogenic_habitat.seagrass.build import (
        build_seagrass_habitat,
    )

    build_seagrass_habitat(config_path=ctx.config_path)


def _run_seascape_kelp_habitat(ctx: DomainBuildContext) -> None:
    from seascape.biogenic_habitat.kelp.build import (
        build_kelp_habitat,
    )

    build_kelp_habitat(config_path=ctx.config_path)


def _run_seascape_reef_habitat(ctx: DomainBuildContext) -> None:
    from seascape.biogenic_habitat.reef.build import (
        build_reef_habitat,
    )

    build_reef_habitat(config_path=ctx.config_path)


def _run_seascape_benthic_habitat_composite(ctx: DomainBuildContext) -> None:
    from seascape.biogenic_habitat.composite.build import (
        build_benthic_habitat_composite,
    )

    build_benthic_habitat_composite(config_path=ctx.config_path)


def _run_seascape_anthropogenic(ctx: DomainBuildContext) -> None:
    from seascape.anthropogenic.build import (
        build_anthropogenic_seascape,
    )

    build_anthropogenic_seascape(config_path=ctx.config_path)


def _run_environment_feature_catalog(ctx: DomainBuildContext) -> None:
    script = Path(
        __import__(
            "seascape.maintenance.update_seascape_feature_catalog",
            fromlist=["__file__"],
        ).__file__
    )
    if not script.exists():
        raise FileNotFoundError(
            f"Environment feature-catalog generator not found: {script}"
        )
    output = ctx.candidate_root / "config/feature_catalog.yaml"
    with _patched_argv(
        "update_environment_feature_catalog.py",
        ["--output", str(output), "--materialization-root", str(ctx.candidate_root)],
    ):
        namespace = runpy.run_path(str(script))
        namespace["main"]()


def _run_seascape_model_policy(ctx: DomainBuildContext) -> None:
    from seascape.modeling.feature_policy import main

    catalog = ctx.candidate_root / "config/feature_catalog.yaml"
    output = ctx.candidate_root / "config/model_feature_policy.yaml"
    with _patched_argv(
        "feature_policy.py",
        [
            "--catalog",
            str(catalog),
            "--output",
            str(output),
            "--materialization-root",
            str(ctx.candidate_root),
        ],
    ):
        main()


def _run_seascape_documentation(ctx: DomainBuildContext) -> None:
    script = Path(
        __import__(
            "seascape.maintenance.update_seascape_docs", fromlist=["__file__"]
        ).__file__
    )
    catalog = ctx.candidate_root / "config/feature_catalog.yaml"
    canonical_readme = project_root() / "docs/products.md"
    readme = ctx.candidate_root / "docs/products.md"
    readme.parent.mkdir(parents=True, exist_ok=True)
    if not readme.exists():
        shutil.copy2(canonical_readme, readme)
    with _patched_argv(
        "update_seascape_docs.py",
        ["--catalog", str(catalog), "--readme", str(readme)],
    ):
        namespace = runpy.run_path(str(script))
        namespace["main"]()


def _run_seascape_release_audit(ctx: DomainBuildContext) -> None:
    from seascape.core.artifacts import atomic_write_json
    from seascape.release import build_release_audit

    catalog = ctx.candidate_root / "config/feature_catalog.yaml"
    output = (
        ctx.candidate_root
        / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    )
    audit = build_release_audit(ctx.candidate_root, catalog)
    atomic_write_json(output, audit, overwrite=True)


def _run_seascape_release(ctx: DomainBuildContext) -> None:
    from seascape.release import publish_candidate_release

    if ctx.publish:
        publish_candidate_release(
            canonical_project_root=ctx.canonical_root,
            candidate_project_root=ctx.candidate_root,
        )


def _environment_domain_config(ctx: DomainBuildContext, key: str) -> Path:
    payload = yaml.safe_load(ctx.config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get(key):
        raise ValueError(
            f"Environment build config does not declare {key}: {ctx.config_path}"
        )
    return resolve_config_include(ctx.config_path, str(payload[key]))


DOMAIN_LAYER_STAGES: tuple[DomainBuildStage, ...] = (
    DomainBuildStage(
        "seascape-water-geometry",
        "Build base territorial/ocean water polygons.",
        _run_seascape_water_geometry,
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry/water_geometry_manifest.json",
        ),
    ),
    DomainBuildStage(
        "h3-water-universe",
        "Build resolution-specific H3 geometry layers over water.",
        _run_h3_water_universe,
        dependencies=("seascape-water-geometry",),
        declared_outputs=(
            *tuple(
                (
                    f"data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/{name}_{resolution}.parquet"
                    for resolution in (4, 5, 6, 7, 8)
                    for name in ("H3_GRIDS", "H3_GRIDS_CLIPPED")
                )
            ),
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/h3_geometry_manifest.json",
        ),
    ),
    DomainBuildStage(
        "h3-marine-spatial-support",
        "Build canonical H3 marine support and water-passable graphs.",
        _run_h3_marine_spatial_support,
        dependencies=("h3-water-universe",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/spatial_support/water_network",
            *tuple(
                (
                    f"data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/{name}_RES_{resolution}.parquet"
                    for resolution in (6, 8)
                    for name in (
                        "H3_MARINE_SUPPORT",
                        "H3_MODEL_AREA_SUPPORT",
                        "H3_MARINE_FULL_CELL_GEOMETRY",
                        "H3_MARINE_WATER_CLIPPED_GEOMETRY",
                    )
                )
            ),
            "data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_PARENT_CHILD_RES_8_TO_RES_6.parquet",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/spatial_support/water_network/_dataset_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-shoreline-characterization",
        "Build physical shoreline fractions and straight/network class distances.",
        _run_seascape_shoreline_characterization,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/shoreline_characterization",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/shoreline_characterization/shoreline_characterization_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-bathymetry",
        "Build GEBCO bathymetry at the configured H3 resolutions.",
        _run_seascape_bathymetry,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry/bathymetry_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-geomorphometry",
        "Build native and multi-ring seafloor geomorphometry.",
        _run_seascape_geomorphometry,
        dependencies=("seascape-bathymetry",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/seafloor_physiography/geomorphometry",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/seafloor_physiography/geomorphometry/geomorphometry_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-shoreline-proximity",
        "Build straight and canonical-network shoreline proximity.",
        _run_seascape_shoreline_proximity,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/shoreline_proximity",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/shoreline_proximity/shoreline_proximity_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-exposure-and-enclosure",
        "Build directional marine exposure and enclosure.",
        _run_seascape_exposure_and_enclosure,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/exposure_and_enclosure",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/exposure_and_enclosure/exposure_and_enclosure_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-waterbody-morphometry",
        "Build waterbody width, constriction, narrows, and sill metrics.",
        _run_seascape_waterbody_morphometry,
        dependencies=("seascape-bathymetry",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/waterbody_morphometry",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/waterbody_morphometry/waterbody_morphometry_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-geomorphic-units",
        "Classify model-area seafloor geomorphic units.",
        _run_seascape_geomorphic_units,
        dependencies=("seascape-geomorphometry", "seascape-waterbody-morphometry"),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/seafloor_physiography/geomorphic_units",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/seafloor_physiography/geomorphic_units/geomorphic_units_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-freshwater-sources",
        "Build river-mouth inventories and mapped-mouth pressure metrics.",
        _run_seascape_freshwater_sources,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/freshwater_sources",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/freshwater_sources/river_mouths_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-fluvial-connectivity",
        "Build HydroRIVERS topology, mouths, and the watershed-to-marine crosswalk.",
        _run_seascape_fluvial_connectivity,
        dependencies=("seascape-freshwater-sources",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_connectivity",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_connectivity/fluvial_connectivity_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-estuarine-connectivity",
        "Build straight and canonical-network estuary proximity.",
        _run_seascape_estuarine_connectivity,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/estuarine_connectivity",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/estuarine_connectivity/estuarine_connectivity_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-fluvial-barriers",
        "Build sourced barriers and assessed passage status at H3 r8 and r6.",
        _run_seascape_fluvial_barriers,
        dependencies=("seascape-fluvial-connectivity",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_barriers",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_barriers/fluvial_barriers_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-substrate-classification",
        "Build cross-border dbSEABED substrate composition at H3 r8 and r6.",
        _run_seascape_substrate_classification,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/classification",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/classification/benthic_substrate_classification_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-bottom-hardness",
        "Derive bottom-hardness indices from modeled dbSEABED composition.",
        _run_seascape_bottom_hardness,
        dependencies=("seascape-substrate-classification",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/bottom_hardness",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/bottom_hardness/bottom_hardness_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-seagrass-habitat",
        "Build Sentinel-2 seagrass values and modeled-confidence products at H3 r8 and r6.",
        _run_seascape_seagrass_habitat,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/seagrass",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/seagrass/seagrass_habitat_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-kelp-habitat",
        "Build kelp values and survey-confidence products at H3 r8 and r6.",
        _run_seascape_kelp_habitat,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/kelp",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/kelp/kelp_habitat_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-reef-habitat",
        "Build distinct rocky, biogenic, and deep-coral/sponge reef products.",
        _run_seascape_reef_habitat,
        dependencies=("seascape-bottom-hardness", "seascape-geomorphometry"),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/reef",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/reef/reef_habitat_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-benthic-habitat-composite",
        "Assemble the model-ready benthic panel without collapsing habitat families.",
        _run_seascape_benthic_habitat_composite,
        dependencies=(
            "seascape-seagrass-habitat",
            "seascape-kelp-habitat",
            "seascape-reef-habitat",
        ),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/composite",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/composite/benthic_habitat_composite_manifest.json",
        ),
    ),
    DomainBuildStage(
        "seascape-anthropogenic",
        "Build cross-border anthropogenic structures and evidence products.",
        _run_seascape_anthropogenic,
        dependencies=("h3-marine-spatial-support",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/anthropogenic",
        ),
        declared_manifests=(
            "data/processed/domain/environmental_layer/seascape/anthropogenic/anthropogenic_manifest.json",
        ),
    ),
    DomainBuildStage(
        "environment-feature-catalog",
        "Regenerate the artifact-verified environment feature catalog.",
        _run_environment_feature_catalog,
        dependencies=(
            "seascape-shoreline-characterization",
            "seascape-geomorphic-units",
            "seascape-shoreline-proximity",
            "seascape-exposure-and-enclosure",
            "seascape-fluvial-barriers",
            "seascape-estuarine-connectivity",
            "seascape-benthic-habitat-composite",
            "seascape-anthropogenic",
        ),
        declared_outputs=("config/feature_catalog.yaml",),
    ),
    DomainBuildStage(
        "seascape-model-policy",
        "Regenerate the materialization- and scale-gated seascape model policy.",
        _run_seascape_model_policy,
        dependencies=("environment-feature-catalog",),
        declared_outputs=("config/model_feature_policy.yaml",),
    ),
    DomainBuildStage(
        "seascape-documentation",
        "Regenerate the seascape README product and variable index.",
        _run_seascape_documentation,
        dependencies=("environment-feature-catalog",),
        declared_outputs=("docs/products.md",),
    ),
    DomainBuildStage(
        "seascape-release-audit",
        "Audit candidate artifacts, manifests, catalog, policy, and documentation.",
        _run_seascape_release_audit,
        dependencies=("seascape-model-policy", "seascape-documentation"),
        declared_outputs=(
            "outputs/domains/environmental_layer/seascape/seascape_release_audit.json",
        ),
        terminal_action=True,
    ),
    DomainBuildStage(
        "seascape-release",
        "Promote the approved candidate release to stable canonical paths.",
        _run_seascape_release,
        dependencies=("seascape-release-audit",),
        declared_outputs=(
            "data/processed/domain/environmental_layer/seascape/seascape_release_manifest.json",
        ),
        terminal_action=True,
    ),
)


def stage_names() -> list[str]:
    return [stage.name for stage in DOMAIN_LAYER_STAGES]


def _stage_registry(
    stages: Sequence[DomainBuildStage] = DOMAIN_LAYER_STAGES,
) -> dict[str, DomainBuildStage]:
    registry: dict[str, DomainBuildStage] = {}
    for stage in stages:
        if stage.name in registry:
            raise ValueError(f"Duplicate domain build stage: {stage.name}")
        registry[stage.name] = stage
    unknown_dependencies = sorted(
        {
            dependency
            for stage in stages
            for dependency in stage.dependencies
            if dependency not in registry
        }
    )
    if unknown_dependencies:
        raise ValueError(
            "Domain build stages declare unknown dependencies: "
            + ", ".join(unknown_dependencies)
        )
    try:
        TopologicalSorter(
            {stage.name: set(stage.dependencies) for stage in stages}
        ).prepare()
    except CycleError as exc:
        raise ValueError(f"Domain build stage dependency cycle: {exc}") from exc
    return registry


def selected_stages(
    *,
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
    stages: Sequence[DomainBuildStage] = DOMAIN_LAYER_STAGES,
) -> list[DomainBuildStage]:
    by_name = _stage_registry(stages)
    only_set = set(only)
    skip_set = set(skip)
    unknown = (only_set | skip_set) - set(by_name)
    if unknown:
        raise ValueError(
            "Unknown build-domain-layers stage(s): "
            + ", ".join(sorted(unknown))
            + ". Valid stages: "
            + ", ".join(by_name)
        )
    requested = [name for name in by_name if not only_set or name in only_set]
    ordered: list[DomainBuildStage] = []
    complete: set[str] = set()
    visiting: list[str] = []

    def visit(name: str) -> None:
        if name in complete:
            return
        if name in visiting:
            cycle = " -> ".join([*visiting[visiting.index(name) :], name])
            raise ValueError(f"Domain build stage dependency cycle: {cycle}")
        visiting.append(name)
        for dependency in by_name[name].dependencies:
            visit(dependency)
        visiting.pop()
        complete.add(name)
        ordered.append(by_name[name])

    for name in requested:
        visit(name)
    return ordered


_CANDIDATE_PATH_PREFIXES = (
    "data/processed/domain/environmental_layer/seascape",
    "outputs/domains/environmental_layer/seascape",
    "config/feature_catalog.yaml",
    "config/model_feature_policy.yaml",
    "docs/products.md",
)


def _rebase_candidate_values(
    value: Any, canonical_root: Path, candidate_root: Path
) -> Any:
    if isinstance(value, dict):
        return {
            key: _rebase_candidate_values(item, canonical_root, candidate_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rebase_candidate_values(item, canonical_root, candidate_root)
            for item in value
        ]
    if not isinstance(value, str):
        return value
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return value
    normalized = candidate.as_posix()
    if normalized == "data/raw" or normalized.startswith("data/raw/"):
        return str((canonical_root / candidate).resolve())
    if any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _CANDIDATE_PATH_PREFIXES
    ):
        return str((candidate_root / candidate).resolve())
    return value


def _prepare_candidate_config(
    source_config: Path,
    *,
    canonical_root: Path,
    candidate_root: Path,
) -> Path:
    """Create a project config whose processed environment paths target the candidate."""

    config_dir = candidate_root / ".seascape/config"
    config_dir.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load(source_config.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Domain build config must be a mapping: {source_config}")
    rendered = _rebase_candidate_values(raw, canonical_root, candidate_root)
    for key in ("SEASCAPE_LAYER",):
        include = raw.get(key)
        if not include:
            continue
        include_path = resolve_config_path(str(include))
        include_payload = yaml.safe_load(include_path.read_text(encoding="utf-8"))
        if not isinstance(include_payload, dict):
            raise ValueError(f"Environment config must be a mapping: {include_path}")
        candidate_include = config_dir / include_path.name
        candidate_include.write_text(
            yaml.safe_dump(
                _rebase_candidate_values(
                    include_payload, canonical_root, candidate_root
                ),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        rendered[key] = str(candidate_include)
    rendered["base_directory"] = str(canonical_root)
    destination = config_dir / source_config.name
    destination.write_text(yaml.safe_dump(rendered, sort_keys=False), encoding="utf-8")
    return destination


def _stage_state_path(candidate_root: Path, stage: DomainBuildStage) -> Path:
    return candidate_root / ".seascape/stages" / f"{stage.name}.json"


def _configuration_checksum(source_config: Path) -> str:
    """Hash the project config and every declared domain include."""

    source = source_config.resolve()
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Domain build config must be a mapping: {source}")
    paths = [source]
    for key in DOMAIN_CONFIG_KEYS:
        include = payload.get(key)
        if include:
            paths.append(resolve_config_include(source, str(include)))
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=str):
        digest.update(str(path).encode("utf-8"))
        digest.update(checksum_path(path).encode("ascii"))
    return digest.hexdigest()


def _declared_paths(root: Path, stage: DomainBuildStage) -> tuple[Path, ...]:
    return tuple(
        dict.fromkeys(
            root / path for path in (*stage.declared_outputs, *stage.declared_manifests)
        )
    )


def _dependency_state_checksums(
    candidate_root: Path,
    stage: DomainBuildStage,
    registry: dict[str, DomainBuildStage] | None = None,
) -> dict[str, str]:
    checksums: dict[str, str] = {}
    registry = registry or _stage_registry()
    for dependency in stage.dependencies:
        path = _stage_state_path(candidate_root, registry[dependency])
        if path.exists():
            checksums[dependency] = checksum_path(path)
    return checksums


def _stage_is_reusable(
    stage: DomainBuildStage,
    *,
    source_config: Path,
    candidate_root: Path,
    registry: dict[str, DomainBuildStage] | None = None,
) -> bool:
    state_path = _stage_state_path(candidate_root, stage)
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("config_checksum") != _configuration_checksum(source_config):
            return False
        if state.get("upstream_state_checksums") != _dependency_state_checksums(
            candidate_root, stage, registry
        ):
            return False
        observed = {
            str(path.relative_to(candidate_root)): checksum_path(path)
            for path in _declared_paths(candidate_root, stage)
            if path.exists()
        }
        return bool(observed) and observed == state.get("declared_path_checksums")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _canonical_stage_is_seedable(
    stage: DomainBuildStage,
    *,
    canonical_root: Path,
    candidate_root: Path,
) -> bool:
    """Return whether a skipped seascape stage has a strict canonical v3 source."""

    if not stage.declared_manifests:
        return False
    candidate_paths = _declared_paths(candidate_root, stage)
    if any(path.exists() for path in candidate_paths):
        return False
    canonical_paths = _declared_paths(canonical_root, stage)
    if any(not path.exists() for path in canonical_paths):
        return False
    try:
        from seascape.utils.artifacts import (
            load_manifest,
            validate_manifest,
        )

        for relative in stage.declared_manifests:
            manifest_path = canonical_root / relative
            payload = load_manifest(manifest_path)
            validate_manifest(
                payload, project_root=canonical_root, verify_artifacts=True
            )
            for upstream in payload.get("upstream_artifacts", []):
                source = Path(str(upstream["path"]))
                resolved = source if source.is_absolute() else canonical_root / source
                if checksum_path(resolved) != upstream.get("checksum"):
                    return False
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
    return True


def _seed_canonical_stage(
    stage: DomainBuildStage,
    *,
    canonical_root: Path,
    candidate_root: Path,
) -> bool:
    """Copy one checksum-valid canonical stage into an empty candidate transaction."""

    if not _canonical_stage_is_seedable(
        stage,
        canonical_root=canonical_root,
        candidate_root=candidate_root,
    ):
        return False
    from seascape.core.artifacts import TransactionalFamilyPublisher

    all_relative = tuple(
        dict.fromkeys((*stage.declared_outputs, *stage.declared_manifests))
    )
    retained: list[Path] = []
    for relative in sorted(
        (Path(value) for value in all_relative), key=lambda path: len(path.parts)
    ):
        if any(relative.is_relative_to(parent) for parent in retained):
            continue
        retained.append(relative)
    with TransactionalFamilyPublisher(
        candidate_root,
        run_id=f"seed-{stage.name}",
    ) as publisher:
        for relative in retained:
            source = canonical_root / relative
            destination = candidate_root / relative
            staged = publisher.stage_path(destination)
            if source.is_dir():
                shutil.copytree(source, staged)
            else:
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, staged)
        publisher.publish()
    return True


def _record_stage_state(
    stage: DomainBuildStage,
    *,
    source_config: Path,
    candidate_root: Path,
    registry: dict[str, DomainBuildStage] | None = None,
) -> None:
    paths = _declared_paths(candidate_root, stage)
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Stage {stage.name} did not produce declared path: {missing[0]}"
        )
    state_path = _stage_state_path(candidate_root, stage)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "stage": stage.name,
        "config_checksum": _configuration_checksum(source_config),
        "upstream_state_checksums": _dependency_state_checksums(
            candidate_root, stage, registry
        ),
        "declared_path_checksums": {
            str(path.relative_to(candidate_root)): checksum_path(path) for path in paths
        },
    }
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_domain_layer_build(
    *,
    config_path: str | Path,
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
    dry_run: bool = False,
    manifest_path: str | Path | None = None,
    candidate_root: str | Path | None = None,
    resume: bool = False,
    publish: bool = True,
    stage_definitions: Sequence[DomainBuildStage] | None = None,
    **context_kwargs: Any,
) -> list[StageResult]:
    source_config = resolve_config_path(config_path)
    canonical_root = project_root().resolve()
    candidate = (
        Path(candidate_root).expanduser().resolve()
        if candidate_root is not None
        else canonical_root
        / ".seascape/candidates/seascape"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    config = (
        source_config
        if dry_run
        else _prepare_candidate_config(
            source_config,
            canonical_root=canonical_root,
            candidate_root=candidate,
        )
    )
    ctx = DomainBuildContext(
        config_path=config,
        source_config_path=source_config,
        candidate_root=candidate,
        canonical_root=canonical_root,
        resume=resume,
        publish=publish,
        **context_kwargs,
    )
    available_stages = tuple(stage_definitions or DOMAIN_LAYER_STAGES)
    registry = _stage_registry(available_stages)
    stages = selected_stages(only=only, skip=skip, stages=available_stages)
    skip_set = set(skip)
    results: list[StageResult] = []
    status_by_name: dict[str, str] = {}

    print(f"[build-domain-layers] candidate root: {candidate}")
    print("[build-domain-layers] dependency-expanded stage order:")
    for index, stage in enumerate(stages, start=1):
        action = "build"
        if stage.name in skip_set:
            reusable = _stage_is_reusable(
                stage,
                source_config=source_config,
                candidate_root=candidate,
                registry=registry,
            ) or _canonical_stage_is_seedable(
                stage,
                canonical_root=canonical_root,
                candidate_root=candidate,
            )
            action = "reuse" if reusable else "blocked"
        elif (
            resume
            and not ctx.overwrite
            and _stage_is_reusable(
                stage,
                source_config=source_config,
                candidate_root=candidate,
                registry=registry,
            )
        ):
            action = "reuse"
        elif stage.name == "seascape-release":
            action = "publish" if publish else "retain-candidate"
        elif stage.terminal_action:
            action = "release-gate"
        print(f"  {index:02d}. [{action}] {stage.name} - {stage.description}")
    if dry_run:
        for stage in stages:
            blocked = any(
                status_by_name.get(dependency) == "blocked_dependency"
                for dependency in stage.dependencies
            )
            reusable = _stage_is_reusable(
                stage,
                source_config=source_config,
                candidate_root=candidate,
                registry=registry,
            )
            if stage.name in skip_set and not reusable:
                reusable = _canonical_stage_is_seedable(
                    stage,
                    canonical_root=canonical_root,
                    candidate_root=candidate,
                )
            if blocked or (stage.name in skip_set and not reusable):
                status = "blocked_dependency"
            elif (
                stage.name in skip_set or (resume and not ctx.overwrite)
            ) and reusable:
                status = "reused"
            else:
                status = "planned"
            status_by_name[stage.name] = status
            results.append(StageResult(stage.name, status))
        _write_manifest_if_requested(
            manifest_path, source_config, results, dry_run=True
        )
        return results

    for stage in stages:
        failed_dependencies = [
            dependency
            for dependency in stage.dependencies
            if status_by_name.get(dependency) in {"failed", "blocked_dependency"}
        ]
        if failed_dependencies:
            error = "blocked by: " + ", ".join(failed_dependencies)
            status_by_name[stage.name] = "blocked_dependency"
            results.append(StageResult(stage.name, "blocked_dependency", error=error))
            print(f"[build-domain-layers] {stage.name} blocked ({error})")
            continue
        reusable = _stage_is_reusable(
            stage,
            source_config=source_config,
            candidate_root=candidate,
            registry=registry,
        )
        seeded = False
        if stage.name in skip_set and not reusable:
            seeded = _seed_canonical_stage(
                stage,
                canonical_root=canonical_root,
                candidate_root=candidate,
            )
            if seeded:
                _record_stage_state(
                    stage,
                    source_config=source_config,
                    candidate_root=candidate,
                    registry=registry,
                )
                reusable = True
        if (stage.name in skip_set or (resume and not ctx.overwrite)) and reusable:
            status_by_name[stage.name] = "reused"
            results.append(StageResult(stage.name, "reused"))
            suffix = " from validated canonical artifacts" if seeded else ""
            print(f"[build-domain-layers] {stage.name} reused{suffix}")
            continue
        if stage.name in skip_set:
            error = "skipped stage has no checksum/config/upstream-valid candidate artifacts"
            status_by_name[stage.name] = "blocked_dependency"
            results.append(StageResult(stage.name, "blocked_dependency", error=error))
            print(f"[build-domain-layers] {stage.name} blocked ({error})")
            continue
        start = time.perf_counter()
        print(f"[build-domain-layers] {stage.name} start")
        try:
            with _candidate_environment(candidate):
                stage_context = replace(ctx, overwrite=True) if ctx.resume else ctx
                stage.runner(stage_context)
            if stage.name != "seascape-release":
                _record_stage_state(
                    stage,
                    source_config=source_config,
                    candidate_root=candidate,
                    registry=registry,
                )
        except Exception as exc:
            elapsed = time.perf_counter() - start
            status_by_name[stage.name] = "failed"
            results.append(
                StageResult(
                    stage.name, "failed", elapsed_seconds=elapsed, error=str(exc)
                )
            )
            print(f"[build-domain-layers] {stage.name} failed ({elapsed:.1f}s): {exc}")
            if not ctx.continue_on_error:
                _write_manifest_if_requested(
                    manifest_path, source_config, results, dry_run=False
                )
                raise
        else:
            elapsed = time.perf_counter() - start
            status_by_name[stage.name] = "complete"
            results.append(StageResult(stage.name, "complete", elapsed_seconds=elapsed))
            print(f"[build-domain-layers] {stage.name} complete ({elapsed:.1f}s)")

    _write_manifest_if_requested(manifest_path, source_config, results, dry_run=False)
    return results


def _write_manifest_if_requested(
    manifest_path: str | Path | None,
    config_path: Path,
    results: Sequence[StageResult],
    *,
    dry_run: bool,
) -> None:
    if manifest_path is None:
        return
    path = Path(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pipeline": "build-domain-layers",
        "config_path": str(config_path),
        "dry_run": dry_run,
        "created_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "stages": [
            {
                "name": result.name,
                "status": result.status,
                "elapsed_seconds": round(result.elapsed_seconds, 3),
                **({"error": result.error} if result.error else {}),
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"[build-domain-layers] manifest written -> {path}")
