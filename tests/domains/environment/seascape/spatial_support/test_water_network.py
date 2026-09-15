from __future__ import annotations

from dataclasses import replace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from seascape.core.artifacts.checksums import checksum_path
from seascape.core.geo.h3 import grid_disk, latlng_to_cell
from seascape.seafloor_physiography.bathymetry.build import (
    _aggregate_raster,
)
from seascape.spatial_support.water_network.build import (
    _append_hierarchy_only_parents,
    _assign_components,
    _build_connectors,
    _build_edges,
    _build_geometry_and_base_support,
    _build_neighborhoods,
    _crosswalk,
)
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.spatial_support.water_network.geometry import (
    directional_water_fraction,
    water_path_metrics,
)
from seascape.spatial_support.water_network.graph import (
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    _csr,
    _verify_artifact,
    multi_source_shortest_paths,
    nullable_string_values,
)
from seascape.spatial_support.water_network.validation import (
    validate_connectors,
    validate_edges,
    validate_geometry_products,
    validate_manifest_payload,
    validate_neighborhoods,
    validate_support,
)


@pytest.fixture
def network_config():
    return replace(
        load_water_network_config(),
        connector_max_distance_m={6: 20_000.0, 8: 2_000.0},
        edge_chunk_size=100,
        max_workers=1,
    )


def test_water_path_rejects_island_and_accepts_open_channel():
    water = box(-123.3, 48.0, -123.0, 48.3).difference(box(-123.16, 48.0, -123.14, 48.2))
    _distance, blocked_fraction, blocked = water_path_metrics(
        -123.25,
        48.1,
        -123.05,
        48.1,
        water,
        maximum_segment_m=100.0,
        outside_tolerance_m=1.0,
    )
    _distance, clear_fraction, clear = water_path_metrics(
        -123.25,
        48.25,
        -123.05,
        48.25,
        water,
        maximum_segment_m=100.0,
        outside_tolerance_m=1.0,
    )
    assert not blocked
    assert blocked_fraction < 1.0
    assert clear
    assert clear_fraction == pytest.approx(1.0)


def test_directional_fetch_stops_at_peninsula():
    water = box(-123.3, 48.0, -123.0, 48.3).difference(box(-123.16, 48.0, -123.14, 48.2))
    blocked = directional_water_fraction(-123.25, 48.1, 90.0, 20_000.0, water)
    clear = directional_water_fraction(-123.25, 48.25, 90.0, 10_000.0, water)
    assert 0.0 < blocked < 1.0
    assert clear == pytest.approx(1.0)


def test_nullable_string_values_preserves_nulls_for_strict_table_builders():
    assert nullable_string_values(["component", np.nan, pd.NA, None]) == [
        "component",
        None,
        None,
        None,
    ]


def test_hierarchy_only_parent_is_retained_without_fake_graph_connector(network_config):
    parent = latlng_to_cell(48.4, -123.2, 6)
    empty_geometry = gpd.GeoDataFrame(
        columns=["H3_INDEX", "H3_RESOLUTION", "HAS_WATER_OVERLAP", "geometry"],
        geometry="geometry",
        crs="EPSG:4326",
    )
    water = box(-124.0, 47.0, -123.9, 47.1)
    full, clipped, support = _append_hierarchy_only_parents(
        empty_geometry,
        empty_geometry.copy(),
        pd.DataFrame(columns=["H3_INDEX"]),
        {parent},
        resolution=6,
        water_geometry=water,
        aoi=water,
        config=network_config,
    )

    assert full["H3_INDEX"].tolist() == [parent]
    assert clipped.geometry.iloc[0].is_empty
    assert support.loc[0, "WATER_AREA_M2"] == 0
    assert bool(support.loc[0, "IS_HIERARCHY_ONLY_PARENT"])
    assert support.loc[0, "GRAPH_CONNECTION_STATUS"] == "disconnected"
    assert support.loc[0, "GRAPH_QC_REASON"] == ("hierarchy_parent_without_geometric_water_overlap")


