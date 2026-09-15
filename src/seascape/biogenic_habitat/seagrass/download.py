"""Download the global Sentinel-2 shallow-water seagrass product."""

from __future__ import annotations

from pathlib import Path

from seascape.utils.acquisition import (
    invoke_habitat_download,
    run_habitat_download_cli,
)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"
SECTION_NAME = "seagrass_habitat"


def download_seagrass_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    overwrite: bool | None = None,
) -> tuple[list[Path], Path]:
    """Download configured seagrass sources and return artifacts plus manifest."""

    return invoke_habitat_download(SECTION_NAME, config_path, overwrite=overwrite)


def main() -> int:
    """Run the seagrass acquisition command line interface."""

    return run_habitat_download_cli(
        SECTION_NAME,
        __doc__ or "Download seagrass sources.",
        default_config_path=DEFAULT_CONFIG_PATH,
    )


if __name__ == "__main__":
    raise SystemExit(main())
