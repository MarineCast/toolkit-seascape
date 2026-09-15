"""Download floating-kelp inventories and generalized cross-border mapping."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from seascape.utils.habitat_acquisition import (
    download_habitat_sources,
)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"
SECTION_NAME = "kelp_habitat"


def download_kelp_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    include_large: bool = True,
    overwrite: bool | None = None,
) -> tuple[list[Path], Path]:
    """Download kelp sources, including the required annual inventory by default."""

    return download_habitat_sources(
        SECTION_NAME,
        config_path,
        include_large=include_large,
        overwrite=overwrite,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    large_group = parser.add_mutually_exclusive_group()
    large_group.add_argument(
        "--include-large",
        dest="include_large",
        action="store_true",
        help="Include the required approximately 85 MB annual kelp archive (default).",
    )
    large_group.add_argument(
        "--skip-large",
        dest="include_large",
        action="store_false",
        help="Skip the annual archive; subsequent builds require --allow-generalized-only.",
    )
    parser.set_defaults(include_large=True)
    parser.add_argument("--overwrite", action="store_true", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    outputs, manifest = download_kelp_sources(
        args.config,
        include_large=args.include_large,
        overwrite=args.overwrite,
    )
    for path in [*outputs, manifest]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
