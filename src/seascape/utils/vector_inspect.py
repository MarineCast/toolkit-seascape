"""Common basemap, serialization, legend, and output shell for vector inspectors."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from seascape.core.config.presentation import PresentationSettings


def json_property_value(value: Any) -> Any:
    """Normalize nullable NumPy/pandas scalars into JSON-native values."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    return str(value)


def finite_number(value: Any, digits: int = 6) -> float | None:
    """Return a rounded finite scalar or JSON null."""

    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return round(numeric, digits) if math.isfinite(numeric) else None


def h3_metric_feature(
    row: Mapping[str, Any],
    metrics: Sequence[str],
    *,
    digits: int = 6,
) -> dict[str, object]:
    """Serialize one H3 row into the shared compact inspector feature shape."""

    from shapely.geometry import mapping

    from seascape.core.geo.h3 import cell_to_polygon

    cell = str(row["H3_INDEX"])
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, digits), round(y, digits)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    return {
        "type": "Feature",
        "properties": {
            "H3_INDEX": cell,
            "VALUES": [finite_number(row[metric], digits) for metric in metrics],
        },
        "geometry": geometry,
    }


def new_vector_map(
    settings: PresentationSettings,
    bounds_wgs84: Sequence[float],
):
    """Create a configured Folium basemap centered on WGS84 bounds."""

    import folium

    west, south, east, north = (float(value) for value in bounds_wgs84)
    options: dict[str, object] = {
        "location": [(south + north) / 2.0, (west + east) / 2.0],
        "tiles": settings.basemap_tile_layer,
        "zoom_start": settings.default_zoom,
        "control_scale": True,
        "prefer_canvas": True,
    }
    if settings.basemap_attribution:
        options["attr"] = settings.basemap_attribution
    return folium.Map(**options)


def add_html_legend(
    map_: Any,
    *,
    title: str,
    items: Mapping[str, str],
    position: str = "bottomright",
) -> None:
    """Add a compact escaped scalar legend while leaving family colors local."""

    import html

    import folium

    rows = "".join(
        '<div><span style="display:inline-block;width:12px;height:12px;'
        f'background:{html.escape(color)};margin-right:6px"></span>'
        f"{html.escape(label)}</div>"
        for label, color in items.items()
    )
    markup = (
        f'<div class="seascape-legend leaflet-{html.escape(position)}" '
        'style="position:fixed;z-index:9999;background:white;padding:8px;'
        'border:1px solid #999;border-radius:4px">'
        f"<strong>{html.escape(title)}</strong>{rows}</div>"
    )
    map_.get_root().html.add_child(folium.Element(markup))


def save_vector_map(map_: Any, destination: str | Path) -> Path:
    """Create the output parent and write one inspector HTML document."""

    path = Path(destination).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    map_.save(path)
    return path


__all__ = [
    "add_html_legend",
    "finite_number",
    "h3_metric_feature",
    "json_property_value",
    "new_vector_map",
    "save_vector_map",
]
