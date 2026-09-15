"""Inspect every geomorphometry product in one toggle-layer HTML map."""

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

from .build import GeomorphometryConfig, load_geomorphometry_config, output_columns

LOGGER = logging.getLogger(__name__)
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/seafloor_physiography")
GEOMORPHOMETRY_MAP_FILENAME = "geomorphometry.html"


def _metric_definitions(
    config: GeomorphometryConfig,
) -> dict[str, tuple[str, str, str]]:
    metrics: dict[str, tuple[str, str, str]] = {
        "SLOPE": ("Focal H3 plane slope", "degrees", "sequential"),
        "ASPECT": ("Focal H3 aspect", "degrees clockwise from north", "aspect"),
        "TERRAIN_POSITION": ("Legacy terrain position — ring 1", "m", "diverging"),
        "CURVATURE": (
            "Legacy elevation Laplacian — positive concave",
            "1/m",
            "diverging",
        ),
        "RELIEF": ("Legacy depth range — ring 1", "m", "sequential"),
        "RUGGEDNESS": ("Ruggedness — Wilson bathymetric TRI", "m", "sequential"),
        "SLOPE_MEAN_NATIVE_RASTER": (
            "Mean native-raster slope",
            "degrees",
            "sequential",
        ),
        "SLOPE_Q90_NATIVE_RASTER": (
            f"Q{int(config.slope_upper_quantile * 100)} native-raster slope",
            "degrees",
            "sequential",
        ),
        "EASTNESS": ("Eastness", "−1 to 1", "diverging"),
        "NORTHNESS": ("Northness", "−1 to 1", "diverging"),
        "PROFILE_CURVATURE": (
            "Profile curvature — positive convex",
            "1/m",
            "diverging",
        ),
        "PLAN_CURVATURE": (
            "Plan curvature — positive convex",
            "1/m",
            "diverging",
        ),
        "GENERAL_CURVATURE": (
            "General curvature — positive convex",
            "1/m",
            "diverging",
        ),
        "SURFACE_AREA_RATIO_FROM_SLOPE": (
            "Surface-area ratio derived from slope",
            "ratio",
            "sequential",
        ),
    }
    for ring in config.neighborhood_rings:
        metrics.update(
            {
                f"SLOPE_MEAN_RING_{ring}": (
                    f"Mean focal slope — H3 ring {ring}",
                    "degrees",
                    "sequential",
                ),
                f"SLOPE_Q90_RING_{ring}": (
                    f"Q{int(config.slope_upper_quantile * 100)} focal slope — H3 ring {ring}",
                    "degrees",
                    "sequential",
                ),
                f"ASPECT_CIRCULAR_MEAN_RING_{ring}": (
                    f"Circular mean aspect — H3 ring {ring}",
                    "degrees clockwise from north",
                    "aspect",
                ),
                f"ASPECT_RESULTANT_LENGTH_RING_{ring}": (
                    f"Aspect resultant length — H3 ring {ring}",
                    "0–1",
                    "unit",
                ),
                f"TERRAIN_POSITION_RING_{ring}_M": (
                    f"Terrain position — H3 ring {ring}",
                    "m",
                    "diverging",
                ),
                f"TERRAIN_POSITION_RING_{ring}_Z": (
                    f"Standardized terrain position — H3 ring {ring}",
                    "z",
                    "diverging",
                ),
                f"LOCAL_RELIEF_RING_{ring}_M": (
                    f"Focal-centered local relief — H3 ring {ring}",
                    "m",
                    "sequential",
                ),
                f"DEPTH_RANGE_RING_{ring}_M": (
                    f"Neighborhood depth range — H3 ring {ring}",
                    "m",
                    "sequential",
                ),
                f"DEPTH_STD_RING_{ring}_M": (
                    f"Depth standard deviation — H3 ring {ring}",
                    "m",
                    "sequential",
                ),
                f"DEPTH_MAD_RING_{ring}_M": (
                    f"Depth median absolute deviation — H3 ring {ring}",
                    "m",
                    "sequential",
                ),
                f"VECTOR_RUGGEDNESS_RING_{ring}": (
                    f"Vector ruggedness measure — H3 ring {ring}",
                    "0–1",
                    "unit",
                ),
                f"NEIGHBORHOOD_ROUGHNESS_RING_{ring}_M": (
                    f"Detrended neighborhood roughness — H3 ring {ring}",
                    "m",
                    "sequential",
                ),
            }
        )
    metrics.update(
        {
            "POSITIVE_OPENNESS_DEG": (
                f"Positive openness — H3 ring {config.openness_radius_rings}",
                "degrees",
                "openness",
            ),
            "NEGATIVE_OPENNESS_DEG": (
                f"Negative openness — H3 ring {config.openness_radius_rings}",
                "degrees",
                "openness",
            ),
            "OPENNESS_SECTOR_COVERAGE": (
                "Openness sector coverage",
                "0–1",
                "unit",
            ),
            "RIDGE_INDEX": ("Multi-scale ridge index", "0–1", "unit"),
            "VALLEY_INDEX": ("Multi-scale valley index", "0–1", "unit"),
            "CONVEXITY_INDEX": ("Convexity index", "0–1", "unit"),
            "CONCAVITY_INDEX": ("Concavity index", "0–1", "unit"),
        }
    )
    return metrics


