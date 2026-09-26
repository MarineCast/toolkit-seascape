"""Lightweight, read-only input inspection for the existing candidate planner.

A ready report covers configuration loaders and local file/header access, never
pixel values, feature coverage, checksums, resume identity, or release approval.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields
import importlib
import os
from pathlib import Path
import re
from typing import Any

import yaml

from seascape.core.config.data import _preview_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.config import resolve_project_path
from seascape.workflow import plan_domain_layer_build, _render_candidate_config

LIMITATIONS = [
    "Local configuration, path/readability and geospatial headers only; no source acquisition or producer execution.",
    "No dataset hashes, vector/Parquet headers, pixel/feature scans, coverage, vertical datum verification, scientific calculations or release audit.",
    "Generated intermediates are promises of the selected producers, not validated materialized products.",
    "Reuse/skip identities require the existing checksum validators and are not inspected by this lightweight check.",
]
_EXPECTED = (OSError, ValueError, KeyError, TypeError, yaml.YAMLError)


@dataclass(frozen=True)
class Input:
    name: str
    path: Path
    required: bool = True
    native_slope: bool = False


@dataclass
class Contract:
    inputs: list[Input]
    outputs: list[Path]
    checks: list[str]


def _safe(value: Any) -> str:
    text = str(value)
    # Do not emit credential-bearing remote locations, even in rejected paths.
    return (
        "<redacted remote location>"
        if re.search(r"[A-Za-z][A-Za-z0-9+.-]*:/", text)
        else text
    )


def _check(
    stage: str,
    name: str,
    status: str,
    *,
    required: bool = True,
    path: Path | None = None,
    action: str = "",
    performed: list[str] | None = None,
) -> dict:
    return {
        "stage": stage,
        "name": name,
        "status": status,
        "required": required,
        "path": _safe(path) if path is not None else None,
        "performed": performed or [],
        "corrective_action": action,
    }


@contextmanager
def _common_environment(workspace: Path):
    """Match the common document that execution freezes in the candidate."""
    common = workspace / "config/common.yaml"
    previous = os.environ.get("SEASCAPE_COMMON_CONFIG")
    if common.is_file():
        os.environ["SEASCAPE_COMMON_CONFIG"] = str(common)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SEASCAPE_COMMON_CONFIG", None)
        else:
            os.environ["SEASCAPE_COMMON_CONFIG"] = previous


def _network_inputs(path: Path, resolutions=(6, 8)) -> list[Input]:
    from seascape.spatial_support.water_network.config import load_water_network_config

    c = load_water_network_config(path)
    result = [
        Input("water polygon", c.water_polygon_path),
        Input("network manifest", c.manifest_path),
    ]
    for res in resolutions:
        result.extend(
            Input(f"{name} r{res}", getattr(c, method)(res))
            for name, method in (
                ("model support", "model_support_path"),
                ("clipped geometry", "clipped_geometry_path"),
                ("water edges", "edge_path"),
                ("water connectors", "connector_path"),
            )
        )
    return result


def _contract(stage, path: Path, raw: dict) -> Contract:
    """Adapters call the existing family loaders; selection stays in workflow.py."""
    name = stage.name
    inputs: list[Input] = []
    outputs: list[Path] = []
    checks = ["existing family configuration loader (including declared metric CRS)"]
    base = Path(raw["base_directory"])
    if name == "seascape-water-geometry":
        from seascape.spatial_support.water_geometry.config import (
            load_water_geometry_config,
        )
        from seascape.spatial_support.water_geometry.download import (
            CONSUMED_WATER_GEOMETRY_SOURCE_NAMES,
            resolve_water_geometry_paths,
        )

        c = load_water_geometry_config(path)
        sources = resolve_water_geometry_paths(c)
        inputs = [
            Input(key, Path(sources[key]))
            for key in CONSUMED_WATER_GEOMETRY_SOURCE_NAMES
        ]
        outputs = [
            c["output_path"],
            c["output_path"].parent / "water_geometry_manifest.json",
        ]
    elif name == "h3-water-universe":
        from seascape.spatial_support.h3_geometry.build import load_h3_geometry_config

        c = load_h3_geometry_config(path)
        inputs = [Input("water polygon", c["water_path"])]
        outputs = [
            c["output_dir"] / c[key].format(res=res)
            for res in c["h3_resolutions"]
            for key in (
                "output_grid_filename_template",
                "output_clipped_grid_filename_template",
            )
        ]
        outputs.append(c["output_dir"] / "h3_geometry_manifest.json")
    elif name == "h3-marine-spatial-support":
        from seascape.spatial_support.water_network.config import (
            load_water_network_config,
        )

        c = load_water_network_config(path)
        inputs = [Input("water polygon", c.water_polygon_path)]
        outputs = [
            getattr(c, method)(res)
            for res in c.resolutions
            for method in (
                "support_path",
                "model_support_path",
                "full_geometry_path",
                "clipped_geometry_path",
                "edge_path",
                "connector_path",
                "neighborhood_path",
            )
        ]
        outputs += [
            c.parent_child_path,
            c.radius_sum_operator_path,
            c.reachable_water_area_path,
            c.manifest_path,
        ]
    elif name == "seascape-bathymetry":
        from seascape.seafloor_physiography.bathymetry.pipeline import (
            load_bathymetry_config,
        )

        c = load_bathymetry_config(path)
        resolutions = [
            c.h3_resolution,
            *(item.h3_resolution for item in c.additional_exports),
        ]
        inputs = [
            Input("source raster", c.raw_path),
            Input("water polygon", c.water_polygon_path),
        ]
        for res in resolutions:
            inputs += [
                Input(
                    f"model support r{res}",
                    resolve_project_path(c.h3_grid_path_template.format(res=res), base),
                ),
                Input(
                    f"water neighborhoods r{res}",
                    Path(c.water_neighborhood_path_template.format(res=res)),
                ),
            ]
        outputs = [
            c.processed_path,
            *(item.processed_path for item in c.additional_exports),
            c.processed_path.parent / "bathymetry_manifest.json",
        ]
    elif name == "seascape-shoreline-characterization":
        from seascape.coastal_configuration.shoreline_characterization.build import (
            load_shoreline_config,
        )

        c = load_shoreline_config(path)
        inputs = [
            Input(key, resolve_project_path(value["path"], base))
            for key, value in c.sources.items()
        ]
        inputs += [
            Input(f"full geometry r{res}", c.full_geometry_path(res))
            for res in c.resolutions
        ]
        inputs += _network_inputs(path, c.resolutions)
        outputs = [
            c.inventory_path,
            c.manifest_path,
            *(c.feature_path(res) for res in c.resolutions),
        ]
    elif name in {
        "seascape-geomorphometry",
        "seascape-geomorphic-units",
        "seascape-shoreline-proximity",
        "seascape-exposure-and-enclosure",
        "seascape-waterbody-morphometry",
        "seascape-fluvial-connectivity",
        "seascape-estuarine-connectivity",
        "seascape-freshwater-sources",
    }:
        # This maps loader names only, not stage order/dependencies/output declarations.
        module, loader, output_fields = {
            "seascape-geomorphometry": (
                "seafloor_physiography.geomorphometry.build",
                "load_geomorphometry_config",
                {"output_path"},
            ),
            "seascape-geomorphic-units": (
                "seafloor_physiography.geomorphic_units.build",
                "load_geomorphic_units_config",
                {"output_path"},
            ),
            "seascape-shoreline-proximity": (
                "coastal_configuration.shoreline_proximity.build",
                "load_shoreline_proximity_config",
                {"output_path"},
            ),
            "seascape-exposure-and-enclosure": (
                "coastal_configuration.exposure_and_enclosure.build",
                "load_exposure_enclosure_config",
                {"output_path"},
            ),
            "seascape-waterbody-morphometry": (
                "coastal_configuration.waterbody_morphometry.build",
                "load_waterbody_morphometry_config",
                {"output_path"},
            ),
            "seascape-fluvial-connectivity": (
                "hydrologic_connectivity.fluvial_connectivity.topology",
                "load_fluvial_connectivity_config",
                {
                    "feature_path",
                    "crosswalk_path",
                    "network_segments_path",
                    "network_mouths_path",
                },
            ),
            "seascape-estuarine-connectivity": (
                "hydrologic_connectivity.estuarine_connectivity.build",
                "load_estuarine_connectivity_config",
                {"estuary_path", "feature_path"},
            ),
            "seascape-freshwater-sources": (
                "hydrologic_connectivity.freshwater_sources.build",
                "load_river_mouth_build_config",
                {"river_mouths_path", "river_systems_path", "feature_path"},
            ),
        }[name]
        c = getattr(importlib.import_module(f"seascape.{module}"), loader)(path)
        for field in fields(c):
            value = getattr(c, field.name)
            if field.name in output_fields:
                outputs.append(value)
            elif field.name.endswith("_path") and isinstance(value, Path):
                inputs.append(
                    Input(
                        field.name,
                        value,
                        native_slope=field.name == "native_raster_path",
                    )
                )
        if name == "seascape-freshwater-sources":
            from seascape.hydrologic_connectivity.freshwater_sources.build import (
                _hydrorivers_path,
            )

            inputs += [Input(key, value) for key, value in c.raw_paths.items()]
            try:
                hydrorivers = _hydrorivers_path(c)
            except FileNotFoundError:
                hydrorivers = c.hydrorivers_extract_dir
            inputs.append(Input("HydroRIVERS extracted shapefile", hydrorivers))
        manifest_name = (
            "river_mouths"
            if name == "seascape-freshwater-sources"
            else name.removeprefix("seascape-").replace("-", "_")
        )
        outputs.append(outputs[0].parent / f"{manifest_name}_manifest.json")
        if name != "seascape-freshwater-sources":
            inputs += _network_inputs(path, (c.h3_resolution,))
        if name == "seascape-geomorphometry":
            from seascape.spatial_support.water_network.config import (
                load_water_network_config,
            )

            inputs.append(
                Input(
                    "water neighborhoods",
                    load_water_network_config(path).neighborhood_path(c.h3_resolution),
                )
            )
    elif name.startswith("seascape-") and name.removeprefix("seascape-") in {
        "substrate-classification",
        "bottom-hardness",
        "seagrass-habitat",
        "kelp-habitat",
        "reef-habitat",
        "benthic-habitat-composite",
        "fluvial-barriers",
        "anthropogenic",
    }:
        from seascape.utils.habitat_configuration import load_habitat_surface_config
        from seascape.utils.habitat_acquisition import load_habitat_download_config
        from seascape.spatial_support.water_network.config import (
            load_water_network_config,
        )

        module = {
            "seascape-substrate-classification": "benthic_substrate.classification",
            "seascape-bottom-hardness": "benthic_substrate.bottom_hardness",
            "seascape-seagrass-habitat": "biogenic_habitat.seagrass",
            "seascape-kelp-habitat": "biogenic_habitat.kelp",
            "seascape-reef-habitat": "biogenic_habitat.reef",
            "seascape-benthic-habitat-composite": "biogenic_habitat.composite",
            "seascape-fluvial-barriers": "hydrologic_connectivity.fluvial_barriers",
            "seascape-anthropogenic": "anthropogenic",
        }[name]
        build = importlib.import_module(f"seascape.{module}.build")
        c = load_habitat_surface_config(build.SECTION_NAME, build.PREFIX, path)
        outputs = [
            c.inventory_path,
            c.manifest_path,
            *(
                getattr(c, method)(res)
                for res in (6, 8)
                for method in ("feature_path", "confidence_path")
            ),
        ]
        inputs = _network_inputs(path) + [
            Input("parent child crosswalk", c.parent_child_path)
        ]
        if name == "seascape-bottom-hardness":
            substrate = load_habitat_surface_config(
                build.SUBSTRATE_SECTION, build.SUBSTRATE_PREFIX, path
            )
            inputs += [
                Input(f"substrate {method} r{res}", getattr(substrate, method)(res))
                for res in (6, 8)
                for method in ("feature_path", "confidence_path")
            ]
        elif name == "seascape-benthic-habitat-composite":
            inputs += [
                Input(f"{key} {method} r{res}", getattr(family, method)(res))
                for key, family in build._family_configs(path).items()
                for res in (6, 8)
                for method in ("feature_path", "confidence_path")
                if key != "substrate" or method == "confidence_path"
            ]
        else:
            d = load_habitat_download_config(build.SECTION_NAME, path)
            for key, value in d.sources.items():
                if not value.get("enabled", True):
                    checks.append(f"source {key}: disabled, not applicable")
                    continue
                # Kelp and reef readers permit partial source inventories; presence of
                # a usable inventory remains a producer gate, not a header claim.
                optional = name in {"seascape-kelp-habitat", "seascape-reef-habitat"}
                inputs.append(
                    Input(
                        key,
                        d.raw_dir / str(value["raw_filename"]),
                        required=not optional,
                    )
                )
            if name == "seascape-substrate-classification":
                if any(
                    str(value.get("units", "percent")).lower() != "percent"
                    for value in d.sources.values()
                ):
                    raise ValueError("dbSEABED units must be percent")
                checks.append("dbSEABED declared percent units")
            if name == "seascape-reef-habitat":
                processing = build._reef_processing(path)
                inputs += [
                    Input(key, processing[key])
                    for key in ("geomorphometry_path", "bathymetry_path")
                ]
                for section, prefix in (
                    (build.SUBSTRATE_SECTION, build.SUBSTRATE_PREFIX),
                    (build.HARDNESS_SECTION, build.HARDNESS_PREFIX),
                ):
                    upstream = load_habitat_surface_config(section, prefix, path)
                    inputs += [
                        Input(section, upstream.feature_path(res)) for res in (6, 8)
                    ]
            if name in {"seascape-anthropogenic", "seascape-fluvial-barriers"}:
                sources = importlib.import_module(f"seascape.{module}.sources")
                processing = sources._processing(path)
                if name == "seascape-fluvial-barriers":
                    processing, processing_base = processing
                    inputs += [
                        Input(
                            key, resolve_project_path(processing[key], processing_base)
                        )
                        for key in (
                            "water_polygon_path",
                            "fluvial_segments_path",
                            "fluvial_mouths_path",
                            "watershed_crosswalk_path",
                        )
                    ]
                    outputs += [
                        c.processed_dir / str(processing[key])
                        for key in (
                            "lineage_filename",
                            "barriers_filename",
                            "mouth_summary_filename",
                        )
                    ]
            if name == "seascape-anthropogenic":
                n = load_water_network_config(path)
                inputs += [
                    Input("radius operator", n.radius_sum_operator_path),
                    Input("reachable water area", n.reachable_water_area_path),
                ]
    elif name in {
        "environment-feature-catalog",
        "seascape-feature-eligibility",
        "seascape-documentation",
        "seascape-release-audit",
        "seascape-release",
    }:
        checks = [
            "existing stage dependency declarations; generated governance/release artifacts inspected during execution"
        ]
    else:
        raise ValueError("No input inspector for this stage")
    return Contract(inputs, outputs, checks)


def _inspect(item: Input, stage: str, generated: dict[Path, str]) -> dict:
    path = item.path.resolve()
    if path in generated:
        return _check(
            stage,
            item.name,
            "generated_by_plan",
            path=path,
            required=item.required,
            action=f"Run selected upstream stage {generated[path]}; validate its resulting artifact during execution.",
            performed=["exact resolved path matched selected upstream output"],
        )
    if re.search(r"[A-Za-z][A-Za-z0-9+.-]*:/", str(path)):
        return _check(
            stage,
            item.name,
            "invalid",
            path=path,
            required=item.required,
            action="Provide a local source path; preflight never opens remote locations.",
        )
    if not path.exists():
        return _check(
            stage,
            item.name,
            "missing_external",
            path=path,
            required=item.required,
            action="Provide the configured local input; review the family's DATA_SOURCES.md before separate acquisition.",
            performed=["local existence"],
        )
    performed = ["local existence", "readability (open and one byte; no hash)"]
    try:
        if not path.is_file():
            return _check(
                stage,
                item.name,
                "unverified",
                path=path,
                required=item.required,
                action="Review directory/archive inputs with the family's validator; this inspector requires a regular file.",
            )
        with path.open("rb") as handle:
            if not handle.read(1):
                raise ValueError("Empty source")
        if path.suffix.lower() in {".tif", ".tiff"}:
            import rasterio

            # Reject disguised VRT/remote datasets before asking GDAL to open them.
            with path.open("rb") as handle:
                if handle.read(4) not in {
                    b"II*\x00",
                    b"MM\x00*",
                    b"II+\x00",
                    b"MM\x00+",
                }:
                    raise ValueError("Expected a local TIFF signature")
            with (
                rasterio.Env(
                    GDAL_PAM_ENABLED="NO", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"
                ),
                rasterio.open(path, driver="GTiff") as raster,
            ):
                if raster.crs is None or raster.count < 1:
                    raise ValueError("Missing raster CRS or bands")
                if item.native_slope:
                    from seascape.seafloor_physiography.geomorphometry.build import (
                        validate_native_raster_header,
                    )

                    validate_native_raster_header(raster)
                    performed.append(
                        "existing native slope header contract (one band, EPSG:4326, north-up, minimum dimensions)"
                    )
                performed.append("raster CRS/bands/dimensions header; no pixel read")
    except (OSError, ValueError) as exc:
        return _check(
            stage,
            item.name,
            "invalid",
            path=path,
            required=item.required,
            action=f"Correct local input access/header ({type(exc).__name__}); review docs/CONTRACTS.md and the family's DATA_SOURCES.md.",
            performed=performed,
        )
    return _check(
        stage,
        item.name,
        "ready",
        path=path,
        required=item.required,
        performed=performed,
    )


def preflight_build(
    *,
    config_path="config/data/project.yaml",
    only=(),
    skip=(),
    candidate_root=None,
    publish=False,
    resume=False,
    overwrite=False,
    check_inputs=True,
) -> dict:
    """Report selected prerequisites without writes, hashes, downloads or builders."""
    only, skip = tuple(only), tuple(skip)
    report = {
        "schema_version": 1,
        "status": "not_run",
        "inspection_level": "local configuration/path and GeoTIFF header; vector/Parquet readability only",
        "workspace": _safe(project_root()),
        "config": _safe(resolve_config_path(config_path)),
        "candidate_root": None,
        "publication_requested": bool(publish),
        "stages": [],
        "checks": [],
        "limitations": LIMITATIONS.copy(),
    }
    try:
        plan = plan_domain_layer_build(
            config_path=config_path, only=only, skip=skip, candidate_root=candidate_root
        )
        report["candidate_root"] = _safe(plan.candidate_root)
        for stage in plan.stages:
            report["stages"].append(
                {
                    "name": stage.name,
                    "dependencies": list(stage.dependencies),
                    "action": (
                        "reuse_requested"
                        if stage.name in skip
                        else ("publish" if publish else "retain-candidate")
                        if stage.name == "seascape-release"
                        else "release-gate"
                        if stage.terminal_action
                        else "build"
                    ),
                    "outputs": [
                        _safe(plan.candidate_root / p)
                        for p in (*stage.declared_outputs, *stage.declared_manifests)
                    ],
                }
            )
        if not check_inputs:
            return report
        rendered = _render_candidate_config(
            plan.source_config,
            canonical_root=plan.canonical_root,
            candidate_root=plan.candidate_root,
        )
    except _EXPECTED as exc:
        report["checks"].append(
            _check(
                "plan",
                "configuration/selection/destination",
                "invalid",
                action=f"Review selected stages, config mapping/includes, metric CRS and candidate confinement ({type(exc).__name__}); see docs/WORKFLOWS.md.",
            )
        )
        report["status"] = "failed"
        return report
    report["checks"].append(
        _check(
            "plan",
            "configuration",
            "ready",
            performed=[
                "existing config composition and metric CRS validator",
                "existing candidate rebase and output confinement",
            ],
        )
    )
    ancestor = plan.candidate_root
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    accessible = ancestor.is_dir() and os.access(ancestor, os.W_OK | os.X_OK)
    report["checks"].append(
        _check(
            "plan",
            "candidate destination access",
            "ready" if accessible else "invalid",
            path=ancestor,
            performed=["nearest existing parent directory/access; no write probe"],
            action="Choose an accessible candidate directory; review existing paths before changing them."
            if not accessible
            else "",
        )
    )
    generated: dict[Path, str] = {}
    with (
        _common_environment(plan.canonical_root),
        _preview_data_config(plan.source_config, rendered),
    ):
        for stage, entry in zip(plan.stages, report["stages"], strict=True):
            if stage.name in skip:
                report["checks"].append(
                    _check(
                        stage.name,
                        "reuse identity",
                        "unverified",
                        action="Use the existing checksum/config/upstream reuse validation; remove --skip to plan rebuilding.",
                    )
                )
                continue
            try:
                contract = _contract(stage, plan.source_config, rendered)
                outputs = contract.outputs or [
                    plan.candidate_root / p for p in stage.declared_outputs
                ]
                # Existing default declarations remain visible, alongside actual configured outputs.
                for output in outputs:
                    if not output.resolve().is_relative_to(plan.candidate_root):
                        raise ValueError("Resolved output escapes candidate")
                entry["configured_outputs"] = [_safe(p) for p in outputs]
                report["checks"].append(
                    _check(
                        stage.name, "configuration", "ready", performed=contract.checks
                    )
                )
                report["checks"] += [
                    _inspect(item, stage.name, generated) for item in contract.inputs
                ]
                if stage.name in {"seascape-kelp-habitat", "seascape-reef-habitat"}:
                    report["checks"].append(
                        _check(
                            stage.name,
                            "usable partial inventory",
                            "unverified",
                            action="Validate a usable inventory with the family producer; optional source existence alone cannot establish this prerequisite.",
                        )
                    )
                generated.update({p.resolve(): stage.name for p in outputs})
            except _EXPECTED as exc:
                report["checks"].append(
                    _check(
                        stage.name,
                        "configuration/input contract",
                        "invalid",
                        action=f"Correct this family's configuration, spatial/unit/sign declarations or input access ({type(exc).__name__}); see docs/CONTRACTS.md and its DATA_SOURCES.md.",
                    )
                )
    report["checks"].append(
        _check(
            "plan",
            "resume identity",
            "unverified" if resume and not overwrite else "not_applicable",
            required=False,
            action="Execution will perform the existing checksum/config/code/upstream validation."
            if resume
            else "",
        )
    )
    report["checks"].append(
        _check(
            "plan",
            "publication/release audit",
            "unverified" if publish else "not_applicable",
            required=False,
            action="Publication requires a successful executed release audit; this command cannot approve it."
            if publish
            else "",
        )
    )
    report["status"] = (
        "failed"
        if any(
            c["required"]
            and c["status"] in {"missing_external", "invalid", "unverified"}
            for c in report["checks"]
        )
        else "ready"
    )
    return report


def print_preflight(report: dict) -> None:
    print(
        f"Preflight: {report['status'].upper()} (configuration/path/header checks only)"
    )
    for name in ("workspace", "config", "candidate_root", "publication_requested"):
        print(f"{name}: {report[name]}")
    for entry in report["stages"]:
        print(f"  [{entry['action']}] {entry['name']}")
        for output in entry.get("configured_outputs", entry["outputs"]):
            print(f"    output: {output}")
    for check in report["checks"]:
        print(
            f"  [{check['status']}] {check['stage']}: {check['name']} ({'required' if check['required'] else 'optional'}) {check['path'] or ''}"
        )
        for performed in check["performed"]:
            print(f"    checked: {performed}")
        if check["corrective_action"]:
            print(f"    action: {check['corrective_action']}")
    for limitation in report["limitations"]:
        print(f"Limit: {limitation}")
