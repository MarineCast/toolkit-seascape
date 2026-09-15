from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import requests
from shapely.geometry import LineString, Point, box

from seascape.anthropogenic import inspect as anthropogenic_inspect
from seascape.anthropogenic.aggregation import (
    aggregate_r8_to_r6,
)
from seascape.anthropogenic.build import (
    _armoring_metrics,
    _mapped_presence,
    distance_from_seed_sources,
)
from seascape.anthropogenic.sources import (
    CONFIDENCE_FAMILIES,
    DISTANCE_FEATURES,
    _normalize_aquaculture_csv,
    _normalize_bc_shorezone,
    _normalize_wa_shorezone,
    _record,
    classify_osm_tags,
    deduplicate_inventory,
)
from seascape.spatial_support.water_network.graph import (
    WaterGraph,
)
from seascape.utils.habitat_acquisition import (
    _build_overpass_query,
    _download_overpass,
)


def _graph() -> WaterGraph:
    support = pd.DataFrame(
        {
            "H3_INDEX": ["a", "b"],
            "GRAPH_CONNECTION_STATUS": ["graph_node", "graph_node"],
            "CONNECTOR_TARGET_H3_INDEX": [None, None],
            "CONNECTOR_DISTANCE_M": [np.nan, np.nan],
            "GRAPH_QC_REASON": [None, None],
        }
    )
    return WaterGraph(
        resolution=8,
        cells=np.asarray(["a", "b"], dtype=object),
        offsets=np.asarray([0, 1, 2], dtype=np.int64),
        neighbors=np.asarray([1, 0], dtype=np.int64),
        weights_m=np.asarray([1_000.0, 1_000.0]),
        support=support,
        cell_to_position={"a": 0, "b": 1},
        water_mask_version="test",
        spatial_support_version="test",
    )


def test_osm_tag_crosswalk_keeps_distinct_model_families():
    assert classify_osm_tags({"man_made": "pier", "amenity": "ferry_terminal"}) == [
        "ferry_terminal",
        "pier",
    ]
    assert classify_osm_tags({"seamark:type": "dredged_area"}) == ["dredged_channel"]
    assert classify_osm_tags({"seamark:type": "dumping_ground"}) == ["disposal_site"]
    assert classify_osm_tags({"seamark:type": "artificial_reef"}) == ["artificial_reef"]
    assert classify_osm_tags(
        {
            "seamark:type": "shoreline_construction",
            "seamark:shoreline_construction:category": "wharf;breakwater",
        }
    ) == ["breakwater", "pier"]


def test_overpass_query_is_bounded_and_endpoint_fallback_is_manifested(tmp_path):
    source = {
        "endpoints": ["https://first.invalid", "https://second.invalid"],
        "attempts_per_endpoint": 1,
        "retry_backoff_seconds": 0,
        "query_timeout_seconds": 60,
        "query_filters": ['["man_made"="pier"]'],
    }
    bbox = {"min_lon": -125, "min_lat": 47, "max_lon": -122, "max_lat": 50}
    query = _build_overpass_query(source, bbox)
    assert 'nwr["man_made"="pier"](47.0,-125.0,50.0,-122.0);' in query
    assert query.endswith("out meta geom;")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"version": 0.6, "elements": [{"type": "node", "id": 1}]}

    class Session:
        def __init__(self):
            self.endpoints = []

        def post(self, endpoint, **_kwargs):
            self.endpoints.append(endpoint)
            if "first" in endpoint:
                raise requests.ConnectionError("offline")
            return Response()

    destination = tmp_path / "osm.json"
    session = Session()
    count, metadata = _download_overpass(session, source, destination, bbox=bbox, timeout=5)
    assert count == 1
    assert session.endpoints == source["endpoints"]
    assert metadata["endpoint"] == source["endpoints"][1]
    assert metadata["geometry_mode"] == "geom"
    assert metadata["tile_count"] == 1
    document = json.loads(destination.read_text())
    assert document["_orcacast"]["query_sha256"] == metadata["query_sha256"]