def test_small_support_graph_contract_and_determinism(network_config):
    water = box(-123.2, 48.4, -123.1, 48.5)
    full, clipped, support = _build_geometry_and_base_support(water, water, 8, network_config)
    edges = _build_edges(support, water, 8, network_config)
    _assign_components(support, edges)
    connectors = _build_connectors(support, water, 8, network_config)
    support = support.sort_values("H3_INDEX").reset_index(drop=True)
    edges = edges.sort_values(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).reset_index(drop=True)
    connectors = connectors.sort_values("H3_INDEX").reset_index(drop=True)

    validate_geometry_products(full, clipped, 8)
    validate_support(
        support,
        8,
        water_mask_version=network_config.water_mask_version,
        spatial_support_version=network_config.spatial_support_version,
        area_tolerance_m2=network_config.area_tolerance_m2,
    )
    validate_edges(edges, support, 8)
    validate_connectors(connectors, support, 8)
    assert support["WATER_FRACTION"].between(0, 1).all()
    assert np.allclose(support["WATER_FRACTION"] + support["LAND_FRACTION"], 1.0)
    assert (edges["SOURCE_H3_INDEX"] < edges["TARGET_H3_INDEX"]).all()
    assert not edges.duplicated(["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]).any()

    neighborhoods = _build_neighborhoods(
        support,
        edges,
        connectors,
        8,
        network_config,
    )
    validate_neighborhoods(
        neighborhoods,
        support,
        8,
        maximum_hops=network_config.maximum_neighborhood_hops,
    )
    self_rows = neighborhoods.loc[
        neighborhoods["SOURCE_H3_INDEX"] == neighborhoods["TARGET_H3_INDEX"]
    ]
    assert len(self_rows) == len(support)
    assert (self_rows["MINIMUM_HOP_COUNT"] == 0).all()
    assert neighborhoods["MINIMUM_HOP_COUNT"].max() <= 4

    rebuilt = support.copy()
    rebuilt["GRAPH_DEGREE"] = 0
    rebuilt["GRAPH_CONNECTION_STATUS"] = "disconnected"
    rebuilt["WATER_COMPONENT_ID"] = None
    shuffled = edges.sample(frac=1.0, random_state=7).reset_index(drop=True)
    _assign_components(rebuilt, shuffled)
    graph_cells = support.loc[support["GRAPH_DEGREE"] > 0, "H3_INDEX"]
    expected = support.set_index("H3_INDEX").loc[graph_cells, "WATER_COMPONENT_ID"].to_dict()
    observed = rebuilt.set_index("H3_INDEX").loc[graph_cells, "WATER_COMPONENT_ID"].to_dict()
    assert observed == expected


def test_offline_water_mask_support_to_bathymetry_fixture(tmp_path, network_config):
    """Exercise the P0 fixture without downloads or repository artifacts."""

    import rasterio
    from rasterio.transform import from_bounds

    water = box(-123.2, 48.4, -123.1, 48.5)
    _full, _clipped, support = _build_geometry_and_base_support(water, water, 8, network_config)
    edges = _build_edges(support, water, 8, network_config)
    _assign_components(support, edges)
    connectors = _build_connectors(support, water, 8, network_config)
    neighborhoods = _build_neighborhoods(support, edges, connectors, 8, network_config)

    raster_path = tmp_path / "offline_bathymetry.tif"
    elevation = np.linspace(-5.0, -205.0, 64 * 64, dtype="float32").reshape(64, 64)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=elevation.shape[0],
        width=elevation.shape[1],
        count=1,
        dtype=elevation.dtype,
        crs="EPSG:4326",
        transform=from_bounds(*water.bounds, elevation.shape[1], elevation.shape[0]),
        nodata=-9999.0,
    ) as target:
        target.write(elevation, 1)

    output = _aggregate_raster(
        raster_path,
        support["H3_INDEX"].astype(str).tolist(),
        8,
        "positive_down",
        (0.1, 0.9),
        2,
        (),
        "EPSG:32610",
        neighborhoods,
    )
    assert output["H3_INDEX"].tolist() == support["H3_INDEX"].astype(str).tolist()
    assert output["BATHYMETRY"].notna().any()
    fractions = output.filter(regex=r"^BATHYMETRY_FRAC_").dropna(how="all")
    assert np.allclose(fractions.sum(axis=1), 1.0)


def test_component_id_is_lexicographically_smallest_cell():
    origin = "8828f1d489fffff"
    cells = sorted(grid_disk(origin, 1))[:4]
    support = pd.DataFrame(
        {
            "H3_INDEX": cells,
            "GRAPH_DEGREE": 0,
            "GRAPH_CONNECTION_STATUS": "disconnected",
            "WATER_COMPONENT_ID": None,
        }
    )
    edges = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": [min(cells[0], cells[1]), min(cells[2], cells[3])],
            "TARGET_H3_INDEX": [max(cells[0], cells[1]), max(cells[2], cells[3])],
            "EDGE_IS_WATER_PASSABLE": [True, True],
        }
    )
    _assign_components(support, edges.sample(frac=1.0, random_state=2))
    assert support.loc[0, "WATER_COMPONENT_ID"] == min(cells[0], cells[1])
    assert support.loc[2, "WATER_COMPONENT_ID"] == min(cells[2], cells[3])


