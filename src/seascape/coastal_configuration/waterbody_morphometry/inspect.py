"""Inspect waterbody morphometry in one toggle-layer HTML map."""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np
import polars as pl

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.core.geo.h3 import cell_to_polygon
from seascape.utils.vector_inspect import h3_metric_feature

from .build import OUTPUT_COLUMNS, load_waterbody_morphometry_config

LOGGER = logging.getLogger(__name__)
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/coastal_configuration")
WATERBODY_MAP_FILENAME = "waterbody_morphometry.html"


def _metric_definitions() -> dict[str, tuple[str, str, str]]:
    return {
        "LOCAL_WATERBODY_WIDTH_M": ("Local waterbody width", "m", "sequential"),
        "WATERBODY_WIDTH_MEAN_M": ("Width mean", "m", "sequential"),
        "WATERBODY_WIDTH_MEDIAN_M": ("Width median", "m", "sequential"),
        "WATERBODY_WIDTH_STD_M": ("Width standard deviation", "m", "sequential"),
        "WATERBODY_WIDTH_CENSORED_FRACTION": (
            "Width censored fraction",
            "0–1",
            "unit",
        ),
        "DISTANCE_TO_OPPOSITE_SHORE_M": (
            "Distance to opposite shore",
            "m",
            "sequential",
        ),
        "OPPOSITE_SHORE_CENSORED": ("Opposite shore censored", "0/1", "unit"),
        "CONSTRICTION_INDEX": ("Channel or inlet constriction", "0–1", "unit"),
        "LOCAL_WATERSPACE_AREA_KM2": (
            "Local reachable water-space area",
            "km²",
            "sequential",
        ),
        "LOCAL_WATERSPACE_PERIMETER_KM": (
            "Local reachable water-space perimeter",
            "km",
            "sequential",
        ),
        "LOCAL_WATERSPACE_COMPACTNESS": (
            "Local water-space compactness",
            "0–1",
            "unit",
        ),
        "LOCAL_WATERSPACE_BRANCH_COUNT": (
            "Local water-space branch count",
            "count",
            "sequential",
        ),
        "DISTANCE_TO_CONSTRICTED_PASSAGE_M": (
            "Distance to narrows, pass, or strait candidate",
            "m",
            "sequential",
        ),
        "DISTANCE_TO_SILL_CANDIDATE_M": (
            "Water-network distance to sill candidate",
            "m",
            "sequential",
        ),
    }


METRICS = _metric_definitions()


def _scale(values: np.ndarray, kind: str) -> tuple[float, float]:
    if kind == "unit":
        return 0.0, 1.0
    numeric = np.asarray(values, dtype="float64")
    numeric = numeric[np.isfinite(numeric)]
    if not len(numeric):
        return 0.0, 1.0
    lower = float(np.nanquantile(numeric, 0.02))
    upper = float(np.nanquantile(numeric, 0.98))
    if math.isclose(lower, upper):
        upper = lower + 1.0
    return lower, upper


