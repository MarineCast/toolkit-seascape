"""Source-agnostic acquisition helpers shared by seascape product families."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from .habitat_acquisition import download_habitat_sources as download_sources
from .habitat_acquisition import load_habitat_download_config as load_download_config


def invoke_habitat_download(
    section_name: str,
    config_path: str | Path,
    *,
    overwrite: bool | None = None,
) -> tuple[list[Path], Path]:
    """Invoke the generic downloader while keeping family wrappers declarative."""

    return download_sources(section_name, config_path, overwrite=overwrite)


def run_habitat_download_cli(
    section_name: str,
    description: str,
    *,
    default_config_path: str,
    argv: Sequence[str] | None = None,
) -> int:
    """Run the common CLI used by substrate, seagrass, and reef acquisition."""

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", default=default_config_path)
    parser.add_argument("--overwrite", action="store_true", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    outputs, manifest = invoke_habitat_download(
        section_name,
        args.config,
        overwrite=args.overwrite,
    )
    for path in [*outputs, manifest]:
        print(path)
    return 0


__all__ = [
    "download_sources",
    "invoke_habitat_download",
    "load_download_config",
    "run_habitat_download_cli",
]
