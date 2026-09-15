"""Inspect the H3 distance-to-estuary surface and mapped source locations."""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from shapely.geometry import mapping

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.core.geo.h3 import cell_to_polygon
from seascape.utils.vector_inspect import (
    json_property_value as _property_value,
)

from .build import (
    DEFAULT_CONFIG_PATH,
    ESTUARY_COLUMNS,
    FEATURE_COLUMNS,
    load_estuarine_connectivity_config,
)

LOGGER = logging.getLogger(__name__)

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/hydrologic_connectivity")
MAP_FILENAME = "estuarine_connectivity.html"
SOURCE_COLORS = {
    "BC_PECP_DATABASIN": "#00A6A6",
    "US_PMEP": "#E45B5B",
}


def _h3_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    cell = str(row["H3_INDEX"])
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, 6), round(y, 6)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    return {
        "type": "Feature",
        "properties": {
            "H3_INDEX": cell,
            "STRAIGHT_DISTANCE_M": round(float(row["DISTANCE_TO_ESTUARY_M"]), 3),
            "MARINE_DISTANCE_M": round(float(row["WATER_NETWORK_DISTANCE_TO_ESTUARY_M"]), 3),
        },
        "geometry": geometry,
    }


def _estuary_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = {
        column: _property_value(row.get(column))
        for column in ESTUARY_COLUMNS
        if column != "geometry"
    }
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": mapping(row["geometry"]),
    }


def _load_map_inputs(config_path: str | Path):
    import geopandas as gpd

    config = load_estuarine_connectivity_config(config_path)
    for path in (config.feature_path, config.estuary_path):
        if not path.exists():
            raise FileNotFoundError(f"Estuary-distance product not found: {path}")
    features = pd.read_parquet(config.feature_path)
    estuaries = gpd.read_parquet(config.estuary_path)
    if list(features.columns) != FEATURE_COLUMNS:
        raise ValueError(f"Unexpected estuary-distance schema: {list(features.columns)}")
    if list(estuaries.columns) != ESTUARY_COLUMNS:
        raise ValueError(f"Unexpected mapped-estuary schema: {list(estuaries.columns)}")
    if features.empty or not features["H3_INDEX"].is_unique:
        raise ValueError("Estuary-distance product must contain one row per H3 cell.")
    if estuaries.empty or estuaries.crs is None:
        raise ValueError("Mapped estuary locations must be nonempty and retain CRS metadata.")
    return config, features, estuaries.to_crs("EPSG:4326")


