"""Inspect the retained core benthic habitat features and composite summaries."""

from __future__ import annotations

import argparse
from pathlib import Path

from seascape.core.config.presentation import DEFAULT_PRESENTATION_CONFIG_PATH
from seascape.utils.habitat_configuration import (
    load_habitat_surface_config,
)
from seascape.utils.habitat_inspect import inspect_habitat_surface

from .build import PREFIX, SECTION_NAME
from .download import DEFAULT_CONFIG_PATH

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/biogenic_habitat")


def inspect_benthic_habitat_composite(
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
            ("SEAGRASS_FRAC", "Sentinel-2 seagrass fraction"),
            ("KELP_FRAC", "Kelp fraction"),
            ("ROCKY_REEF_FRAC", "Modeled rocky-reef fraction"),
            ("BENTHIC_HABITAT_RICHNESS", "Habitat richness"),
            ("BENTHIC_EDGE_DENSITY_M_PER_KM2", "Benthic edge density"),
        ],
        map_subdirectory=MAP_EXPORT_SUBDIRECTORY,
        map_stem="benthic_habitat_composite",
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
        inspect_benthic_habitat_composite(
            args.config,
            resolution=args.resolution,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
