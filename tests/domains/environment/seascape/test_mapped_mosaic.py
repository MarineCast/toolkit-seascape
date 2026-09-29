from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from seascape.biogenic_habitat.mosaic import (
    VectorProviderContract,
    build_mapped_mosaic,
    normalize_vector_provider,
)


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
