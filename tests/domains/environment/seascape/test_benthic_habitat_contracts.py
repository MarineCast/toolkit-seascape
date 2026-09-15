from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from seascape.benthic_substrate.bottom_hardness.build import (
    CLASS_WEIGHTS,
    _derive,
)
from seascape.benthic_substrate.classification.build import (
    CLASSES,
    _close_composition,
)
from seascape.biogenic_habitat.composite.build import (
    CORE_FEATURES,
    _coverage_gated_richness,
)
from seascape.biogenic_habitat.kelp.build import (
    _is_annual_polygon_frame,
    _require_annual_inventory,
)
from seascape.biogenic_habitat.reef.build import (
    _rocky_fraction,
)
from seascape.spatial_support.water_network.graph import (
    WaterGraph,
)
from seascape.spatial_support.water_network.radius_operator import (
    RadiusSumOperator,
)
from seascape.utils.habitat_acquisition import (
    _download_arcgis,
    _download_http_file,
)
from seascape.utils.habitat_aggregation import (
    _aggregate_persistence,
    aggregate_r8_to_r6,
)
from seascape.utils.habitat_inventory import (
    NORMALIZED_INVENTORY_COLUMNS,
    normalize_inventory,
)
from seascape.utils.habitat_raster import (
    positive_raster_polygons,
    sample_raster_bilinear,
)
from seascape.utils.habitat_surface import (
    _network_metrics,
    _record_metrics,
    build_r8_tables,
)


def _two_cell_graph(support: pd.DataFrame) -> WaterGraph:
    cells = support["H3_INDEX"].astype(str).to_numpy(dtype=object)
    return WaterGraph(
        resolution=8,
        cells=cells,
        offsets=np.asarray([0, 1, 2], dtype=np.int64),
        neighbors=np.asarray([1, 0], dtype=np.int64),
        weights_m=np.asarray([1_000.0, 1_000.0]),
        support=support,
        cell_to_position={str(cell): index for index, cell in enumerate(cells)},
        water_mask_version="test",
        spatial_support_version="test",
    )


def _inventory_frame():
    import geopandas as gpd

    return gpd.GeoDataFrame(
        {
            "RECORD_ID": ["survey:1"],
            "HABITAT_TYPE": ["seagrass"],
            "SOURCE_DATASET": ["synthetic_survey"],
            "SOURCE_FEATURE_ID": ["1"],
            "EVIDENCE_CLASS": ["direct_observation"],
            "OBSERVED_VS_MODELED": ["observed"],
            "OBSERVATION_STATUS": ["present"],
            "OBSERVATION_YEAR": [2025],
            "COMPOSITION_ELIGIBLE": [True],
            "SUPPORTS_AREA": [True],
            "COVERAGE_WEIGHT": [1.0],
            "SOURCE_PERSISTENCE_RATIO": [np.nan],
            "CONFIDENCE_CLASS": [3],
            "SURVEY_METHOD": ["synthetic polygon"],
            "SPATIAL_PRECISION_CLASS": ["exact_polygon"],
            "TEMPORAL_PRECISION_CLASS": ["survey_year"],
        },
        geometry=[box(0, 0, 5, 10)],
        crs="EPSG:6933",
    ).loc[:, NORMALIZED_INVENTORY_COLUMNS]


