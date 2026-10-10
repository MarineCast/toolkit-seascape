"""Explicit native raster and retained full-compute-graph orchestration."""

from collections import defaultdict
from dataclasses import replace

import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
import shapely
from pyproj import Transformer

from .configuration import configuration
from .contract import RegionalError
from .geometry import inventory


def _certificate_binding(job, certificate, dependencies):
    """Refuse source/halo flags certified for a different compute/source graph."""
    expected = {name: job.inputs[name].sha256 for name in dependencies}
    supplied = job.inputs[certificate].qualification.get("certificate_input_sha256")
    if supplied != expected:
        raise RegionalError(
            "Source/halo certificate binding must exactly match pinned "
            + ", ".join(dependencies)
        )


def _raster(job):
    from seascape.seafloor_physiography.geomorphometry.build import (
        validate_native_raster_header,
    )

    path = job.source("raster")
    with rasterio.open(path) as source:
        validate_native_raster_header(source)
        if source.width * source.height > job.settings.get(
            "max_raster_pixels", 10_000_000
        ):
            raise RegionalError("Native raster pixel budget exceeded before allocation")
    return path


def bathymetry(job):
    from seascape.seafloor_physiography.bathymetry.build import _aggregate_raster

    path = _raster(job)
    keys = job.keys()
    compute = job.source("compute").read_text().splitlines()
    if (
        compute != sorted(set(compute))
        or not set(keys) <= set(compute)
        or any(
            not h3.is_valid_cell(k) or h3.get_resolution(k) != job.resolution
            for k in compute
        )
    ):
        raise RegionalError(
            "Explicit native compute support must contain every reporting cell"
        )
    from seascape.seafloor_physiography.bathymetry.build import (
        _latlngs_to_h3,
        _local_depth_anomaly,
        _pixel_centers,
    )

    empty = pd.DataFrame(
        columns=[
            "SOURCE_H3_INDEX",
            "TARGET_H3_INDEX",
            "MINIMUM_HOP_COUNT",
            "NETWORK_DISTANCE_M",
        ]
    )
    output = _aggregate_raster(
        path,
        compute,
        job.resolution,
        "positive_down",
        (0.1, 0.25, 0.75, 0.9),
        2,
        (6.1, 50.0, 100.0, 200.0),
        "EPSG:32610",
        empty,
    ).set_index("H3_INDEX", verify_integrity=True)
    # Stream graph source batches while retaining every native compute depth.
    previous = None
    seen = set()
    for batch in pq.ParquetFile(job.source("neighborhoods")).iter_batches(
        batch_size=job.limits["batch_rows"], use_threads=False
    ):
        frame = batch.to_pandas()
        if previous is not None:
            frame = pd.concat([previous, frame], ignore_index=True)
        if frame.empty:
            continue
        if not set(frame.SOURCE_H3_INDEX) <= set(compute) or not set(
            frame.TARGET_H3_INDEX
        ) <= set(compute):
            raise RegionalError(
                "Neighborhood endpoints outside full compute depth support"
            )
        tail = frame.SOURCE_H3_INDEX.iloc[-1]
        ready = frame[frame.SOURCE_H3_INDEX != tail]
        previous = frame[frame.SOURCE_H3_INDEX == tail]
        if len(previous) > 10000:
            raise RegionalError(
                "Native two-hop source neighborhood exceeds bounded batch"
            )
        if not ready.empty:
            sources = ready.SOURCE_H3_INDEX.unique().tolist()
            if seen.intersection(sources):
                raise RegionalError(
                    "Neighborhood sources must be contiguous and unique"
                )
            seen.update(sources)
            local = sorted(set(ready.SOURCE_H3_INDEX) | set(ready.TARGET_H3_INDEX))
            values = _local_depth_anomaly(
                local, output.loc[local, "BATHYMETRY"], 2, ready
            )
            lookup = dict(zip(local, values, strict=True))
            output.loc[sources, "BATHYMETRY_LOCAL_ANOMALY"] = [
                lookup[k] for k in sources
            ]
        job.guard()
    if previous is not None and not previous.empty:
        sources = previous.SOURCE_H3_INDEX.unique().tolist()
        if seen.intersection(sources):
            raise RegionalError("Neighborhood source repeated")
        seen.update(sources)
        local = sorted(set(previous.SOURCE_H3_INDEX) | set(previous.TARGET_H3_INDEX))
        lookup = dict(
            zip(
                local,
                _local_depth_anomaly(
                    local, output.loc[local, "BATHYMETRY"], 2, previous
                ),
                strict=True,
            )
        )
        output.loc[sources, "BATHYMETRY_LOCAL_ANOMALY"] = [lookup[k] for k in sources]
    if not set(keys) <= seen:
        raise RegionalError("Reporting sources missing neighborhood coverage")
    positions = {cell: i for i, cell in enumerate(compute)}
    counters = {
        name: np.zeros(len(compute), dtype=np.int64)
        for name in (
            "NATIVE_EXPECTED_PIXEL_COUNT",
            "NATIVE_VALID_MARINE_SAMPLE_COUNT",
            "NATIVE_NONNEGATIVE_ELEVATION_PIXEL_COUNT",
            "NATIVE_ZERO_ELEVATION_PIXEL_COUNT",
            "NATIVE_NODATA_PIXEL_COUNT",
        )
    }
    with rasterio.open(path) as raster:
        extent = shapely.box(*raster.bounds)
        for first in range(0, raster.height, 64):
            window = rasterio.windows.Window(
                0, first, raster.width, min(64, raster.height - first)
            )
            raw = raster.read(1, window=window, masked=True)
            lat, lon = _pixel_centers(raster.window_transform(window), raw.shape)
            selected = _latlngs_to_h3(lat.ravel(), lon.ravel(), job.resolution)
            indexes = np.fromiter(
                (positions.get(cell, -1) for cell in selected), dtype=np.int64
            )
            keep = indexes >= 0
            indexes = indexes[keep]
            values = raw.data.ravel()[keep]
            valid = ~np.ma.getmaskarray(raw).ravel()[keep] & np.isfinite(values)
            for name, condition in [
                ("NATIVE_EXPECTED_PIXEL_COUNT", np.ones(len(values), dtype=bool)),
                ("NATIVE_VALID_MARINE_SAMPLE_COUNT", valid & (values < 0)),
                ("NATIVE_NONNEGATIVE_ELEVATION_PIXEL_COUNT", valid & (values >= 0)),
                ("NATIVE_ZERO_ELEVATION_PIXEL_COUNT", valid & (values == 0)),
                ("NATIVE_NODATA_PIXEL_COUNT", ~valid),
            ]:
                np.add.at(counters[name], indexes[condition], 1)
            job.guard()
    for name, values in counters.items():
        output[name] = values
    output["NATIVE_FULL_H3_SOURCE_COVERAGE"] = [
        extent.covers(
            shapely.Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(cell)])
        )
        for cell in compute
    ]
    pq.write_table(
        pa.Table.from_pandas(output.reset_index(), preserve_index=False),
        job.output / "compute-depth.parquet",
        compression="zstd",
    )
    report = output.loc[keys].reset_index()
    report["H3_RESOLUTION"] = job.resolution
    report["SOURCE_COVERAGE_STATUS"] = job.inputs["raster"].qualification[
        "coverage_status"
    ]
    pq.write_table(
        pa.Table.from_pandas(report, preserve_index=False),
        job.output / "metrics.parquet",
        compression="zstd",
    )
    return "full_h3_native_gebco_pixel_centers_positive_down_v2", {
        "rows": len(keys),
        "compute_rows": len(compute),
        "context_qualification": job.inputs["neighborhoods"].qualification,
        "no_vertical_transform": True,
    }


