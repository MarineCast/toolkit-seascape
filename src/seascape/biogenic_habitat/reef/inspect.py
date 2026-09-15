"""Inspect distinct rocky, biogenic, and deep-coral/sponge reef evidence."""

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

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/biogenic_habitat")


def inspect_reef_habitat(
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
            ("ROCKY_REEF_FRAC", "dbSEABED modeled rocky-reef fraction"),
            ("ROCKY_REEF_DISTANCE_M", "Marine-connected distance to rocky reef (m)"),
            ("ROCKY_REEF_AREA_WITHIN_5KM_M2", "Rocky-reef area within 5 km (m²)"),
            ("POTENTIAL_ROCKY_REEF_SUITABILITY", "Potential rocky-reef suitability"),
            ("BIOGENIC_REEF_FRAC", "Mapped bivalve-bed proxy fraction"),
            ("BIOGENIC_REEF_DISTANCE_M", "Marine-connected distance to bivalve beds (m)"),
            ("DEEP_CORAL_SPONGE_FRAC", "Deep coral/sponge mapped fraction"),
        ],
        map_subdirectory=MAP_EXPORT_SUBDIRECTORY,
        map_stem="reef_habitat",
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
        inspect_reef_habitat(
            args.config,
            resolution=args.resolution,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
