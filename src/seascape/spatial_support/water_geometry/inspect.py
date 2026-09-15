"""Inspect the canonical water geometry on an interactive HTML map."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.utils.vector_inspect import (
    new_vector_map,
    save_vector_map,
)

from .config import load_water_geometry_config

LOGGER = logging.getLogger(__name__)
DEFAULT_SEASCAPE_CONFIG_PATH = "config/data/project.yaml"
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/spatial_support")
WATER_GEOMETRY_MAP_FILENAME = "water_geometry.html"


def _read_geometry(path: Path, label: str) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label} Parquet not found: {path}")
    frame = gpd.read_parquet(path)
    if frame.crs is None:
        raise ValueError(f"{label} has no coordinate reference system: {path}")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].to_crs("EPSG:4326")
    if frame.empty:
        raise ValueError(f"{label} contains no mappable geometry: {path}")
    return frame


def inspect_water_geometry(
    config_path: str | Path = DEFAULT_SEASCAPE_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    parquet_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Open the canonical water Parquet and save its configured HTML map."""

    import folium

    water_config = load_water_geometry_config(config_path)
    settings = load_presentation_settings(presentation_config_path)
    source = (
        Path(parquet_path).expanduser().resolve()
        if parquet_path
        else Path(water_config["output_path"])
    )
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, WATER_GEOMETRY_MAP_FILENAME)
    )
    frame = _read_geometry(source, "Water geometry")
    water_map = new_vector_map(settings, frame.total_bounds)

    tooltip_fields = [field for field in ("NAME", "AREA", "TYPE") if field in frame.columns]
    layer_options: dict[str, object] = {}
    if tooltip_fields:
        layer_options["tooltip"] = folium.GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=[field.replace("_", " ").title() for field in tooltip_fields],
            localize=True,
        )
    folium.GeoJson(
        json.loads(frame.to_json(drop_id=True)),
        name="Territorial water geometry",
        style_function=lambda _feature: {
            "fillColor": settings.static_color,
            "color": "#0C1C3A",
            "weight": 1.0,
            "fillOpacity": 0.5,
        },
        highlight_function=lambda _feature: {"weight": 2.0, "fillOpacity": 0.7},
        smooth_factor=0.5,
        **layer_options,
    ).add_to(water_map)
    folium.LayerControl(collapsed=False).add_to(water_map)
    water_map.get_root().header.add_child(folium.Element("<title>Seascape Toolkit Water Geometry</title>"))
    destination = save_vector_map(water_map, destination)
    LOGGER.info("Saved water-geometry inspection map: %s", destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_SEASCAPE_CONFIG_PATH)
    parser.add_argument(
        "--presentation-config",
        default=DEFAULT_PRESENTATION_CONFIG_PATH,
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(
        inspect_water_geometry(
            args.config,
            presentation_config_path=args.presentation_config,
            parquet_path=args.input,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
