from __future__ import annotations

import runpy
from pathlib import Path

import pyarrow as pa
import pytest


@pytest.fixture(scope="module")
def infer_unit():
    script = Path(__file__).parents[4] / "scripts" / "update_seascape_feature_catalog.py"
    return runpy.run_path(str(script))["unit"]


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("BATHYMETRY_FRAC_0_TO_10_M", "proportion"),
        ("BATHYMETRY_PIXEL_COUNT_0_TO_10_M", "count"),
        ("SURFACE_AREA_RATIO_FROM_SLOPE", "dimensionless"),
        ("MAPPED_FLUVIAL_MOUTH_COUNT_IN_COMPONENT", "count"),
        ("OVERWATER_STRUCTURE_COUNT_WITHIN_5KM", "count"),
        ("GRAPH_COMPONENT_COUNT", "count"),
    ],
)
def test_semantic_units_precede_physical_suffixes(infer_unit, column, expected) -> None:
    assert infer_unit(column, pa.field(column, pa.float64())) == expected