def test_exact_polygon_overlay_and_three_state_contract_survive_r8_to_r6():
    import geopandas as gpd

    support_r8 = pd.DataFrame(
        {
            "H3_INDEX": ["child-a", "child-b"],
            "WATER_AREA_M2": [100.0, 100.0],
            "WATER_COMPONENT_ID": ["component", "component"],
            "CONNECTOR_METHOD": ["graph_node", "graph_node"],
            "CONNECTOR_DISTANCE_M": [0.0, 0.0],
        }
    )
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": ["child-a", "child-b"]},
        geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)],
        crs="EPSG:6933",
    )
    graph = _two_cell_graph(support_r8)
    radius_operator = RadiusSumOperator.build(
        graph,
        support_r8["H3_INDEX"].astype(str).tolist(),
        radius_m=5_000.0,
        graph_checksum="fixture",
    )
    features, confidence = build_r8_tables(
        _inventory_frame(),
        support_r8,
        cells,
        graph,
        radius_operator,
        prefix="SEAGRASS",
        equal_area_crs="EPSG:6933",
        reference_year=2026,
    )
    first = features.set_index("H3_INDEX").loc["child-a"]
    second = features.set_index("H3_INDEX").loc["child-b"]
    assert first["SEAGRASS_AREA_M2"] == pytest.approx(50.0, rel=1e-6)
    assert first["SEAGRASS_FRAC"] == pytest.approx(0.5, rel=1e-6)
    assert first["SEAGRASS_MEAN_PATCH_AREA_M2"] == pytest.approx(50.0, rel=1e-6)
    assert first["SEAGRASS_FRAGMENTATION_INDEX"] == pytest.approx(0.0)
    assert first["SEAGRASS_OBSERVED_PRESENCE"]
    assert not first["SEAGRASS_UNSURVEYED"]
    assert second["SEAGRASS_UNSURVEYED"]
    assert not second["SEAGRASS_OBSERVED_ABSENCE"]
    assert second["SEAGRASS_DISTANCE_M"] == pytest.approx(1_000.0)

    crosswalk = pd.DataFrame(
        {
            "CHILD_H3_INDEX": ["child-a", "child-b"],
            "PARENT_H3_INDEX": ["parent", "parent"],
            "CHILD_WATER_AREA_M2": [100.0, 100.0],
        }
    )
    support_r6 = pd.DataFrame(
        {
            "H3_INDEX": ["parent"],
            "WATER_AREA_M2": [200.0],
            "WATER_COMPONENT_ID": ["component"],
            "CONNECTOR_METHOD": ["graph_node"],
            "CONNECTOR_DISTANCE_M": [0.0],
        }
    )
    parent_features, parent_confidence = aggregate_r8_to_r6(
        features,
        confidence,
        crosswalk,
        support_r6,
        prefix="SEAGRASS",
    )
    parent = parent_features.iloc[0]
    assert parent["SEAGRASS_AREA_M2"] == pytest.approx(50.0, rel=1e-6)
    assert parent["SEAGRASS_FRAC"] == pytest.approx(0.25, rel=1e-6)
    assert parent["SEAGRASS_MAX_LOCAL_FRAC"] == pytest.approx(0.5, rel=1e-6)
    assert parent["SEAGRASS_OCCUPIED_CHILD_COUNT"] == 1
    assert parent["SEAGRASS_DISTANCE_M"] == pytest.approx(0.0)
    assert parent_confidence.iloc[0]["SEAGRASS_UNMAPPED_AREA"]


def test_disconnected_habitat_source_retains_local_area_distance_and_qc():
    support = pd.DataFrame(
        {
            "H3_INDEX": ["connected", "disconnected"],
            "GRAPH_CONNECTION_STATUS": ["graph_node", "disconnected"],
            "GRAPH_QC_REASON": [None, "connector_crosses_land"],
        }
    )
    graph = WaterGraph(
        resolution=8,
        cells=np.asarray(["connected"], dtype=object),
        offsets=np.asarray([0, 0], dtype=np.int64),
        neighbors=np.asarray([], dtype=np.int64),
        weights_m=np.asarray([], dtype=np.float64),
        support=support,
        cell_to_position={"connected": 0},
        water_mask_version="test",
        spatial_support_version="test",
    )
    cells = ["connected", "disconnected"]
    radius_operator = RadiusSumOperator.build(
        graph,
        cells,
        radius_m=5_000.0,
        graph_checksum="fixture",
    )
    area = pd.Series([0.0, 12.0], index=cells)
    distance, radius_sum, qc = _network_metrics(
        graph,
        cells,
        {"disconnected"},
        area,
        radius_operator,
    )
    assert np.isnan(distance[0])
    assert distance[1] == pytest.approx(0.0)
    assert radius_sum.tolist() == pytest.approx([0.0, 12.0])
    assert qc[1] == "connector_crosses_land"


