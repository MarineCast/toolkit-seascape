"""Inspect mapped river-mouth distance, pressure, widths, and systems in HTML."""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import mapping

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import resolve_config_path
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
    load_river_mouth_build_config,
    output_columns,
    pressure_columns,
)

LOGGER = logging.getLogger(__name__)

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/hydrologic_connectivity")
RIVER_MOUTH_MAP_FILENAME = "freshwater_sources.html"
RIVER_SOURCE_COLORS = {
    "BC_FWA_STREAM_NETWORK": "#176F7D",
    "US_NHD_SMALL_SCALE": "#38A9AA",
    "HYDRORIVERS_V10": "#76CFCA",
}


def _h3_feature(
    row: Mapping[str, Any],
    pressure_column: str,
    weighted_pressure_column: str,
) -> dict[str, Any]:
    cell = str(row["H3_INDEX"])
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, 6), round(y, 6)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    return {
        "type": "Feature",
        "properties": {
            "H3_INDEX": cell,
            "DISTANCE_M": round(float(row["DISTANCE_TO_RIVER_MOUTH_M"]), 3),
            "MOUTH_ID": _property_value(row["NEAREST_RIVER_MOUTH_ID"]),
            "MOUTH_WIDTH_M": _property_value(row["NEAREST_RIVER_MOUTH_WIDTH_M"]),
            "PRESSURE": round(float(row[pressure_column]), 6),
            "WIDTH_WEIGHTED_PRESSURE": round(float(row[weighted_pressure_column]), 6),
        },
        "geometry": geometry,
    }


def _mouth_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = {
        column: _property_value(row.get(column))
        for column in (
            "RIVER_MOUTH_ID",
            "SOURCE_DATASET",
            "RIVER_NAME",
            "MOUTH_WIDTH_M",
            "MOUTH_WIDTH_SOURCE_DATASET",
            "MOUTH_WIDTH_METHOD",
            "COAST_DISTANCE_M",
        )
    }
    return {"type": "Feature", "properties": properties, "geometry": mapping(row["geometry"])}


def _river_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = {
        column: _property_value(row.get(column))
        for column in ("RIVER_SEGMENT_ID", "SOURCE_DATASET", "RIVER_NAME")
    }
    return {"type": "Feature", "properties": properties, "geometry": mapping(row["geometry"])}


def _inspection_simplification(config_path: str | Path) -> float:
    raw = load_data_config(resolve_config_path(config_path), domains="SEASCAPE_LAYER")
    section = raw.get("freshwater_sources", {})
    inspect = section.get("inspect", {}) if isinstance(section, Mapping) else {}
    if not isinstance(inspect, Mapping):
        raise ValueError("freshwater_sources.inspect must be a mapping.")
    simplify_m = float(inspect.get("river_simplify_tolerance_m", 75))
    if simplify_m < 0:
        raise ValueError("river_simplify_tolerance_m must be nonnegative.")
    return simplify_m


def _load_map_inputs(config_path: str | Path):
    import geopandas as gpd

    config = load_river_mouth_build_config(config_path)
    for path in (config.feature_path, config.river_mouths_path, config.river_systems_path):
        if not path.exists():
            raise FileNotFoundError(f"River-mouth processed product not found: {path}")
    features = pd.read_parquet(config.feature_path)
    missing = sorted(set(output_columns(config)).difference(features.columns))
    if missing:
        raise ValueError(f"River-mouth H3 product is missing columns: {missing}")
    if features.empty or not features["H3_INDEX"].is_unique:
        raise ValueError("River-mouth H3 product must have one nonempty row per H3_INDEX.")
    mouths = gpd.read_parquet(config.river_mouths_path)
    rivers = gpd.read_parquet(config.river_systems_path)
    if mouths.crs is None or rivers.crs is None:
        raise ValueError("River mouth and system products must retain CRS metadata.")
    return config, features, mouths.to_crs("EPSG:4326"), rivers.to_crs("EPSG:4326")


