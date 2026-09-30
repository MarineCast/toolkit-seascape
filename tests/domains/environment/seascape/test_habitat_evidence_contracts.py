from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from seascape.spatial_support.water_network.graph import WaterGraph
from seascape.spatial_support.water_network.radius_operator import RadiusSumOperator
from seascape.utils.habitat_aggregation import aggregate_r8_to_r6
from seascape.utils.habitat_inventory import normalize_inventory
from seascape.utils.habitat_surface import build_r8_tables, habitat_topology_for_support


def _row(
    record_id: str,
    geometry,
    *,
    status: str = "present",
    year: int = 2025,
    modeled: bool = False,
    role: str = "observation",
    event: str | None = None,
    complete: bool = False,
    priority: int = 0,
) -> dict:
    return {
        "RECORD_ID": record_id,
        "HABITAT_TYPE": "kelp",
        "SOURCE_DATASET": "synthetic_evidence",
        "SOURCE_FEATURE_ID": record_id,
        "EVIDENCE_CLASS": "modeled_occurrence" if modeled else "direct_observation",
        "OBSERVED_VS_MODELED": "modeled" if modeled else "observed",
        "OBSERVATION_STATUS": status,
        "OBSERVATION_YEAR": year,
        "COMPOSITION_ELIGIBLE": status == "present",
        "SUPPORTS_AREA": True,
        "COVERAGE_WEIGHT": 1.0,
        "SOURCE_PERSISTENCE_RATIO": np.nan,
        "CONFIDENCE_CLASS": 2,
        "SURVEY_METHOD": "fixture",
        "SPATIAL_PRECISION_CLASS": "polygon",
        "TEMPORAL_PRECISION_CLASS": "year",
        "GEOMETRY_ROLE": role,
        "SURVEY_EVENT_ID": event,
        "SURVEY_COMPLETENESS": "complete" if complete else "unknown",
        "AVAILABLE_YEAR": year,
        "SOURCE_PRIORITY": priority,
        "geometry": geometry,
    }


def _build(rows: list[dict], *, reference_year: int = 2026):
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["west", "east"]},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)],
        crs="EPSG:6933",
    )
    support = pd.DataFrame(
        {
            "H3_INDEX": ["west", "east"],
            "WATER_AREA_M2": [100.0, 100.0],
            "WATER_COMPONENT_ID": ["water", "water"],
            "CONNECTOR_METHOD": ["graph_node", "graph_node"],
            "CONNECTOR_DISTANCE_M": [0.0, 0.0],
        }
    )
    graph = WaterGraph(
        resolution=8,
        cells=np.asarray(["west", "east"], dtype=object),
        offsets=np.asarray([0, 1, 2], dtype=np.int64),
        neighbors=np.asarray([1, 0], dtype=np.int64),
        weights_m=np.asarray([10.0, 10.0]),
        support=support,
        cell_to_position={"west": 0, "east": 1},
        water_mask_version="fixture",
        spatial_support_version="fixture",
    )
    radius = RadiusSumOperator.build(
        graph, ["west", "east"], radius_m=100.0, graph_checksum="fixture"
    )
    inventory = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:6933")
    features, confidence = build_r8_tables(
        inventory,
        support,
        cells,
        graph,
        radius,
        prefix="KELP",
        equal_area_crs="EPSG:6933",
        reference_year=reference_year,
    )
    return (
        features.set_index("H3_INDEX"),
        confidence.set_index("H3_INDEX"),
        cells,
        inventory,
    )


def test_presence_only_and_modeled_maps_do_not_claim_survey_coverage() -> None:
    features, confidence, _cells, _inventory = _build(
        [
            _row("observed", box(0, 0, 5, 10)),
            _row("model", box(10, 0, 20, 10), modeled=True),
        ]
    )
    assert features.loc["west", "KELP_OBSERVATION_STATE"] == "partial_present"
    assert features.loc["west", "KELP_PRESENT_AREA_FRAC"] == pytest.approx(0.5)
    assert features.loc["west", "KELP_UNKNOWN_AREA_FRAC"] == pytest.approx(0.5)
    assert pd.isna(confidence.loc["west", "KELP_SURVEYED_AREA_FRAC"])
    assert confidence.loc["west", "KELP_SURVEY_COMPLETENESS_STATUS"] == "unknown"
    assert features.loc["east", "KELP_OBSERVATION_STATE"] == "unknown"
    assert features.loc["east", "KELP_AREA_M2"] == pytest.approx(100.0)
    assert not features.loc["east", "KELP_OBSERVED_PRESENCE"]


def test_complete_event_footprint_supports_absence_only_inside_it() -> None:
    features, confidence, _cells, _inventory = _build(
        [
            _row(
                "footprint",
                box(0, 0, 10, 10),
                status="surveyed",
                role="survey_footprint",
                event="event-2025",
                complete=True,
            ),
            _row("presence", box(0, 0, 5, 10), event="event-2025"),
        ]
    )
    assert confidence.loc["west", "KELP_SURVEYED_AREA_FRAC"] == pytest.approx(1.0)
    assert confidence.loc["west", "KELP_SURVEY_COMPLETENESS_STATUS"] == "complete"
    assert features.loc["west", "KELP_PRESENT_AREA_FRAC"] == pytest.approx(0.5)
    assert features.loc["west", "KELP_ABSENT_AREA_FRAC"] == pytest.approx(0.5)
    assert features.loc["west", "KELP_OBSERVATION_STATE"] == "mixed_partial"
    assert pd.isna(confidence.loc["east", "KELP_SURVEYED_AREA_FRAC"])


