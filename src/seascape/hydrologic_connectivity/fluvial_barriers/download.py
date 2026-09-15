"""Download authoritative B.C. and Washington fluvial-barrier inventories."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from seascape.utils.acquisition import (
    download_sources,
)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"
SECTION_NAME = "fluvial_barriers"


def download_fluvial_barrier_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    include_large: bool = False,
    overwrite: bool | None = None,
) -> tuple[list[Path], Path]:
    """Download configured snapshots and their checksum-bearing manifest."""

    return download_sources(
        SECTION_NAME,
        config_path,
        include_large=include_large,
        overwrite=overwrite,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--include-large", action="store_true")
    parser.add_argument("--overwrite", action="store_true", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    outputs, manifest = download_fluvial_barrier_sources(
        args.config,
        include_large=args.include_large,
        overwrite=args.overwrite,
    )
    for path in [*outputs, manifest]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
