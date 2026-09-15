"""Inspect fluvial network structure and watershed-to-marine crosswalks in HTML."""

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

from .topology import (
    CROSSWALK_COLUMNS,
    DEFAULT_CONFIG_PATH,
    FEATURE_COLUMNS,
    MOUTH_COLUMNS,
    NETWORK_SEGMENT_COLUMNS,
    load_fluvial_connectivity_config,
)

LOGGER = logging.getLogger(__name__)

MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/hydrologic_connectivity")
MAP_FILENAME = "fluvial_connectivity.html"


def _h3_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    cell = str(row["H3_INDEX"])
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, 6), round(y, 6)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    properties = {
        "H3_INDEX": cell,
        "NETWORK_DISTANCE_M": _property_value(row["WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M"]),
        "EUCLIDEAN_DISTANCE_M": _property_value(row["EUCLIDEAN_DISTANCE_TO_FLUVIAL_MOUTH_M"]),
        "DETOUR_M": _property_value(row["FLUVIAL_PATH_DETOUR_M"]),
        "DETOUR_RATIO": _property_value(row["FLUVIAL_PATH_DETOUR_RATIO"]),
        "REACHABLE": _property_value(row["FLUVIAL_MOUTH_REACHABLE"]),
        "DISCONTINUITY": _property_value(row["STRUCTURAL_DISCONTINUITY_FLAG"]),
        "MOUTH_ID": _property_value(row["NEAREST_FLUVIAL_MOUTH_ID"]),
        "BASIN_ID": _property_value(row["NEAREST_RIVER_BASIN_ID"]),
        "SUBBASIN_ID": _property_value(row["NEAREST_OUTLET_SUBBASIN_ID"]),
        "SEGMENTS": _property_value(row["CONNECTED_UPSTREAM_SEGMENT_COUNT"]),
        "JUNCTIONS": _property_value(row["CONNECTED_TRIBUTARY_JUNCTION_COUNT"]),
        "HEADWATERS": _property_value(row["CONNECTED_HEADWATER_COUNT"]),
        "STRAHLER": _property_value(row["CONNECTED_STRAHLER_ORDER"]),
        "NETWORK_LENGTH_KM": _property_value(row["CONNECTED_UPSTREAM_NETWORK_LENGTH_KM"]),
        "UPSTREAM_DISTANCE_KM": _property_value(row["CONNECTED_UPSTREAM_DISTANCE_KM"]),
        "DRAINAGE_AREA_KM2": _property_value(row["CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2"]),
        "TOPOLOGY_GAPS": _property_value(row["SOURCE_NETWORK_TOPOLOGY_GAP_COUNT"]),
        "COMPONENT_ID": _property_value(row["MARINE_NETWORK_COMPONENT_ID"]),
        "MOUTHS_IN_COMPONENT": _property_value(row["MAPPED_FLUVIAL_MOUTH_COUNT_IN_COMPONENT"]),
    }
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _mouth_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = {
        key: _property_value(row.get(key))
        for key in (
            "FLUVIAL_MOUTH_ID",
            "RIVER_BASIN_ID",
            "OUTLET_SUBBASIN_ID",
            "CONNECTED_UPSTREAM_SEGMENT_COUNT",
            "CONNECTED_TRIBUTARY_JUNCTION_COUNT",
            "CONNECTED_HEADWATER_COUNT",
            "CONNECTED_STRAHLER_ORDER",
            "CONNECTED_UPSTREAM_NETWORK_LENGTH_KM",
            "CONNECTED_UPSTREAM_DISTANCE_KM",
            "CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2",
            "SOURCE_NETWORK_TOPOLOGY_GAP_COUNT",
            "GRAPH_SNAP_DISTANCE_M",
            "MARINE_NETWORK_COMPONENT_ID",
        )
    }
    return {"type": "Feature", "properties": properties, "geometry": mapping(row["geometry"])}


def _segment_feature(row: Mapping[str, Any]) -> dict[str, Any]:
    properties = {
        key: _property_value(row.get(key))
        for key in (
            "FLUVIAL_SEGMENT_ID",
            "HYRIV_ID",
            "NEXT_DOWN_ID",
            "RIVER_BASIN_ID",
            "SUBBASIN_ID",
            "ALONG_NETWORK_DISTANCE_TO_OUTLET_KM",
            "UPSTREAM_DISTANCE_KM",
            "SEGMENT_LENGTH_KM",
            "UPSTREAM_DRAINAGE_AREA_KM2",
            "STRAHLER_ORDER",
            "DIRECT_UPSTREAM_SEGMENT_COUNT",
            "SOURCE_NETWORK_TOPOLOGY_GAP",
        )
    }
    return {"type": "Feature", "properties": properties, "geometry": mapping(row["geometry"])}


