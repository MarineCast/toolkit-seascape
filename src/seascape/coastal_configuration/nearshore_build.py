"""Optional bounded nearshore transition candidate from canonical source inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from shapely.geometry import Point
from shapely.ops import unary_union

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.core.geo.h3 import cell_to_parent
from seascape.seafloor_physiography.bathymetry.pipeline import load_bathymetry_config
from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.spatial_support.water_network.graph import target_graph_mapping
from seascape.spatial_support.water_network.load import (
    load_water_graph,
    multi_source_shortest_paths,
)
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_family,
)

from .nearshore_transitions import first_water_facing_contour, nearshore_depth_areas
from .shoreline_characterization.build import load_shoreline_config


@dataclass(frozen=True)
class NearshoreConfig:
    shoreline_path: Path
    water_path: Path
    clipped_r8_path: Path
    depth_raster_path: Path
    output_dir: Path
    projected_crs: str
    threshold_m: float
    band_width_m: float
    station_spacing_m: float
    tangent_scale_m: float
    transect_step_m: float
    transect_max_m: float
    max_cells: int
    max_transects: int
    selected_h3_indices: tuple[str, ...]


def load_nearshore_config(config_path: str | Path) -> NearshoreConfig:
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("nearshore_transitions")
    if not isinstance(section, dict):
        raise ValueError("Configure nearshore_transitions before selecting its stage")
    shoreline = load_shoreline_config(config_path)
    network = load_water_network_config(config_path)
    bathymetry = load_bathymetry_config(config_path)
    values = {name: float(section[name]) for name in (
        "threshold_m", "band_width_m", "station_spacing_m", "tangent_scale_m",
        "transect_step_m", "transect_max_m",
    )}
    if values["threshold_m"] < 0 or any(value <= 0 for key, value in values.items() if key != "threshold_m"):
        raise ValueError("Nearshore analysis scales must be positive and threshold nonnegative")
    max_cells = int(section.get("max_cells", 200))
    max_transects = int(section.get("max_transects", 200))
    if min(max_cells, max_transects) < 1:
        raise ValueError("Nearshore resource bounds must be positive")
    selected = tuple(str(value) for value in section.get("selected_h3_indices", ()))
    if len(selected) != len(set(selected)):
        raise ValueError("Nearshore selected H3 IDs must be unique")
    output = project_root() / str(section.get(
        "output_dir",
        "data/processed/domain/environmental_layer/seascape/coastal_configuration/nearshore_transitions",
    ))
    if not output.resolve().is_relative_to(project_root().resolve()):
        raise ValueError("Nearshore output escapes workspace")
    return NearshoreConfig(
        shoreline.inventory_path,
        network.water_polygon_path,
        network.clipped_geometry_path(8),
        bathymetry.raw_path,
        output,
        shoreline.projected_crs,
        **values,
        max_cells=max_cells,
        max_transects=max_transects,
        selected_h3_indices=selected,
    )


def _deep_network_distance(
    table: pd.DataFrame, graph: object, *, resolution: int
) -> tuple[np.ndarray, list[str]]:
    cells = table.H3_INDEX.astype(str).tolist()
    positions, connectors, reasons = target_graph_mapping(graph, cells)
    deep = table.NEARSHORE_DEEP_WATER_AREA_M2.gt(0).fillna(False).to_numpy()
    seeds = [
        (str(graph.cells[int(position)]), float(connectors[index]), index)
        for index, position in enumerate(positions)
        if position >= 0 and deep[index]
    ]
    distances = np.full(len(cells), np.nan)
    qc = ["no_mapped_deep_target_in_bounded_support"] * len(cells)
    if seeds:
        routed, _owners = multi_source_shortest_paths(graph, seeds)
        for index, position in enumerate(positions):
            if position < 0:
                qc[index] = str(reasons[index] or "target_attachment_unavailable")
            elif np.isfinite(routed[int(position)]):
                distances[index] = 0.0 if deep[index] else routed[int(position)] + connectors[index]
                qc[index] = "mapped_deep_h3_target_graph_v1"
            else:
                qc[index] = "disconnected_within_available_graph"
    return distances, qc


def build_nearshore_transitions(config_path: str | Path) -> tuple[Path, ...]:
    config = load_nearshore_config(config_path)
    cells = gpd.read_parquet(config.clipped_r8_path)
    if config.selected_h3_indices:
        missing = set(config.selected_h3_indices) - set(cells.H3_INDEX.astype(str))
        if missing:
            raise KeyError(f"Selected H3 cells missing from R8 support: {sorted(missing)}")
        cells = cells.loc[cells.H3_INDEX.isin(config.selected_h3_indices)]
    if cells.empty or len(cells) > config.max_cells:
        raise ValueError(f"Nearshore cell count {len(cells)} exceeds configured bound {config.max_cells} or is empty")
    cells = cells.to_crs(config.projected_crs).sort_values("H3_INDEX").reset_index(drop=True)
    water = gpd.read_parquet(config.water_path).to_crs(config.projected_crs).geometry.union_all()
    shoreline = gpd.read_parquet(config.shoreline_path).to_crs(config.projected_crs)
    if shoreline.SEGMENT_ID.isna().any() or shoreline.SEGMENT_ID.duplicated().any():
        raise ValueError("Source shoreline segment IDs must be unique and nonnull")
    interest = unary_union(list(cells.geometry)).buffer(config.transect_max_m)
    shoreline = shoreline.loc[shoreline.geometry.intersects(interest)]
    summary_rows = []
    station_rows = []
    transect_rows = []
    with rasterio.open(config.depth_raster_path) as source:
        with WarpedVRT(source, crs=config.projected_crs, resampling=Resampling.nearest) as depth:
            supports = {8: cells}
            parent_rows = []
            for parent, child_rows in cells.assign(
                PARENT_H3_INDEX=cells.H3_INDEX.map(lambda value: cell_to_parent(str(value), 6))
            ).groupby("PARENT_H3_INDEX", sort=True):
                parent_rows.append({"H3_INDEX": parent, "geometry": unary_union(list(child_rows.geometry))})
            supports[6] = gpd.GeoDataFrame(parent_rows, geometry="geometry", crs=cells.crs)
            for resolution, frame in supports.items():
                for cell in frame.itertuples(index=False):
                    area = nearshore_depth_areas(
                        cell.geometry, water, shoreline.geometry.union_all(), depth,
                        depth_threshold_m=config.threshold_m,
                        band_width_m=config.band_width_m,
                        raster_depth_convention="negative_elevation",
                    )
                    summary_rows.append({
                        "H3_INDEX": str(cell.H3_INDEX),
                        "H3_RESOLUTION": resolution,
                        "DEPTH_THRESHOLD_M": config.threshold_m,
                        "NEARSHORE_BAND_WIDTH_M": config.band_width_m,
                        "NEARSHORE_ELIGIBLE_AREA_M2": area.eligible_area_m2,
                        "NEARSHORE_VALID_BATHYMETRY_AREA_M2": area.valid_area_m2,
                        "NEARSHORE_DEEP_WATER_AREA_M2": area.deep_area_m2,
                        "NEARSHORE_DEEP_WATER_FRAC_OF_VALID": area.deep_fraction_of_valid,
                        "NEARSHORE_BATHYMETRY_COVERAGE_FRAC": area.bathymetry_coverage_fraction,
                        "BATHYMETRY_STATUS": area.status,
                        "SPATIAL_SUPPORT": "water_clipped_r8" if resolution == 8 else "hierarchical_r8_child_union",
                    })
            for segment in shoreline.itertuples(index=False):
                line = segment.geometry
                if line.geom_type != "LineString" or line.length <= 0:
                    continue
                count = max(1, int(line.length // config.station_spacing_m))
                if len(station_rows) + count > config.max_transects:
                    raise ValueError("Nearshore transect budget exceeded")
                for index in range(count):
                    position = min(line.length, (index + 0.5) * config.station_spacing_m)
                    station = line.interpolate(position)
                    if not interest.covers(station):
                        continue
                    before = line.interpolate(max(0, position - config.tangent_scale_m / 2))
                    after = line.interpolate(min(line.length, position + config.tangent_scale_m / 2))
                    tangent = (after.x - before.x, after.y - before.y)
                    station_id = f"{segment.SEGMENT_ID}:{position:.3f}m"
                    crossing = first_water_facing_contour(
                        station, tangent, water, depth,
                        depth_threshold_m=config.threshold_m,
                        step_m=config.transect_step_m,
                        max_distance_m=config.transect_max_m,
                        raster_depth_convention="negative_elevation",
                    )
                    station_rows.append({
                        "STATION_ID": station_id, "SOURCE_SEGMENT_ID": segment.SEGMENT_ID,
                        "ALONG_SEGMENT_M": position, "TANGENT_X": tangent[0], "TANGENT_Y": tangent[1],
                        "geometry": station,
                    })
                    transect_rows.append({
                        "STATION_ID": station_id, "DEPTH_THRESHOLD_M": config.threshold_m,
                        "SHORE_TO_DEPTH_CONTOUR_WIDTH_M": crossing.width_m,
                        "CROSS_SHORE_DEPTH_GRADIENT": crossing.gradient_m_per_m,
                        "CROSSING_STATUS": crossing.status,
                        "SAMPLE_COUNT": len(crossing.samples),
                    })
    summary = pd.DataFrame(summary_rows)
    for resolution in (8, 6):
        index = summary.H3_RESOLUTION.eq(resolution)
        graph = load_water_graph(resolution, config_path)
        distances, qc = _deep_network_distance(summary.loc[index], graph, resolution=resolution)
        summary.loc[index, "DISTANCE_TO_CONNECTED_DEEP_WATER_M"] = distances
        summary.loc[index, "DEEP_WATER_NETWORK_QC"] = qc
    station_frame = gpd.GeoDataFrame(station_rows, geometry="geometry", crs=config.projected_crs)
    outputs: list[tuple[object, Path]] = [
        (station_frame, config.output_dir / "SHORELINE_STATIONS.parquet"),
        (pd.DataFrame(transect_rows), config.output_dir / "SHORELINE_TRANSECTS.parquet"),
        *(
            (summary.loc[summary.H3_RESOLUTION.eq(res)].reset_index(drop=True), config.output_dir / f"NEARSHORE_TRANSITIONS_RES_{res}.parquet")
            for res in (8, 6)
        ),
    ]
    publisher = stage_parquet_family(config.output_dir, outputs)
    manifest = build_manifest(
        dataset_family="environment.seascape.nearshore_transitions",
        run_id=publisher.run_id,
        resolved_config=asdict(config),
        artifacts=publisher.artifacts,
        project_root=project_root(),
        sources=[{"name": "Configured shoreline and positive-down bathymetry", "path": str(config.depth_raster_path), "checksum": checksum_artifact(config.depth_raster_path), "license": "See configured source manifests"}],
        upstream_artifacts=[{"path": str(path), "checksum": checksum_artifact(path)} for path in (config.shoreline_path, config.water_path, config.clipped_r8_path)],
        attribution=[], source_completeness="partial",
        metadata={"scientific_method_version": "nearshore_raster_footprint_v1", "sample_support": "nearest-neighbor virtual projected native raster; R6 union of selected R8 water-clipped supports; boundary censored for bounded selection"},
    )
    publisher.publish_manifest(config.output_dir / "nearshore_transitions_manifest.json", manifest)
    return tuple(path for _frame, path in outputs)
