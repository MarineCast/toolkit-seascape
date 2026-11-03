import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from seascape.hydrologic_connectivity.freshwater_sources.native_nhd import (
    normalize_legacy_nhd,
)


def test_network_end_requires_explicit_evidence_and_export_boundary_is_unknown():
    frame = gpd.GeoDataFrame(
        {
            "permanent_identifier": ["end", "export", "conflict", "{ABC}"],
            "ftype": [460] * 4,
            "fcode": [46006] * 4,
            "gnis_name": ["one"] * 4,
            "SOURCE_HU4": ["1711"] * 4,
            "SOURCE_ROW_ID": ["1", "2", "3", "4"],
        },
        geometry=[LineString([(0, i), (1, i)]) for i in range(4)],
        crs=4326,
    )
    flow = pd.DataFrame(
        {
            "direction": [713, 709, 713, 709, 713],
            "from_permanent_identifier": [
                "end",
                "export",
                "conflict",
                "conflict",
                "abc",
            ],
            "to_permanent_identifier": ["0", "0", "0", "next", "0"],
        }
    )
    result, quarantine, report = normalize_legacy_nhd(frame, flow)
    lookup = result.set_index("COMID")
    assert lookup.loc["end", "TERMINALFL"] == 1
    assert lookup.loc["abc", "TERMINALFL"] == 1
    assert lookup.loc["abc", "PERMANENT_IDENTIFIER"] == "{ABC}"
    assert pd.isna(lookup.loc["export", "TERMINALFL"])
    assert pd.isna(lookup.loc["conflict", "TERMINALFL"])
    assert "conflicting" in lookup.loc["conflict", "TERMINAL_QC"]
    assert quarantine.empty
    assert report["source_completeness"] == "partial"


def test_conflicting_source_versions_are_quarantined():
    frame = gpd.GeoDataFrame(
        {
            "permanent_identifier": ["same", "same", "ok"],
            "ftype": [460] * 3,
            "fcode": [46006] * 3,
            "gnis_name": ["one"] * 3,
            "SOURCE_HU4": ["1711", "1710", "1711"],
            "SOURCE_ROW_ID": ["1", "2", "3"],
        },
        geometry=[
            LineString([(0, 0), (1, 0)]),
            LineString([(0, 0), (2, 0)]),
            LineString([(0, 1), (1, 1)]),
        ],
        crs=4326,
    )
    flow = pd.DataFrame(
        {
            "direction": [713],
            "from_permanent_identifier": ["ok"],
            "to_permanent_identifier": ["0"],
        }
    )
    result, quarantine, report = normalize_legacy_nhd(frame, flow)
    assert result.COMID.tolist() == ["ok"]
    assert len(quarantine) == 2
    assert report["conflicting_feature_ids"] == ["same"]
