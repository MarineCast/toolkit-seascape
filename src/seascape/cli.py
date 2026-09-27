"""Installed command line interface for independent seascape workspaces."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from seascape._cli_diagnostics import (
    EXPECTED_TYPES,
    build_operation,
    identify_failure,
    safe_detail,
)

FAMILIES = {
    "water-geometry": "spatial_support.water_geometry",
    "h3-geometry": "spatial_support.h3_geometry",
    "water-network": "spatial_support.water_network",
    "bathymetry": "seafloor_physiography.bathymetry",
    "geomorphometry": "seafloor_physiography.geomorphometry",
    "geomorphic-units": "seafloor_physiography.geomorphic_units",
    "shoreline-characterization": "coastal_configuration.shoreline_characterization",
    "shoreline-proximity": "coastal_configuration.shoreline_proximity",
    "exposure-and-enclosure": "coastal_configuration.exposure_and_enclosure",
    "waterbody-morphometry": "coastal_configuration.waterbody_morphometry",
    "freshwater-sources": "hydrologic_connectivity.freshwater_sources",
    "fluvial-connectivity": "hydrologic_connectivity.fluvial_connectivity",
    "estuarine-connectivity": "hydrologic_connectivity.estuarine_connectivity",
    "fluvial-barriers": "hydrologic_connectivity.fluvial_barriers",
    "substrate-classification": "benthic_substrate.classification",
    "bottom-hardness": "benthic_substrate.bottom_hardness",
    "seagrass": "biogenic_habitat.seagrass",
    "kelp": "biogenic_habitat.kelp",
    "reef": "biogenic_habitat.reef",
    "habitat-composite": "biogenic_habitat.composite",
    "anthropogenic": "anthropogenic",
}
DOWNLOAD_FAMILIES = (
    "water-geometry",
    "bathymetry",
    "shoreline-characterization",
    "freshwater-sources",
    "estuarine-connectivity",
    "fluvial-barriers",
    "substrate-classification",
    "bottom-hardness",
    "seagrass",
    "kelp",
    "reef",
    "habitat-composite",
    "anthropogenic",
)


def initialize_workspace(root: Path) -> None:
    """Copy packaged configuration and governance templates without overwriting files."""

    def copy_tree(source: Traversable, destination: Path) -> None:
        for item in source.iterdir():
            path = destination / item.name
            if item.is_dir():
                copy_tree(item, path)
            elif not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.read_bytes())

    copy_tree(files("seascape").joinpath("resources"), root)


def _config_selection(args: argparse.Namespace) -> str:
    if hasattr(args, "config"):
        return args.config
    for index, argument in enumerate(getattr(args, "arguments", [])):
        if argument.startswith("--config="):
            return argument.split("=", 1)[1]
        if argument == "--config" and index + 1 < len(args.arguments):
            return args.arguments[index + 1]
    return "family default (see --help) / release metadata"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Data/config/output root (default: current directory)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print chained tracebacks for identified failures; place before the command",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init", help="Create editable configuration from packaged templates"
    )
    commands.add_parser("stages", help="List dependency-ordered build stages")
    demo = commands.add_parser(
        "demo",
        help="Run synthetic offline software acceptance (not a regional release)",
    )
    demo.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace only known artifacts in an owned demo directory",
    )
    build = commands.add_parser(
        "build", help="Build an isolated candidate from local source data"
    )
    build.add_argument("--config", default="config/data/project.yaml")
    build.add_argument("--only", action="append", default=[])
    build.add_argument("--skip", action="append", default=[])
    build.add_argument("--candidate-root", type=Path)
    build.add_argument("--dry-run", action="store_true")
    build.add_argument(
        "--check-inputs",
        action="store_true",
        help="Read-only local configuration/path/header preflight; requires --dry-run",
    )
    build.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable planning/preflight output; requires --dry-run",
    )
    build.add_argument("--resume", action="store_true")
    build.add_argument("--overwrite", action="store_true")
    build.add_argument(
        "--publish",
        action="store_true",
        help="Promote candidate after the release audit passes",
    )
    export = commands.add_parser(
        "export-metric-matrix",
        help="Write one H3 cell by metric Parquet from a Seascape release",
    )
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--resolution", type=int, action="append", choices=(6, 8))
    export.add_argument("--catalog", type=Path)
    export.add_argument("--legacy-unverified", action="store_true")
    export.add_argument("--overwrite", action="store_true")
    for action in ("download", "inspect"):
        sub = commands.add_parser(
            action, help=f"Run a family's {action} command", add_help=False
        )
        sub.add_argument(
            "family", choices=DOWNLOAD_FAMILIES if action == "download" else FAMILIES
        )
        sub.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if (
        args.command == "build"
        and (args.check_inputs or args.json)
        and not args.dry_run
    ):
        parser.error("build --check-inputs and --json require --dry-run")
    previous = os.environ.get("SEASCAPE_WORKSPACE")
    if args.workspace is not None:
        os.environ["SEASCAPE_WORKSPACE"] = str(args.workspace.expanduser().resolve())
    try:
        from seascape.core.config.paths import project_root

        if args.command == "init":
            initialize_workspace(project_root())
            print(f"Initialized seascape workspace: {project_root()}")
            return 0
        if args.command == "demo":
            from seascape.demo import DemoWorkspaceError, run_demo

            try:
                demo_result = run_demo(project_root(), overwrite=args.overwrite)
            except DemoWorkspaceError as exc:
                if args.debug:
                    traceback.print_exception(exc, file=sys.stderr)
                print(
                    f"demo: {safe_detail(exc)}. Use a fresh workspace or review the demo ownership before --overwrite. Guide: docs/demo.md.",
                    file=sys.stderr,
                )
                return 1
            print("Synthetic software acceptance: PASS (not a regional release)")
            for path in (
                demo_result.parquet_path,
                demo_result.manifest_path,
                demo_result.report_path,
                *demo_result.figure_paths,
            ):
                print(path)
            return 0
        if args.command in {"download", "inspect"}:
            module = f"seascape.{FAMILIES[args.family]}.{args.command}"
            old_argv = sys.argv
            sys.argv = [module, *args.arguments]
            try:
                result = importlib.import_module(module).main()
                return int(result or 0)
            finally:
                sys.argv = old_argv
        if args.command == "export-metric-matrix":
            from seascape.metric_matrix import build_metric_matrix

            matrix_result = build_metric_matrix(
                workspace=project_root(),
                output=args.output,
                resolutions=tuple(args.resolution or (6, 8)),
                legacy_unverified=args.legacy_unverified,
                catalog_path=args.catalog,
                overwrite=args.overwrite,
            )
            print(
                f"{matrix_result.path}\t{matrix_result.row_count} H3 cells\t"
                f"{matrix_result.field_count} catalog fields\t{matrix_result.source_validation}"
            )
            return 0
        from seascape.workflow import DOMAIN_LAYER_STAGES, run_domain_layer_build

        if args.command == "stages":
            for stage in DOMAIN_LAYER_STAGES:
                print(f"{stage.name}: {stage.description}")
            return 0
        if args.check_inputs or args.json:
            from seascape.preflight import preflight_build, print_preflight

            report = preflight_build(
                config_path=args.config,
                only=args.only,
                skip=args.skip,
                candidate_root=args.candidate_root,
                publish=args.publish,
                resume=args.resume,
                overwrite=args.overwrite,
                check_inputs=args.check_inputs,
            )
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print_preflight(report)
            for check in report["checks"]:
                if check["required"] and check["status"] in {
                    "missing_external",
                    "invalid",
                    "unverified",
                }:
                    print(
                        f"build preflight / {check['stage']}: {check['name']} "
                        f"is {check['status']} ({check['path'] or report['config']}). "
                        f"Action: {check['corrective_action']} Guide: docs/WORKFLOWS.md.",
                        file=sys.stderr,
                    )
            return int(report["status"] == "failed")
        results = run_domain_layer_build(
            config_path=args.config,
            only=args.only,
            skip=args.skip,
            dry_run=args.dry_run,
            candidate_root=args.candidate_root,
            resume=args.resume,
            overwrite=args.overwrite,
            publish=args.publish,
            _failure_reporter=lambda name, elapsed, exc: print(
                f"build / {name}: failed ({elapsed:.1f}s; {type(exc).__name__})",
                file=sys.stderr,
            ),
        )
        for result in results:
            if result.status == "blocked_dependency":
                print(
                    f"build / {result.name}: incomplete dependency "
                    f"({safe_detail(result.error or 'no validated reusable output')}). "
                    "Action: repair the upstream failure or provide checksum/config/upstream-valid "
                    "output; remove --skip to build a missing stage in a fresh candidate. "
                    "Guide: docs/WORKFLOWS.md#4-build-a-candidate.",
                    file=sys.stderr,
                )
        return int(
            any(result.status in {"failed", "blocked_dependency"} for result in results)
        )
    except EXPECTED_TYPES as exc:
        diagnostic = identify_failure(exc)
        if diagnostic is None:
            raise
        operation = (
            build_operation(exc)
            if args.command == "build"
            else f"{args.command} / {args.family}"
            if args.command in {"download", "inspect"}
            else args.command
        )
        if args.debug:
            traceback.print_exception(exc, file=sys.stderr)
        print(
            f"{operation}: {diagnostic.reason}\n"
            f"Location: {safe_detail(project_root())}; "
            f"config: {safe_detail(_config_selection(args))}\n"
            f"Action: {diagnostic.action}\nGuide: {diagnostic.guide}",
            file=sys.stderr,
        )
        return 1
    finally:
        if previous is None:
            os.environ.pop("SEASCAPE_WORKSPACE", None)
        else:
            os.environ["SEASCAPE_WORKSPACE"] = previous