def _inspection_simplification(config_path: str | Path) -> float:
    raw = load_data_config(resolve_config_path(config_path), domains="SEASCAPE_LAYER")
    section = raw.get("fluvial_connectivity", {})
    inspect = section.get("inspect", {}) if isinstance(section, Mapping) else {}
    if not isinstance(inspect, Mapping):
        raise ValueError("fluvial_connectivity.inspect must be a mapping.")
    tolerance = float(inspect.get("river_simplify_tolerance_m", 75))
    if tolerance < 0:
        raise ValueError("river_simplify_tolerance_m must be nonnegative.")
    return tolerance


def _load_map_inputs(config_path: str | Path):
    import geopandas as gpd

    config = load_fluvial_connectivity_config(config_path)
    required_paths = (
        config.feature_path,
        config.crosswalk_path,
        config.network_segments_path,
        config.network_mouths_path,
    )
    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Fluvial-connectivity product not found: {path}")
    features = pd.read_parquet(config.feature_path)
    crosswalk = pd.read_parquet(config.crosswalk_path)
    segments = gpd.read_parquet(config.network_segments_path)
    mouths = gpd.read_parquet(config.network_mouths_path)
    contracts = (
        ("feature", features, FEATURE_COLUMNS),
        ("crosswalk", crosswalk, CROSSWALK_COLUMNS),
        ("network segment", segments, NETWORK_SEGMENT_COLUMNS),
        ("network mouth", mouths, MOUTH_COLUMNS),
    )
    for name, frame, columns in contracts:
        missing = sorted(set(columns).difference(frame.columns))
        if missing:
            raise ValueError(f"Fluvial {name} product is missing columns: {missing}")
    if features.empty or not features["H3_INDEX"].is_unique:
        raise ValueError("Fluvial feature product must have one nonempty row per H3 cell.")
    if not features["H3_INDEX"].equals(crosswalk["H3_INDEX"]):
        raise ValueError("Feature and watershed crosswalk H3 support must match exactly.")
    if segments.crs is None or mouths.crs is None:
        raise ValueError("Fluvial network geometries must retain CRS metadata.")
    return config, features, crosswalk, segments, mouths


def _prepare_segments(segments: Any, *, simplify_m: float, projected_crs: str):
    selected = segments.loc[segments.geometry.notna() & ~segments.geometry.is_empty].copy()
    if selected.empty:
        raise ValueError("Fluvial network product contains no displayable linework.")
    if simplify_m > 0:
        projected = selected.to_crs(projected_crs)
        projected.geometry = projected.geometry.simplify(simplify_m, preserve_topology=True)
        selected = projected.to_crs("EPSG:4326")
    return selected.loc[selected.geometry.notna() & ~selected.geometry.is_empty].reset_index(
        drop=True
    )


def _metric_specs(features: pd.DataFrame) -> list[dict[str, Any]]:
    definitions = (
        (
            "NETWORK_DISTANCE_M",
            "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M",
            "Along-water-network distance to mapped fluvial mouth",
            True,
            "m",
        ),
        (
            "DETOUR_M",
            "FLUVIAL_PATH_DETOUR_M",
            "Additional freshwater path distance from land barriers",
            True,
            "m",
        ),
        (
            "DETOUR_RATIO",
            "FLUVIAL_PATH_DETOUR_RATIO",
            "H3-stabilized freshwater path detour ratio",
            True,
            "ratio",
        ),
        (
            "JUNCTIONS",
            "CONNECTED_TRIBUTARY_JUNCTION_COUNT",
            "Connected upstream tributary junctions",
            True,
            "count",
        ),
        (
            "HEADWATERS",
            "CONNECTED_HEADWATER_COUNT",
            "Connected mapped headwater reaches",
            True,
            "count",
        ),
        (
            "STRAHLER",
            "CONNECTED_STRAHLER_ORDER",
            "Connected outlet Strahler order",
            False,
            "order",
        ),
        (
            "NETWORK_LENGTH_KM",
            "CONNECTED_UPSTREAM_NETWORK_LENGTH_KM",
            "Connected upstream network length",
            True,
            "km",
        ),
        (
            "DRAINAGE_AREA_KM2",
            "CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2",
            "Connected upstream drainage area",
            True,
            "km2",
        ),
    )
    output: list[dict[str, Any]] = []
    for property_name, column, label, log_scale, unit in definitions:
        numeric = pd.to_numeric(features[column], errors="coerce").dropna()
        if numeric.empty:
            continue
        display = np.log1p(numeric) if log_scale else numeric
        lower = float(display.quantile(0.02))
        upper = float(display.quantile(0.98))
        if math.isclose(lower, upper):
            upper = lower + 1
        output.append(
            {
                "property": property_name,
                "label": label,
                "minimum": lower,
                "maximum": upper,
                "log_scale": log_scale,
                "unit": unit,
            }
        )
    return output


