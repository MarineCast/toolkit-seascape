from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from seascape.hydrologic_connectivity.fluvial_barriers import (
    inspect as inspector,
)
from seascape.hydrologic_connectivity.fluvial_barriers.aggregation import (
    aggregate_r8_to_r6,
)
from seascape.hydrologic_connectivity.fluvial_barriers.build import (
    summarize_mouths,
)
from seascape.hydrologic_connectivity.fluvial_barriers.sources import (
    COUNT_COLUMNS,
    PREFIX,
    _record,
    deduplicate_inventory,
    normalize_pscis_status,
    normalize_wdfw_status,
)


def _source_record(record_id: str, priority: int, longitude: float) -> dict[str, object]:
    return _record(
        source_name=record_id,
        source_id="1",
        jurisdiction="WA",
        barrier_type="CULVERT",
        subtype="culvert",
        origin="ANTHROPOGENIC",
        passage_status="BLOCKED",
        passable_fraction=0.0,
        physical_status=None,
        remediation_status=None,
        assessment_date="2025-01-01",
        status_date=None,
        species_scope=None,
        fishway_present=None,
        evidence_class="assessed_crossing",
        confidence=3,
        priority=priority,
        raw_type="culvert",
        raw_status="barrier",
        properties={},
        geometry=Point(longitude, 48.0),
    )


def test_passage_status_normalization_preserves_assessment_semantics() -> None:
    assert normalize_pscis_status("Passable - No barrier") == ("PASSABLE", 1.0)
    assert normalize_pscis_status("Potential barrier") == ("POTENTIAL_BARRIER", None)
    assert normalize_wdfw_status(10.0, 30.0) == ("PARTIAL", 0.67)
    assert normalize_wdfw_status(20.0, 40.0) == ("PASSABLE", 1.0)
    assert normalize_wdfw_status(99.0, 99.0) == ("UNKNOWN", None)


def test_deduplication_retains_lineage_and_authoritative_precedence() -> None:
    frame = gpd.GeoDataFrame(
        [
            _source_record("authoritative", 100, -123.0000),
            _source_record("secondary", 60, -123.0003),
            _source_record("separate", 60, -123.1000),
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    inventory, lineage = deduplicate_inventory(frame, tolerance_m=100.0)
    authoritative = inventory.loc[inventory["SOURCE_DATASET"].eq("authoritative")].iloc[0]
    secondary = inventory.loc[inventory["SOURCE_DATASET"].eq("secondary")].iloc[0]
    assert bool(authoritative["IS_CANONICAL"])
    assert not bool(secondary["IS_CANONICAL"])
    assert secondary["CANONICAL_BARRIER_ID"] == authoritative["CANONICAL_BARRIER_ID"]
    assert len(lineage) == 3
    assert set(lineage["RELATIONSHIP"]) == {
        "CANONICAL_SOURCE_RECORD",
        "OVERLAPPING_SOURCE_RECORD",
    }


def test_no_mapped_barrier_is_null_not_zero() -> None:
    attached = pd.DataFrame(
        columns=[
            "NETWORK_SNAP_STATUS",
            "FLUVIAL_MOUTH_ID",
            "BARRIER_TYPE",
            "PASSAGE_STATUS",
            "ALONG_RIVER_DISTANCE_TO_MOUTH_KM",
            "SOURCE_DATASET",
            "ASSESSMENT_DATE",
            "CONFIDENCE_CLASS",
        ]
    )
    mouths = pd.DataFrame(
        [
            {
                "FLUVIAL_MOUTH_ID": "mouth-1",
                "RIVER_BASIN_ID": "basin-1",
                "OUTLET_SUBBASIN_ID": "subbasin-1",
            }
        ]
    )
    summary = summarize_mouths(attached, mouths).iloc[0]
    assert summary["BARRIER_INVENTORY_STATE"] == "NO_MAPPED_BARRIER_RECORDS"
    assert pd.isna(summary["MAPPED_UPSTREAM_BARRIER_COUNT"])
    assert pd.isna(summary["MAPPED_UPSTREAM_BARRIER_PRESENT"])


def test_r8_to_r6_uses_nearest_barrier_affected_child() -> None:
    rows = []
    for cell, affected_distance, barrier_count in (
        ("child-a", 900.0, 2.0),
        ("child-b", 100.0, 7.0),
    ):
        row = {
            "H3_INDEX": cell,
            "H3_RESOLUTION": 8,
            "BARRIER_INVENTORY_STATE": "MAPPED_BARRIERS_PRESENT",
            "MAPPED_UPSTREAM_BARRIER_PRESENT": 1.0,
            "PASSAGE_STATUS_COVERAGE_FRAC": 0.5,
            "NEAREST_MAPPED_BARRIER_FROM_MOUTH_KM": 1.0,
            "NEAREST_MAPPED_BLOCKING_BARRIER_FROM_MOUTH_KM": 2.0,
            "WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M": affected_distance,
            "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M": affected_distance,
        }
        row.update({column: np.nan for column in COUNT_COLUMNS})
        row["MAPPED_UPSTREAM_BARRIER_COUNT"] = barrier_count
        rows.append(row)
    features = pd.DataFrame(rows)
    confidence = pd.DataFrame(
        {
            "H3_INDEX": ["child-a", "child-b"],
            "H3_RESOLUTION": [8, 8],
            f"{PREFIX}_CONFIDENCE": [2, 3],
            f"{PREFIX}_UNMAPPED_AREA": [False, False],
            f"{PREFIX}_SOURCE_DATASETS": ["one", "two"],
            f"{PREFIX}_EVIDENCE_BASIS": ["test", "test"],
            f"{PREFIX}_LATEST_SURVEY_YEAR": [2020, 2025],
        }
    )
    parent_child = pd.DataFrame(
        {
            "CHILD_H3_INDEX": ["child-a", "child-b"],
            "PARENT_H3_INDEX": ["parent", "parent"],
        }
    )
    support = pd.DataFrame({"H3_INDEX": ["parent"]})
    r6, r6_confidence = aggregate_r8_to_r6(features, confidence, parent_child, support)
    assert r6.loc[0, "H3_INDEX"] == "parent"
    assert r6.loc[0, "MAPPED_UPSTREAM_BARRIER_COUNT"] == 7.0
    assert r6.loc[0, "WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M"] == 100.0
    assert r6_confidence.loc[0, f"{PREFIX}_CONFIDENCE"] == 3


def test_inspector_uses_hydrologic_connectivity_output_directory(monkeypatch, tmp_path) -> None:
    captured = {}
    monkeypatch.setattr(
        inspector,
        "load_habitat_surface_config",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    def fake_inspect(*_args, **kwargs):
        captured.update(kwargs)
        return tmp_path / "map.html"

    monkeypatch.setattr(inspector, "inspect_habitat_surface", fake_inspect)
    result = inspector.inspect_fluvial_barriers(output_path=tmp_path / "map.html")
    assert result == tmp_path / "map.html"
    assert str(captured["map_subdirectory"]).endswith("hydrologic_connectivity/fluvial_barriers")
    assert captured["map_stem"] == "fluvial_barriers"
