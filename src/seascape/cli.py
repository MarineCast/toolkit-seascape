"""Installed command line interface for independent seascape workspaces."""

from __future__ import annotations

import argparse
from importlib.resources import files
import os
from pathlib import Path
import importlib
import sys

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

    def copy_tree(source, destination):
        for item in source.iterdir():
            path = destination / item.name
            if item.is_dir():
                copy_tree(item, path)
            elif not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.read_bytes())

    copy_tree(files("seascape").joinpath("resources"), root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Data/config/output root (default: current directory)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init", help="Create editable configuration from packaged templates"
    )
    commands.add_parser("stages", help="List dependency-ordered build stages")
    build = commands.add_parser(
        "build", help="Build an isolated candidate from local source data"
    )
    build.add_argument("--config", default="config/data/project.yaml")
    build.add_argument("--only", action="append", default=[])
    build.add_argument("--skip", action="append", default=[])
    build.add_argument("--candidate-root", type=Path)
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--resume", action="store_true")
    build.add_argument("--overwrite", action="store_true")
    build.add_argument(
        "--publish",
        action="store_true",
        help="Promote candidate after the release audit passes",
    )
    for action in ("download", "inspect"):
        sub = commands.add_parser(
            action, help=f"Run a family's {action} command", add_help=False
        )
        sub.add_argument(
            "family", choices=DOWNLOAD_FAMILIES if action == "download" else FAMILIES
        )
        sub.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    previous = os.environ.get("SEASCAPE_WORKSPACE")
    if args.workspace is not None:
        os.environ["SEASCAPE_WORKSPACE"] = str(args.workspace.expanduser().resolve())
    try:
        from seascape.core.config.paths import project_root

        if args.command == "init":
            initialize_workspace(project_root())
            print(f"Initialized seascape workspace: {project_root()}")
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
        from seascape.workflow import DOMAIN_LAYER_STAGES, run_domain_layer_build

        if args.command == "stages":
            for stage in DOMAIN_LAYER_STAGES:
                print(f"{stage.name}: {stage.description}")
            return 0
        results = run_domain_layer_build(
            config_path=args.config,
            only=args.only,
            skip=args.skip,
            dry_run=args.dry_run,
            candidate_root=args.candidate_root,
            resume=args.resume,
            overwrite=args.overwrite,
            publish=args.publish,
        )
        return int(
            any(result.status in {"failed", "blocked_dependency"} for result in results)
        )
    finally:
        if previous is None:
            os.environ.pop("SEASCAPE_WORKSPACE", None)
        else:
            os.environ["SEASCAPE_WORKSPACE"] = previous
