from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from seascape.biogenic_habitat.mosaic import (
    VectorProviderContract,
    build_mapped_mosaic,
    normalize_vector_provider,
)
from seascape.biogenic_habitat.mosaic_build import _radius_area
from seascape.spatial_support.water_network.graph import WaterGraph


def _raw(rows):
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:6933")


def _contract():
    return VectorProviderContract(
        source_id="fixture", source_version="2026", rights="fixture only",
        mapping_method="synthetic polygon survey",
        class_crosswalk={"E": "eelgrass", "F": "floating_kelp", "M": "tidal_marsh"},
    )


def _row(feature, cls, geometry, status="present", year=2025, **extra):
    return {
        "SOURCE_FEATURE_ID": feature,
        "SOURCE_CLASS": cls,
        "geometry": geometry,
        "OBSERVATION_YEAR": year,
        "AVAILABLE_YEAR": year,
        "OBSERVATION_STATUS": status,
        "EVIDENCE_CLASS": "direct_observation",
        **extra,
    }


def test_overlap_union_survey_and_intertidal_support() -> None:
    raw = _raw([
        _row("eel", "E", box(0, 0, 5, 10), SURVEY_EVENT_ID="s1"),
        _row("kelp", "F", box(0, 0, 5, 10)),
        _row("survey", "E", box(0, 0, 10, 10), "surveyed",
             GEOMETRY_ROLE="survey_footprint", SURVEY_EVENT_ID="s1",
             SURVEY_COMPLETENESS="complete"),
        _row("marsh", "M", box(0, 10, 5, 20)),
    ])
    inventory = normalize_vector_provider(raw, _contract())
    assert set(inventory.RAW_CLASS) == {"E", "F", "M"}
    support = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell", "cell"], "H3_RESOLUTION": [8, 8],
         "SUPPORT_TYPE": ["marine", "intertidal"]},
        geometry=[box(0, 0, 10, 10), box(0, 10, 10, 20)], crs="EPSG:6933",
    )
    result = build_mapped_mosaic(support, inventory, as_of_year=2025)
    indexed = result.set_index(["SUPPORT_TYPE", "HABITAT_TYPE"])
    assert indexed.loc[("marine", "eelgrass"), "MAPPED_AREA_M2"] == pytest.approx(50)
    assert indexed.loc[("marine", "eelgrass"), "SURVEYED_AREA_M2"] == pytest.approx(100)
    assert pd.isna(indexed.loc[("marine", "floating_kelp"), "SURVEYED_AREA_M2"])
    assert indexed.loc[("marine", "compatible_union"), "MAPPED_AREA_M2"] == pytest.approx(50)
    assert indexed.loc[("intertidal", "tidal_marsh"), "MAPPED_AREA_M2"] == pytest.approx(50)
    assert indexed.loc[("marine", "eelgrass"), "INTERSECTING_EVIDENCE_RECORD_IDS"] == (
        "fixture:2026:eel|fixture:2026:survey"
    )


def test_later_absence_and_future_data_filtering() -> None:
    raw = _raw([
        _row("old", "E", box(0, 0, 10, 10), year=2020),
        _row("absence", "E", box(5, 0, 10, 10), "absent", year=2025),
        _row("future", "E", box(0, 0, 5, 10), "absent", year=2027),
    ])
    support = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell"], "H3_RESOLUTION": [8], "SUPPORT_TYPE": ["marine"]},
        geometry=[box(0, 0, 10, 10)], crs="EPSG:6933",
    )
    result = build_mapped_mosaic(support, normalize_vector_provider(raw, _contract()), as_of_year=2026)
    assert result.loc[result.HABITAT_TYPE.eq("eelgrass"), "MAPPED_AREA_M2"].iloc[0] == pytest.approx(50)
    assert result.loc[result.HABITAT_TYPE.eq("compatible_union"), "MOSAIC_STATUS"].iloc[0] == "temporal_support_conflict"
    assert pd.isna(result.loc[result.HABITAT_TYPE.eq("compatible_union"), "MAPPED_AREA_M2"].iloc[0])
    assert result.loc[result.HABITAT_TYPE.eq("eelgrass"), "INTERSECTING_EVIDENCE_RECORD_IDS"].iloc[0] == (
        "fixture:2026:absence|fixture:2026:old"
    )


def test_valid_empty_map_stays_empty_evidence() -> None:
    raw = _raw({
        "SOURCE_FEATURE_ID": [], "SOURCE_CLASS": [], "OBSERVATION_YEAR": [],
        "OBSERVATION_STATUS": [], "EVIDENCE_CLASS": [], "geometry": [],
    })
    normalized = normalize_vector_provider(raw, _contract())
    assert normalized.empty


def test_radius_area_counts_terminal_mapped_habitat_once() -> None:
    graph = WaterGraph(
        8, np.array(["node"]), np.array([0, 0]),
        np.array([], dtype=int), np.array([], dtype=float),
        pd.DataFrame({
            "H3_INDEX": ["node", "terminal"],
            "GRAPH_CONNECTION_STATUS": ["graph_node", "terminal_connector"],
            "CONNECTOR_TARGET_H3_INDEX": [None, "node"],
            "CONNECTOR_DISTANCE_M": [0.0, 100.0],
            "GRAPH_QC_REASON": [None, None],
        }),
        {"node": 0}, "fixture", "fixture",
    )
    sources = [("terminal", 0, 100.0, 50.0)]
    assert _radius_area(graph, "node", sources, 5000) == 50
    assert _radius_area(graph, "terminal", sources, 5000) == 50
    assert _radius_area(graph, "node", sources, 99) == 0