def distance(job):
    from seascape.coastal_configuration.shoreline_proximity.build import (
        _shoreline_distances,
    )
    from seascape.seafloor_physiography.bathymetry.build import (
        _distance_to_isobaths,
        _pixel_centers,
    )

    keys = job.keys()
    with rasterio.open(_raster(job)) as source:
        elevation = source.read(1, masked=True).astype(float).filled(np.nan)
        latitude, longitude = _pixel_centers(source.transform, elevation.shape)
    marine = np.isfinite(elevation) & (elevation < 0)
    output = _distance_to_isobaths(
        keys,
        np.where(marine, -elevation, np.nan),
        marine,
        latitude,
        longitude,
        (6.1, 50.0, 100.0, 200.0),
        "EPSG:32610",
    )
    if "land_water" in job.inputs:
        import geopandas as gpd

        from .shoreline_parts import mapped_shoreline_parts

        geometry = job.source("land_water")
        land = gpd.read_file(geometry, layer="land_area")
        water = gpd.read_file(geometry, layer="water_area")
        extent = shapely.union_all(
            inventory(job, "extent").to_crs(4326).geometry.to_numpy()
        )
        parts, shore_qualification = mapped_shoreline_parts(
            land, water, extent, job.guard
        )
        shore = shapely.MultiLineString(parts)
    else:
        native_shore = inventory(job, "shoreline").to_crs(4326)
        if not native_shore.geometry.geom_type.isin(
            ["LineString", "MultiLineString"]
        ).all():
            raise RegionalError("Qualified seam-aware mapped shoreline lines required")
        shore = shapely.union_all(native_shore.geometry.to_numpy())
        extent = shapely.union_all(
            inventory(job, "extent").to_crs(4326).geometry.to_numpy()
        )
        shore_qualification = job.inputs["shoreline"].qualification
    locations = np.asarray([h3.cell_to_latlng(key) for key in keys])
    xx, yy = Transformer.from_crs(4326, 32610, always_xy=True).transform(
        locations[:, 1], locations[:, 0]
    )
    output = pd.DataFrame({"H3_INDEX": keys, **output})
    output["MAPPED_SHORELINE_DISTANCE_M"] = _shoreline_distances(
        shore, xx, yy, "EPSG:32610"
    )
    from pyproj import Proj

    transformer = Transformer.from_crs(4326, 32610, always_xy=True)
    targets = shapely.points(xx, yy)

    def context_bound(geometry):
        boundary = shapely.transform(
            shapely.segmentize(geometry.boundary, 0.005),
            transformer.transform,
            interleaved=False,
        )
        inside = shapely.covers(
            geometry, shapely.points(locations[:, 1], locations[:, 0])
        )
        return np.where(inside, shapely.distance(targets, boundary), 0.0), inside

    pixel_extent = shapely.box(
        float(longitude.min()),
        float(latitude.min()),
        float(longitude.max()),
        float(latitude.max()),
    )
    contour_bound, contour_inside = context_bound(pixel_extent)
    shore_bound, shore_inside = context_bound(extent)
    output["CONTOUR_CONTEXT_BOUNDARY_CLEARANCE_M"] = contour_bound
    output["CENTER_WITHIN_CONTOUR_NATIVE_PIXEL_CENTER_EXTENT"] = contour_inside
    output["SHORELINE_CONTEXT_BOUNDARY_CLEARANCE_M"] = shore_bound
    output["SHORELINE_CROP_CONTEXT_SUFFICIENT"] = shore_inside & (
        output.MAPPED_SHORELINE_DISTANCE_M + 1 < shore_bound
    )
    for level in (6.1, 50.0, 100.0, 200.0):
        token = (
            str(int(level))
            if float(level).is_integer()
            else str(level).replace(".", "_")
        )
        column = f"DISTANCE_TO_ISOBATH_{token}_M"
        output[f"ISOBATH_{token}_CROP_CONTEXT_SUFFICIENT"] = (
            np.isfinite(output[column])
            & contour_inside
            & (output[column] + 1 < contour_bound)
        )
    factors = Proj("EPSG:32610").get_factors(locations[:, 1], locations[:, 0])
    output["PROJECTION_LOCAL_MAX_RELATIVE_SCALE_DEPARTURE"] = np.maximum(
        np.abs(np.asarray(factors.meridional_scale) - 1),
        np.abs(np.asarray(factors.parallel_scale) - 1),
    )
    output["PROJECTION_OUTSIDE_AREA_OF_USE"] = (
        (locations[:, 1] < -126)
        | (locations[:, 1] > -120)
        | (locations[:, 0] < 0)
        | (locations[:, 0] > 84)
    )
    output["H3_RESOLUTION"] = job.resolution
    output["DISTANCE_SUPPORT"] = (
        "finite_native_contour_and_mapped_shoreline_extent_not_network"
    )
    pq.write_table(
        pa.Table.from_pandas(output, preserve_index=False),
        job.output / "metrics.parquet",
        compression="zstd",
    )
    return "native_marine_marching_squares_and_mapped_shoreline_euclidean_v1", {
        "rows": len(keys),
        "source_extent_qualification": job.inputs["raster"].qualification,
        "shoreline_selection": shore_qualification,
    }