def test_normalized_inventory_rejects_invalid_source_persistence():
    inventory = _inventory_frame()
    inventory.loc[0, "SOURCE_PERSISTENCE_RATIO"] = 1.1
    with pytest.raises(ValueError, match="persistence ratios"):
        normalize_inventory(inventory)


def test_persistence_distinguishes_survey_ratio_from_published_bin():
    import geopandas as gpd

    rows = []
    for record_id, status, year, source_ratio in (
        ("survey-present", "present", 2020, np.nan),
        ("survey-absent", "absent", 2021, np.nan),
        ("mapped-bin", "present", None, 0.7),
    ):
        row = _inventory_frame().iloc[0].to_dict()
        row.update(
            {
                "RECORD_ID": record_id,
                "OBSERVATION_STATUS": status,
                "OBSERVATION_YEAR": year,
                "SOURCE_PERSISTENCE_RATIO": source_ratio,
            }
        )
        rows.append(row)
    inventory = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:6933")
    pairs = pd.DataFrame(
        {
            "H3_INDEX": ["survey-cell", "survey-cell", "mapped-cell"],
            "index_right": [0, 1, 2],
        }
    )
    features, _confidence, _present = _record_metrics(
        inventory,
        pairs,
        ["survey-cell", "mapped-cell", "unmapped-cell"],
        2026,
    )
    features = features.set_index("H3_INDEX")
    assert features.loc["survey-cell", "PERSISTENCE_RATIO"] == pytest.approx(0.5)
    assert features.loc["survey-cell", "PERSISTENCE_BASIS"] == "surveyed_years"
    assert features.loc["mapped-cell", "PERSISTENCE_RATIO"] == pytest.approx(0.7)
    assert features.loc["mapped-cell", "PERSISTENCE_BASIS"] == "mapped_binned_proportion_midpoint"
    assert pd.isna(features.loc["unmapped-cell", "PERSISTENCE_RATIO"])


def test_r6_persistence_does_not_mix_year_and_area_weights():
    rows = pd.DataFrame(
        {
            "KELP_PERSISTENCE_RATIO": [0.5, 0.9],
            "KELP_PERSISTENCE_BASIS": [
                "surveyed_years",
                "mapped_binned_proportion_midpoint",
            ],
            "KELP_YEARS_SURVEYED": [2, 0],
            "CHILD_WATER_AREA_M2": [100.0, 10_000.0],
        }
    )
    value, basis = _aggregate_persistence(rows, "KELP")
    assert np.isnan(value)
    assert basis == "mapped_binned_proportion_midpoint|surveyed_years"


def test_r6_persistence_uses_coherent_weights_within_one_basis():
    rows = pd.DataFrame(
        {
            "KELP_PERSISTENCE_RATIO": [0.25, 0.75],
            "KELP_PERSISTENCE_BASIS": ["surveyed_years", "surveyed_years"],
            "KELP_YEARS_SURVEYED": [1, 3],
            "CHILD_WATER_AREA_M2": [100.0, 10_000.0],
        }
    )
    value, basis = _aggregate_persistence(rows, "KELP")
    assert value == pytest.approx(0.625)
    assert basis == "surveyed_years"


def test_modeled_presence_drives_distance_sources_without_claiming_observed_presence():
    inventory = _inventory_frame()
    inventory.loc[0, "OBSERVED_VS_MODELED"] = "modeled"
    inventory.loc[0, "EVIDENCE_CLASS"] = "modeled_occurrence"
    pairs = pd.DataFrame({"H3_INDEX": ["modeled-cell"], "index_right": [0]})
    features, confidence, present = _record_metrics(inventory, pairs, ["modeled-cell"], 2026)
    assert present == {"modeled-cell"}
    assert features.loc[0, "UNSURVEYED"]
    assert not features.loc[0, "OBSERVED_PRESENCE"]
    assert confidence.loc[0, "OBSERVED_VS_MODELED"] == "modeled"
    assert confidence.loc[0, "CONFIDENCE"] == 3


