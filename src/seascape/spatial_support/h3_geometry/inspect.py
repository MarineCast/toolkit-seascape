"""Inspect configured water-clipped H3 geometry on interactive HTML maps."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd

from seascape.core.config.presentation import (
    DEFAULT_PRESENTATION_CONFIG_PATH,
    load_presentation_settings,
)
from seascape.utils.vector_inspect import (
    new_vector_map,
    save_vector_map,
)

from .build import load_h3_geometry_config

LOGGER = logging.getLogger(__name__)
DEFAULT_SEASCAPE_CONFIG_PATH = "config/data/project.yaml"
MAP_EXPORT_SUBDIRECTORY = Path("domains/environmental_layer/seascape/spatial_support")
H3_WATER_GEOMETRY_MAP_FILENAME_TEMPLATE = "H3_RES{res}_water_geometry.html"


def _read_h3_geometry(path: Path, resolution: int) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"H3 resolution {resolution} Parquet not found: {path}")
    frame = gpd.read_parquet(path)
    if frame.crs is None:
        raise ValueError(f"H3 resolution {resolution} geometry has no CRS: {path}")
    required = {"H3_INDEX", "H3_RESOLUTION", "geometry"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"H3 resolution {resolution} geometry is missing columns: {missing}")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].to_crs("EPSG:4326")
    if frame.empty:
        raise ValueError(f"H3 resolution {resolution} contains no mappable geometry: {path}")
    observed = set(frame["H3_RESOLUTION"].dropna().astype(int).unique())
    if observed != {resolution}:
        raise ValueError(
            f"Expected only H3 resolution {resolution} in {path}; observed {sorted(observed)}"
        )
    return frame


def inspect_h3_water_geometry(
    resolution: int,
    config_path: str | Path = DEFAULT_SEASCAPE_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    parquet_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Open one water-clipped H3 layer and save its configured HTML map."""

    import folium

    config = load_h3_geometry_config(config_path)
    if not 0 <= int(resolution) <= 15:
        raise ValueError("H3 resolution must be between 0 and 15.")
    settings = load_presentation_settings(presentation_config_path)
    source = (
        Path(parquet_path).expanduser().resolve()
        if parquet_path
        else Path(config["output_dir"])
        / config["output_clipped_grid_filename_template"].format(res=resolution)
    )
    destination = (
        Path(output_path).expanduser().resolve()
        if output_path
        else settings.export_path(
            MAP_EXPORT_SUBDIRECTORY,
            H3_WATER_GEOMETRY_MAP_FILENAME_TEMPLATE.format(res=resolution),
        )
    )
    frame = _read_h3_geometry(source, resolution)
    h3_map = new_vector_map(settings, frame.total_bounds)

    folium.GeoJson(
        json.loads(frame.to_json(drop_id=True)),
        name=f"Water geometry — H3 resolution {resolution}",
        style_function=lambda _feature: {
            "fillColor": settings.static_color,
            "color": "#0C1C3A",
            "weight": 0.5,
            "fillOpacity": 0.5,
        },
        highlight_function=lambda _feature: {"weight": 1.5, "fillOpacity": 0.72},
        tooltip=folium.GeoJsonTooltip(
            fields=["H3_INDEX", "H3_RESOLUTION"],
            aliases=["H3 index", "H3 resolution"],
            localize=True,
        ),
        smooth_factor=0.5,
    ).add_to(h3_map)
    folium.LayerControl(collapsed=False).add_to(h3_map)
    h3_map.get_root().header.add_child(
        folium.Element(f"<title>Seascape Toolkit H3 Resolution {resolution} Water Geometry</title>")
    )
    destination = save_vector_map(h3_map, destination)
    LOGGER.info("Saved H3 water-geometry inspection map: %s", destination)
    return destination


def inspect_configured_h3_water_geometry(
    config_path: str | Path = DEFAULT_SEASCAPE_CONFIG_PATH,
    *,
    presentation_config_path: str | Path = DEFAULT_PRESENTATION_CONFIG_PATH,
    resolutions: tuple[int, ...] | None = None,
) -> tuple[Path, ...]:
    """Export maps for every configured or explicitly selected H3 resolution."""

    config = load_h3_geometry_config(config_path)
    selected = config["h3_resolutions"] if resolutions is None else resolutions
    selected = tuple(dict.fromkeys(int(resolution) for resolution in selected))
    if not selected:
        raise ValueError("At least one H3 resolution is required.")
    return tuple(
        inspect_h3_water_geometry(
            resolution,
            config_path,
            presentation_config_path=presentation_config_path,
        )
        for resolution in selected
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_SEASCAPE_CONFIG_PATH)
    parser.add_argument(
        "--presentation-config",
        default=DEFAULT_PRESENTATION_CONFIG_PATH,
    )
    parser.add_argument(
        "--resolution",
        type=int,
        action="append",
        dest="resolutions",
        help="H3 resolution to inspect; repeat to select multiple resolutions.",
    )
    args = parser.parse_args()
    outputs = inspect_configured_h3_water_geometry(
        args.config,
        presentation_config_path=args.presentation_config,
        resolutions=tuple(args.resolutions) if args.resolutions else None,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