def inspect_estuarine_connectivity(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Write the interactive estuary-distance inspection map."""

    import folium
    from branca.element import MacroElement, Template

    config, features, estuaries = _load_map_inputs(config_path)
    settings = load_presentation_settings(presentation_config_path)
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, MAP_FILENAME)
    )
    h3_data = {
        "type": "FeatureCollection",
        "features": [_h3_feature(row) for row in features.to_dict("records")],
    }
    estuary_data = {
        "type": "FeatureCollection",
        "features": [_estuary_feature(row) for row in estuaries.to_dict("records")],
    }
    metric_specs: list[dict[str, str | float]] = []
    for property_name, column, label in (
        (
            "STRAIGHT_DISTANCE_M",
            "DISTANCE_TO_ESTUARY_M",
            "Straight-line distance to nearest mapped estuary",
        ),
        (
            "MARINE_DISTANCE_M",
            "WATER_NETWORK_DISTANCE_TO_ESTUARY_M",
            "Marine-connected distance to nearest mapped estuary",
        ),
    ):
        values = pd.to_numeric(features[column], errors="raise").astype("float64")
        minimum = float(values.quantile(0.02))
        maximum = float(values.quantile(0.98))
        if math.isclose(minimum, maximum):
            maximum = minimum + 1.0
        metric_specs.append(
            {
                "property": property_name,
                "label": label,
                "minimum": minimum,
                "maximum": maximum,
            }
        )

    map_options: dict[str, Any] = {
        "location": [
            (config.bbox["min_lat"] + config.bbox["max_lat"]) / 2,
            (config.bbox["min_lon"] + config.bbox["max_lon"]) / 2,
        ],
        "tiles": settings.basemap_tile_layer,
        "control_scale": True,
        "prefer_canvas": True,
        "zoom_start": settings.default_zoom,
    }
    if settings.basemap_attribution:
        map_options["attr"] = settings.basemap_attribution
    map_ = folium.Map(**map_options)
    map_name = map_.get_name()
    script = f"""
    const estuaryDistanceH3 = {json.dumps(h3_data, separators=(',', ':'))};
    const mappedEstuaryPoints = {json.dumps(estuary_data, separators=(',', ':'))};
    const estuaryDistanceColors = {
        json.dumps(list(settings.color_map()), separators=(',', ':'))
    };
    const estuarySourceColors = {json.dumps(SOURCE_COLORS, separators=(',', ':'))};
    const estuaryMetricSpecs = {json.dumps(metric_specs, separators=(',', ':'))};

    function estuaryHexRgb(hex) {{
      const value = hex.replace('#', '');
      return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
    }}
    function estuaryDistanceColor(spec, value) {{
      if (!Number.isFinite(Number(value))) return '#8A8A8A';
      const t = Math.max(0, Math.min(
        1,
        (Number(value) - spec.minimum) /
          (spec.maximum - spec.minimum)
      ));
      const position = t * (estuaryDistanceColors.length - 1);
      const lo = Math.floor(position);
      const hi = Math.min(estuaryDistanceColors.length - 1, lo + 1);
      const fraction = position - lo;
      const a = estuaryHexRgb(estuaryDistanceColors[lo]);
      const b = estuaryHexRgb(estuaryDistanceColors[hi]);
      const rgb = a.map(
        (channel, index) => Math.round(channel + (b[index] - channel) * fraction)
      );
      return 'rgb(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ')';
    }}
    function estuaryValue(value, digits=1) {{
      return Number(value).toLocaleString(
        undefined,
        {{maximumFractionDigits: digits}}
      );
    }}

    function estuaryMetricLayer(spec) {{
      return L.geoJSON(estuaryDistanceH3, {{
        style: feature => ({{
          fillColor: estuaryDistanceColor(spec, feature.properties[spec.property]),
          color: estuaryDistanceColors[estuaryDistanceColors.length - 1],
          weight: 0.22,
          fillOpacity: 0.80
        }}),
        onEachFeature: (feature, layer) => {{
          const p = feature.properties;
          layer.bindTooltip(
            '<b>' + spec.label + '</b><br>' +
            estuaryValue(p[spec.property]) + ' m' +
            '<br>Straight-line distance: ' + estuaryValue(p.STRAIGHT_DISTANCE_M) + ' m' +
            '<br>Marine-connected distance: ' + estuaryValue(p.MARINE_DISTANCE_M) + ' m' +
            '<br>H3: ' + p.H3_INDEX,
            {{sticky: true}}
          );
        }}
      }});
    }}
    const estuaryMetricLayers = estuaryMetricSpecs.map(estuaryMetricLayer);
    estuaryMetricLayers[0].addTo({map_name});

    const mappedEstuaryLayer = L.geoJSON(mappedEstuaryPoints, {{
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {{
        radius: 4.5,
        color: '#FFFFFF',
        weight: 0.8,
        fillColor: estuarySourceColors[feature.properties.SOURCE_DATASET] || '#6B6B6B',
        fillOpacity: 0.95
      }}),
      onEachFeature: (feature, layer) => {{
        const p = feature.properties;
        layer.bindTooltip(
          '<b>' + (p.ESTUARY_NAME || p.ESTUARY_ID) + '</b>' +
          '<br>ID: ' + p.ESTUARY_ID +
          '<br>Source: ' + p.SOURCE_DATASET +
          '<br>Region: ' + p.SOURCE_REGION +
          '<br>Location method: ' + p.LOCATION_METHOD +
          '<br>Marine graph cell: ' + p.MARINE_GRAPH_H3_INDEX +
          '<br>Graph snap connector: ' +
            estuaryValue(p.MARINE_GRAPH_SNAP_DISTANCE_M) + ' m',
          {{sticky: true}}
        );
      }}
    }}).addTo({map_name});

    const estuaryOverlays = {{'Mapped estuary locations': mappedEstuaryLayer}};
    estuaryMetricSpecs.forEach((spec, index) => {{
      estuaryOverlays[spec.label] = estuaryMetricLayers[index];
    }});
    L.control.layers({{}}, estuaryOverlays, {{collapsed: true}}).addTo({map_name});
    """
    element = MacroElement()
    element._template = Template("{% macro script(this, kwargs) %}" + script + "{% endmacro %}")
    map_.add_child(element)
    note = """
    <div style="position:fixed;bottom:28px;left:10px;z-index:9999;background:white;
      border:1px solid #777;padding:7px 9px;max-width:350px;font:12px/1.3 sans-serif;">
      <b>Two estuary-distance covariates.</b> Straight-line distance uses mapped
      points directly. Marine-connected distance follows the contextual water H3
      graph and includes the point-to-graph connector. Each layer uses its own
      2nd–98th percentile color scale; neither maps full tidal extent.
    </div>
    """
    map_.get_root().html.add_child(folium.Element(note))
    map_.fit_bounds(
        [
            [config.bbox["min_lat"], config.bbox["min_lon"]],
            [config.bbox["max_lat"], config.bbox["max_lon"]],
        ]
    )
    map_.get_root().header.add_child(folium.Element("<title>Seascape Toolkit Distance to Estuary</title>"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    map_.save(destination)
    LOGGER.info(
        "Saved estuary-distance inspection map (%d H3 cells, %d points): %s",
        len(features),
        len(estuaries),
        destination,
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--presentation-config", default=DEFAULT_PRESENTATION_CONFIG_PATH)
    parser.add_argument("--output")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(
        inspect_estuarine_connectivity(
            args.config,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