def test_shorezone_normalizers_preserve_denominator_and_structure_counts(tmp_path):
    import geopandas as gpd

    wa_path = tmp_path / "wa.geojson"
    gpd.GeoDataFrame(
        {
            "OBJECTID": [1],
            "SM_TOT_PCT": [50],
            "SM1_TYPE": ["CONCRETE BULKHEAD"],
            "PIERDOCK": [3],
        },
        geometry=[LineString([(0, 0), (10, 0)])],
        crs="EPSG:4326",
    ).to_file(wa_path, driver="GeoJSON")
    wa = _normalize_wa_shorezone(
        wa_path, "wa_dnr", {"evidence_class": "systematic_shoreline_mapping"}
    )
    survey = wa.loc[wa["FEATURE_CLASS"].eq("shoreline_survey")].iloc[0]
    assert survey["ARMORING_FRACTION_ESTIMATE"] == pytest.approx(0.5)
    assert wa.loc[wa["FEATURE_CLASS"].eq("pier"), "STRUCTURE_COUNT"].iloc[0] == 3
    assert wa["FEATURE_CLASS"].tolist() == ["shoreline_survey", "seawall", "pier"]

    bc_path = tmp_path / "bc.geojson"
    gpd.GeoDataFrame(
        {"SHORE_UNIT_ID": ["unit"], "REP_TYPE_NAME": ["Man-made"], "FORM": ["Asjwn"]},
        geometry=[LineString([(0, 0), (10, 0)])],
        crs="EPSG:4326",
    ).to_file(bc_path, driver="GeoJSON")
    bc = _normalize_bc_shorezone(
        bc_path, "bc_shorezone", {"evidence_class": "systematic_shoreline_mapping"}
    )
    assert set(bc["FEATURE_CLASS"]) == {
        "shoreline_survey",
        "seawall",
        "jetty",
        "pier",
        "ferry_terminal",
    }
    assert (
        bc.loc[bc["FEATURE_CLASS"].eq("shoreline_survey"), "ARMORING_FRACTION_ESTIMATE"].iloc[0]
        == 1
    )


def test_aquaculture_csv_finds_current_dfo_coordinate_columns(tmp_path):
    path = tmp_path / "licences.csv"
    pd.DataFrame(
        {
            "Licence Number": ["A-1"],
            "Facility Latitude": [49.1],
            "Facility Longitude": [-123.2],
        }
    ).to_csv(path, index=False)
    frame = _normalize_aquaculture_csv(
        path, "bc_dfo", {"evidence_class": "authoritative_inventory"}
    )
    assert frame.iloc[0]["SOURCE_FEATURE_ID"] == "A-1"
    assert frame.iloc[0]["FEATURE_CLASS"] == "aquaculture"
    assert frame.geometry.iloc[0].equals(Point(-123.2, 49.1))


def test_authoritative_overlap_suppresses_osm_metric_record_but_retains_lineage():
    import geopandas as gpd

    rows = [
        _record(
            record_id="official:1:pier",
            source_dataset="official",
            source_feature_id="1",
            jurisdiction="WA",
            feature_class="pier",
            feature_subtype=None,
            evidence_class="authoritative_inventory",
            source_priority=50,
            confidence_class=3,
            geometry_precision_class="exact",
            geometry=Point(0, 0),
            structure_count=1,
        ),
        _record(
            record_id="osm:1:pier",
            source_dataset="osm",
            source_feature_id="1",
            jurisdiction="WA",
            feature_class="pier",
            feature_subtype=None,
            evidence_class="volunteered_mapping",
            source_priority=10,
            confidence_class=1,
            geometry_precision_class="community",
            geometry=Point(0.0001, 0),
            structure_count=1,
        ),
    ]
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    output = deduplicate_inventory(frame, 100)
    osm = output.set_index("RECORD_ID").loc["osm:1:pier"]
    assert not osm["IS_CANONICAL"]
    assert osm["DUPLICATE_OF_RECORD_ID"] == "official:1:pier"
    assert len(output) == 2


