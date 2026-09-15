"""Inspect sourced fluvial barriers and passage evidence on marine H3 cells."""

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

MAP_EXPORT_SUBDIRECTORY = Path(
    "domains/environmental_layer/seascape/hydrologic_connectivity/fluvial_barriers"
)


def inspect_fluvial_barriers(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    resolution: int = 6,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Render switchable structural-connectivity metrics and evidence confidence."""

    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    return inspect_habitat_surface(
        config,
        metrics=[
            ("MAPPED_UPSTREAM_BARRIER_COUNT", "Mapped upstream physical barriers"),
            ("MAPPED_UPSTREAM_DAM_COUNT", "Mapped upstream dams"),
            ("MAPPED_UPSTREAM_CULVERT_COUNT", "Mapped upstream culverts"),
            ("MAPPED_UPSTREAM_WATERFALL_COUNT", "Mapped upstream waterfalls"),
            ("MAPPED_UPSTREAM_TIDE_GATE_COUNT", "Mapped upstream tide gates"),
            ("MAPPED_BLOCKED_COUNT", "Assessed blocked sites upstream"),
            ("MAPPED_PARTIAL_COUNT", "Assessed partially passable sites upstream"),
            ("MAPPED_PASSABLE_COUNT", "Assessed passable sites upstream"),
            ("PASSAGE_STATUS_COVERAGE_FRAC", "Passage-status coverage fraction"),
            (
                "NEAREST_MAPPED_BARRIER_FROM_MOUTH_KM",
                "Nearest mapped upstream barrier from mouth (km)",
            ),
            (
                "NEAREST_MAPPED_BLOCKING_BARRIER_FROM_MOUTH_KM",
                "Nearest mapped blocking barrier from mouth (km)",
            ),
            (
                "WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M",
                "Marine-network distance to a barrier-affected mouth (m)",
            ),
        ],
        map_subdirectory=MAP_EXPORT_SUBDIRECTORY,
        map_stem="fluvial_barriers",
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
        inspect_fluvial_barriers(
            args.config,
            resolution=args.resolution,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