def watergraph(job):
    from seascape.spatial_support.water_network.config import load_water_network_config
    from seascape.spatial_support.water_network.graph import (
        _assign_components,
        _build_connectors,
        _iter_edge_batches,
        _iter_neighborhood_batches,
    )
    from seascape.spatial_support.water_network.validation import (
        validate_connectors,
        validate_edges,
        validate_neighborhoods,
        validate_support,
    )

    from .water import LocalSourceWater

    keys = job.keys()
    compute = job.source("compute").read_text().splitlines()
    if (
        compute != sorted(set(compute))
        or not set(keys) <= set(compute)
        or any(h3.get_resolution(k) != job.resolution for k in compute)
    ):
        raise RegionalError("Explicit qualified compute registry required")
    extent = shapely.union_all(
        inventory(job, "extent").to_crs(4326).geometry.to_numpy()
    )
    with configuration(job) as config_path:
        base_config = load_water_network_config(config_path)
    config = replace(
        base_config,
        max_workers=1,
        edge_chunk_size=4096,
        maximum_neighborhood_hops=2,
        water_mask_version=job.domain["revision"],
        spatial_support_version=job.domain["revision"],
    )
    source = LocalSourceWater(job.source("water"), job.guard)
    frames = []
    for _, _, support in source.geometry_batches(
        compute, job.resolution, config, extent, 256
    ):
        frames.append(support)
        job.guard()
    if not frames:
        raise RegionalError("No positive mapped water support")
    support = (
        pd.concat(frames, ignore_index=True)
        .sort_values("H3_INDEX")
        .reset_index(drop=True)
    )
    if not support.H3_INDEX.is_unique or not set(keys) <= set(support.H3_INDEX):
        raise RegionalError("Graph cannot represent every reporting cell")
    edge_frames = list(
        _iter_edge_batches(
            support, None, job.resolution, config, path_metrics=source.path_metrics
        )
    )
    edges = pd.concat(edge_frames, ignore_index=True)
    _assign_components(support, edges)
    connectors = _build_connectors(
        support, None, job.resolution, config, path_metrics=source.path_metrics
    )
    validate_support(
        support,
        job.resolution,
        water_mask_version=config.water_mask_version,
        spatial_support_version=config.spatial_support_version,
        area_tolerance_m2=1,
    )
    validate_edges(edges, support, job.resolution)
    validate_connectors(connectors, support, job.resolution)
    for name, frame in [
        ("support", support),
        ("edges", edges),
        ("connectors", connectors),
    ]:
        pq.write_table(
            pa.Table.from_pandas(frame, preserve_index=False),
            job.output / f"{name}.parquet",
            compression="zstd",
        )
    _certificate_binding(
        job, "context", ("compute", "water", "extent", "config", "common")
    )
    certificates = (
        job.table("context").to_pandas().set_index("H3_INDEX", verify_integrity=True)
    )
    required = (
        "REGULAR_NEIGHBOR_CENSUS_COMPLETE",
        "INCOMING_CONNECTOR_CANDIDATE_CENSUS_COMPLETE",
        "OUTGOING_CONNECTOR_GLOBAL16_SEARCH_COMPLETE",
        "FULL_H3_WITHIN_SOURCE_RECTANGLE",
        "GENERALIZED_FALLBACK",
        "NATIVE_LAND_FOOTPRINT_UNKNOWN",
        "POLICY_EDGE_REVIEW",
    )
    if not set(support.H3_INDEX) <= set(certificates.index) or any(
        field not in certificates for field in required
    ):
        raise RegionalError("Independent compute-context certificates missing")
    for field in required:
        values = certificates.loc[support.H3_INDEX, field]
        if values.isna().any() or not all(
            isinstance(value, (bool, np.bool_)) for value in values
        ):
            raise RegionalError(
                "Source/halo certificate requires non-null boolean flags"
            )
        support[field] = values.to_numpy()
    depth = job.table("depth").to_pandas().set_index("H3_INDEX", verify_integrity=True)
    if not set(support.H3_INDEX) <= set(depth.index):
        raise RegionalError("Native depth misses graph compute nodes")
    pq.write_table(
        pa.Table.from_pandas(support, preserve_index=False),
        job.output / "qualified-support.parquet",
        compression="zstd",
    )
    from seascape.seafloor_physiography.bathymetry.build import _local_depth_anomaly

    source_index = {cell: i for i, cell in enumerate(support.H3_INDEX)}
    writer = None
    metric_writer = None
    count = 0
    try:
        for frame in _iter_neighborhood_batches(
            support,
            edges,
            connectors,
            job.resolution,
            config,
            source_cells=keys,
            batch_sources=128,
        ):
            validate_neighborhoods(
                frame,
                support,
                job.resolution,
                maximum_hops=2,
                source_cells=frame.SOURCE_H3_INDEX.unique().tolist(),
            )
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(
                    job.output / "neighborhoods.parquet",
                    table.schema,
                    compression="zstd",
                )
            writer.write_table(table)
            count += len(frame)
            local = sorted(set(frame.SOURCE_H3_INDEX) | set(frame.TARGET_H3_INDEX))
            lookup = dict(
                zip(
                    local,
                    _local_depth_anomaly(
                        local, depth.loc[local, "BATHYMETRY"], 2, frame
                    ),
                    strict=True,
                )
            )
            rows = []
            for cell, group in frame.groupby("SOURCE_H3_INDEX", sort=True):
                positions = np.array(
                    [source_index[key] for key in group.TARGET_H3_INDEX]
                )
                interior = positions[group.MINIMUM_HOP_COUNT.to_numpy() < 2]
                regular = bool(
                    support.REGULAR_NEIGHBOR_CENSUS_COMPLETE.iloc[interior].all()
                )
                incoming = bool(
                    support.INCOMING_CONNECTOR_CANDIDATE_CENSUS_COMPLETE.iloc[
                        interior
                    ].all()
                )
                outgoing = bool(
                    support.OUTGOING_CONNECTOR_GLOBAL16_SEARCH_COMPLETE.iloc[
                        positions
                    ].all()
                )
                extent_ok = bool(
                    support.FULL_H3_WITHIN_SOURCE_RECTANGLE.iloc[positions].all()
                )
                native_ok = bool(
                    depth.loc[
                        group.TARGET_H3_INDEX, "NATIVE_FULL_H3_SOURCE_COVERAGE"
                    ].all()
                ) and bool(
                    (
                        depth.loc[group.TARGET_H3_INDEX, "NATIVE_NODATA_PIXEL_COUNT"]
                        == 0
                    ).all()
                )
                complete = regular and incoming and outgoing and extent_ok and native_ok
                within = lookup[cell]
                status = (
                    "valid_source_relative_two_hop_anomaly"
                    if complete and np.isfinite(within)
                    else "context_incomplete_primary_anomaly_null"
                    if not complete
                    else "no_native_marine_focal_depth"
                    if pd.isna(depth.loc[cell, "BATHYMETRY"])
                    else "no_finite_native_marine_graph_neighbors"
                )
                rows.append(
                    {
                        "H3_INDEX": cell,
                        "H3_RESOLUTION": job.resolution,
                        "BATHYMETRY_LOCAL_ANOMALY": within if complete else np.nan,
                        "LOCAL_ANOMALY_STATUS": status,
                        "WITHIN_COMPUTE_GRAPH_ANOMALY_M": within,
                        "ANOMALY_COMPUTE_CONTEXT_COMPLETE": complete,
                        "REGULAR_NEIGHBOR_CLOSURE_COMPLETE": regular,
                        "INCOMING_CONNECTOR_CONTEXT_COMPLETE": incoming,
                        "OUTGOING_CONNECTOR_CONTEXT_COMPLETE": outgoing,
                        "SOURCE_RECTANGLE_CONTEXT_COMPLETE": extent_ok,
                        "NATIVE_DEPTH_CONTEXT_COMPLETE": native_ok,
                        "CONTEXT_GENERALIZED_FALLBACK": bool(
                            support.GENERALIZED_FALLBACK.iloc[positions].any()
                        ),
                        "CONTEXT_NATIVE_LAND_FOOTPRINT_UNKNOWN": bool(
                            support.NATIVE_LAND_FOOTPRINT_UNKNOWN.iloc[positions].any()
                        ),
                        "CONTEXT_POLICY_EDGE_REVIEW": bool(
                            support.POLICY_EDGE_REVIEW.iloc[positions].any()
                        ),
                    }
                )
            metrics = pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False)
            if metric_writer is None:
                metric_writer = pq.ParquetWriter(
                    job.output / "metrics.parquet", metrics.schema, compression="zstd"
                )
            metric_writer.write_table(metrics)
            job.guard()
    finally:
        if writer:
            writer.close()
        if metric_writer:
            metric_writer.close()
    return "native_mapped_water_full_compute_graph_v1", {
        "reporting_rows": len(keys),
        "compute_water_rows": len(support),
        "edges": len(edges),
        "connectors": len(connectors),
        "neighborhood_rows": count,
        "component_scope": "declared_compute_graph_not_global",
        "context_qualification": job.inputs["context"].qualification,
    }