def _prepare_rivers(rivers: Any, *, simplify_m: float, projected_crs: str):
    selected = rivers.loc[rivers.geometry.notna() & ~rivers.geometry.is_empty].copy()
    if selected.empty:
        raise ValueError("River-system product contains no displayable linework.")
    if simplify_m > 0:
        projected = selected.to_crs(projected_crs)
        projected.geometry = projected.geometry.simplify(simplify_m, preserve_topology=True)
        selected = projected.to_crs("EPSG:4326")
    return selected.loc[selected.geometry.notna() & ~selected.geometry.is_empty].reset_index(
        drop=True
    )


def inspect_river_mouths(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Write one interactive map of the narrowed river-mouth products."""

    import folium
    from branca.element import MacroElement, Template

    config, features, mouths, rivers = _load_map_inputs(config_path)
    rivers = _prepare_rivers(
        rivers,
        simplify_m=_inspection_simplification(config_path),
        projected_crs=config.projected_crs,
    )
    settings = load_presentation_settings(presentation_config_path)
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, RIVER_MOUTH_MAP_FILENAME)
    )

    pressure_column, weighted_pressure_column = pressure_columns(config)
    h3_data = {
        "type": "FeatureCollection",
        "features": [
            _h3_feature(row, pressure_column, weighted_pressure_column)
            for row in features.to_dict("records")
        ],
    }
    mouth_data = {
        "type": "FeatureCollection",
        "features": [_mouth_feature(row) for row in mouths.to_dict("records")],
    }
    river_data = {
        "type": "FeatureCollection",
        "features": [_river_feature(row) for row in rivers.to_dict("records")],
    }
    metric_specs = []
    for property_name, column, label, log_scale in (
        ("DISTANCE_M", "DISTANCE_TO_RIVER_MOUTH_M", "Distance to nearest river mouth", False),
        (
            "PRESSURE",
            pressure_column,
            f"Mapped river-mouth pressure ({config.river_mouth_pressure_decay_km} km)",
            True,
        ),
        (
            "WIDTH_WEIGHTED_PRESSURE",
            weighted_pressure_column,
            (
                "Mapped width-weighted river-mouth pressure "
                f"({config.river_mouth_pressure_decay_km} km, experimental)"
            ),
            True,
        ),
    ):
        numeric = pd.to_numeric(features[column], errors="coerce").dropna()
        display = np.log1p(numeric) if log_scale else numeric
        lower = float(display.quantile(0.02))
        upper = float(display.quantile(0.98))
        if math.isclose(lower, upper):
            upper = lower + 1
        metric_specs.append(
            {
                "property": property_name,
                "label": label,
                "minimum": lower,
                "maximum": upper,
                "log_scale": log_scale,
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
    const riverMouthH3 = {json.dumps(h3_data, separators=(',', ':'))};
    const riverMouths = {json.dumps(mouth_data, separators=(',', ':'))};
    const riverSystems = {json.dumps(river_data, separators=(',', ':'))};
    const riverSourceColors = {json.dumps(RIVER_SOURCE_COLORS, separators=(',', ':'))};
    const riverMetricColors = {json.dumps(list(settings.color_map()), separators=(',', ':'))};
    const riverMetricSpecs = {json.dumps(metric_specs, separators=(',', ':'))};

    function riverHexRgb(hex) {{
      const value = hex.replace('#', '');
      return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
    }}
    function riverMetricColor(spec, value) {{
      if (value === null || !Number.isFinite(Number(value))) return '#00000000';
      const transformed = spec.log_scale ? Math.log1p(Number(value)) : Number(value);
      const t = Math.max(0, Math.min(1, (transformed - spec.minimum) / (spec.maximum - spec.minimum)));
      const position = t * (riverMetricColors.length - 1);
      const lo = Math.floor(position);
      const hi = Math.min(riverMetricColors.length - 1, lo + 1);
      const fraction = position - lo;
      const a = riverHexRgb(riverMetricColors[lo]);
      const b = riverHexRgb(riverMetricColors[hi]);
      const rgb = a.map((channel, index) => Math.round(channel + (b[index] - channel) * fraction));
      return `rgb(${{rgb[0]}},${{rgb[1]}},${{rgb[2]}})`;
    }}
    function riverValue(value, digits=1) {{
      return value === null || !Number.isFinite(Number(value))
        ? 'Not mapped'
        : Number(value).toLocaleString(undefined, {{maximumFractionDigits: digits}});
    }}

    const riverSystemLayer = L.geoJSON(riverSystems, {{
      style: feature => ({{
        color: riverSourceColors[feature.properties.SOURCE_DATASET] || '#38A9AA',
        weight: 1.1,
        opacity: 0.72
      }}),
      onEachFeature: (feature, layer) => {{
        const p = feature.properties;
        layer.bindTooltip(
          `<b>${{p.RIVER_NAME || 'Unnamed river segment'}}</b><br>Source: ${{p.SOURCE_DATASET}}`,
          {{sticky: true}}
        );
      }}
    }}).addTo({map_name});

    const riverMouthLayer = L.geoJSON(riverMouths, {{
      pointToLayer: (feature, latlng) => {{
        const width = Number(feature.properties.MOUTH_WIDTH_M);
        const radius = Number.isFinite(width) ? Math.max(4, Math.min(11, 3 + Math.log2(width + 1))) : 3.5;
        return L.circleMarker(latlng, {{
          radius,
          color: '#0C1C3A',
          weight: 0.8,
          fillColor: riverSourceColors[feature.properties.SOURCE_DATASET] || '#38A9AA',
          fillOpacity: 0.92
        }});
      }},
      onEachFeature: (feature, layer) => {{
        const p = feature.properties;
        layer.bindTooltip(
          `<b>${{p.RIVER_NAME || 'Unnamed river mouth'}}</b>` +
          `<br>Mouth width: ${{riverValue(p.MOUTH_WIDTH_M)}} m` +
          `<br>Width source: ${{p.MOUTH_WIDTH_SOURCE_DATASET || 'No mapped river polygon'}}` +
          `<br>Source: ${{p.SOURCE_DATASET}}`,
          {{sticky: true}}
        );
      }}
    }}).addTo({map_name});

    function riverMetricLayer(spec) {{
      return L.geoJSON(riverMouthH3, {{
        style: feature => ({{
          fillColor: riverMetricColor(spec, feature.properties[spec.property]),
          color: riverMetricColors[riverMetricColors.length - 1],
          weight: 0.22,
          fillOpacity: 0.80
        }}),
        onEachFeature: (feature, layer) => {{
          const p = feature.properties;
          const unit = spec.property === 'DISTANCE_M' ? ' m' : '';
          layer.bindTooltip(
            `<b>${{spec.label}}</b><br>${{riverValue(p[spec.property], 3)}}${{unit}}` +
            `<br>Nearest mouth width: ${{riverValue(p.MOUTH_WIDTH_M)}} m` +
            `<br>H3: ${{p.H3_INDEX}}`,
            {{sticky: true}}
          );
        }}
      }});
    }}

    const riverMetricLayers = riverMetricSpecs.map(riverMetricLayer);
    riverMetricLayers[0].addTo({map_name});
    const riverOverlays = {{
      'River mouths (marker size = mapped width)': riverMouthLayer,
      'River systems': riverSystemLayer
    }};
    riverMetricSpecs.forEach((spec, index) => {{
      riverOverlays[spec.label] = riverMetricLayers[index];
    }});
    L.control.layers({{}}, riverOverlays, {{collapsed: true}}).addTo({map_name});
    """
    element = MacroElement()
    element._template = Template("{% macro script(this, kwargs) %}" + script + "{% endmacro %}")
    map_.add_child(element)
    map_.fit_bounds(
        [
            [config.bbox["min_lat"], config.bbox["min_lon"]],
            [config.bbox["max_lat"], config.bbox["max_lon"]],
        ]
    )
    map_.get_root().header.add_child(
        folium.Element("<title>Seascape Toolkit Mapped River-Mouth Pressure</title>")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    map_.save(destination)
    LOGGER.info(
        "Saved river-mouth inspection map (%d H3 cells, %d mouths, %d river segments): %s",
        len(features),
        len(mouths),
        len(rivers),
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
        inspect_river_mouths(
            args.config,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