def inspect_fluvial_connectivity(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Write the interactive fluvial-connectivity inspection map."""

    import folium
    from branca.element import MacroElement, Template

    config, features, crosswalk, segments, mouths = _load_map_inputs(config_path)
    del crosswalk
    segments = _prepare_segments(
        segments,
        simplify_m=_inspection_simplification(config_path),
        projected_crs=config.projected_crs,
    )
    mouths = mouths.to_crs("EPSG:4326")
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
    mouth_data = {
        "type": "FeatureCollection",
        "features": [_mouth_feature(row) for row in mouths.to_dict("records")],
    }
    segment_data = {
        "type": "FeatureCollection",
        "features": [_segment_feature(row) for row in segments.to_dict("records")],
    }
    metric_specs = _metric_specs(features)

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
    const fluvialH3 = {json.dumps(h3_data, separators=(',', ':'))};
    const fluvialMouths = {json.dumps(mouth_data, separators=(',', ':'))};
    const fluvialSegments = {json.dumps(segment_data, separators=(',', ':'))};
    const fluvialColors = {json.dumps(list(settings.color_map()), separators=(',', ':'))};
    const fluvialMetricSpecs = {json.dumps(metric_specs, separators=(',', ':'))};

    function fluvialHexRgb(hex) {{
      const value = hex.replace('#', '');
      return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
    }}
    function fluvialColor(spec, value) {{
      if (value === null || !Number.isFinite(Number(value))) return '#7A7A7A';
      const transformed = spec.log_scale ? Math.log1p(Number(value)) : Number(value);
      const t = Math.max(0, Math.min(1, (transformed - spec.minimum) / (spec.maximum - spec.minimum)));
      const position = t * (fluvialColors.length - 1);
      const lo = Math.floor(position);
      const hi = Math.min(fluvialColors.length - 1, lo + 1);
      const fraction = position - lo;
      const a = fluvialHexRgb(fluvialColors[lo]);
      const b = fluvialHexRgb(fluvialColors[hi]);
      const rgb = a.map((channel, index) => Math.round(channel + (b[index] - channel) * fraction));
      return `rgb(${{rgb[0]}},${{rgb[1]}},${{rgb[2]}})`;
    }}
    function fluvialValue(value, digits=2) {{
      return value === null || !Number.isFinite(Number(value))
        ? 'Not mapped'
        : Number(value).toLocaleString(undefined, {{maximumFractionDigits: digits}});
    }}
    function fluvialUnit(spec) {{
      if (spec.unit === 'm') return ' m';
      if (spec.unit === 'km') return ' km';
      if (spec.unit === 'km2') return ' km²';
      return '';
    }}

    function fluvialMetricLayer(spec) {{
      return L.geoJSON(fluvialH3, {{
        style: feature => ({{
          fillColor: feature.properties.DISCONTINUITY
            ? '#4B4B4B'
            : fluvialColor(spec, feature.properties[spec.property]),
          color: fluvialColors[fluvialColors.length - 1],
          weight: 0.22,
          fillOpacity: 0.80
        }}),
        onEachFeature: (feature, layer) => {{
          const p = feature.properties;
          layer.bindTooltip(
            `<b>${{spec.label}}</b><br>${{fluvialValue(p[spec.property], 3)}}${{fluvialUnit(spec)}}` +
            `<br>Water-network distance: ${{fluvialValue(p.NETWORK_DISTANCE_M)}} m` +
            `<br>Euclidean distance: ${{fluvialValue(p.EUCLIDEAN_DISTANCE_M)}} m` +
            `<br>Additional path distance: ${{fluvialValue(p.DETOUR_M)}} m` +
            `<br>Detour ratio: ${{fluvialValue(p.DETOUR_RATIO, 3)}}` +
            `<br>Mapped junctions: ${{fluvialValue(p.JUNCTIONS, 0)}}` +
            `<br>Strahler order: ${{fluvialValue(p.STRAHLER, 0)}}` +
            `<br>River basin: ${{p.BASIN_ID || 'Not mapped'}}` +
            `<br>Outlet sub-basin: ${{p.SUBBASIN_ID || 'Not mapped'}}` +
            `<br>Reachable: ${{p.REACHABLE ? 'Yes' : 'No'}}` +
            `<br>H3: ${{p.H3_INDEX}}`,
            {{sticky: true}}
          );
        }}
      }});
    }}

    const fluvialMetricLayers = fluvialMetricSpecs.map(fluvialMetricLayer);
    fluvialMetricLayers[0].addTo({map_name});

    const fluvialSegmentLayer = L.geoJSON(fluvialSegments, {{
      style: feature => {{
        const order = Number(feature.properties.STRAHLER_ORDER || 1);
        const colorIndex = Math.max(0, Math.min(fluvialColors.length - 1, order - 1));
        return {{color: fluvialColors[colorIndex], weight: Math.min(3.4, 0.65 + order * 0.28), opacity: 0.74}};
      }},
      onEachFeature: (feature, layer) => {{
        const p = feature.properties;
        layer.bindTooltip(
          `<b>${{p.FLUVIAL_SEGMENT_ID}}</b>` +
          `<br>Distance to outlet: ${{fluvialValue(p.ALONG_NETWORK_DISTANCE_TO_OUTLET_KM)}} km` +
          `<br>Strahler order: ${{fluvialValue(p.STRAHLER_ORDER, 0)}}` +
          `<br>Direct upstream reaches: ${{fluvialValue(p.DIRECT_UPSTREAM_SEGMENT_COUNT, 0)}}` +
          `<br>Upstream drainage area: ${{fluvialValue(p.UPSTREAM_DRAINAGE_AREA_KM2)}} km²` +
          `<br>Source topology gap: ${{p.SOURCE_NETWORK_TOPOLOGY_GAP ? 'Yes' : 'No'}}`,
          {{sticky: true}}
        );
      }}
    }}).addTo({map_name});

    const fluvialMouthLayer = L.geoJSON(fluvialMouths, {{
      pointToLayer: (feature, latlng) => {{
        const segments = Number(feature.properties.CONNECTED_UPSTREAM_SEGMENT_COUNT || 1);
        return L.circleMarker(latlng, {{
          radius: Math.max(4, Math.min(12, 3 + Math.log2(segments + 1))),
          color: '#0C1C3A',
          weight: 0.9,
          fillColor: '#38A9AA',
          fillOpacity: 0.94
        }});
      }},
      onEachFeature: (feature, layer) => {{
        const p = feature.properties;
        layer.bindTooltip(
          `<b>${{p.FLUVIAL_MOUTH_ID}}</b>` +
          `<br>River basin: ${{p.RIVER_BASIN_ID}}` +
          `<br>Outlet sub-basin: ${{p.OUTLET_SUBBASIN_ID}}` +
          `<br>Connected segments: ${{fluvialValue(p.CONNECTED_UPSTREAM_SEGMENT_COUNT, 0)}}` +
          `<br>Tributary junctions: ${{fluvialValue(p.CONNECTED_TRIBUTARY_JUNCTION_COUNT, 0)}}` +
          `<br>Headwaters: ${{fluvialValue(p.CONNECTED_HEADWATER_COUNT, 0)}}` +
          `<br>Strahler order: ${{fluvialValue(p.CONNECTED_STRAHLER_ORDER, 0)}}` +
          `<br>Upstream network length: ${{fluvialValue(p.CONNECTED_UPSTREAM_NETWORK_LENGTH_KM)}} km` +
          `<br>Upstream drainage area: ${{fluvialValue(p.CONNECTED_UPSTREAM_DRAINAGE_AREA_KM2)}} km²`,
          {{sticky: true}}
        );
      }}
    }}).addTo({map_name});

    const fluvialOverlays = {{
      'HydroRIVERS network (color = Strahler order)': fluvialSegmentLayer,
      'Mapped fluvial mouths (size = connected segments)': fluvialMouthLayer
    }};
    fluvialMetricSpecs.forEach((spec, index) => {{
      fluvialOverlays[spec.label] = fluvialMetricLayers[index];
    }});
    L.control.layers({{}}, fluvialOverlays, {{collapsed: true}}).addTo({map_name});
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
    map_.get_root().header.add_child(folium.Element("<title>Seascape Toolkit Fluvial Connectivity</title>"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    map_.save(destination)
    LOGGER.info(
        "Saved fluvial inspection map (%d H3 cells, %d mouths, %d segments): %s",
        len(features),
        len(mouths),
        len(segments),
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
        inspect_fluvial_connectivity(
            args.config,
            presentation_config_path=args.presentation_config,
            output_path=args.output,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
