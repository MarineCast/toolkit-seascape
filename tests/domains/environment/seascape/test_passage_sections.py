from __future__ import annotations

import pandas as pd
import pytest
from shapely.geometry import LineString, box

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
