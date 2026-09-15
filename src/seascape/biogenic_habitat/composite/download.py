"""Acquire or validate the configured sources for all benthic habitat families."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from seascape.benthic_substrate.classification.download import (
    download_substrate_sources,
)
from seascape.biogenic_habitat.kelp.download import (
    download_kelp_sources,
)
from seascape.biogenic_habitat.reef.download import (
    download_reef_sources,
)
from seascape.biogenic_habitat.seagrass.download import (
    download_seagrass_sources,
)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"


def download_benthic_habitat_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    include_large: bool = True,
    overwrite: bool | None = None,
) -> list[Path]:
    outputs: list[Path] = []
    for paths, manifest in (
        download_substrate_sources(config_path, overwrite=overwrite),
        download_seagrass_sources(config_path, overwrite=overwrite),
        download_kelp_sources(config_path, include_large=include_large, overwrite=overwrite),
        download_reef_sources(config_path, overwrite=overwrite),
    ):
        outputs.extend(paths)
        outputs.append(manifest)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    large_group = parser.add_mutually_exclusive_group()
    large_group.add_argument("--include-large", dest="include_large", action="store_true")
    large_group.add_argument("--skip-large", dest="include_large", action="store_false")
    parser.set_defaults(include_large=True)
    parser.add_argument("--overwrite", action="store_true", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in download_benthic_habitat_sources(
        args.config,
        include_large=args.include_large,
        overwrite=args.overwrite,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
