"""Download cross-border anthropogenic marine-structure source inventories."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from seascape.utils.acquisition import (
    download_sources,
)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"
SECTION_NAME = "anthropogenic_seascape"


def download_anthropogenic_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    overwrite: bool | None = None,
) -> tuple[list[Path], Path]:
    """Download configured anthropogenic sources and their checksum manifest."""

    return download_sources(SECTION_NAME, config_path, overwrite=overwrite)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--overwrite", action="store_true", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    outputs, manifest = download_anthropogenic_sources(args.config, overwrite=args.overwrite)
    for path in [*outputs, manifest]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
