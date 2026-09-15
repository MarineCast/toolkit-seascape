"""Inspect seafloor geomorphic units in one toggle-layer HTML map."""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from shapely.geometry import mapping

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.core.geo.h3 import cell_to_polygon
from seascape.utils.vector_inspect import finite_number as _finite

from .build import (
    DISTANCE_COLUMNS,
    GEOMORPHIC_UNITS,
    OUTPUT_COLUMNS,
    PROPORTION_COLUMNS,
    load_geomorphic_units_config,
)

LOGGER = logging.getLogger(__name__)
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/seafloor_physiography")
GEOMORPHIC_UNITS_MAP_FILENAME = "geomorphic_units.html"

LABELS = {
    "BROAD_TERRAIN_POSITION_M": ("Broad terrain position", "m", "diverging"),
    "BROAD_TERRAIN_POSITION_Z": ("Standardized broad terrain position", "z", "diverging"),
    "DIRECTIONAL_ANISOTROPY": ("Directional terrain anisotropy", "0–1", "unit"),
    "CANYON_DENSITY": ("Canyon-axis and rim density", "0–1", "unit"),
    "CLASSIFICATION_CONFIDENCE": ("Classification confidence", "0–1", "unit"),
    "MAPPING_UNIT_CELL_COUNT": ("Mapping-unit cell count", "cells", "sequential"),
}


def _humanize(unit: str) -> str:
    return unit.replace("_OR_", " or ").replace("_", " ").title()


def _metric_definitions() -> dict[str, tuple[str, str, str]]:
    metrics = dict(LABELS)
    for unit, column in zip(GEOMORPHIC_UNITS, DISTANCE_COLUMNS, strict=True):
        metrics[column] = (f"Distance to {_humanize(unit)}", "m", "sequential")
    for unit, column in zip(GEOMORPHIC_UNITS, PROPORTION_COLUMNS, strict=True):
        metrics[column] = (f"Local proportion: {_humanize(unit)}", "0–1", "unit")
    return metrics


METRICS = _metric_definitions()


def _scale(values: pd.Series, kind: str) -> tuple[float, float]:
    if kind == "unit":
        return 0.0, 1.0
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return 0.0, 1.0
    if kind == "diverging":
        limit = float(np.nanquantile(np.abs(numeric), 0.98))
        limit = limit if math.isfinite(limit) and limit > 0.0 else 1.0
        return -limit, limit
    lower = float(np.nanquantile(numeric, 0.02))
    upper = float(np.nanquantile(numeric, 0.98))
    if math.isclose(lower, upper):
        upper = lower + 1.0
    return lower, upper