def test_armoring_fraction_uses_only_mapped_shoreline_denominator():
    import geopandas as gpd

    cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["a", "b"]},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)],
        crs="EPSG:6933",
    )
    rows = [
        _record(
            record_id="survey:a",
            source_dataset="survey",
            source_feature_id="a",
            jurisdiction="WA",
            feature_class="shoreline_survey",
            feature_subtype=None,
            evidence_class="systematic",
            source_priority=50,
            confidence_class=3,
            geometry_precision_class="line",
            geometry=LineString([(0, 5), (10, 5)]),
            supports_shoreline_denominator=True,
            armoring_fraction_estimate=0.5,
        ),
        _record(
            record_id="osm:b",
            source_dataset="osm",
            source_feature_id="b",
            jurisdiction="WA",
            feature_class="seawall",
            feature_subtype=None,
            evidence_class="volunteered",
            source_priority=10,
            confidence_class=1,
            geometry_precision_class="line",
            geometry=LineString([(10, 5), (20, 5)]),
        ),
    ]
    inventory = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:6933")
    pairs = pd.DataFrame({"H3_INDEX": ["a", "b"], "index_right": [0, 1]})
    armored, surveyed, fraction = _armoring_metrics(cells, inventory, pairs, ["a", "b"])
    assert surveyed.tolist() == pytest.approx([10, 0])
    assert armored.tolist() == pytest.approx([5, 0])
    assert fraction[0] == pytest.approx(0.5)
    assert np.isnan(fraction[1])


def test_distance_uses_water_graph_not_direct_geometry():
    distance, qc = distance_from_seed_sources(
        _graph(), ["a", "b"], [("a", 0.0, 0)], {"a"}, empty_reason="empty"
    )
    assert distance.tolist() == pytest.approx([0, 1_000])
    assert qc.tolist() == [None, None]


def test_distance_handles_missing_graph_qc_reason_without_boolean_coercion():
    graph = _graph()
    support = pd.concat(
        [
            graph.support,
            pd.DataFrame(
                {
                    "H3_INDEX": ["c"],
                    "GRAPH_CONNECTION_STATUS": ["disconnected"],
                    "CONNECTOR_TARGET_H3_INDEX": [None],
                    "CONNECTOR_DISTANCE_M": [np.nan],
                    "GRAPH_QC_REASON": [pd.NA],
                }
            ),
        ],
        ignore_index=True,
    )
    graph = WaterGraph(
        resolution=graph.resolution,
        cells=graph.cells,
        offsets=graph.offsets,
        neighbors=graph.neighbors,
        weights_m=graph.weights_m,
        support=support,
        cell_to_position=graph.cell_to_position,
        water_mask_version=graph.water_mask_version,
        spatial_support_version=graph.spatial_support_version,
    )
    distance, qc = distance_from_seed_sources(graph, ["c"], [("a", 0.0, 0)], empty_reason="empty")
    assert np.isnan(distance[0])
    assert qc.tolist() == ["target_has_no_graph_mapping"]


def test_mapped_presence_marks_every_intersected_cell_and_leaves_others_unmapped():
    import geopandas as gpd

    inventory = gpd.GeoDataFrame(
        [
            _record(
                record_id="farm:1",
                source_dataset="farm",
                source_feature_id="1",
                jurisdiction="WA",
                feature_class="aquaculture",
                feature_subtype=None,
                evidence_class="authoritative_inventory",
                source_priority=50,
                confidence_class=3,
                geometry_precision_class="polygon",
                geometry=box(0, 0, 2, 1),
            )
        ],
        geometry="geometry",
        crs="EPSG:6933",
    )
    values = _mapped_presence(
        inventory,
        "aquaculture",
        ["a", "b", "c"],
        {0: ["a", "b"]},
        {},
    )
    assert values[:2].tolist() == [1.0, 1.0]
    assert np.isnan(values[2])


