"""Build the canonical territorial-water geometry from configured GIS sources."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.artifacts.checksums import checksum_path
from seascape.publication import (
    TransactionalSeascapePublisher,
)
from seascape.utils.artifacts import (
    build_manifest,
    capture_staged_parquet_artifact,
)

from .config import load_water_geometry_config
from .download import (
    CONSUMED_WATER_GEOMETRY_SOURCE_NAMES,
    download_water_geometry_sources,
    open_water_geometry_sources,
    resolve_water_geometry_paths,
)
from .geometry_operations import clean_connected_lines as clean_connect_lines_fast
from .geometry_operations import closed_lines as find_closed_lines
from .geometry_operations import (
    connect_lines_to_polygon,
    linestrings_to_polygons_if_closed,
    polygonize_boundary_cycle,
)
from .geometry_operations import smooth_coastline as get_smoothed_coastline
from .source_assembly import (
    build_us_coastline,
    build_us_waters_boundary,
)
from .source_assembly import clip_us_water_lines as get_us_waters

SOURCE_ATTRIBUTION = {
    "ca_regions_path": ("Fisheries and Oceans Canada", "Open Government Licence - Canada"),
    "wsdot_shorelines_path": ("Washington State Department of Transportation", "Public data"),
    "ws_marine_shoreline_type_path": (
        "NOAA Northwest Fisheries Science Center",
        "United States Government work",
    ),
    "us_coastline_path": ("United States Census Bureau", "United States public domain"),
    "tz_file_path": ("MarineRegions.org", "CC BY 4.0"),
    "us_waters_path": ("NOAA Office of Coast Survey", "United States Government work"),
}


# Get US Waters
def get_us_water_shapes(us_waters, us_coastline):
    # 1. Full Pacific Borders
    us_waters_pacific_border = build_us_waters_boundary(us_waters)

    # 2. US - Pacific Border (Contiguous)
    us_waters_pacific_border_contiguous = get_us_waters(us_waters_pacific_border, "CONTIGUOUS")

    # 3. US - Simplify Geometry and Clean Border
    us_waters_pacific_border_contiguous = clean_connect_lines_fast(
        us_waters_pacific_border_contiguous
    )

    # 4. US - Pacific Border (Alaska)
    us_waters_pacific_border_alaska = get_us_waters(us_waters_pacific_border, "ALASKA")

    # 5. US - Simplify Geometry and Clean Border
    us_waters_pacific_border_alaska = clean_connect_lines_fast(us_waters_pacific_border_alaska)

    # 6.  Full Pacific Coastline
    us_coastline_pacific = build_us_coastline(us_coastline)

    return (
        us_coastline_pacific,
        us_waters_pacific_border_contiguous,
        us_waters_pacific_border_alaska,
    )


# Get US Contiguous Waters
def get_us_contiguous(
    us_coastline_pacific, us_waters_pacific_border_contiguous, wsdot_shorelines, ws_marine_shoreline
):
    ## US - Pacific Border (Contiguous)
    us_coastline_pacific_contiguous = get_us_waters(us_coastline_pacific, "CONTIGUOUS")

    ## US -  Simplify Geometry and Smooth (Contiguous)
    us_coastline_pacific_contiguous = get_smoothed_coastline(us_coastline_pacific_contiguous)

    # Get Territorial Waters Polygon - Get Coast Line
    us_coastline_pacific_contiguous = us_coastline_pacific_contiguous.explode()
    us_coastline_pacific_contiguous_cs = us_coastline_pacific_contiguous[
        us_coastline_pacific_contiguous["length"] == us_coastline_pacific_contiguous["length"].max()
    ]

    # Get Island Polygons from Coastlines
    us_coastline_pacific_contiguous_is = us_coastline_pacific_contiguous[
        us_coastline_pacific_contiguous["length"] < us_coastline_pacific_contiguous["length"].max()
    ]
    us_coastline_pacific_contiguous_is = find_closed_lines(us_coastline_pacific_contiguous_is)

    us_coastline_pacific_contiguous_is = linestrings_to_polygons_if_closed(
        us_coastline_pacific_contiguous_is
    )

    us_waters_continguous = pd.concat(
        [us_coastline_pacific_contiguous_cs, us_waters_pacific_border_contiguous]
    )
    us_waters_continguous = us_waters_continguous.dissolve()
    us_waters_continguous = us_waters_continguous.explode()

    us_waters_continguous = get_smoothed_coastline(us_waters_continguous, tolerance=1)
    us_waters_continguous = us_waters_continguous[
        us_waters_continguous["length"] != us_waters_continguous["length"].min()
    ]
    us_waters_continguous = connect_lines_to_polygon(
        us_waters_continguous.iloc[0].geometry,
        us_waters_continguous.iloc[1].geometry,
        tolerance=1e-9,
    )
    us_waters_continguous = gpd.GeoDataFrame(
        geometry=[us_waters_continguous], crs=us_coastline_pacific_contiguous_cs.crs
    )

    # Clip Out Islands
    islands_union = unary_union(us_coastline_pacific_contiguous_is.geometry)
    us_waters_continguous["geometry"] = us_waters_continguous.geometry.difference(islands_union)

    # Get Bounds of Contiguous US to Fill In Areas
    us_waters_continguous_exterior = us_waters_continguous.explode()
    us_waters_continguous_exterior = us_waters_continguous_exterior["geometry"].apply(
        lambda x: Polygon(x.exterior)
    )

    wsdot_shorelines_add = wsdot_shorelines.clip(us_waters_continguous_exterior)

    # Bounding box for Point Edwards
    point_edwards = box(-123.0950, 48.90, -123.00, 49.0021)
    point_edwards = gpd.GeoDataFrame(
        {"name": ["Point Roberts"]}, geometry=[point_edwards], crs="EPSG:4326"
    )
    point_edwards_water = wsdot_shorelines.clip(point_edwards)
    point_edwards = point_edwards.difference(point_edwards_water).reset_index()
    us_waters_continguous = us_waters_continguous.difference(point_edwards).reset_index()
    us_waters_continguous.columns = ["", "geometry"]
    us_waters_continguous = us_waters_continguous[["geometry"]]

    # Bounding box for Sequim
    sequim_bbox = box(-123.20, 47.53, -122.00, 48.15)
    sequim_bbox = gpd.GeoDataFrame(geometry=[sequim_bbox], crs="EPSG:4326")
    sequim_bbox = wsdot_shorelines.clip(sequim_bbox)

    # Bounding box for Puget
    puget_bbox = box(-123.90, 46.50, -120.60, 48.0)
    puget_bbox = gpd.GeoDataFrame(geometry=[puget_bbox], crs="EPSG:4326")
    puget_bbox = wsdot_shorelines.clip(puget_bbox)

    # Bounding box for Deception Pass
    everett_bbox = box(-122.90, 47.9000, -120.1000, 49.000)
    everett_bbox = gpd.GeoDataFrame(geometry=[everett_bbox], crs="EPSG:4326")
    everett_bbox = wsdot_shorelines.clip(everett_bbox)

    # Add WSDOT Corrections
    us_waters_continguous = pd.concat(
        [us_waters_continguous, wsdot_shorelines_add, puget_bbox, sequim_bbox, everett_bbox]
    )
    us_waters_continguous = gpd.GeoDataFrame(
        us_waters_continguous, geometry="geometry", crs="EPSG:4326"
    )
    us_waters_continguous = us_waters_continguous.dissolve()

    islands_puget_bbox = box(-122.80, 48.3000, -120.1000, 48.750)
    islands_puget_bbox = gpd.GeoDataFrame(geometry=[islands_puget_bbox], crs="EPSG:4326")
    islands_puget_bbox = wsdot_shorelines.clip(islands_puget_bbox)

    ws_marine_shoreline = ws_marine_shoreline.clip(islands_puget_bbox)
    ws_marine_shoreline = ws_marine_shoreline.dissolve().explode()
    ws_marine_shoreline = get_smoothed_coastline(ws_marine_shoreline, tolerance=2)
    ws_marine_shoreline = linestrings_to_polygons_if_closed(ws_marine_shoreline)
    ws_marine_shoreline = ws_marine_shoreline[ws_marine_shoreline.geometry.type == "Polygon"]
    ws_marine_shoreline = ws_marine_shoreline.dissolve()

    us_waters_continguous["geometry"] = us_waters_continguous.difference(ws_marine_shoreline)
    us_waters_continguous["NAME"] = "UNITED_STATES"
    us_waters_continguous["AREA"] = "CONTIGUOUS"
    us_waters_continguous["TYPE"] = "TERRITORIAL"

    return us_waters_continguous


def get_alaska_waters(
    us_coastline_pacific,
    us_waters_pacific_border_alaska,
    *,
    boundary_snap_tolerance_m: float = 75_000.0,
):
    ## US - Pacific Border (Alaska)
    us_coastline_pacific_alaska = get_us_waters(us_coastline_pacific, "ALASKA")

    ## US -  Simplify Geometry and Smooth (Alaska)
    us_coastline_pacific_alaska = get_smoothed_coastline(us_coastline_pacific_alaska)

    # Get Territorial Waters Polygon - Get Coast Line
    us_coastline_pacific_alaska = us_coastline_pacific_alaska.explode()
    us_coastline_pacific_alaska_cs = us_coastline_pacific_alaska[
        us_coastline_pacific_alaska["length"] == us_coastline_pacific_alaska["length"].max()
    ]

    # Get Island Polygons from Coastlines
    us_coastline_pacific_alaska_is = us_coastline_pacific_alaska[
        us_coastline_pacific_alaska["length"] < us_coastline_pacific_alaska["length"].max()
    ]
    us_coastline_pacific_alaska_is = find_closed_lines(us_coastline_pacific_alaska_is)
    us_coastline_pacific_alaska_is = linestrings_to_polygons_if_closed(
        us_coastline_pacific_alaska_is
    )

    min_lon = -180.0  # Wrapping antimeridian west of Alaska
    max_lon = -130.0  # East border of Alaska / Yukon
    min_lat = 65.5
    max_lat = 72.0

    # Make the box
    beringia_box = box(min_lon, min_lat, max_lon, max_lat)
    beringia_gdf = gpd.GeoDataFrame(
        {"name": ["Beringia + Alaska to Canada"]}, geometry=[beringia_box], crs="EPSG:4326"
    )

    # Filter to Southern Alaska
    us_waters_pacific_border_alaska = us_waters_pacific_border_alaska.dissolve()
    us_waters_pacific_border_alaska["geometry"] = us_waters_pacific_border_alaska.difference(
        beringia_gdf.geometry
    )

    us_waters_alaska = pd.concat([us_coastline_pacific_alaska_cs, us_waters_pacific_border_alaska])
    us_waters_alaska = us_waters_alaska.dissolve()
    us_waters_alaska = us_waters_alaska.explode()

    us_waters_alaska = get_smoothed_coastline(us_waters_alaska, tolerance=5)
    us_waters_alaska = us_waters_alaska[
        us_waters_alaska["length"] != us_waters_alaska["length"].min()
    ]

    alaska_poly = polygonize_boundary_cycle(
        us_waters_alaska,
        snap_tolerance_m=boundary_snap_tolerance_m,
    )
    us_waters_alaska = gpd.GeoDataFrame(geometry=[alaska_poly], crs="EPSG:4326")

    # Add Back in Islands
    us_coastline_pacific_alaska_is = us_coastline_pacific_alaska_is[["geometry"]].dissolve()
    us_coastline_pacific_alaska_is["geometry"] = us_coastline_pacific_alaska_is.buffer(0)

    us_waters_alaska_ = us_waters_alaska.copy()
    us_waters_alaska_["geometry"] = us_waters_alaska_.buffer(0)

    us_coastline_pacific_alaska_is_outside = gpd.overlay(
        us_coastline_pacific_alaska_is, us_waters_alaska_, how="difference"
    )

    us_waters_alaska_["geometry"] = us_waters_alaska_.dissolve().difference(
        us_coastline_pacific_alaska_is.dissolve()
    )

    us_waters_alaska_ = pd.concat([us_waters_alaska_, us_coastline_pacific_alaska_is_outside])
    us_waters_alaska = gpd.GeoDataFrame(us_waters_alaska_, geometry="geometry", crs="EPSG:4326")
    us_waters_alaska = us_waters_alaska.dissolve()
    us_waters_alaska = us_waters_alaska[["geometry"]]
    us_waters_alaska["NAME"] = "UNITED_STATES"
    us_waters_alaska["AREA"] = "CONTIGUOUS"
    us_waters_alaska["TYPE"] = "TERRITORIAL"

    us_waters_alaska = us_waters_alaska.dropna()

    return us_waters_alaska


def get_ca_waters(ca_waters, tz_canada):
    ca_waters = ca_waters[ca_waters.OCEAN_E == "Pacific"]
    ca_waters = ca_waters.to_crs("EPSG:4326")

    tz_canada = tz_canada[tz_canada.SOVEREIGN1 == "Canada"]
    tz_canada = tz_canada.to_crs("EPSG:4326")

    # British Columbia full bounding box
    minx, miny = -140.30, 40.25
    maxx, maxy = -122.00, 60.50

    bc_bbox = box(minx, miny, maxx, maxy)
    bc_bbox = gpd.GeoDataFrame({"name": ["British Columbia"]}, geometry=[bc_bbox], crs="EPSG:4326")

    tz_new = tz_canada.explode(index_parts=False).to_crs("EPSG:3347")
    tz_new["geometry"] = tz_new.buffer(1000.0)
    tz_new = tz_new.to_crs("EPSG:4326").clip(bc_bbox)

    # British Columbia full bounding box
    minx, miny = -133.25, 54.4
    maxx, maxy = -132.85, 54.6

    bc_tt_bbox_add = box(minx, miny, maxx, maxy)
    bc_tt_bbox_add = gpd.GeoDataFrame(
        {"name": ["British Columbia"]}, geometry=[bc_tt_bbox_add], crs="EPSG:4326"
    )

    tz_new = pd.concat([bc_tt_bbox_add, tz_new])
    tz_new = tz_new.dissolve()

    bc_ca = ca_waters.dissolve()
    bc_ca["geometry"] = bc_ca.difference(tz_new.dissolve())
    bc_ca = bc_ca.explode(index_parts=False).reset_index(drop=True)
    projected_areas = bc_ca.to_crs("EPSG:3347").geometry.area
    bc_ca = bc_ca.loc[bc_ca.index != projected_areas.idxmax()]
    bc_ca = bc_ca.dissolve()

    bc_waters = pd.concat([bc_ca, tz_new])
    bc_waters = bc_waters.dissolve()
    bc_waters = bc_waters[["geometry"]]

    bc_waters["NAME"] = "CANADA"
    bc_waters["AREA"] = "BRITISH_COLUMBIA"
    bc_waters["TYPE"] = "TERRITORIAL"

    return bc_waters


def finalize_water_polygons(us_waters_continguous, us_waters_alaska, bc_waters):
    # Post Process Waters
    us_waters_alaska = gpd.overlay(us_waters_alaska, bc_waters, how="difference")
    bc_waters = gpd.overlay(bc_waters, us_waters_continguous, how="difference")

    us_waters_continguous = us_waters_continguous[["NAME", "AREA", "TYPE", "geometry"]]
    us_waters_alaska = us_waters_alaska[["NAME", "AREA", "TYPE", "geometry"]]
    us_waters_alaska = us_waters_alaska.dissolve()
    us_waters_alaska["AREA"] = "ALASKA"
    bc_waters = bc_waters[["NAME", "AREA", "TYPE", "geometry"]]

    all_waters = pd.concat([bc_waters, us_waters_alaska, us_waters_continguous])

    return all_waters


def _clip_to_bbox(gdf: gpd.GeoDataFrame, bbox: dict[str, float]) -> gpd.GeoDataFrame:
    bounds = box(bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"])
    bbox_gdf = gpd.GeoDataFrame(geometry=[bounds], crs="EPSG:4326")
    return gpd.clip(gdf.to_crs("EPSG:4326"), bbox_gdf)


def collect_all_waters(
    config_dict: dict[str, Any],
    *,
    data_paths: Mapping[str, str | Path] | None = None,
) -> Path:
    """Build and save the territorial-water geometry from resolved source paths."""

    ####################################################

    # 1. Resolve source paths
    if data_paths is None:
        data_paths = resolve_water_geometry_paths(config_dict)

    # 2. Open Data
    us_waters, us_coastline, wsdot_shorelines, ws_marine_shoreline, ca_waters, tz_canada = (
        open_water_geometry_sources(data_paths)
    )

    ####################################################

    # 3. Get US Waters
    us_coastline_pacific, us_waters_pacific_border_contiguous, us_waters_pacific_border_alaska = (
        get_us_water_shapes(us_waters, us_coastline)
    )

    # 4. Get Alaskan Waters
    us_waters_alaska = get_alaska_waters(
        us_coastline_pacific,
        us_waters_pacific_border_alaska,
        boundary_snap_tolerance_m=config_dict["alaska_boundary_snap_tolerance_m"],
    )

    # 5. US Contiguous Waters
    us_waters_continguous = get_us_contiguous(
        us_coastline_pacific,
        us_waters_pacific_border_contiguous,
        wsdot_shorelines,
        ws_marine_shoreline,
    )

    # 6. Canadian Waters Territorial
    bc_waters = get_ca_waters(ca_waters, tz_canada)

    ####################################################

    # All Waters
    all_waters = finalize_water_polygons(us_waters_continguous, us_waters_alaska, bc_waters)
    all_waters = _clip_to_bbox(all_waters, config_dict["bbox"])

    # m = all_waters[all_waters.AREA == "ALASKA"].explore(color="#20ABAD", tiles="CartoDB positron")
    # all_waters[all_waters.AREA == "BRITISH_COLUMBIA"].explore(m=m, color="#8367C7")
    # all_waters[all_waters.AREA == "CONTIGUOUS"].explore(m=m, color="#DB5461")

    # Save them out
    output_path = Path(config_dict["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_waters.to_parquet(output_path)
    return output_path


def build_water_geometry(
    config_path: str | Path = "config/data/project.yaml",
    *,
    overwrite_downloads: bool = False,
    skip_download: bool = False,
    manifest_only: bool = False,
) -> Path:
    """Validate inputs and build the canonical water geometry."""

    config_path = resolve_config_path(config_path)
    config = load_water_geometry_config(config_path)
    if skip_download:
        data_paths = resolve_water_geometry_paths(config)
        missing = [
            f"{name}: {path}" for name, path in data_paths.items() if not Path(path).exists()
        ]
        if missing:
            raise FileNotFoundError(
                "Missing water-geometry sources while downloads are disabled:\n  - "
                + "\n  - ".join(missing)
            )
    else:
        data_paths = download_water_geometry_sources(
            config_path,
            overwrite=overwrite_downloads,
        )
    output_path = Path(config["output_path"])
    if manifest_only and not output_path.exists():
        raise FileNotFoundError(
            f"Cannot refresh the water-geometry manifest; artifact is missing: {output_path}"
        )
    with TransactionalSeascapePublisher(output_path.parent) as publisher:
        staged_output = publisher.stage_path(output_path)
        if manifest_only:
            staged_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output_path, staged_output)
        else:
            staged_config = {**config, "output_path": staged_output}
            collect_all_waters(staged_config, data_paths=data_paths)
        artifact = capture_staged_parquet_artifact(publisher, output_path)
        sources = []
        for name in sorted(CONSUMED_WATER_GEOMETRY_SOURCE_NAMES):
            value = data_paths[name]
            source_path = Path(value)
            attribution, license_name = SOURCE_ATTRIBUTION.get(
                name,
                (name, "See source distribution metadata"),
            )
            sources.append(
                {
                    "name": name,
                    "path": str(source_path),
                    "checksum": checksum_path(source_path),
                    "attribution": attribution,
                    "license": license_name,
                }
            )
        manifest = build_manifest(
            dataset_family="environment.seascape.territorial_water_geometry",
            run_id=publisher.run_id,
            resolved_config=config,
            artifacts=[artifact],
            project_root=project_root(),
            sources=sources,
            upstream_artifacts=[],
            attribution=[
                {
                    "text": attribution,
                    "license": license_name,
                }
                for attribution, license_name in SOURCE_ATTRIBUTION.values()
            ],
            source_completeness="complete",
            metadata={
                "distance_crs": "EPSG:3338",
                "alaska_boundary_snap_tolerance_m": config["alaska_boundary_snap_tolerance_m"],
                "consumed_source_names": sorted(CONSUMED_WATER_GEOMETRY_SOURCE_NAMES),
            },
        )
        publisher.stage_manifest(output_path.parent / "water_geometry_manifest.json", manifest)
        publisher.publish()
    return output_path


#                                                                   #
# ----------------------------------------------------------------- #

__all__ = ["build_water_geometry", "collect_all_waters"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build territorial water polygons (US + BC) and save to processed GIS directory."
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/data/project.yaml",
        help=(
            "Path to Seascape Toolkit data_config.yaml. "
            "Defaults to 'config/data/project.yaml' when run from the repo root."
        ),
    )
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Refresh lineage for the existing artifact without rebuilding its geometry.",
    )
    args = parser.parse_args()

    build_water_geometry(
        config_path=args.config,
        skip_download=args.skip_download,
        manifest_only=args.manifest_only,
    )