def test_raster_helpers_polygonize_classes_and_sample_percentages(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "classes.tif"
    values = np.asarray([[0, 100], [1, 50]], dtype="uint8")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
        nodata=255,
    ) as raster:
        raster.write(values, 1)
    sampled, valid = sample_raster_bilinear(path, [1.5, 0.5], [1.5, 0.5])
    assert valid.tolist() == [True, True]
    assert sampled.tolist() == pytest.approx([100.0, 1.0])
    polygons, crs = positive_raster_polygons(
        [path],
        bbox={"min_lon": 0, "min_lat": 0, "max_lon": 2, "max_lat": 2},
        positive_values=[1],
    )
    assert crs == "EPSG:4326"
    assert len(polygons) == 1
    assert polygons[0].area == pytest.approx(1.0)


def test_arcgis_feature_batches_use_post_to_avoid_url_length_failures(tmp_path):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.posts = []

        def get(self, _url, **_kwargs):
            return Response({"objectIds": [1, 2]})

        def post(self, _url, *, data, **_kwargs):
            self.posts.append(data)
            ids = [int(value) for value in data["objectIds"].split(",")]
            return Response(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"OBJECTID": value},
                            "geometry": {"type": "Point", "coordinates": [0, 0]},
                        }
                        for value in ids
                    ],
                }
            )

    session = Session()
    destination = tmp_path / "source.geojson"
    count = _download_arcgis(
        session,
        {"layer_url": "https://example.test/MapServer/0", "fields": ["OBJECTID"]},
        destination,
        bbox={"min_lon": -1, "min_lat": -1, "max_lon": 1, "max_lat": 1},
        timeout=1.0,
        page_size=1,
    )
    assert count == 2
    assert len(session.posts) == 2
    assert destination.is_file()


def test_http_file_download_supports_post_and_validates_size(tmp_path):
    class Response:
        def raise_for_status(self):
            return None

        def iter_content(self, *, chunk_size):
            assert chunk_size == 1024 * 1024
            yield b"dbseabed"

    class Session:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response()

    session = Session()
    destination = tmp_path / "source.tif"
    size = _download_http_file(
        session,
        {
            "url": "https://example.test/source.tif",
            "http_method": "POST",
            "expected_bytes": 8,
        },
        destination,
        timeout=1.0,
    )
    assert size == 8
    assert destination.read_bytes() == b"dbseabed"
    assert session.calls[0][0] == "POST"


def test_substrate_ontology_and_hardness_derivation_are_bounded():
    classes, valid = _close_composition(
        np.asarray([0.25]),
        np.asarray([0.2]),
        np.asarray([0.3]),
        np.asarray([0.5]),
    )
    assert valid.tolist() == [True]
    assert classes["ROCK"][0] == pytest.approx(0.25)
    assert classes["GRAVEL"][0] == pytest.approx(0.15)
    assert classes["SAND"][0] == pytest.approx(0.225)
    assert classes["MUD"][0] == pytest.approx(0.375)
    assert sum(classes[name][0] for name in CLASSES) == pytest.approx(1.0)
    features = pd.DataFrame(
        {
            "H3_INDEX": ["cell"],
            "H3_RESOLUTION": [8],
            **{f"SUBSTRATE_{name}_FRAC": [1.0 if name == "ROCK" else 0.0] for name in CLASSES},
            "SUBSTRATE_HARD_SUBSTRATE_FRAC": [0.4],
            "SUBSTRATE_DISTANCE_TO_HARD_SUBSTRATE_M": [0.0],
            "WATER_COMPONENT_ID": ["cell"],
            "NETWORK_CONNECTOR_METHOD": ["graph_node"],
            "NETWORK_CONNECTOR_DISTANCE_M": [0.0],
            "NETWORK_DISTANCE_QC_REASON": [None],
        }
    )
    confidence = pd.DataFrame(
        {
            "H3_INDEX": ["cell"],
            "H3_RESOLUTION": [8],
            "SUBSTRATE_CONFIDENCE": [2],
            "SUBSTRATE_UNMAPPED_AREA": [True],
        }
    )
    hardness, hardness_confidence = _derive(features, confidence)
    assert hardness.loc[0, "BOTTOM_HARDNESS_INDEX"] == CLASS_WEIGHTS["ROCK"]
    assert hardness.loc[0, "DERIVATION_METHOD"].startswith("fixed documented")
    assert (
        hardness_confidence.loc[0, "BOTTOM_HARDNESS_OBSERVED_VS_MODELED"]
        == "derived_from_modeled_dbseabed_substrate"
    )