def test_feature_aware_r8_to_r6_aggregation():
    rows = []
    for cell, armor, surveyed, dredged, distance, reef, aquaculture in (
        ("a", 5.0, 10.0, 20.0, 100.0, 1.0, np.nan),
        ("b", 0.0, 10.0, 0.0, 1_000.0, np.nan, 1.0),
    ):
        row = {
            "H3_INDEX": cell,
            "H3_RESOLUTION": 8,
            "SHORELINE_ARMORING_LENGTH_M": armor,
            "SHORELINE_SURVEYED_LENGTH_M": surveyed,
            "SHORELINE_ARMORING_FRAC": armor / surveyed,
            "DREDGED_AREA_M2": dredged,
            "DREDGED_AREA_FRAC": dredged / 100,
            "DISPOSAL_SITE_AREA_M2": 0.0,
            "DISPOSAL_SITE_AREA_FRAC": 0.0,
            "AQUACULTURE_FOOTPRINT_AREA_M2": 0.0,
            "AQUACULTURE_FOOTPRINT_FRAC": np.nan,
            "ARTIFICIAL_REEF_PRESENCE": reef,
            "AQUACULTURE_PRESENCE": aquaculture,
            "OVERWATER_STRUCTURE_COUNT_WITHIN_5KM": 2.0,
            "OVERWATER_STRUCTURE_DENSITY_PER_KM2": 4.0,
            "WATER_COMPONENT_ID": "component",
            "NETWORK_CONNECTOR_METHOD": "graph_node",
            "NETWORK_CONNECTOR_DISTANCE_M": 0.0,
            "NETWORK_DISTANCE_QC_REASON": None,
        }
        for column in DISTANCE_FEATURES:
            row[column] = distance
            row[column.removesuffix("_M") + "_QC_REASON"] = None
        rows.append(row)
    features = pd.DataFrame(rows)
    confidence_rows = []
    for cell in ("a", "b"):
        row = {"H3_INDEX": cell, "H3_RESOLUTION": 8}
        for family in [*CONFIDENCE_FAMILIES, "ANTHROPOGENIC"]:
            row[f"{family}_SOURCE_DATASETS"] = "source"
            row[f"{family}_SOURCE_COUNT"] = 1
            row[f"{family}_CONFIDENCE"] = 3
            row[f"{family}_UNMAPPED_AREA"] = cell == "b"
        confidence_rows.append(row)
    confidence = pd.DataFrame(confidence_rows)
    crosswalk = pd.DataFrame(
        {
            "CHILD_H3_INDEX": ["a", "b"],
            "PARENT_H3_INDEX": ["parent", "parent"],
            "CHILD_WATER_AREA_M2": [100.0, 100.0],
        }
    )
    support = pd.DataFrame(
        {
            "H3_INDEX": ["parent"],
            "WATER_COMPONENT_ID": ["component"],
            "CONNECTOR_METHOD": ["graph_node"],
            "CONNECTOR_DISTANCE_M": [0.0],
            "GRAPH_QC_REASON": [None],
        }
    )
    output, output_confidence = aggregate_r8_to_r6(features, confidence, crosswalk, support)
    parent = output.iloc[0]
    assert parent["SHORELINE_ARMORING_FRAC"] == pytest.approx(0.25)
    assert parent["DREDGED_AREA_FRAC"] == pytest.approx(0.1)
    assert parent["DISTANCE_TO_PIER_M"] == pytest.approx(100)
    assert parent["ARTIFICIAL_REEF_PRESENCE"] == 1
    assert parent["AQUACULTURE_PRESENCE"] == 1
    assert output_confidence.iloc[0]["ANTHROPOGENIC_UNMAPPED_AREA"]


def test_inspector_routes_to_shared_anthropogenic_output(monkeypatch, tmp_path):
    config = object()
    captured = {}
    expected = tmp_path / "anthropogenic_RES_8.html"

    monkeypatch.setattr(
        anthropogenic_inspect,
        "load_habitat_surface_config",
        lambda *_args, **_kwargs: config,
    )

    def fake_inspector(received_config, **kwargs):
        captured["config"] = received_config
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        anthropogenic_inspect,
        "inspect_habitat_surface",
        fake_inspector,
    )
    output = anthropogenic_inspect.inspect_anthropogenic_seascape(
        resolution=8,
        presentation_config_path="presentation.yaml",
    )
    assert output == expected
    assert captured["config"] is config
    assert captured["map_subdirectory"] == anthropogenic_inspect.MAP_EXPORT_SUBDIRECTORY
    assert captured["map_stem"] == "anthropogenic"
    assert captured["resolution"] == 8
    assert {column for column, _label in captured["metrics"]}.issuperset(
        {
            "SHORELINE_ARMORING_FRAC",
            "DISTANCE_TO_PIER_M",
            "DISTANCE_TO_DREDGED_CHANNEL_M",
            "AQUACULTURE_FOOTPRINT_FRAC",
            "OVERWATER_STRUCTURE_DENSITY_PER_KM2",
        }
    )
