from __future__ import annotations

import numpy as np
import pandas as pd

from seascape.seafloor_physiography.geomorphic_units.build import (
    _select_labels,
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