def _feature(row: Mapping[str, Any]) -> dict[str, object]:
    cell = str(row["H3_INDEX"])
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, 6), round(y, 6)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    properties: dict[str, object] = {
        "H3_INDEX": cell,
        "UNIT": str(row["GEOMORPHIC_UNIT"]),
        "CONFIDENCE": _finite(row["CLASSIFICATION_CONFIDENCE"]),
        "MAPPING_CELLS": int(row["MAPPING_UNIT_CELL_COUNT"]),
        "MINIMUM_CELLS": int(row["MINIMUM_MAPPING_UNIT_CELLS"]),
        "MEETS_MINIMUM": bool(row["MEETS_MINIMUM_MAPPING_UNIT"]),
        "VALUES": [_finite(row[metric]) for metric in METRICS],
    }
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def inspect_geomorphic_units(
    config_path: str | Path = "config/data/environment_seascape.yaml",
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    parquet_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Write a categorical unit map plus toggleable confidence and proximity layers."""

    import folium
    from branca.element import MacroElement, Template

    config = load_geomorphic_units_config(config_path)
    settings = load_presentation_settings(presentation_config_path)
    source = Path(parquet_path).expanduser().resolve() if parquet_path else config.output_path
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, GEOMORPHIC_UNITS_MAP_FILENAME)
    )
    if not source.exists():
        raise FileNotFoundError(f"Geomorphic-unit Parquet not found: {source}")
    frame = pd.read_parquet(source)
    missing = sorted(set(OUTPUT_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Geomorphic-unit Parquet is missing columns: {missing}")
    if frame.empty:
        raise ValueError(f"Geomorphic-unit Parquet is empty: {source}")

    features = [_feature(row) for row in frame.to_dict(orient="records")]
    feature_collection = {"type": "FeatureCollection", "features": features}
    default_colors = settings.color_map()
    category_palette = settings.color_maps.get("geomorphic_units", default_colors)
    category_colors = {
        unit: category_palette[index % len(category_palette)]
        for index, unit in enumerate(GEOMORPHIC_UNITS)
    }
    category_colors["UNCLASSIFIED"] = "#9E9E9E"
    scales = {
        metric: {
            "index": index,
            "label": label,
            "units": units,
            "min": bounds[0],
            "max": bounds[1],
            "colors": list(settings.color_maps.get(kind, default_colors)),
        }
        for index, (metric, (label, units, kind)) in enumerate(METRICS.items())
        for bounds in [_scale(frame[metric], kind)]
    }
    centroids = frame["H3_INDEX"].astype(str).map(lambda cell: cell_to_polygon(cell).centroid)
    map_options: dict[str, object] = {
        "location": [
            float(centroids.map(lambda point: point.y).mean()),
            float(centroids.map(lambda point: point.x).mean()),
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
    legend_rows = "".join(
        f'<div><span style="background:{category_colors[unit]}"></span>{_humanize(unit)}</div>'
        for unit in GEOMORPHIC_UNITS
    )
    script = f"""
    const geomorphicData = {json.dumps(feature_collection, separators=(',', ':'))};
    const geomorphicScales = {json.dumps(scales, separators=(',', ':'))};
    const geomorphicUnitColors = {json.dumps(category_colors, separators=(',', ':'))};
    function geomorphicHexRgb(hex) {{
      const value = hex.replace('#', '');
      return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
    }}
    function geomorphicColor(scale, value) {{
      if (value === null || !Number.isFinite(Number(value))) return '#00000000';
      const span = scale.max - scale.min || 1;
      const t = Math.max(0, Math.min(1, (Number(value) - scale.min) / span));
      const position = t * (scale.colors.length - 1);
      const lower = Math.floor(position);
      const upper = Math.min(scale.colors.length - 1, lower + 1);
      const fraction = position - lower;
      const a = geomorphicHexRgb(scale.colors[lower]);
      const b = geomorphicHexRgb(scale.colors[upper]);
      const rgb = a.map((channel, index) => Math.round(channel + (b[index] - channel) * fraction));
      return `rgb(${{rgb[0]}},${{rgb[1]}},${{rgb[2]}})`;
    }}
    const geomorphicLayers = {{}};
    const classificationLayer = L.geoJSON(geomorphicData, {{
      style: feature => ({{
        fillColor: geomorphicUnitColors[feature.properties.UNIT] || '#9E9E9E',
        color: '#17324D',
        weight: 0.25,
        fillOpacity: 0.84
      }}),
      onEachFeature: (feature, layer) => {{
        const p = feature.properties;
        const unit = p.UNIT.replaceAll('_OR_', ' or ').replaceAll('_', ' ').toLowerCase();
        layer.bindTooltip(
          `<b>${{unit.replace(/\\b\\w/g, letter => letter.toUpperCase())}}</b><br>` +
          `H3: ${{p.H3_INDEX}}<br>Confidence: ${{Number(p.CONFIDENCE).toFixed(2)}}<br>` +
          `Mapping unit: ${{p.MAPPING_CELLS}} cells (minimum ${{p.MINIMUM_CELLS}})`,
          {{sticky: true}}
        );
      }}
    }}).addTo({map_name});
    geomorphicLayers['Geomorphic unit classification'] = classificationLayer;
    Object.entries(geomorphicScales).forEach(([metric, scale]) => {{
      const layer = L.geoJSON(geomorphicData, {{
        style: feature => {{
          const value = feature.properties.VALUES[scale.index];
          return {{
            fillColor: geomorphicColor(scale, value),
            color: scale.colors.slice(-1)[0],
            weight: 0.25,
            fillOpacity: value === null ? 0 : 0.84
          }};
        }},
        onEachFeature: (feature, featureLayer) => {{
          const value = feature.properties.VALUES[scale.index];
          const rendered = value === null ? 'No data' : Number(value).toLocaleString(undefined, {{maximumFractionDigits: 5}});
          featureLayer.bindTooltip(
            `<b>${{scale.label}}</b><br>H3: ${{feature.properties.H3_INDEX}}<br>${{rendered}} ${{scale.units}}`,
            {{sticky: true}}
          );
        }}
      }});
      geomorphicLayers[`${{scale.label}} (${{scale.units}})`] = layer;
    }});
    L.control.layers({{}}, geomorphicLayers, {{collapsed: true}}).addTo({map_name});
    const geomorphicLegend = L.control({{position: 'bottomright'}});
    geomorphicLegend.onAdd = function() {{
      const div = L.DomUtil.create('div', 'geomorphic-unit-legend');
      div.innerHTML = '<strong>Geomorphic units</strong>{legend_rows}';
      return div;
    }};
    geomorphicLegend.addTo({map_name});
    """
    layer_script = MacroElement()
    layer_script._template = Template(
        "{% macro script(this, kwargs) %}" + script + "{% endmacro %}"
    )
    map_.add_child(layer_script)
    map_.get_root().header.add_child(folium.Element("""
            <style>
            .geomorphic-unit-legend {
              background: rgba(255,255,255,0.94); padding: 8px 10px;
              border: 1px solid #9aa6ad; border-radius: 4px; line-height: 16px;
              max-height: 330px; overflow-y: auto; font-size: 11px;
            }
            .geomorphic-unit-legend strong { display: block; margin-bottom: 5px; }
            .geomorphic-unit-legend span {
              display: inline-block; width: 13px; height: 13px; margin-right: 6px;
              border: 1px solid #52616b; vertical-align: -2px;
            }
            </style>
            <title>Seascape Toolkit Seafloor Geomorphic Units</title>
            """))
    bounds = frame["H3_INDEX"].astype(str).map(cell_to_polygon).map(lambda polygon: polygon.bounds)
    map_.fit_bounds(
        [
            [min(item[1] for item in bounds), min(item[0] for item in bounds)],
            [max(item[3] for item in bounds), max(item[2] for item in bounds)],
        ]
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    map_.save(destination)
    LOGGER.info("Saved geomorphic-unit inspection map: %s", destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    parser.add_argument("--presentation-config", default=DEFAULT_PRESENTATION_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(
        inspect_geomorphic_units(
            args.config,
            presentation_config_path=args.presentation_config,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