def test_latest_local_evidence_and_asof_excludes_future_absence() -> None:
    rows = [
        _row("old_presence", box(0, 0, 10, 10), year=2020),
        _row("later_absence", box(5, 0, 10, 10), status="absent", year=2025),
        _row("future_absence", box(0, 0, 5, 10), status="absent", year=2027),
    ]
    features, _confidence, cells, inventory = _build(rows, reference_year=2026)
    assert features.loc["west", "KELP_PRESENT_AREA_FRAC"] == pytest.approx(0.5)
    assert features.loc["west", "KELP_ABSENT_AREA_FRAC"] == pytest.approx(0.5)
    assert features.loc["west", "KELP_OBSERVATION_STATE"] == "mixed_partial"
    assert features.loc["west", "KELP_AREA_M2"] == pytest.approx(50.0)
    # Priority breaks same-year conflicting polygons at the same location.
    higher = _row(
        "priority_absence", box(0, 0, 5, 10), status="absent", year=2020, priority=1
    )
    priority_features, _, _, _ = _build([rows[0], higher], reference_year=2026)
    assert priority_features.loc["west", "KELP_ABSENT_AREA_FRAC"] == pytest.approx(0.5)
    assert cells.crs is not None
    assert len(normalize_inventory(inventory)) == 3


def test_one_absent_child_and_one_unknown_child_is_partial_parent() -> None:
    child, confidence, cells, inventory = _build(
        [
            _row("absence", box(0, 0, 10, 10), status="absent"),
        ]
    )
    crosswalk = pd.DataFrame(
        {
            "CHILD_H3_INDEX": ["west", "east"],
            "PARENT_H3_INDEX": ["parent", "parent"],
            "CHILD_WATER_AREA_M2": [100.0, 100.0],
        }
    )
    parent_support = pd.DataFrame(
        {
            "H3_INDEX": ["parent"],
            "WATER_AREA_M2": [200.0],
            "WATER_COMPONENT_ID": ["water"],
            "CONNECTOR_METHOD": ["graph_node"],
            "CONNECTOR_DISTANCE_M": [0.0],
        }
    )
    parent_cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["parent"]}, geometry=[box(0, 0, 20, 10)], crs=cells.crs
    )
    topology = habitat_topology_for_support(
        parent_cells, normalize_inventory(inventory), "EPSG:6933"
    )
    parent, parent_conf = aggregate_r8_to_r6(
        child.reset_index(),
        confidence.reset_index(),
        crosswalk,
        parent_support,
        prefix="KELP",
        topology=topology,
    )
    row = parent.iloc[0]
    assert row["KELP_ABSENT_AREA_FRAC"] == pytest.approx(0.5)
    assert row["KELP_UNKNOWN_AREA_FRAC"] == pytest.approx(0.5)
    assert row["KELP_OBSERVATION_STATE"] == "partial_absent"
    assert not row["KELP_OBSERVED_ABSENCE"]
    assert pd.isna(parent_conf.iloc[0]["KELP_SURVEYED_AREA_FRAC"])


def test_point_evidence_has_no_invented_survey_area() -> None:
    point = _row("point", Point(5, 5))
    point["SUPPORTS_AREA"] = False
    point["COMPOSITION_ELIGIBLE"] = False
    features, confidence, _, _ = _build([point])
    assert features.loc["west", "KELP_OBSERVATION_STATE"] == "point_or_line_presence"
    assert features.loc["west", "KELP_PRESENT_AREA_FRAC"] == 0
    assert features.loc["west", "KELP_UNKNOWN_AREA_FRAC"] == 1
    assert pd.isna(confidence.loc["west", "KELP_SURVEYED_AREA_FRAC"])


def test_varying_annual_footprints_do_not_make_unknown_area_absent() -> None:
    rows = [
        _row(
            "year-2020",
            box(0, 0, 5, 10),
            status="surveyed",
            year=2020,
            role="survey_footprint",
            event="y2020",
            complete=True,
        ),
        _row(
            "year-2025",
            box(5, 0, 10, 10),
            status="surveyed",
            year=2025,
            role="survey_footprint",
            event="y2025",
            complete=True,
        ),
    ]
    features, confidence, _, _ = _build(rows)
    assert features.loc["west", "KELP_ABSENT_AREA_FRAC"] == pytest.approx(1.0)
    assert features.loc["west", "KELP_OBSERVATION_STATE"] == "absent"
    assert confidence.loc["west", "KELP_SURVEYED_AREA_FRAC"] == pytest.approx(1.0)
    assert (
        confidence.loc["west", "KELP_SURVEY_COMPLETENESS_STATUS"]
        == "spatiotemporal_mosaic"
    )
    assert features.loc["east", "KELP_OBSERVATION_STATE"] == "unknown"
    assert pd.isna(confidence.loc["east", "KELP_SURVEYED_AREA_FRAC"])
