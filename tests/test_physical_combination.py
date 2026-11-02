"""Physical overlap and per-dataset cell maxima use the production calculations."""

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from seascape.anthropogenic.armoring import combine_estimates, maximum_estimate
from seascape.anthropogenic.build import _armoring_metrics, _mapped_evidence_fields
from seascape.coastal_configuration.shoreline_characterization.build import (
    CLASS_TOKENS,
    _aggregate_lengths,
)


def test_duplicate_shoreline_does_not_change_physical_class_fractions():
    records = []
    for index, token in enumerate(("ROCKY", "ROCKY", "SANDY")):
        y = 2 if token == "ROCKY" else 8
        records.append(
            {
                "SEGMENT_ID": str(index),
                "IS_PHYSICALLY_CLASSIFIED": True,
                **{f"IS_{name}_SHORE": name == token for name in CLASS_TOKENS},
                "geometry": LineString([(0, y), (10, y)]),
            }
        )
    inventory = gpd.GeoDataFrame(records, geometry="geometry", crs=6933)
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell"]}, geometry=[box(0, 0, 10, 10)], crs=6933
    )
    support = pd.DataFrame({"H3_INDEX": ["cell"]})
    result = _aggregate_lengths(inventory, cells, support, projected_crs="EPSG:6933")
    assert result.iloc[0].SHORELINE_TOTAL_MAPPED_LENGTH_M == 20
    assert result.iloc[0].ROCKY_SHORE_FRAC == result.iloc[0].SANDY_SHORE_FRAC == 0.5
    assert not any("DISAGREEMENT" in name for name in result)
    reference = _aggregate_lengths(
        inventory.iloc[[0, 2]], cells, support, projected_crs="EPSG:6933"
    )
    pd.testing.assert_frame_equal(result, reference)


def test_armoring_maximum_ignores_unknown_and_duplicate_dataset_records():
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell", "unknown"]},
        geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)],
        crs=6933,
    )
    inventory = gpd.GeoDataFrame(
        {
            "SOURCE_DATASET": ["zero", "positive", "positive", "unknown"],
            "SUPPORTS_SHORELINE_DENOMINATOR": [True] * 4,
            "ARMORING_FRACTION_ESTIMATE": [0.0, 1.0, 1.0, np.nan],
        },
        geometry=[LineString([(0, 5), (10, 5)])] * 4,
        crs=6933,
    )
    pairs = pd.DataFrame({"H3_INDEX": ["cell"] * 4, "index_right": range(4)})
    evidence = {}
    armored, surveyed, fraction = _armoring_metrics(
        cells, inventory, pairs, ["cell", "unknown"], estimates_by_cell=evidence
    )
    assert armored.tolist() == surveyed.tolist() == [10.0, 0.0]
    assert fraction[0] == 1 and np.isnan(fraction[1])
    assert set(evidence["cell"]) == {"zero", "positive"}


def test_armoring_cell_estimates_weight_disjoint_segments_within_each_dataset():
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell"]}, geometry=[box(0, 0, 10, 10)], crs=6933
    )
    inventory = gpd.GeoDataFrame(
        {
            "SOURCE_DATASET": ["a", "a", "b"],
            "SUPPORTS_SHORELINE_DENOMINATOR": [True] * 3,
            "ARMORING_FRACTION_ESTIMATE": [0.0, 1.0, 0.75],
        },
        geometry=[
            LineString([(0, 5), (5, 5)]),
            LineString([(5, 5), (10, 5)]),
            LineString([(0, 5), (10, 5)]),
        ],
        crs=6933,
    )
    pairs = pd.DataFrame({"H3_INDEX": ["cell"] * 3, "index_right": range(3)})
    _, _, fraction = _armoring_metrics(cells, inventory, pairs, ["cell"])
    assert fraction[0] == 0.75


def test_armoring_parent_maximum_follows_per_dataset_child_aggregation():
    children = [
        {
            "a": {"weighted_length_m": 10, "surveyed_length_m": 10},
            "b": {"weighted_length_m": 0, "surveyed_length_m": 10},
        },
        {
            "a": {"weighted_length_m": 0, "surveyed_length_m": 10},
            "b": {"weighted_length_m": 7.5, "surveyed_length_m": 10},
        },
    ]
    assert maximum_estimate(combine_estimates(children)) == (10, 20, 0.5)
    assert np.isnan(maximum_estimate({})[-1])
    with pytest.raises(ValueError, match="Invalid"):
        maximum_estimate({"bad": {"weighted_length_m": -1, "surveyed_length_m": 10}})


def test_mapped_evidence_assigns_full_native_cell_without_water_snapping():
    from shapely.geometry import Point

    cell = h3.latlng_to_cell(48.5, -123, 8)
    inventory = gpd.GeoDataFrame(
        {
            "FEATURE_CLASS": ["artificial_reef", "aquaculture"],
            "IS_CANONICAL": [True, False],
            "SUPPORTS_AREA": [False, False],
        },
        geometry=[Point(-123, 48.5)] * 2,
        crs=4326,
    )
    result = _mapped_evidence_fields(inventory, [cell], 8)
    assert result["ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE"].tolist() == [True]
    assert pd.isna(result["AQUACULTURE_MAPPED_POSITIVE_EVIDENCE"][0])
