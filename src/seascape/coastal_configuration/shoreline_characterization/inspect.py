"""Export a lightweight physical-shoreline inventory inspector."""

from __future__ import annotations

import argparse
import logging
from html import escape
from pathlib import Path

import folium
import geopandas as gpd

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)

from .build import CLASS_TOKENS, load_shoreline_config

LOGGER = logging.getLogger(__name__)
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/coastal_configuration")
MAP_FILENAME = "shoreline_characterization.html"


def build_shoreline_characterization_map(
    config_path: str | Path = "config/data/environment_seascape.yaml",
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    inventory_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Render classified shoreline segments with source and raw-label tooltips."""

    config = load_shoreline_config(config_path)
    settings = load_presentation_settings(presentation_config_path)
    source = (
        Path(inventory_path).expanduser().resolve() if inventory_path else config.inventory_path
    )
    if not source.exists():
        raise FileNotFoundError(f"Shoreline inventory Parquet not found: {source}")
    inventory = gpd.read_parquet(source).to_crs("EPSG:4326")
    if inventory.empty:
        raise ValueError(f"Shoreline inventory is empty: {source}")
    output = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, MAP_FILENAME)
    )
    west, south, east, north = inventory.total_bounds
    map_options: dict[str, object] = {
        "location": [(south + north) / 2.0, (west + east) / 2.0],
        "zoom_start": settings.default_zoom,
        "tiles": settings.basemap_tile_layer,
        "control_scale": True,
        "prefer_canvas": True,
    }
    if settings.basemap_attribution:
        map_options["attr"] = settings.basemap_attribution
    map_object = folium.Map(**map_options)
    colors = {
        "ROCKY": "#555555",
        "SANDY": "#E1B955",
        "GRAVEL": "#A77B4D",
        "CLIFF": "#6C4C3C",
        "BLUFF": "#B46A55",
        "DELTAIC": "#35A36F",
        "ESTUARINE": "#397FB8",
    }
    for token in CLASS_TOKENS:
        selected = inventory.loc[inventory[f"IS_{token}_SHORE"]].copy()
        if selected.empty:
            continue
        selected["geometry"] = selected.geometry.simplify(0.0002)
        folium.GeoJson(
            selected[["SEGMENT_ID", "SOURCE_DATASET", "RAW_CLASSIFICATION", "geometry"]],
            name=token.title(),
            style_function=lambda _feature, color=colors[token]: {"color": color, "weight": 2},
            tooltip=folium.GeoJsonTooltip(
                fields=["SEGMENT_ID", "SOURCE_DATASET", "RAW_CLASSIFICATION"]
            ),
        ).add_to(map_object)
    source_rows = []
    for name, source in sorted(config.sources.items()):
        source_rows.append(
            "<li><strong>{name}</strong> — {attribution}; observation: {observation}; "
            "license: {license}. {warning} {restrictions}</li>".format(
                name=escape(name),
                attribution=escape(str(source.get("attribution") or "not documented")),
                observation=escape(str(source.get("observation_date") or "not documented")),
                license=escape(str(source.get("license") or "not documented")),
                warning=escape(str(source.get("source_completeness_warning") or "")),
                restrictions=escape(str(source.get("redistribution_restrictions") or "")),
            )
        )
    source_panel = """
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                max-width: 520px; background: white; border: 1px solid #777;
                padding: 10px; font-size: 11px;">
      <strong>Sources, observation periods, and use constraints</strong>
      <ul style="padding-left: 18px; margin: 6px 0;">{rows}</ul>
      Fractions use physically classified shoreline length. Unmapped segments
      remain visible through coverage and are not encoded as absence.
    </div>
    """.format(rows="".join(source_rows))
    map_object.get_root().html.add_child(folium.Element(source_panel))
    folium.LayerControl(collapsed=False).add_to(map_object)
    map_object.fit_bounds([[south, west], [north, east]])
    map_object.get_root().header.add_child(
        folium.Element("<title>Seascape Toolkit Shoreline Characterization</title>")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    map_object.save(output)
    LOGGER.info("Saved shoreline-characterization inspection map: %s", output)
    return output


def main() -> int:
    """Run the shoreline-characterization inspector command line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    parser.add_argument("--presentation-config", default=DEFAULT_PRESENTATION_CONFIG_PATH)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(
        build_shoreline_characterization_map(
            args.config,
            presentation_config_path=args.presentation_config,
            inventory_path=args.input,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
