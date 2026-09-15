"""Inspect cross-border anthropogenic seascape features on an interactive H3 map."""

from __future__ import annotations

import argparse
from pathlib import Path

from seascape.core.config.presentation import DEFAULT_PRESENTATION_CONFIG_PATH
from seascape.utils.inspect import (
    inspect_surface as inspect_habitat_surface,
)
from seascape.utils.surface import (
    load_surface_config as load_habitat_surface_config,
)

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME
from .sources import PREFIX

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/anthropogenic")


def inspect_anthropogenic_seascape(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    resolution: int = 6,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Render all principal anthropogenic metrics as switchable H3 layers."""

    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    return inspect_habitat_surface(
        config,
        metrics=[
            ("SHORELINE_ARMORING_FRAC", "Mapped shoreline armoring fraction"),
            ("DISTANCE_TO_SEAWALL_M", "Marine-connected distance to seawall (m)"),
            ("DISTANCE_TO_BREAKWATER_M", "Marine-connected distance to breakwater (m)"),
            ("DISTANCE_TO_JETTY_M", "Marine-connected distance to jetty or groyne (m)"),
            ("DISTANCE_TO_CAUSEWAY_M", "Marine-connected distance to causeway (m)"),
            ("DISTANCE_TO_PIER_M", "Marine-connected distance to pier, dock, or wharf (m)"),
            (
                "DISTANCE_TO_FERRY_TERMINAL_M",
                "Marine-connected distance to ferry terminal (m)",
            ),
            ("DISTANCE_TO_MARINA_M", "Marine-connected distance to marina (m)"),
            ("DISTANCE_TO_PORT_M", "Marine-connected distance to port (m)"),
            (
                "DISTANCE_TO_DREDGED_CHANNEL_M",
                "Marine-connected distance to dredged channel (m)",
            ),
            ("DREDGED_AREA_FRAC", "Mapped dredged-area fraction"),
            (
                "DISTANCE_TO_DISPOSAL_SITE_M",
                "Marine-connected distance to disposal site (m)",
            ),
            ("DISPOSAL_SITE_AREA_FRAC", "Mapped disposal-site area fraction"),
            ("ARTIFICIAL_REEF_PRESENCE", "Mapped artificial-reef presence"),
            (
                "DISTANCE_TO_ARTIFICIAL_REEF_M",
                "Marine-connected distance to artificial reef (m)",
            ),
            ("AQUACULTURE_PRESENCE", "Mapped aquaculture presence"),
            ("AQUACULTURE_FOOTPRINT_FRAC", "Mapped aquaculture footprint fraction"),
            (
                "DISTANCE_TO_AQUACULTURE_M",
                "Marine-connected distance to aquaculture (m)",
            ),
            (
                "OVERWATER_STRUCTURE_COUNT_WITHIN_5KM",
                "Mapped overwater structures within 5 km",
            ),
            (
                "OVERWATER_STRUCTURE_DENSITY_PER_KM2",
                "Mapped overwater-structure density within 5 km (per km²)",
            ),
        ],
        map_subdirectory=MAP_EXPORT_SUBDIRECTORY,
        map_stem="anthropogenic",
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
        inspect_anthropogenic_seascape(
            args.config,
            resolution=args.resolution,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
