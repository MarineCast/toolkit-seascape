"""Shared interactive HTML inspection map for H3 habitat products."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import mapping

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.core.geo.h3 import cell_to_polygon

from .habitat_configuration import HabitatSurfaceConfig
from .vector_inspect import json_property_value as _property
from .vector_inspect import (
    new_vector_map,
    save_vector_map,
)

CONFIDENCE_COLORS = {0: "#8A8A8A", 1: "#F2D06B", 2: "#38A9AA", 3: "#0C1C3A"}


def _metric_configs(
    frame: pd.DataFrame,
    metrics: list[tuple[str, str]],
    confidence_column: str,
) -> list[dict[str, Any]]:
    """Describe nonempty metric domains for the browser-side selector."""

    output: list[dict[str, Any]] = []
    for column, label in metrics:
        values = pd.to_numeric(frame[column], errors="coerce")
        finite = values[np.isfinite(values)]
        if finite.empty:
            continue
        minimum = float(finite.quantile(0.02))
        maximum = float(finite.quantile(0.98))
        if math.isclose(minimum, maximum):
            maximum = minimum + 1.0
        output.append(
            {
                "column": column,
                "label": label,
                "kind": "continuous",
                "minimum": minimum,
                "maximum": maximum,
            }
        )
    output.append(
        {
            "column": confidence_column,
            "label": "Evidence confidence / provenance",
            "kind": "confidence",
            "minimum": 0.0,
            "maximum": 3.0,
        }
    )
    return output


def _palette_color(
    value: Any,
    *,
    minimum: float,
    maximum: float,
    palette: list[str],
) -> str:
    if value is None or not np.isfinite(float(value)):
        return "#8A8A8A"
    scaled = np.clip((float(value) - minimum) / (maximum - minimum), 0.0, 1.0)
    index = min(int(float(scaled) * len(palette)), len(palette) - 1)
    return palette[index]


def _shared_geojson(
    records: list[dict[str, Any]],
    property_columns: list[str],
) -> dict[str, Any]:
    """Serialize each H3 geometry exactly once with all switchable properties."""

    features = []
    for row in records:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "H3_INDEX": str(row["H3_INDEX"]),
                    **{column: _property(row.get(column)) for column in property_columns},
                },
                "geometry": mapping(cell_to_polygon(str(row["H3_INDEX"]))),
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _interactive_script(
    *,
    map_name: str,
    layer_name: str,
    selector_id: str,
    metric_configs: list[dict[str, Any]],
    palette: list[str],
    confidence_column: str,
    unmapped_column: str,
    latest_year_column: str,
    provenance_columns: list[str],
    prefix: str,
) -> str:
    """Create the browser-side selector, dynamic styling, legend, and tooltip."""

    provenance_aliases = {
        column: column.replace(f"{prefix}_", "").replace("_", " ").title()
        for column in provenance_columns
    }
    payloads = {
        "metrics": metric_configs,
        "palette": palette,
        "confidenceColors": {str(key): value for key, value in CONFIDENCE_COLORS.items()},
        "confidenceColumn": confidence_column,
        "unmappedColumn": unmapped_column,
        "latestYearColumn": latest_year_column,
        "provenanceAliases": provenance_aliases,
    }
    encoded = {
        key: json.dumps(value, ensure_ascii=False).replace("</", "<\\/")
        for key, value in payloads.items()
    }
    return f"""
