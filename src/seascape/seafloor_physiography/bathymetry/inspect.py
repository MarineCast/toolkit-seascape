"""Inspect processed bathymetry with an interactive layered map."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from shapely.geometry import mapping

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.core.geo.h3 import cell_to_polygon

if TYPE_CHECKING:
    from .pipeline import BathymetryConfig

LOGGER = logging.getLogger(__name__)
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/seafloor_physiography")
BATHYMETRY_MAP_FILENAME = "bathymetry.html"
GEBCO_ATTRIBUTION = (
    "GEBCO Bathymetric Compilation Group 2026 (2026), The GEBCO_2026 Grid, "
    "doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa"
)

METRIC_LABELS = {
    "BATHYMETRY": "Mean depth (m)",
    "BATHYMETRY_MEDIAN": "Median depth (m)",
    "BATHYMETRY_MIN": "Minimum depth (m)",
    "BATHYMETRY_MAX": "Maximum depth (m)",
    "BATHYMETRY_STD": "Depth standard deviation (m)",
    "BATHYMETRY_RANGE": "Depth range (m)",
    "BATHYMETRY_LOCAL_ANOMALY": "Local depth anomaly (m)",
    "BATHYMETRY_Q10": "Depth Q10 (m)",
    "BATHYMETRY_Q25": "Depth Q25 (m)",
    "BATHYMETRY_Q75": "Depth Q75 (m)",
    "BATHYMETRY_Q90": "Depth Q90 (m)",
    "DISTANCE_TO_ISOBATH_6_1_M": "Distance to 6.1 m isobath (m)",
    "DISTANCE_TO_ISOBATH_50_M": "Distance to 50 m isobath (m)",
    "DISTANCE_TO_ISOBATH_100_M": "Distance to 100 m isobath (m)",
    "DISTANCE_TO_ISOBATH_200_M": "Distance to 200 m isobath (m)",
    "BATHYMETRY_PIXEL_COUNT": "GEBCO source-pixel count",
}


def _map_feature(
    cell: str,
    values: dict[str, Any],
    metric_columns: list[str],
) -> dict[str, Any]:
    geometry = mapping(cell_to_polygon(cell))
    geometry["coordinates"] = [
        [[round(x, 6), round(y, 6)] for x, y in ring] for ring in geometry["coordinates"]
    ]
    properties: dict[str, Any] = {"H3_INDEX": cell}
    for column in metric_columns:
        value = values[column]
        properties[column] = (
            None if pd.isna(value) or not np.isfinite(float(value)) else round(float(value), 2)
        )
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": geometry,
    }


def _metric_label(column: str) -> str:
    return METRIC_LABELS.get(column, column.replace("_", " ").title())


def _metric_ranges(
    frames: list[tuple[int, pd.DataFrame]],
    metric_columns: list[str],
) -> dict[str, dict[str, float | str]]:
    settings: dict[str, dict[str, float | str]] = {}
    for column in metric_columns:
        values = pd.concat([frame[column] for _resolution, frame in frames])
        values = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if values.empty:
            continue
        lower = float(values.min())
        upper = float(values.max())
        if math.isclose(lower, upper):
            upper = lower + 1.0
        settings[column] = {
            "label": _metric_label(column),
            "min": lower,
            "max": upper,
        }
    return settings


def _add_metric_selector(
    bathymetry_map: Any,
    metric_layers: list[Any],
    metric_settings: dict[str, dict[str, float | str]],
    colors: tuple[str, ...],
) -> None:
    """Add one shared selector that recolors each H3-resolution layer."""

    from branca.element import MacroElement, Template

    layer_names = ", ".join(layer.get_name() for layer in metric_layers)
    settings_json = json.dumps(metric_settings, separators=(",", ":"))
    colors_json = json.dumps(list(colors), separators=(",", ":"))
    script = f"""
    var bathymetryMetricSettings = {settings_json};
    var bathymetryMetricColors = {colors_json};
    var bathymetryMetricLayers = [{layer_names}];
    var bathymetryActiveMetric = "BATHYMETRY";

    function bathymetryHexToRgb(hex) {{
        return [
            parseInt(hex.slice(1, 3), 16),
            parseInt(hex.slice(3, 5), 16),
            parseInt(hex.slice(5, 7), 16)
        ];
    }}

    function bathymetryMetricColor(value, settings) {{
        if (value === null || value === undefined || !Number.isFinite(Number(value))) {{
            return "#d9d9d9";
        }}
        var fraction = (Number(value) - settings.min) / (settings.max - settings.min);
        fraction = Math.max(0, Math.min(1, fraction));
        var scaled = fraction * (bathymetryMetricColors.length - 1);
        var index = Math.min(Math.floor(scaled), bathymetryMetricColors.length - 2);
        var local = scaled - index;
        var start = bathymetryHexToRgb(bathymetryMetricColors[index]);
        var end = bathymetryHexToRgb(bathymetryMetricColors[index + 1]);
        var rgb = start.map(function(channel, position) {{
            return Math.round(channel + local * (end[position] - channel));
        }});
        return "rgb(" + rgb.join(",") + ")";
    }}

    function bathymetryMetricStyle(feature) {{
        var value = feature.properties[bathymetryActiveMetric];
        var hasValue = value !== null && value !== undefined && Number.isFinite(Number(value));
        return {{
            fillColor: bathymetryMetricColor(
                value,
                bathymetryMetricSettings[bathymetryActiveMetric]
            ),
            color: bathymetryMetricColors[bathymetryMetricColors.length - 1],
            weight: 0.25,
            fillOpacity: hasValue ? 0.84 : 0.20
        }};
    }}

    function bathymetryFormatValue(value, metric) {{
        if (value === null || value === undefined || !Number.isFinite(Number(value))) {{
            return "No data";
        }}
        if (metric === "BATHYMETRY_PIXEL_COUNT") {{
            return Math.round(Number(value)).toLocaleString();
        }}
        return Number(value).toLocaleString(undefined, {{maximumFractionDigits: 2}});
    }}

    var bathymetryMetricControl = L.control({{position: "topleft"}});
    bathymetryMetricControl.onAdd = function() {{
        var container = L.DomUtil.create("div", "bathymetry-metric-control");
        container.style.background = "rgba(255,255,255,.94)";
        container.style.padding = "8px 10px";
        container.style.border = "1px solid #a8b6b5";
        container.style.borderRadius = "4px";
        container.style.boxShadow = "0 1px 5px rgba(0,0,0,.25)";
        container.style.minWidth = "250px";

        var label = L.DomUtil.create("label", "", container);
        label.textContent = "Bathymetry variable";
        label.style.display = "block";
        label.style.fontWeight = "600";
        label.style.marginBottom = "4px";

        var select = L.DomUtil.create("select", "", container);
        select.style.width = "100%";
        select.style.padding = "3px";
        Object.keys(bathymetryMetricSettings).forEach(function(metric) {{
            var option = document.createElement("option");
            option.value = metric;
            option.textContent = bathymetryMetricSettings[metric].label;
            select.appendChild(option);
        }});

        var gradient = L.DomUtil.create("div", "", container);
        gradient.style.height = "10px";
        gradient.style.marginTop = "8px";
        gradient.style.background = "linear-gradient(to right," +
            bathymetryMetricColors.join(",") + ")";

        var range = L.DomUtil.create("div", "", container);
        range.style.display = "flex";
        range.style.justifyContent = "space-between";
        range.style.fontSize = "11px";
        range.style.marginTop = "2px";
        var minimum = L.DomUtil.create("span", "", range);
        var maximum = L.DomUtil.create("span", "", range);

        function updateMetric() {{
            bathymetryActiveMetric = select.value;
            var settings = bathymetryMetricSettings[bathymetryActiveMetric];
            minimum.textContent = bathymetryFormatValue(settings.min, bathymetryActiveMetric);
            maximum.textContent = bathymetryFormatValue(settings.max, bathymetryActiveMetric);
            bathymetryMetricLayers.forEach(function(group) {{
                group.eachLayer(function(layer) {{
                    if (layer.feature) {{
                        layer.setStyle(bathymetryMetricStyle(layer.feature));
                    }}
                }});
            }});
        }}

        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);
        L.DomEvent.on(select, "change", updateMetric);
        container._bathymetrySelect = select;
        container._bathymetryUpdate = updateMetric;
        return container;
    }};
    bathymetryMetricControl.addTo({bathymetry_map.get_name()});

    bathymetryMetricLayers.forEach(function(group) {{
        group.eachLayer(function(layer) {{
            if (layer.feature) {{
                layer.bindTooltip(function(sourceLayer) {{
                    var properties = sourceLayer.feature.properties;
                    var settings = bathymetryMetricSettings[bathymetryActiveMetric];
                    return "<strong>H3:</strong> " + properties.H3_INDEX +
                        "<br><strong>" + settings.label + ":</strong> " +
                        bathymetryFormatValue(
                            properties[bathymetryActiveMetric],
                            bathymetryActiveMetric
                        );
                }}, {{sticky: true}});
            }}
        }});
    }});
    document.querySelector(".bathymetry-metric-control")._bathymetryUpdate();
    """
    element = MacroElement()
    element._template = Template("{% macro script(this, kwargs) %}" + script + "{% endmacro %}")
    bathymetry_map.add_child(element)


def _masked_gaussian_filter(
    values: np.ndarray,
    support_mask: np.ndarray,
    *,
    sigma_pixels: float,
) -> np.ndarray:
    """Smooth within modeled support without edge attenuation or diffusion."""

    from scipy.ndimage import gaussian_filter

    mask = np.asarray(support_mask, dtype=bool)
    value_array = np.asarray(values, dtype="float32")
    output = np.full(value_array.shape, np.nan, dtype="float32")
    if not mask.any():
        return output
    numerator = gaussian_filter(
        np.where(mask, value_array, 0.0),
        sigma=(sigma_pixels, sigma_pixels),
        mode="constant",
        cval=0.0,
        truncate=3.0,
        output=np.float32,
    )
    denominator = gaussian_filter(
        mask.astype("float32"),
        sigma=(sigma_pixels, sigma_pixels),
        mode="constant",
        cval=0.0,
        truncate=3.0,
        output=np.float32,
    )
    np.divide(
        numerator,
        denominator,
        out=output,
        where=mask & (denominator > np.finfo("float32").eps),
    )
    output[~mask] = np.nan
    return output


def _smoothed_bathymetry_image(
    frame: pd.DataFrame,
    config: BathymetryConfig,
    *,
    vmin: float,
    vmax: float,
    colors: tuple[str, ...],
) -> tuple[np.ndarray, list[list[float]]]:
    """Rasterize and smooth H3 bathymetry using the viewshed map method."""

    import geopandas as gpd
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from rasterio.features import rasterize
    from rasterio.transform import array_bounds, from_origin
    from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

    valid = frame.dropna(subset=["H3_INDEX", "BATHYMETRY"]).copy()
    valid["geometry"] = valid["H3_INDEX"].astype(str).map(cell_to_polygon)
    grid = gpd.GeoDataFrame(valid, geometry="geometry", crs="EPSG:4326").to_crs(
        config.smoothing_projected_crs
    )
    pixel = config.smoothing_analysis_pixel_size_m
    padding = max(3_000.0, config.smoothing_gaussian_sigma_km * 3_000.0)
    min_x, min_y, max_x, max_y = grid.total_bounds
    west = np.floor((min_x - padding) / pixel) * pixel
    south = np.floor((min_y - padding) / pixel) * pixel
    east = np.ceil((max_x + padding) / pixel) * pixel
    north = np.ceil((max_y + padding) / pixel) * pixel
    width = max(1, int(round((east - west) / pixel)))
    height = max(1, int(round((north - south) / pixel)))
    transform = from_origin(west, north, pixel, pixel)
    shapes = [(mapping(row.geometry), float(row.BATHYMETRY)) for row in grid.itertuples()]
    support = rasterize(
        [(geometry, 1) for geometry, _value in shapes],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    )
    values = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        all_touched=True,
        dtype="float32",
    )
    smoothed = _masked_gaussian_filter(
        values,
        support,
        sigma_pixels=config.smoothing_gaussian_sigma_km * 1_000.0 / pixel,
    )
    left, bottom, right, top = array_bounds(height, width, transform)
    output_transform, output_width, output_height = calculate_default_transform(
        config.smoothing_projected_crs,
        config.smoothing_output_crs,
        width,
        height,
        left,
        bottom,
        right,
        top,
        resolution=config.smoothing_output_pixel_size_m,
    )
    output = np.full((output_height, output_width), np.nan, dtype="float32")
    output_support = np.zeros((output_height, output_width), dtype="uint8")
    reproject(
        source=smoothed,
        destination=output,
        src_transform=transform,
        src_crs=config.smoothing_projected_crs,
        dst_transform=output_transform,
        dst_crs=config.smoothing_output_crs,
        src_nodata=np.nan,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    reproject(
        source=support,
        destination=output_support,
        src_transform=transform,
        src_crs=config.smoothing_projected_crs,
        dst_transform=output_transform,
        dst_crs=config.smoothing_output_crs,
        src_nodata=0,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    output[~output_support.astype(bool)] = np.nan
    normalized = Normalize(vmin=vmin, vmax=vmax, clip=True)(np.nan_to_num(output, nan=vmin))
    colormap = LinearSegmentedColormap.from_list("bathymetry", list(colors))
    rgba = colormap(normalized)
    rgba[..., 3] = np.where(
        np.isfinite(output) & output_support.astype(bool), config.smoothing_fill_opacity, 0.0
    )
    bounds = transform_bounds(
        config.smoothing_output_crs,
        "EPSG:4326",
        *array_bounds(output_height, output_width, output_transform),
    )
    return np.clip(rgba * 255.0, 0, 255).astype("uint8"), [
        [bounds[1], bounds[0]],
        [bounds[3], bounds[2]],
    ]


def build_bathymetry_map(
    config: BathymetryConfig,
    *,
    parquet_path: str | Path | None = None,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    output_path: str | Path | None = None,
) -> Path:
    """Create one interactive inspection map for every metric and resolution."""

    import folium
    from branca.colormap import LinearColormap

    settings = load_presentation_settings(presentation_config_path)
    colors = settings.color_map()
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(MAP_EXPORT_SUBDIRECTORY, BATHYMETRY_MAP_FILENAME)
    )
    primary = Path(parquet_path).expanduser().resolve() if parquet_path else config.processed_path
    layer_sources = [(config.h3_resolution, primary)] + [
        (export.h3_resolution, export.processed_path) for export in config.additional_exports
    ]
    frames: list[tuple[int, pd.DataFrame]] = []
    metric_columns: list[str] = []
    for resolution, source in layer_sources:
        if not source.exists():
            raise FileNotFoundError(f"Bathymetry Parquet not found: {source}")
        frame = pd.read_parquet(source)
        missing = sorted({"H3_INDEX", "BATHYMETRY"}.difference(frame.columns))
        if missing:
            raise ValueError(f"Bathymetry Parquet is missing columns {missing}: {source}")
        frame_metrics = [
            column
            for column in frame.columns
            if column != "H3_INDEX" and pd.api.types.is_numeric_dtype(frame[column])
        ]
        if not metric_columns:
            metric_columns = frame_metrics
        elif frame_metrics != metric_columns:
            raise ValueError(
                "Bathymetry exports must expose identical numeric columns; "
                f"expected {metric_columns}, found {frame_metrics} in {source}."
            )
        frame = frame.dropna(subset=["H3_INDEX"])
        if frame.empty:
            raise ValueError(f"Bathymetry Parquet contains no mapped values: {source}")
        frames.append((resolution, frame))
    metric_settings = _metric_ranges(frames, metric_columns)
    if "BATHYMETRY" not in metric_settings:
        raise ValueError("Bathymetry exports contain no finite BATHYMETRY values.")
    lower = float(metric_settings["BATHYMETRY"]["min"])
    upper = float(metric_settings["BATHYMETRY"]["max"])
    color_scale = LinearColormap(
        colors=list(colors),
        vmin=lower,
        vmax=upper,
    )
    map_options: dict[str, object] = {
        "location": [
            (config.bbox["min_lat"] + config.bbox["max_lat"]) / 2.0,
            (config.bbox["min_lon"] + config.bbox["max_lon"]) / 2.0,
        ],
        "tiles": settings.basemap_tile_layer,
        "control_scale": True,
        "prefer_canvas": True,
        "zoom_start": settings.default_zoom,
    }
    if settings.basemap_attribution:
        map_options["attr"] = settings.basemap_attribution
    bathymetry_map = folium.Map(**map_options)
    metric_layers: list[Any] = []
    for resolution, frame in frames:
        features = [
            _map_feature(str(values["H3_INDEX"]), values, metric_columns)
            for values in frame[["H3_INDEX", *metric_columns]].to_dict(orient="records")
        ]
        metric_layer = folium.GeoJson(
            {"type": "FeatureCollection", "features": features},
            name=f"Bathymetry metrics — H3 resolution {resolution}",
            show=resolution == config.h3_resolution,
            style_function=lambda feature: {
                "fillColor": (
                    color_scale(feature["properties"]["BATHYMETRY"])
                    if feature["properties"]["BATHYMETRY"] is not None
                    else "#d9d9d9"
                ),
                "color": colors[-1],
                "weight": 0.25,
                "fillOpacity": (0.84 if feature["properties"]["BATHYMETRY"] is not None else 0.20),
            },
            popup=folium.GeoJsonPopup(
                fields=["H3_INDEX", *metric_columns],
                aliases=["H3", *[_metric_label(column) for column in metric_columns]],
                localize=True,
                max_width=420,
            ),
            smooth_factor=0.5,
        )
        metric_layer.add_to(bathymetry_map)
        metric_layers.append(metric_layer)
        smooth_image, smooth_bounds = _smoothed_bathymetry_image(
            frame, config, vmin=lower, vmax=upper, colors=colors
        )
        folium.raster_layers.ImageOverlay(
            image=smooth_image,
            bounds=smooth_bounds,
            name=f"Bathymetry — smoothed H3 resolution {resolution}",
            opacity=1.0,
            interactive=True,
            cross_origin=False,
            zindex=2,
            show=False,
        ).add_to(bathymetry_map)
    _add_metric_selector(bathymetry_map, metric_layers, metric_settings, colors)
    folium.LayerControl(collapsed=False).add_to(bathymetry_map)
    bathymetry_map.fit_bounds(
        [
            [config.bbox["min_lat"], config.bbox["min_lon"]],
            [config.bbox["max_lat"], config.bbox["max_lon"]],
        ]
    )
    attribution = (
        '<div style="position:fixed;bottom:20px;left:10px;z-index:9999;'
        "background:rgba(255,255,255,.88);padding:4px 7px;font-size:10px;"
        'max-width:390px;border-radius:3px;">'
        f"{GEBCO_ATTRIBUTION}. Not for navigation.</div>"
    )
    bathymetry_map.get_root().header.add_child(folium.Element("<title>Seascape Toolkit Bathymetry</title>"))
    bathymetry_map.get_root().html.add_child(folium.Element(attribution))
    destination.parent.mkdir(parents=True, exist_ok=True)
    bathymetry_map.save(destination)
    LOGGER.info("Saved bathymetry inspection map: %s", destination)
    return destination


def main() -> int:
    """Inspect an existing bathymetry product without rebuilding it."""
    import argparse
    from .pipeline import load_bathymetry_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/data/project.yaml")
    parser.add_argument("--presentation-config", default=DEFAULT_PRESENTATION_CONFIG_PATH)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(build_bathymetry_map(
        load_bathymetry_config(args.config), parquet_path=args.input,
        presentation_config_path=args.presentation_config, output_path=args.output,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
