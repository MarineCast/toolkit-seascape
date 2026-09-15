"""Export bounded HTML inspections of canonical marine support and water edges."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)

from .config import DEFAULT_CONFIG_PATH, load_water_network_config
from .load import load_water_support

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/spatial_support")


def _component_color(value: object) -> str:
    if value is None or pd.isna(value):
        return "#777777"
    return f"#{hashlib.sha256(str(value).encode()).hexdigest()[:6]}"


def inspect_water_network(
    resolution: int,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    bbox: tuple[float, float, float, float] | None = None,
    component_id: str | None = None,
    invalid_only: bool = False,
    maximum_edges: int = 5_000,
    output_path: str | Path | None = None,
) -> Path:
    """Render support, pass/fail edges, and terminal connectors for a bounded view."""

    import folium

    config = load_water_network_config(config_path)
    settings = load_presentation_settings(presentation_config_path)
    support = load_water_support(
        resolution,
        config_path,
        bbox=bbox,
        component_id=component_id,
    )
    if support.empty:
        raise ValueError("No canonical support rows match the requested inspection filters.")
    geometry = gpd.read_parquet(config.clipped_geometry_path(resolution)).to_crs("EPSG:4326")
    geometry = geometry.loc[geometry["H3_INDEX"].isin(support["H3_INDEX"])].merge(
        support,
        on=["H3_INDEX", "H3_RESOLUTION"],
        how="inner",
    )
    west, south, east, north = geometry.total_bounds
    map_options: dict[str, object] = {
        "location": [(south + north) / 2, (west + east) / 2],
        "tiles": settings.basemap_tile_layer,
        "zoom_start": settings.default_zoom,
        "control_scale": True,
        "prefer_canvas": True,
    }
    if settings.basemap_attribution:
        map_options["attr"] = settings.basemap_attribution
    output = folium.Map(**map_options)
    folium.GeoJson(
        json.loads(geometry.to_json(drop_id=True)),
        name="Marine support",
        style_function=lambda feature: {
            "fillColor": _component_color(feature["properties"].get("WATER_COMPONENT_ID")),
            "color": "#102A43",
            "weight": 0.35,
            "fillOpacity": 0.55,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[
                "H3_INDEX",
                "WATER_FRACTION",
                "WATER_COMPONENT_ID",
                "GRAPH_CONNECTION_STATUS",
                "GRAPH_QC_REASON",
            ],
            aliases=["H3", "Water fraction", "Component", "Graph status", "QC"],
        ),
    ).add_to(output)
    selected = support.set_index("H3_INDEX")
    edges = pd.read_parquet(config.edge_path(resolution))
    edges = edges.loc[
        edges["SOURCE_H3_INDEX"].isin(selected.index)
        & edges["TARGET_H3_INDEX"].isin(selected.index)
    ]
    if invalid_only:
        edges = edges.loc[~edges["EDGE_IS_WATER_PASSABLE"].astype(bool)]
    edges = edges.sort_values(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).head(maximum_edges)
    line_rows = []
    for row in edges.itertuples(index=False):
        source = selected.loc[str(row.SOURCE_H3_INDEX)]
        target = selected.loc[str(row.TARGET_H3_INDEX)]
        line_rows.append(
            {
                "PASSABLE": bool(row.EDGE_IS_WATER_PASSABLE),
                "WATER_PATH_FRACTION": float(row.WATER_PATH_FRACTION),
                "geometry": LineString(
                    [
                        (
                            source["REPRESENTATIVE_POINT_LONGITUDE"],
                            source["REPRESENTATIVE_POINT_LATITUDE"],
                        ),
                        (
                            target["REPRESENTATIVE_POINT_LONGITUDE"],
                            target["REPRESENTATIVE_POINT_LATITUDE"],
                        ),
                    ]
                ),
            }
        )
    if line_rows:
        lines = gpd.GeoDataFrame(line_rows, crs="EPSG:4326")
        folium.GeoJson(
            json.loads(lines.to_json(drop_id=True)),
            name="Water edge candidates",
            style_function=lambda feature: {
                "color": "#168AAD" if feature["properties"]["PASSABLE"] else "#D62828",
                "weight": 1.5,
                "opacity": 0.8,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["PASSABLE", "WATER_PATH_FRACTION"],
                aliases=["Passable", "Water path fraction"],
            ),
        ).add_to(output)
    connectors = pd.read_parquet(config.connector_path(resolution))
    connectors = connectors.loc[
        connectors["H3_INDEX"].isin(selected.index)
        & connectors["TARGET_H3_INDEX"].isin(selected.index)
    ]
    if invalid_only:
        connectors = connectors.loc[~connectors["CONNECTOR_IS_WATER_PASSABLE"].astype(bool)]
    connector_rows = []
    for row in connectors.sort_values("H3_INDEX").itertuples(index=False):
        source = selected.loc[str(row.H3_INDEX)]
        target = selected.loc[str(row.TARGET_H3_INDEX)]
        connector_rows.append(
            {
                "PASSABLE": bool(row.CONNECTOR_IS_WATER_PASSABLE),
                "DISTANCE_M": float(row.CONNECTOR_DISTANCE_M),
                "QC_REASON": row.QC_REASON,
                "geometry": LineString(
                    [
                        (
                            source["REPRESENTATIVE_POINT_LONGITUDE"],
                            source["REPRESENTATIVE_POINT_LATITUDE"],
                        ),
                        (
                            target["REPRESENTATIVE_POINT_LONGITUDE"],
                            target["REPRESENTATIVE_POINT_LATITUDE"],
                        ),
                    ]
                ),
            }
        )
    if connector_rows:
        connector_lines = gpd.GeoDataFrame(connector_rows, crs="EPSG:4326")
        folium.GeoJson(
            json.loads(connector_lines.to_json(drop_id=True)),
            name="Terminal connectors",
            style_function=lambda feature: {
                "color": "#FFB703" if feature["properties"]["PASSABLE"] else "#9B2226",
                "weight": 2.25,
                "opacity": 0.9,
                "dashArray": "5 3",
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["PASSABLE", "DISTANCE_M", "QC_REASON"],
                aliases=["Passable", "Distance (m)", "QC"],
            ),
        ).add_to(output)
    folium.LayerControl(collapsed=False).add_to(output)
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(
            MAP_EXPORT_SUBDIRECTORY,
            f"H3_RES{resolution}_water_network.html",
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    output.save(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--presentation-config", default=DEFAULT_PRESENTATION_CONFIG_PATH)
    parser.add_argument("--resolution", required=True, choices=(6, 8), type=int)
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    parser.add_argument("--component")
    parser.add_argument("--invalid-only", action="store_true")
    parser.add_argument("--maximum-edges", type=int, default=5_000)
    parser.add_argument("--output")
    args = parser.parse_args()
    print(
        inspect_water_network(
            args.resolution,
            args.config,
            presentation_config_path=args.presentation_config,
            bbox=tuple(args.bbox) if args.bbox else None,
            component_id=args.component,
            invalid_only=args.invalid_only,
            maximum_edges=args.maximum_edges,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