def test_csr_is_symmetric_and_shortest_paths_are_deterministic(network_config):
    water = box(-123.2, 48.4, -123.1, 48.5)
    _full, _clipped, support = _build_geometry_and_base_support(water, water, 8, network_config)
    edges = _build_edges(support, water, 8, network_config)
    _assign_components(support, edges)
    valid = edges.loc[edges["EDGE_IS_WATER_PASSABLE"]]
    graph = _csr(support, valid, 8)
    source = str(graph.cells[0])
    distances, owners = multi_source_shortest_paths(graph, [(source, 0.0, 3)])
    assert distances[0] == 0.0
    assert owners[0] == 3
    for position in range(len(graph.cells)):
        neighbors, _weights = graph.neighbors_of(position)
        for neighbor in neighbors:
            reverse, _reverse_weights = graph.neighbors_of(int(neighbor))
            assert position in reverse


def test_target_mapping_never_uses_unbounded_nearest_cell(network_config):
    water = box(-123.2, 48.4, -123.1, 48.5)
    _full, _clipped, support = _build_geometry_and_base_support(water, water, 8, network_config)
    edges = _build_edges(support, water, 8, network_config)
    _assign_components(support, edges)
    connectors = _build_connectors(support, water, 8, network_config)
    graph = _csr(support, edges.loc[edges["EDGE_IS_WATER_PASSABLE"]], 8)
    positions, distances, reasons = target_graph_mapping(
        graph, support["H3_INDEX"].astype(str).tolist()
    )
    assert (positions >= 0).all()
    terminal = support["GRAPH_CONNECTION_STATUS"] == "terminal_connector"
    assert np.allclose(
        distances[terminal.to_numpy()],
        support.loc[terminal, "CONNECTOR_DISTANCE_M"].to_numpy(),
    )
    assert set(connectors.loc[connectors["CONNECTOR_IS_WATER_PASSABLE"], "H3_INDEX"]).issubset(
        set(support.loc[terminal, "H3_INDEX"])
    )
    assert reasons.shape == positions.shape


def test_h8_to_h6_crosswalk_uses_h3_parent(network_config):
    water = box(-123.2, 48.4, -123.15, 48.45)
    supports = {}
    for resolution in (6, 8):
        _full, _clipped, support = _build_geometry_and_base_support(
            water, water, resolution, network_config
        )
        edges = _build_edges(support, water, resolution, network_config)
        _assign_components(support, edges)
        _build_connectors(support, water, resolution, network_config)
        supports[resolution] = support
    crosswalk = _crosswalk(supports, network_config)
    assert crosswalk is not None
    assert len(crosswalk) == len(supports[8])
    assert set(crosswalk["PARENT_H3_INDEX"]).issubset(set(supports[6]["H3_INDEX"]))
    assert crosswalk["PARENT_IN_MARINE_SUPPORT"].all()

    dry_parent = str(crosswalk["PARENT_H3_INDEX"].iloc[0])
    pruned_supports = {
        6: supports[6].loc[supports[6]["H3_INDEX"] != dry_parent].copy(),
        8: supports[8],
    }
    dry_parent_crosswalk = _crosswalk(pruned_supports, network_config)
    dry_rows = dry_parent_crosswalk.loc[dry_parent_crosswalk["PARENT_H3_INDEX"] == dry_parent]
    assert not dry_rows["PARENT_IN_MARINE_SUPPORT"].any()
    assert (dry_rows["PARENT_WATER_AREA_M2"] == 0.0).all()
    assert dry_rows["PARENT_WATER_COMPONENT_ID"].isna().all()


def test_manifest_checksum_mismatch_fails_closed(tmp_path):
    artifact = tmp_path / "artifact.parquet"
    artifact.write_bytes(b"canonical")
    payload = {
        "artifacts": [
            {
                "path": str(artifact),
                "checksum": checksum_path(artifact),
            }
        ]
    }
    _verify_artifact(artifact, payload)
    artifact.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="checksum"):
        _verify_artifact(artifact, payload)


def test_manifest_relative_artifact_resolves_against_candidate_root(tmp_path, monkeypatch):
    artifact = tmp_path / "data/processed/artifact.parquet"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"candidate")
    monkeypatch.setenv("SEASCAPE_CANDIDATE_ROOT", str(tmp_path))
    payload = {
        "artifacts": [
            {
                "path": "data/processed/artifact.parquet",
                "checksum": checksum_path(artifact),
            }
        ]
    }

    _verify_artifact(artifact, payload)


def test_manifest_schema_version_mismatch_fails_closed():
    payload = {
        "dataset_family": "environment.seascape.h3_marine_spatial_support",
        "schema_version": "999",
        "water_mask_version": "territorial_water_v1",
        "spatial_support_version": "marine_spatial_support_v1",
        "water_input": {},
        "resolved_config": {},
        "schemas": {"test.artifact": {"fields": []}},
        "artifacts": [
            {
                "dataset_id": "test.artifact",
                "path": "artifact.parquet",
                "checksum": "sha256:unused",
                "row_count": 1,
                "schema_version": "999",
            }
        ],
    }
    with pytest.raises(ValueError, match="schema version"):
        validate_manifest_payload(payload)