def native_terrain(job):
    from seascape.seafloor_physiography.geomorphometry.build import (
        _derive_metrics,
        load_geomorphometry_config,
        output_columns,
    )

    from .native_slope import native_slope_batch

    if job.resolution != 8:
        raise RegionalError("Native terrain requires R8; R6 classifier unsupported")
    _certificate_binding(
        job, "support", ("compute", "edges", "connectors", "raster", "config", "common")
    )
    compute = job.source("compute").read_text().splitlines()
    if compute != sorted(set(compute)) or any(
        h3.get_resolution(k) != 8 for k in compute
    ):
        raise RegionalError("Explicit qualified native R8 compute registry required")
    raster = _raster(job)
    keys = job.keys()
    support = (
        job.table("support").to_pandas().set_index("H3_INDEX", verify_integrity=True)
    )
    depth = job.table("depth").to_pandas().set_index("H3_INDEX", verify_integrity=True)
    if not set(keys) <= set(support.index) or not set(support.index) <= set(
        depth.index
    ):
        raise RegionalError("Depth/support compute context does not cover reporting")
    if not set(support.index) <= set(compute) or not set(compute) <= set(depth.index):
        raise RegionalError("Certified compute registry and depth/support differ")
    records = support.to_dict("index")
    depths = depth.to_dict("index")
    required = [
        "REGULAR_NEIGHBOR_CENSUS_COMPLETE",
        "INCOMING_CONNECTOR_CANDIDATE_CENSUS_COMPLETE",
        "OUTGOING_CONNECTOR_GLOBAL16_SEARCH_COMPLETE",
        "FULL_H3_WITHIN_SOURCE_RECTANGLE",
        "GENERALIZED_FALLBACK",
        "NATIVE_LAND_FOOTPRINT_UNKNOWN",
        "POLICY_EDGE_REVIEW",
    ]
    if any(name not in support or support[name].isna().any() for name in required):
        raise RegionalError("Non-null source/halo qualification certificates required")
    adjacency = defaultdict(set)
    for name, source_column, pass_column in [
        ("edges", "SOURCE_H3_INDEX", "EDGE_IS_WATER_PASSABLE"),
        ("connectors", "H3_INDEX", "CONNECTOR_IS_WATER_PASSABLE"),
    ]:
        frame = job.table(name).to_pandas()
        for row in frame.loc[frame[pass_column].eq(True)].to_dict("records"):
            source, target = row[source_column], row["TARGET_H3_INDEX"]
            if source not in records or target not in records:
                raise RegionalError("Passable endpoint outside retained compute graph")
            adjacency[source].add(target)
            adjacency[target].add(source)
    with configuration(job) as config_path:
        config = load_geomorphometry_config(config_path)
    if (
        config.neighborhood_rings != (1, 2, 4)
        or config.neighbor_ring != 1
        or config.openness_radius_rings != 4
    ):
        raise RegionalError(
            "Native terrain requires reviewed one/two/four-hop and nested five-hop context"
        )
    requirements = {}
    for field in output_columns((1, 2, 4)):
        if field in (
            "H3_INDEX",
            "NATIVE_RASTER_RESOLUTION_ARC_SECONDS",
            "SLOPE_MEAN_NATIVE_RASTER",
            "SLOPE_Q90_NATIVE_RASTER",
        ):
            requirements[field] = 0
            continue
        hops = (
            4
            if field
            in (
                "POSITIVE_OPENNESS_DEG",
                "NEGATIVE_OPENNESS_DEG",
                "OPENNESS_SECTOR_COVERAGE",
                "RIDGE_INDEX",
                "VALLEY_INDEX",
            )
            else 1
        )
        if "_RING_" in field:
            hops = int(field.split("_RING_")[1].split("_")[0])
            if field.startswith(("SLOPE_", "ASPECT_", "VECTOR_RUGGEDNESS")):
                hops += 1
        requirements[field] = hops
    writers = {}

    def stream(name, frame):
        table = pa.Table.from_pandas(frame.reset_index(), preserve_index=False)
        for i, field in enumerate(table.schema):
            if (
                field.name.endswith("QC_REASON")
                or field.name == "SOURCE_OBSERVATION_PERIOD"
            ):
                table = table.set_column(
                    i, field.name, table.column(i).cast(pa.large_string())
                )
        if name not in writers:
            writers[name] = pq.ParquetWriter(
                job.output / name, table.schema, compression="zstd"
            )
        writers[name].write_table(table)

    try:
        for first in range(0, len(keys), min(256, job.limits["batch_rows"])):
            selected = keys[first : first + min(256, job.limits["batch_rows"])]
            paths = {}
            all_context = set()
            slope_sources = set()
            lookups = {1: {}, 2: {}, 4: {}}
            for source in selected:
                best = {source: 0}
                layer = {source}
                for hop in range(1, 6):
                    layer = (
                        set().union(*(adjacency[c] for c in layer)) - set(best)
                        if layer
                        else set()
                    )
                    best.update({c: hop for c in layer})
                paths[source] = best
                all_context.update(best)
                slope_sources.update(c for c, hop in best.items() if hop <= 4)
                for radius in (1, 2, 4):
                    lookups[radius][source] = tuple(
                        c
                        for c in sorted(best, key=lambda c: (best[c], c))
                        if 0 < best[c] <= radius
                    )
            for source in slope_sources:
                lookups[1][source] = tuple(sorted(adjacency[source]))
            context_frame = depth.loc[sorted(all_context)].reset_index()
            derived = (
                _derive_metrics(context_frame, config, lookups)
                .set_index("H3_INDEX")
                .loc[selected]
            )
            for column in derived:
                if column.endswith("QC_REASON"):
                    derived[column] = derived[column].astype("string")
            native = native_slope_batch(selected, depths, raster, job.guard)
            derived[["SLOPE_MEAN_NATIVE_RASTER", "SLOPE_Q90_NATIVE_RASTER"]] = native[
                ["SLOPE_MEAN_NATIVE_RASTER", "SLOPE_Q90_NATIVE_RASTER"]
            ]
            coverage = []
            for cell in selected:
                best = paths[cell]
                row = {
                    "H3_INDEX": cell,
                    "H3_RESOLUTION": 8,
                    "FOCAL_NATIVE_MARINE_DEPTH_PRESENT": bool(
                        np.isfinite(depths[cell]["BATHYMETRY"])
                    ),
                    "FOCAL_FINITE_ONE_HOP_NEIGHBOR_COUNT": sum(
                        bool(np.isfinite(depths[c]["BATHYMETRY"]))
                        for c, hop in best.items()
                        if hop == 1
                    ),
                }
                for radius in (1, 2, 3, 4, 5):
                    visited = [c for c, hop in best.items() if hop <= radius]
                    interior = [c for c, hop in best.items() if hop < radius]
                    row[f"CONTEXT_HOP{radius}_COMPLETE"] = all(
                        records[c]["REGULAR_NEIGHBOR_CENSUS_COMPLETE"]
                        and records[c]["INCOMING_CONNECTOR_CANDIDATE_CENSUS_COMPLETE"]
                        for c in interior
                    ) and all(
                        records[c]["OUTGOING_CONNECTOR_GLOBAL16_SEARCH_COMPLETE"]
                        and records[c]["FULL_H3_WITHIN_SOURCE_RECTANGLE"]
                        and depths[c]["NATIVE_FULL_H3_SOURCE_COVERAGE"]
                        and depths[c]["NATIVE_NODATA_PIXEL_COUNT"] == 0
                        for c in visited
                    )
                    row[f"CONTEXT_HOP{radius}_CELL_COUNT"] = len(visited)
                for flag in (
                    "GENERALIZED_FALLBACK",
                    "NATIVE_LAND_FOOTPRINT_UNKNOWN",
                    "POLICY_EDGE_REVIEW",
                ):
                    row["CONTEXT_" + flag] = any(records[c][flag] for c in best)
                row["SOURCE_OBSERVATION_PERIOD"] = None
                coverage.append(row)
            coverage = pd.DataFrame(coverage).set_index("H3_INDEX")
            primary = derived.copy()
            for column, radius in requirements.items():
                if radius:
                    primary.loc[~coverage[f"CONTEXT_HOP{radius}_COMPLETE"], column] = (
                        "context_incomplete_primary_metric_null"
                        if column.endswith("QC_REASON")
                        else np.nan
                    )
            stream("metrics.parquet", primary)
            stream("within-compute-diagnostics.parquet", derived)
            stream("stencil-coverage.parquet", native)
            stream("context.parquet", coverage)
            job.guard()
    finally:
        for writer in writers.values():
            writer.close()
    return "native_r8_terrain_full_compute_five_hop_context_gated_v3", {
        "rows": len(keys),
        "context_requirements": requirements,
        "R6_status": "unsupported_not_invented",
        "source_accuracy": "not_established_uniform_GEBCO_accuracy",
    }
