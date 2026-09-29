"""Small deterministic software fixture for SV-01..SV-06 (no regional inputs)."""

from __future__ import annotations

import json
import math
import time
import tracemalloc

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from seascape.biogenic_habitat.mosaic import (
    VectorProviderContract,
    build_mapped_mosaic,
    normalize_vector_provider,
)
from seascape.coastal_configuration.coast_complexity import summarize_coast
from seascape.coastal_configuration.gateways import (
    alternate_route_after_gateway_removal,
    gateway_relationships,
)
from seascape.coastal_configuration.nearshore_transitions import (
    bounded_deep_target_components,
    first_water_facing_contour,
    nearshore_depth_areas,
)
from seascape.coastal_configuration.passage_sections import measure_passage_section
from seascape.hydrologic_connectivity.fluvial_connectivity.multiple_outlets import (
    build_outlet_relationships,
)
from seascape.spatial_support.water_network.graph import WaterGraph


def main() -> int:
    started = time.perf_counter()
    tracemalloc.start()
    names = np.array(["a", "b", "c", "d", "e"])
    graph = WaterGraph(
        8,
        names,
        np.array([0, 2, 4, 6, 8, 8]),
        np.array([1, 2, 0, 3, 0, 3, 1, 2]),
        np.array([100, 300, 100, 100, 300, 300, 100, 300], dtype=float),
        pd.DataFrame(
            {"H3_INDEX": names, "WATER_COMPONENT_ID": ["main"] * 4 + ["island"]}
        ),
        {str(name): index for index, name in enumerate(names)},
        "fixture",
        "fixture",
    )
    cells = pd.DataFrame(
        {
            "H3_INDEX": names,
            "H3_RESOLUTION": [8] * 5,
            "GRAPH_H3_INDEX": names,
            "TARGET_CONNECTOR_DISTANCE_M": [0.0] * 5,
            "REPRESENTATIVE_X_M": [0, 100, 0, 200, 500],
            "REPRESENTATIVE_Y_M": [0, 0, 300, 0, 500],
        }
    )
    outlets = pd.DataFrame(
        {
            "OUTLET_ID": ["o1", "o2", "o3", "o4"],
            "SOURCE_ID": ["fixture"] * 4,
            "SOURCE_VERSION": ["v1"] * 4,
            "SOURCE_FEATURE_ID": ["1", "2", "3", "4"],
            "RIVER_BASIN_ID": ["b1", "b1", "b2", "b3"],
            "OUTLET_X_M": [0, 100, 0, 200],
            "OUTLET_Y_M": [0, 0, 300, 0],
            "GRAPH_H3_INDEX": ["a", "b", "c", "d"],
            "SOURCE_CONNECTOR_DISTANCE_M": [0.0] * 4,
            "SELECTION_PROVENANCE": ["fixture"] * 4,
            "MULTIPLE_MOUTH_GROUP_ID": [None] * 4,
        }
    )
    outlet_rows = build_outlet_relationships(cells, outlets, graph)
    gateway_attachments = pd.DataFrame(
        {
            "GATEWAY_ID": ["g1", "g2"],
            "GRAPH_H3_INDEX": ["b", "c"],
            "GATEWAY_CONNECTOR_DISTANCE_M": [0.0, 0.0],
        }
    )
    gateway_rows = gateway_relationships(cells, gateway_attachments, graph)
    alternate = alternate_route_after_gateway_removal(graph, "a", "d", [("b", "d")])
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=10,
            height=10,
            count=1,
            dtype="float32",
            crs="EPSG:32610",
            transform=from_origin(0, 100, 10, 10),
        ) as raster:
            raster.write(np.tile(np.arange(5, 105, 10, dtype="float32"), (10, 1)), 1)
            water = box(0, 0, 100, 100)
            coast = LineString([(0, 0), (0, 100)])
            nearshore = nearshore_depth_areas(
                water,
                water,
                coast,
                raster,
                depth_threshold_m=25,
                band_width_m=50,
            )
            deep_components, _deep_by_cell = bounded_deep_target_components(
                [("fixture", water)],
                water,
                coast,
                raster,
                depth_threshold_m=25,
                band_width_m=50,
                max_pixels=100,
            )
            transect = first_water_facing_contour(
                Point(0, 50),
                (0, 1),
                water,
                raster,
                depth_threshold_m=25,
                step_m=10,
                max_distance_m=100,
            )
    passage = measure_passage_section(
        "p1",
        box(-100, 0, 100, 500),
        LineString([(0, 0), (0, 500)]),
        box(-100, 0, 100, 500),
        lambda x, y: 50,
        along_axis_m=250,
        half_length_m=150,
        sample_step_m=20,
        depth_threshold_m=25,
        tangent_scale_m=50,
    )
    coast_summary = summarize_coast(
        [coast],
        water,
        water,
        {"island1": box(20, 20, 30, 30)},
        box(-100, -100, 200, 200).boundary,
        minimum_island_area_m2=10,
        normal_probe_m=1,
    )
    raw = gpd.GeoDataFrame(
        {
            "SOURCE_FEATURE_ID": ["e", "k"],
            "SOURCE_CLASS": ["E", "K"],
            "OBSERVATION_YEAR": [2025, 2025],
            "AVAILABLE_YEAR": [2025, 2025],
            "OBSERVATION_STATUS": ["present", "present"],
            "EVIDENCE_CLASS": ["direct_observation", "direct_observation"],
        },
        geometry=[box(0, 0, 5, 10), box(0, 0, 5, 10)],
        crs="EPSG:6933",
    )
    inventory = normalize_vector_provider(
        raw,
        VectorProviderContract(
            "fixture",
            "v1",
            "fixture only",
            "synthetic mapped polygons",
            {"E": "eelgrass", "K": "floating_kelp"},
        ),
    )
    support = gpd.GeoDataFrame(
        {"H3_INDEX": ["fixture"], "H3_RESOLUTION": [8], "SUPPORT_TYPE": ["marine"]},
        geometry=[box(0, 0, 10, 10)],
        crs="EPSG:6933",
    )
    mosaic = build_mapped_mosaic(support, inventory, as_of_year=2025)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {
        "status": "PASS",
        "fixture_only": True,
        "cells": len(cells),
        "outlets": len(outlets),
        "gateways": 2,
        "passages": 1,
        "raster_shape": [10, 10],
        "outlet_rows": len(outlet_rows),
        "gateway_rows": len(gateway_rows),
        "nearshore_deep_area_m2": nearshore.deep_area_m2,
        "deep_component_count": len(deep_components),
        "contour_width_m": transect.width_m,
        "passage_area_m2": passage.cross_section_area_m2,
        "alternate_route_m": alternate[
            "ALTERNATE_ROUTE_LENGTH_AFTER_GATEWAY_REMOVAL_M"
        ],
        "source_island_count": coast_summary.island_count,
        "mosaic_union_area_m2": float(
            mosaic.loc[
                mosaic.HABITAT_TYPE.eq("compatible_union"), "MAPPED_AREA_M2"
            ].iloc[0]
        ),
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "python_peak_tracemalloc_bytes": peak,
    }
    assert report["outlet_rows"] == 20
    assert report["gateway_rows"] == 10
    assert report["nearshore_deep_area_m2"] == 3000
    assert report["deep_component_count"] == 1
    assert report["contour_width_m"] == 20
    assert report["passage_area_m2"] == 10_000
    assert math.isclose(report["mosaic_union_area_m2"], 50, abs_tol=1e-5)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