(function() {{
    const metricConfigs = {encoded["metrics"]};
    const palette = {encoded["palette"]};
    const confidenceColors = {encoded["confidenceColors"]};
    const confidenceColumn = {encoded["confidenceColumn"]};
    const unmappedColumn = {encoded["unmappedColumn"]};
    const latestYearColumn = {encoded["latestYearColumn"]};
    const provenanceAliases = {encoded["provenanceAliases"]};
    const sharedLayer = {layer_name};
    const habitatMap = {map_name};
    let activeConfig = metricConfigs[0];

    function escapeHtml(value) {{
        return String(value).replace(/[&<>"']/g, function(character) {{
            return {{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"}}[character];
        }});
    }}

    function formatValue(value) {{
        if (value === null || value === undefined || (typeof value === "number" && !Number.isFinite(value))) {{
            return "Unmapped";
        }}
        if (typeof value === "boolean") {{
            return value ? "Yes" : "No";
        }}
        if (typeof value === "number") {{
            return value.toLocaleString(undefined, {{maximumFractionDigits: 4}});
        }}
        return String(value);
    }}

    function hexToRgb(color) {{
        const value = color.replace("#", "");
        return [
            parseInt(value.slice(0, 2), 16),
            parseInt(value.slice(2, 4), 16),
            parseInt(value.slice(4, 6), 16)
        ];
    }}

    function interpolateColor(value, minimum, maximum) {{
        if (value === null || value === undefined || !Number.isFinite(Number(value))) {{
            return "#8A8A8A";
        }}
        const span = maximum - minimum;
        const scaled = Math.max(0, Math.min(1, span > 0 ? (Number(value) - minimum) / span : 0));
        const position = scaled * (palette.length - 1);
        const lower = Math.floor(position);
        const upper = Math.min(lower + 1, palette.length - 1);
        const fraction = position - lower;
        const low = hexToRgb(palette[lower]);
        const high = hexToRgb(palette[upper]);
        const channels = low.map(function(channel, index) {{
            return Math.round(channel + (high[index] - channel) * fraction);
        }});
        return "#" + channels.map(function(channel) {{
            return channel.toString(16).padStart(2, "0");
        }}).join("");
    }}

    function fillColor(properties) {{
        const value = properties[activeConfig.column];
        if (activeConfig.kind === "confidence") {{
            if (value === null || value === undefined || !Number.isFinite(Number(value))) {{
                return "#8A8A8A";
            }}
            return confidenceColors[String(Math.round(Number(value)))] || "#8A8A8A";
        }}
        return interpolateColor(value, activeConfig.minimum, activeConfig.maximum);
    }}

    function styleFeature(feature) {{
        return {{
            fillColor: fillColor(feature.properties),
            color: "#0C1C3A",
            weight: 0.25,
            fillOpacity: activeConfig.kind === "confidence" ? 0.80 : 0.78
        }};
    }}

    function tooltipHtml(properties) {{
        const rows = [
            ["H3", properties.H3_INDEX],
            [activeConfig.label, formatValue(properties[activeConfig.column])]
        ];
        if (activeConfig.column !== confidenceColumn) {{
            rows.push(["Confidence (0-3)", formatValue(properties[confidenceColumn])]);
        }}
        if (Object.prototype.hasOwnProperty.call(properties, unmappedColumn)) {{
            rows.push(["Contains unmapped area", formatValue(properties[unmappedColumn])]);
        }}
        if (properties[latestYearColumn] !== null && properties[latestYearColumn] !== undefined) {{
            rows.push(["Latest year", formatValue(properties[latestYearColumn])]);
        }}
        Object.keys(provenanceAliases).forEach(function(column) {{
            if (properties[column] !== null && properties[column] !== undefined) {{
                rows.push([provenanceAliases[column], formatValue(properties[column])]);
            }}
        }});
        return rows.map(function(row) {{
            return "<div><strong>" + escapeHtml(row[0]) + ":</strong> " + escapeHtml(row[1]) + "</div>";
        }}).join("");
    }}

    function renderLegend(container) {{
        container.replaceChildren();
        const title = document.createElement("div");
        title.className = "habitat-legend-title";
        title.textContent = activeConfig.label;
        container.appendChild(title);
        if (activeConfig.kind === "confidence") {{
            [[0, "Unmapped"], [1, "Low"], [2, "Medium"], [3, "High"]].forEach(function(item) {{
                const row = document.createElement("div");
                row.className = "habitat-legend-row";
                row.innerHTML = '<span class="habitat-swatch" style="background:' + confidenceColors[String(item[0])] + '"></span>' + escapeHtml(item[0] + " — " + item[1]);
                container.appendChild(row);
            }});
            return;
        }}
        palette.forEach(function(color, index) {{
            const fraction = palette.length === 1 ? 0 : index / (palette.length - 1);
            const value = activeConfig.minimum + fraction * (activeConfig.maximum - activeConfig.minimum);
            const row = document.createElement("div");
            row.className = "habitat-legend-row";
            row.innerHTML = '<span class="habitat-swatch" style="background:' + color + '"></span>' + escapeHtml(formatValue(value));
            container.appendChild(row);
        }});
        const nullRow = document.createElement("div");
        nullRow.className = "habitat-legend-row";
        nullRow.innerHTML = '<span class="habitat-swatch" style="background:#8A8A8A"></span>Unmapped';
        container.appendChild(nullRow);
    }}

    const metricControl = L.control({{position: "topright"}});
    metricControl.onAdd = function() {{
        const container = L.DomUtil.create("div", "habitat-metric-control");
        const label = document.createElement("label");
        label.setAttribute("for", {json.dumps(selector_id)});
        label.textContent = "Habitat metric";
        const select = document.createElement("select");
        select.id = {json.dumps(selector_id)};
        select.className = "habitat-metric-select";
        metricConfigs.forEach(function(config) {{
            const option = document.createElement("option");
            option.value = config.column;
            option.textContent = config.label;
            select.appendChild(option);
        }});
        const legend = document.createElement("div");
        legend.className = "habitat-dynamic-legend";
        container.appendChild(label);
        container.appendChild(select);
        container.appendChild(legend);
        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        select.addEventListener("change", function(event) {{
            activeConfig = metricConfigs.find(function(config) {{
                return config.column === event.target.value;
            }}) || metricConfigs[0];
            sharedLayer.setStyle(styleFeature);
            renderLegend(legend);
        }});
        renderLegend(legend);
        return container;
    }};
    metricControl.addTo(habitatMap);
    sharedLayer.eachLayer(function(featureLayer) {{
        featureLayer.bindTooltip(function(sourceLayer) {{
            return tooltipHtml(sourceLayer.feature.properties);
        }}, {{sticky: true}});
    }});
    sharedLayer.setStyle(styleFeature);
}})();
"""


def inspect_habitat_surface(
    config: HabitatSurfaceConfig,
    *,
    metrics: list[tuple[str, str]],
    map_subdirectory: str | Path,
    map_stem: str,
    resolution: int = 6,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Write a single-payload map with switchable metrics and provenance."""

    import folium
    from branca.element import Element, MacroElement, Template

    if resolution not in {6, 8}:
        raise ValueError("Habitat inspectors support H3 resolution 6 or 8.")
    feature_path = config.feature_path(resolution)
    confidence_path = config.confidence_path(resolution)
    for path in (feature_path, confidence_path):
        if not path.exists():
            raise FileNotFoundError(f"Habitat product not found: {path}. Run build.py first.")
    features = pd.read_parquet(feature_path)
    confidence = pd.read_parquet(confidence_path)
    frame = features.merge(
        confidence,
        on=["H3_INDEX", "H3_RESOLUTION"],
        how="left",
        validate="one_to_one",
    )
    if frame.empty or not frame["H3_INDEX"].is_unique:
        raise ValueError("Habitat inspector requires one nonempty row per H3 cell.")
    missing = [column for column, _label in metrics if column not in frame]
    if missing:
        raise ValueError(f"Habitat inspection metrics are missing: {missing}")
    confidence_column = f"{config.prefix}_CONFIDENCE"
    if confidence_column not in frame:
        raise ValueError(f"Habitat confidence column is missing: {confidence_column}")

    settings = load_presentation_settings(presentation_config_path)
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(Path(map_subdirectory), f"{map_stem}_RES_{resolution}.html")
    )
    map_ = new_vector_map(
        settings,
        (
            config.bbox["min_lon"],
            config.bbox["min_lat"],
            config.bbox["max_lon"],
            config.bbox["max_lat"],
        ),
    )
    records = frame.to_dict("records")
    provenance_columns = [
        column
        for column in (
            f"{config.prefix}_SOURCE_DATASETS",
            f"{config.prefix}_EVIDENCE_BASIS",
            f"{config.prefix}_OBSERVED_VS_MODELED",
            f"{config.prefix}_SURVEY_METHOD",
        )
        if column in frame
    ]
    palette = list(settings.color_map())
    metric_configs = _metric_configs(frame, metrics, confidence_column)
    property_columns = list(
        dict.fromkeys(
            [
                *[item["column"] for item in metric_configs],
                f"{config.prefix}_UNMAPPED_AREA",
                f"{config.prefix}_LATEST_SURVEY_YEAR",
                *provenance_columns,
            ]
        )
    )
    shared_data = _shared_geojson(records, property_columns)
    initial = metric_configs[0]
    shared_layer = folium.GeoJson(
        data=shared_data,
        name="Habitat metrics",
        style_function=lambda feature: {
            "fillColor": (
                CONFIDENCE_COLORS.get(
                    int(feature["properties"].get(initial["column"]) or 0),
                    "#8A8A8A",
                )
                if initial["kind"] == "confidence"
                else _palette_color(
                    feature["properties"].get(initial["column"]),
                    minimum=float(initial["minimum"]),
                    maximum=float(initial["maximum"]),
                    palette=palette,
                )
            ),
            "color": "#0C1C3A",
            "weight": 0.25,
            "fillOpacity": 0.78,
        },
    ).add_to(map_)
    selector_id = f"habitat_metric_{map_.get_name()}"
    map_.get_root().header.add_child(Element("""
<style>
.habitat-metric-control {
    background: rgba(255, 255, 255, 0.96);
    border: 1px solid rgba(12, 28, 58, 0.25);
    border-radius: 4px;
    box-shadow: 0 1px 5px rgba(0, 0, 0, 0.35);
    color: #0C1C3A;
    font: 12px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-height: calc(100vh - 40px);
    max-width: 320px;
    overflow: auto;
    padding: 10px;
}
.habitat-metric-control label,
.habitat-legend-title {
    display: block;
    font-weight: 700;
    margin-bottom: 5px;
}
.habitat-metric-select {
    box-sizing: border-box;
    margin-bottom: 9px;
    max-width: 290px;
    width: 100%;
}
.habitat-legend-row {
    align-items: center;
    display: flex;
    gap: 6px;
    margin: 2px 0;
}
.habitat-swatch {
    border: 1px solid rgba(12, 28, 58, 0.35);
    display: inline-block;
    height: 10px;
    width: 18px;
}
</style>
"""))
    control = MacroElement()
    control._template = Template(
        "{% macro script(this, kwargs) %}"
        + _interactive_script(
            map_name=map_.get_name(),
            layer_name=shared_layer.get_name(),
            selector_id=selector_id,
            metric_configs=metric_configs,
            palette=palette,
            confidence_column=confidence_column,
            unmapped_column=f"{config.prefix}_UNMAPPED_AREA",
            latest_year_column=f"{config.prefix}_LATEST_SURVEY_YEAR",
            provenance_columns=provenance_columns,
            prefix=config.prefix,
        )
        + "{% endmacro %}"
    )
    control.add_to(map_)
    destination = save_vector_map(map_, destination)
    if not destination.exists() or destination.stat().st_size <= 0:
        raise RuntimeError(f"Habitat inspection map was not written: {destination}")
    return destination