def test_model_panel_keeps_exactly_the_requested_initial_core_features():
    assert CORE_FEATURES == [
        "SEAGRASS_FRAC",
        "SEAGRASS_MAX_LOCAL_FRAC",
        "SEAGRASS_DISTANCE_M",
        "SEAGRASS_AREA_WITHIN_5KM_M2",
        "KELP_FRAC",
        "KELP_MAX_LOCAL_FRAC",
        "KELP_DISTANCE_M",
        "KELP_AREA_WITHIN_5KM_M2",
        "KELP_PERSISTENCE_RATIO",
        "ROCKY_REEF_FRAC",
        "ROCKY_REEF_DISTANCE_M",
        "ROCKY_REEF_AREA_WITHIN_5KM_M2",
    ]


def test_unmapped_substrate_remains_null_in_rocky_reef_fraction():
    base = pd.DataFrame(
        {
            "H3_INDEX": ["mapped", "unmapped"],
            "SUBSTRATE_HARD_SUBSTRATE_FRAC": [0.4, np.nan],
        }
    )
    confidence = pd.DataFrame(
        {
            "H3_INDEX": ["mapped", "unmapped"],
            "SUBSTRATE_CONFIDENCE": [2, 0],
            "SUBSTRATE_UNMAPPED_AREA": [False, True],
        }
    )
    fraction, _confidence = _rocky_fraction(base, confidence, ["mapped", "unmapped"])
    assert fraction.iloc[0] == pytest.approx(0.4)
    assert np.isnan(fraction.iloc[1])


def test_benthic_richness_is_null_when_any_family_is_unmapped():
    values = pd.DataFrame(
        {
            "SEAGRASS_FRAC": [0.2, 0.2],
            "KELP_FRAC": [0.0, 0.0],
            "ROCKY_REEF_FRAC": [0.4, np.nan],
            "BIOGENIC_REEF_FRAC": [0.0, 0.0],
        }
    )
    confidence = pd.DataFrame(
        {
            "SEAGRASS_UNMAPPED_AREA": [False, False],
            "KELP_UNMAPPED_AREA": [False, False],
            "ROCKY_REEF_UNMAPPED_AREA": [False, True],
            "BIOGENIC_REEF_UNMAPPED_AREA": [False, False],
        }
    )
    richness = _coverage_gated_richness(values, confidence)
    assert richness.iloc[0] == pytest.approx(2.0)
    assert np.isnan(richness.iloc[1])


def test_kelp_build_requires_annual_inventory_without_explicit_override():
    with pytest.raises(FileNotFoundError, match="required WA DNR annual"):
        _require_annual_inventory([], allow_generalized_only=False)
    _require_annual_inventory([], allow_generalized_only=True)


def test_kelp_annual_inventory_ignores_nonspatial_geodatabase_tables():
    assert not _is_annual_polygon_frame(pd.DataFrame({"YEAR": [2024]}))