def _scale(values: pd.Series, kind: str) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return 0.0, 1.0
    if kind == "aspect":
        return 0.0, 360.0
    if kind == "unit":
        return 0.0, 1.0
    if kind == "openness":
        return 0.0, 180.0
    if kind == "diverging":
        limit = float(np.nanquantile(np.abs(numeric), 0.98))
        limit = limit if math.isfinite(limit) and limit > 0.0 else 1.0
        return -limit, limit
    lower = float(np.nanquantile(numeric, 0.02))
    upper = float(np.nanquantile(numeric, 0.98))
    if math.isclose(lower, upper):
        upper = lower + 1.0
    return lower, upper


def _feature(
    row: Mapping[str, Any], metrics: Mapping[str, tuple[str, str, str]]
) -> dict[str, object]:
    cell = str(row["H3_INDEX"])
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, 6), round(y, 6)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    properties: dict[str, object] = {
        "H3_INDEX": cell,
        "VALUES": [_finite(row[metric], digits=8) for metric in metrics],
    }
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def inspect_geomorphometry(
    config_path: str | Path = "config/data/environment_seascape.yaml",
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    parquet_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Write one map containing every geomorphometric metric as a toggleable layer."""

    import folium
    from branca.element import MacroElement, Template

    config = load_geomorphometry_config(config_path)
    settings = load_presentation_settings(presentation_config_path)
    source = Path(parquet_path).expanduser().resolve() if parquet_path else config.output_path
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, GEOMORPHOMETRY_MAP_FILENAME)
    )
    if not source.exists():
        raise FileNotFoundError(f"Geomorphometry Parquet not found: {source}")
    frame = pd.read_parquet(source)
    expected_columns = output_columns(config.neighborhood_rings)
    missing = sorted(set(expected_columns).difference(frame.columns))
    if missing:
        raise ValueError(f"Geomorphometry Parquet is missing columns: {missing}")
    if frame.empty:
        raise ValueError(f"Geomorphometry Parquet is empty: {source}")

    metrics = _metric_definitions(config)
    features = [_feature(row, metrics) for row in frame.to_dict(orient="records")]
    feature_collection = {"type": "FeatureCollection", "features": features}
    default_colors = settings.color_map()
    scales = {
        metric: {
            "index": index,
            "label": label,
            "units": units,
            "kind": kind,
            "min": bounds[0],
            "max": bounds[1],
            "colors": list(settings.color_maps.get(kind, default_colors)),
        }
        for index, (metric, (label, units, kind)) in enumerate(metrics.items())
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
    script = f"""
    const geomorphometryData = {json.dumps(feature_collection, separators=(',', ':'))};
    const geomorphometryScales = {json.dumps(scales, separators=(',', ':'))};
    function geomorphometryHexRgb(hex) {{
      const value = hex.replace('#', '');
      return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
    }}
    function geomorphometryColor(scale, value) {{
      if (value === null || !Number.isFinite(Number(value))) return '#00000000';
      const span = scale.max - scale.min || 1;
      const t = Math.max(0, Math.min(1, (Number(value) - scale.min) / span));
      const position = t * (scale.colors.length - 1);
      const lower = Math.floor(position);
      const upper = Math.min(scale.colors.length - 1, lower + 1);
      const fraction = position - lower;
      const a = geomorphometryHexRgb(scale.colors[lower]);
      const b = geomorphometryHexRgb(scale.colors[upper]);
      const rgb = a.map((channel, index) => Math.round(channel + (b[index] - channel) * fraction));
      return `rgb(${{rgb[0]}},${{rgb[1]}},${{rgb[2]}})`;
    }}
    const geomorphometryLayers = {{}};
    Object.entries(geomorphometryScales).forEach(([metric, scale], index) => {{
      const layer = L.geoJSON(geomorphometryData, {{
        style: feature => {{
          const value = feature.properties.VALUES[scale.index];
          return {{
            fillColor: geomorphometryColor(scale, value),
            color: scale.colors.slice(-1)[0],
            weight: 0.25,
            fillOpacity: value === null ? 0 : 0.84
          }};
        }},
        onEachFeature: (feature, featureLayer) => {{
          const value = feature.properties.VALUES[scale.index];
          const rendered = value === null ? 'No data' : Number(value).toLocaleString(undefined, {{maximumFractionDigits: 6}});
          featureLayer.bindTooltip(`<b>${{scale.label}}</b><br>H3: ${{feature.properties.H3_INDEX}}<br>${{rendered}} ${{scale.units}}`, {{sticky: true}});
        }}
      }});
      geomorphometryLayers[`${{scale.label}} (${{scale.units}})`] = layer;
      if (index === 0) layer.addTo({map_name});
    }});
    L.control.layers({{}}, geomorphometryLayers, {{collapsed: true}}).addTo({map_name});
    """
    layer_script = MacroElement()
    layer_script._template = Template(
        "{% macro script(this, kwargs) %}" + script + "{% endmacro %}"
    )
    map_.add_child(layer_script)
    bounds = frame["H3_INDEX"].astype(str).map(cell_to_polygon).map(lambda polygon: polygon.bounds)
    map_.fit_bounds(
        [
            [min(item[1] for item in bounds), min(item[0] for item in bounds)],
            [max(item[3] for item in bounds), max(item[2] for item in bounds)],
        ]
    )
    map_.get_root().header.add_child(
        folium.Element("<title>Seascape Toolkit Seafloor Geomorphometry</title>")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    map_.save(destination)
    LOGGER.info("Saved geomorphometry inspection map: %s", destination)
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
        inspect_geomorphometry(
            args.config,
            presentation_config_path=args.presentation_config,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
