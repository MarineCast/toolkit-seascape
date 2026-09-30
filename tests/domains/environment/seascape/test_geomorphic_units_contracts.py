from __future__ import annotations

import numpy as np
import pandas as pd

from seascape.seafloor_physiography.geomorphic_units.build import (
    GEOMORPHIC_UNITS,
    _apply_minimum_mapping_unit,
    _build_output,
    _classification_scores,
    _fall,
    _rise,
    _select_labels,
    load_geomorphic_units_config,
)


def test_geomorphic_selection_respects_priority_and_missing_depth() -> None:
    frame = pd.DataFrame({"BATHYMETRY": [20.0, 40.0, np.nan]})
    units = (
        "CANYON_AXIS",
        "CANYON_RIM",
        "SILL",
        "CHANNEL",
        "SEAMOUNT_OR_KNOLL",
        "RIDGE",
        "BANK_OR_SHOAL",
        "SHELF_BREAK",
        "TROUGH",
        "BASIN_OR_DEPRESSION",
        "TERRACE",
        "SLOPE",
        "SHELF",
    )
    scores = {unit: np.zeros(3) for unit in units}
    scores["SILL"][:] = [0.8, 0.2, 0.9]
    scores["CANYON_AXIS"][:] = [0.8, 0.1, 0.0]
    scores["SHELF"][:] = [0.1, 0.7, 0.1]

    labels, confidence = _select_labels(frame, scores)

    assert labels.tolist() == ["CANYON_AXIS", "SHELF", "UNCLASSIFIED"]
    assert confidence[0] > 0.0
    assert confidence[2] == 0.0


def test_missing_memberships_and_unsupported_rows_are_not_positive_evidence() -> None:
    assert np.isnan(_rise(np.array([np.nan]), 0, 1)[0])
    assert np.isnan(_fall(np.array([np.nan]), 0, 1)[0])
    frame = pd.DataFrame({"BATHYMETRY": [25.0, 25.0]})
    scores = {
        unit: np.full(2, np.nan)
        for unit in (
            "CANYON_AXIS",
            "CANYON_RIM",
            "SILL",
            "CHANNEL",
            "SEAMOUNT_OR_KNOLL",
            "RIDGE",
            "BANK_OR_SHOAL",
            "SHELF_BREAK",
            "TROUGH",
            "BASIN_OR_DEPRESSION",
            "TERRACE",
            "SLOPE",
            "SHELF",
        )
    }
    scores["SHELF"][1] = 0.7
    labels, support = _select_labels(frame, scores)
    assert labels.tolist() == ["UNCLASSIFIED", "SHELF"]
    assert support[0] == 0.0
    assert support[1] > 0.0


def test_missing_slope_width_and_distance_do_not_create_class_support() -> None:
    config = load_geomorphic_units_config()
    frame = pd.DataFrame(
        {
            "RELIEF": [40.0] * 4,
            "LOCAL_WATERBODY_WIDTH_M": [1000.0, np.nan, 1000.0, 1000.0],
            "CONSTRICTION_INDEX": [0.2] * 4,
            "DISTANCE_TO_SILL_CANDIDATE_M": [100.0, 100.0, np.nan, 100.0],
            "DISTANCE_TO_ISOBATH_200_M": [100.0, 100.0, 100.0, np.nan],
        }
    )
    terrain = {
        "DEPTH": np.array([100.0] * 4),
        "SLOPE": np.array([2.0, 2.0, 2.0, np.nan]),
        "LOCAL_TPI": np.array([35.0] * 4),
        "BROAD_Z": np.array([-2.0] * 4),
        "SLOPE_CONTEXT": np.array([12.0] * 4),
        "DIRECTIONAL_ANISOTROPY": np.array([0.8] * 4),
        "CROSSES_SHELF_DEPTH": np.array([1.0] * 4),
    }
    scores = _classification_scores(frame, terrain, config)
    assert scores["CHANNEL"][0] > 0.0
    assert np.isnan(scores["CHANNEL"][1])
    assert scores["SILL"][0] > 0.0
    assert np.isnan(scores["SILL"][2])
    assert np.isnan(scores["SHELF"][3])
    assert np.isnan(scores["TERRACE"][3])
    # The known shelf crossing is independent of a missing contour distance.
    assert np.isnan(scores["SHELF_BREAK"][3])


def test_mapping_unit_only_adopts_class_with_its_own_evidence() -> None:
    scores = {"SHELF": np.array([0.8, np.nan]), "RIDGE": np.array([0.3, 0.7])}
    labels, sizes = _apply_minimum_mapping_unit(
        ["a", "b"],
        np.array(["SHELF", "RIDGE"], dtype=object),
        scores,
        2,
        {"a": ("b",), "b": ("a",)},
    )
    assert labels.tolist() == ["RIDGE", "RIDGE"]
    assert sizes.tolist() == [2, 2]


def test_unclassified_output_gives_reason_without_invented_support() -> None:
    frame = pd.DataFrame({"H3_INDEX": ["a", "b"]})
    terrain = {
        "DEPTH": np.array([np.nan, 50.0]),
        "BROAD_TPI": np.array([np.nan, 0.0]),
        "BROAD_Z": np.array([np.nan, np.nan]),
        "DIRECTIONAL_ANISOTROPY": np.array([np.nan, np.nan]),
    }
    output = _build_output(
        frame,
        terrain,
        np.array(["UNCLASSIFIED", "UNCLASSIFIED"]),
        np.zeros(2),
        np.zeros(2, dtype="int32"),
        {unit: np.full(2, np.nan) for unit in GEOMORPHIC_UNITS},
        {unit: np.zeros(2) for unit in GEOMORPHIC_UNITS},
        np.zeros(2),
        3,
    )
    assert output.CLASSIFICATION_QC_REASON.tolist() == [
        "depth_unavailable",
        "insufficient_evidence",
    ]
    assert output.CLASSIFICATION_CONFIDENCE.tolist() == [0.0, 0.0]
