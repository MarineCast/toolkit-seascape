from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, box

from seascape.coastal_configuration.passage_build import normalize_mapped_sills
from seascape.coastal_configuration.passage_sections import (
    measure_passage_section,
    sill_candidates,
)


def _section(depth_at, water=None):
    passage = box(-100, 0, 100, 500)
    return measure_passage_section(
        "source:passage:1", passage, LineString([(0, 0), (0, 500)]),
        water if water is not None else passage, depth_at,
        along_axis_m=250, half_length_m=150, sample_step_m=20,
        depth_threshold_m=25, tangent_scale_m=50,
    )


def test_rectangular_and_triangular_sections() -> None:
    rectangular = _section(lambda x, y: 50)
    assert rectangular.bank_status == "complete"
    assert rectangular.wet_width_m == 200
    assert rectangular.cross_section_area_m2 == 10_000
    assert rectangular.width_at_depth_threshold_m == 200
    triangular = _section(lambda x, y: 50 * (1 - abs(x) / 100))
    assert triangular.cross_section_area_m2 == pytest.approx(5000)
    assert triangular.width_at_depth_threshold_m == pytest.approx(100)
    island_water = box(-100, 0, 100, 500).difference(box(-20, 200, 20, 300))
    island = _section(lambda x, y: 50, island_water)
    assert island.wet_intervals == 2
    assert island.wet_width_m == 160
    assert island.cross_section_area_m2 == 8000
    assert island.max_contiguous_width_at_depth_threshold_m == 80
    nodata = _section(lambda x, y: None if x == 0 else 50)
    assert nodata.cross_section_area_m2 is None
    assert nodata.valid_integral_area_m2 < 10_000


def test_interior_shoal_requires_deeper_sections_both_sides() -> None:
    sections = pd.DataFrame(
        {
            "PASSAGE_ID": ["p"] * 3,
            "ALONG_AXIS_M": [0, 100, 200],
            "MAX_DEPTH_M": [50, 20, 60],
            "WET_WIDTH_M": [200] * 3,
            "BANK_STATUS": ["complete"] * 3,
            "BATHYMETRY_STATUS": ["complete"] * 3,
        }
    )
    candidates = sill_candidates(sections, min_relief_m=20)
    assert len(candidates) == 1
    assert candidates.iloc[0].SILL_CANDIDATE_DEPTH_M == 20
    assert candidates.iloc[0].RELIEF_LEFT_M == 30
    assert sill_candidates(sections.assign(MAX_DEPTH_M=[10, 20, 60]), min_relief_m=20).empty


def test_reviewed_sill_crests_remain_distinct_from_candidates() -> None:
    passages = gpd.GeoDataFrame(
        {"PASSAGE_ID": ["p"], "VERTICAL_DATUM": ["fixture"]},
        geometry=[box(0, 0, 100, 100)], crs="EPSG:32610"
    )
    mapped = gpd.GeoDataFrame(
        {
            "SILL_ID": ["s1", "s2"], "PASSAGE_ID": ["p", "p"],
            "MAPPED_SILL_CREST_DEPTH_M": [20.0, 25.0],
            "SOURCE_ID": ["fixture"] * 2, "SOURCE_VERSION": ["v1"] * 2,
            "RIGHTS": ["fixture"] * 2, "VERTICAL_DATUM": ["fixture"] * 2,
            "VALIDATION_STATUS": ["mapped", "validated"],
        },
        geometry=[Point(20, 20), Point(30, 30)], crs="EPSG:32610",
    )
    result = normalize_mapped_sills(mapped, passages, max_sills=2)
    assert pd.isna(result.loc[result.SILL_ID.eq("s1"), "CONFIRMED_SILL_CREST_DEPTH_M"].iloc[0])
    assert result.loc[result.SILL_ID.eq("s2"), "CONFIRMED_SILL_CREST_DEPTH_M"].iloc[0] == 25
    with pytest.raises(ValueError, match="within its reviewed passage"):
        normalize_mapped_sills(mapped.set_geometry([Point(200, 20), Point(30, 30)]), passages, max_sills=2)
    with pytest.raises(ValueError, match="vertical datums disagree"):
        normalize_mapped_sills(mapped.assign(VERTICAL_DATUM="other"), passages, max_sills=2)
