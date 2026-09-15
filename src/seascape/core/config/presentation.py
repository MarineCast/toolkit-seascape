"""Shared presentation settings for exported maps and figures."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seascape.core.config.document import ConfigDocument
from seascape.core.config.paths import project_root, resolve_config_path

DEFAULT_PRESENTATION_CONFIG_PATH = "config/data/presentation_settings.yaml"
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class PresentationSettings:
    """Resolved settings shared by data-presentation exporters."""

    base_export_directory: Path
    color_maps: Mapping[str, tuple[str, ...]]
    basemap_tile_layer: str
    basemap_attribution: str | None
    default_zoom: int
    static_color: str

    def color_map(self, name: str = "default") -> tuple[str, ...]:
        """Return a named color map, raising a useful error for unknown names."""

        try:
            return self.color_maps[name]
        except KeyError as exc:
            available = ", ".join(sorted(self.color_maps))
            raise KeyError(f"Unknown color map {name!r}; available maps: {available}") from exc

    def export_path(self, *parts: str | Path) -> Path:
        """Build a path beneath the configured export root."""

        return self.base_export_directory.joinpath(*parts)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Presentation setting {name!r} must be a mapping.")
    return dict(value)


def _color(value: Any, name: str) -> str:
    color = str(value)
    if not _HEX_COLOR.fullmatch(color):
        raise ValueError(f"Presentation setting {name!r} must be a six-digit hex color.")
    return color


def load_presentation_settings(
    config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
) -> PresentationSettings:
    """Load and validate the shared presentation-settings document."""

    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Presentation settings not found: {path}")
    raw = dict(ConfigDocument.load(path).data)

    configured_root = Path(str(raw.get("base_export_directory", "outputs"))).expanduser()
    export_root = (
        configured_root.resolve()
        if configured_root.is_absolute()
        else (project_root() / configured_root).resolve()
    )

    configured_maps = _mapping(raw.get("color_maps", {}), "color_maps")
    if not configured_maps:
        raise ValueError("Presentation settings must define at least one color map.")
    color_maps: dict[str, tuple[str, ...]] = {}
    for map_name, values in configured_maps.items():
        if not isinstance(values, list) or len(values) < 2:
            raise ValueError(
                f"Presentation color map {map_name!r} must contain at least two colors."
            )
        color_maps[str(map_name)] = tuple(
            _color(value, f"color_maps.{map_name}") for value in values
        )
    if "default" not in color_maps:
        raise ValueError("Presentation settings must define color_maps.default.")

    basemap = _mapping(raw.get("basemap", {}), "basemap")
    tile_layer = str(basemap.get("tile_layer", "")).strip()
    if not tile_layer:
        raise ValueError("Presentation setting 'basemap.tile_layer' cannot be empty.")
    configured_attribution = basemap.get("attribution")
    attribution = (
        str(configured_attribution).strip() if configured_attribution not in (None, "") else None
    )

    default_zoom = int(raw.get("default_zoom", 4))
    if not 0 <= default_zoom <= 22:
        raise ValueError("Presentation setting 'default_zoom' must be between 0 and 22.")

    return PresentationSettings(
        base_export_directory=export_root,
        color_maps=color_maps,
        basemap_tile_layer=tile_layer,
        basemap_attribution=attribution,
        default_zoom=default_zoom,
        static_color=_color(raw.get("static_color", "#38A9AA"), "static_color"),
    )
