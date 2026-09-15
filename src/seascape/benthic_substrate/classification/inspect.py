"""Inspect H3 dbSEABED composition, hard-bottom fraction, and coverage."""

from __future__ import annotations

import argparse
from pathlib import Path

from seascape.core.config.presentation import DEFAULT_PRESENTATION_CONFIG_PATH
from seascape.utils.habitat_configuration import (
    load_habitat_surface_config,
)
from seascape.utils.habitat_inspect import inspect_habitat_surface

from .build import PREFIX
from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/benthic_substrate")


def inspect_substrate_classification(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    resolution: int = 6,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    return inspect_habitat_surface(
        config,
        metrics=[
            ("SUBSTRATE_ROCK_FRAC", "dbSEABED exposed-rock fraction"),
            ("SUBSTRATE_GRAVEL_FRAC", "dbSEABED gravel fraction"),
            ("SUBSTRATE_SAND_FRAC", "dbSEABED sand fraction"),
            ("SUBSTRATE_MUD_FRAC", "dbSEABED mud fraction"),
            ("SUBSTRATE_HARD_SUBSTRATE_FRAC", "Modeled hard-substrate fraction"),
            ("SUBSTRATE_INTERPOLATED_COVERAGE_FRAC", "dbSEABED raster coverage"),
            (
                "SUBSTRATE_DISTANCE_TO_HARD_SUBSTRATE_M",
                "Marine-connected distance to modeled hard substrate (m)",
            ),
        ],
        map_subdirectory=MAP_EXPORT_SUBDIRECTORY,
        map_stem="benthic_substrate_classification",
        resolution=resolution,
        presentation_config_path=presentation_config_path,
        output_path=output_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--presentation-config", default=DEFAULT_PRESENTATION_CONFIG_PATH)
    parser.add_argument("--resolution", type=int, choices=(6, 8), default=6)
    parser.add_argument("--output")
    args = parser.parse_args()
    print(
        inspect_substrate_classification(
            args.config,
            resolution=args.resolution,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