def inspect_waterbody_morphometry(
    config_path: str | Path = "config/data/environment_seascape.yaml",
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    parquet_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Write one map containing every morphometry metric as a toggleable layer."""

    import folium
    from branca.element import MacroElement, Template

    config = load_waterbody_morphometry_config(config_path)
    settings = load_presentation_settings(presentation_config_path)
    source = Path(parquet_path).expanduser().resolve() if parquet_path else config.output_path
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, WATERBODY_MAP_FILENAME)
    )
    if not source.exists():
        raise FileNotFoundError(f"Waterbody-morphometry Parquet not found: {source}")
    frame = pl.read_parquet(source)
    missing = sorted(set(OUTPUT_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Waterbody-morphometry Parquet is missing columns: {missing}")
    if frame.is_empty():
        raise ValueError(f"Waterbody-morphometry Parquet is empty: {source}")

    features = [h3_metric_feature(row, METRICS) for row in frame.to_dicts()]
    feature_collection = {"type": "FeatureCollection", "features": features}
    colors = settings.color_map()
    scales = {
        metric: {
            "label": label,
            "units": units,
            "min": bounds[0],
            "max": bounds[1],
            "colors": list(settings.color_maps.get(kind, colors)),
        }
        for metric, (label, units, kind) in METRICS.items()
        for bounds in [_scale(frame[metric].to_numpy(), kind)]
    }
    centroids = [cell_to_polygon(cell).centroid for cell in frame["H3_INDEX"].to_list()]
    map_options: dict[str, object] = {
        "location": [
            float(np.mean([point.y for point in centroids])),
            float(np.mean([point.x for point in centroids])),
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
    const morphometryData = {json.dumps(feature_collection, separators=(',', ':'))};
    const morphometryScales = {json.dumps(scales, separators=(',', ':'))};
    function morphometryHexRgb(hex) {{
      const value = hex.replace('#', '');
      return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
    }}
    function morphometryColor(metric, value) {{
      if (value === null || !Number.isFinite(Number(value))) return '#00000000';
      const scale = morphometryScales[metric];
      const span = scale.max - scale.min || 1;
      const t = Math.max(0, Math.min(1, (Number(value) - scale.min) / span));
      const position = t * (scale.colors.length - 1);
      const lower = Math.floor(position);
      const upper = Math.min(scale.colors.length - 1, lower + 1);
      const fraction = position - lower;
      const a = morphometryHexRgb(scale.colors[lower]);
      const b = morphometryHexRgb(scale.colors[upper]);
      const rgb = a.map((channel, index) => Math.round(channel + (b[index] - channel) * fraction));
      return `rgb(${{rgb[0]}},${{rgb[1]}},${{rgb[2]}})`;
    }}
    function morphometryPopulateLayer(layer) {{
      if (layer._morphometryLoaded) return;
      const metric = layer._morphometryMetric;
      const scale = morphometryScales[metric];
      const metricIndex = layer._morphometryMetricIndex;
      L.geoJSON(morphometryData, {{
        style: feature => {{
          const value = feature.properties.VALUES[metricIndex];
          return {{
            fillColor: morphometryColor(metric, value),
            color: scale.colors.slice(-1)[0],
            weight: 0.25,
            fillOpacity: value === null ? 0 : 0.84
          }};
        }},
        onEachFeature: (feature, featureLayer) => {{
          const value = feature.properties.VALUES[metricIndex];
          const rendered = value === null ? 'No data' : Number(value).toLocaleString(undefined, {{maximumFractionDigits: 4}});
          featureLayer.bindTooltip(`<b>${{scale.label}}</b><br>H3: ${{feature.properties.H3_INDEX}}<br>${{rendered}} ${{scale.units}}`, {{sticky: true}});
        }}
      }}).addTo(layer);
      layer._morphometryLoaded = true;
    }}
    const morphometryLayers = {{}};
    Object.entries(morphometryScales).forEach(([metric, scale], index) => {{
      const layer = L.layerGroup();
      layer._morphometryMetric = metric;
      layer._morphometryMetricIndex = index;
      layer._morphometryLoaded = false;
      morphometryLayers[`${{scale.label}} (${{scale.units}})`] = layer;
      if (index === 0) {{
        morphometryPopulateLayer(layer);
        layer.addTo({map_name});
      }}
    }});
    L.control.layers({{}}, morphometryLayers, {{collapsed: true}}).addTo({map_name});
    {map_name}.on('overlayadd', event => morphometryPopulateLayer(event.layer));
    """
    layer_script = MacroElement()
    layer_script._template = Template(
        "{% macro script(this, kwargs) %}" + script + "{% endmacro %}"
    )
    map_.add_child(layer_script)
    map_.get_root().header.add_child(
        folium.Element(
            "<style>.leaflet-control-layers-expanded{max-height:75vh;overflow-y:auto;}</style>"
        )
    )
    bounds = [polygon.bounds for polygon in map(cell_to_polygon, frame["H3_INDEX"].to_list())]
    map_.fit_bounds(
        [
            [min(item[1] for item in bounds), min(item[0] for item in bounds)],
            [max(item[3] for item in bounds), max(item[2] for item in bounds)],
        ]
    )
    map_.get_root().header.add_child(
        folium.Element("<title>Seascape Toolkit Waterbody Morphometry</title>")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    map_.save(destination)
    LOGGER.info("Saved waterbody-morphometry inspection map: %s", destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/environment_seascape.yaml")
    parser.add_argument(
        "--presentation-config",
        default=DEFAULT_PRESENTATION_CONFIG_PATH,
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(
        inspect_waterbody_morphometry(
            args.config,
            presentation_config_path=args.presentation_config,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
