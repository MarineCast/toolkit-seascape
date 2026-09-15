from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from seascape.core.config.paths import project_root
from seascape.core.data.registry import DATASETS
from seascape.coastal_configuration.exposure_and_enclosure.build import (
    OUTPUT_COLUMNS as EXPOSURE_COLUMNS,
)
from seascape.coastal_configuration.shoreline_proximity.build import (
    OUTPUT_COLUMNS as SHORELINE_COLUMNS,
)
from seascape.coastal_configuration.waterbody_morphometry.build import (
    OUTPUT_COLUMNS as MORPHOMETRY_COLUMNS,
)
from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
    BC_SOURCE,
)
from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
    ESTUARY_COLUMNS as MAPPED_ESTUARY_COLUMNS,
)
from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
    FEATURE_COLUMNS as ESTUARY_COLUMNS,
)
from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
    US_SOURCE,
)
from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
    _validate as validate_estuarine_connectivity,
)
from seascape.hydrologic_connectivity.fluvial_connectivity.build import (
    FEATURE_COLUMNS as FLUVIAL_COLUMNS,
)
from seascape.workflow import stage_names


def test_private_graph_migrations_have_no_remaining_consumer_entrypoints():
    import importlib

    modules = (
        importlib.import_module(
            "seascape.coastal_configuration."
            "exposure_and_enclosure.build"
        ),
        importlib.import_module(
            "seascape.coastal_configuration."
            "shoreline_proximity.build"
        ),
        importlib.import_module(
            "seascape.coastal_configuration."
            "waterbody_morphometry.build"
        ),
        importlib.import_module(
            "seascape.hydrologic_connectivity."
            "estuarine_connectivity.build"
        ),
        importlib.import_module(
            "seascape.hydrologic_connectivity."
            "fluvial_connectivity.build"
        ),
        importlib.import_module(
            "seascape.spatial_support.h3_geometry.build"
        ),
    )
    retired = {
        "_adjacency",
        "_distance_to_open_water",
        "_graph_components",
        "_marine_graph_distances",
        "_non_land_cells",
        "_non_land_context_cells",
        "_target_graph_indices",
        "_target_network_values",
        "_water_network_distances",
        "_fallback_radial_path",
        "_radial_path",
        "_nearest_mouth_distances",
        "_target_graph_mapping",
        "_geom_to_h3shape",
        "_h3_hex_polygon",
    }
    for module in modules:
        assert not retired.intersection(vars(module)), module.__name__


def test_water_network_package_exports_canonical_algorithms():
    from seascape.spatial_support import water_network

    for name in (
        "attach_points_to_graph",
        "multi_source_shortest_paths",
        "nullable_string_values",
        "target_graph_mapping",
    ):
        assert callable(getattr(water_network, name))


def test_all_network_consumers_export_lineage_and_qc():
    for columns in (
        SHORELINE_COLUMNS,
        EXPOSURE_COLUMNS,
        MORPHOMETRY_COLUMNS,
        FLUVIAL_COLUMNS,
        ESTUARY_COLUMNS,
    ):
        assert "NETWORK_CONNECTOR_METHOD" in columns
        assert "NETWORK_CONNECTOR_DISTANCE_M" in columns
        assert "NETWORK_DISTANCE_QC_REASON" in columns


def test_hydrologic_consumers_retain_component_lineage():
    assert "MARINE_NETWORK_COMPONENT_ID" in FLUVIAL_COLUMNS
    assert "WATER_COMPONENT_ID" in ESTUARY_COLUMNS


def test_estuary_validation_allows_qc_explained_disconnected_support():
    features = pd.DataFrame(
        {
            "H3_INDEX": ["connected", "disconnected"],
            "DISTANCE_TO_ESTUARY_M": [100.0, 200.0],
            "WATER_NETWORK_DISTANCE_TO_ESTUARY_M": [125.0, np.nan],
            "WATER_COMPONENT_ID": ["component-a", "component-b"],
            "NETWORK_CONNECTOR_METHOD": ["direct", None],
            "NETWORK_CONNECTOR_DISTANCE_M": [0.0, np.nan],
            "NETWORK_DISTANCE_QC_REASON": [None, "no_connected_estuary_in_component"],
        },
        columns=ESTUARY_COLUMNS,
    )
    estuaries = pd.DataFrame(
        [
            {
                "ESTUARY_ID": "bc-1",
                "SOURCE_DATASET": BC_SOURCE,
                "MARINE_GRAPH_H3_INDEX": "graph-a",
                "MARINE_GRAPH_SNAP_DISTANCE_M": 10.0,
            },
            {
                "ESTUARY_ID": "us-1",
                "SOURCE_DATASET": US_SOURCE,
                "MARINE_GRAPH_H3_INDEX": "graph-b",
                "MARINE_GRAPH_SNAP_DISTANCE_M": 20.0,
            },
        ]
    ).reindex(columns=MAPPED_ESTUARY_COLUMNS)

    validate_estuarine_connectivity(
        features,
        estuaries,
        SimpleNamespace(expected_h3_cell_count=2, estuary_graph_snap_max_km=15.0),
    )


def test_estuary_validation_rejects_unexplained_null_network_distance():
    features = pd.DataFrame(
        {
            "H3_INDEX": ["disconnected"],
            "DISTANCE_TO_ESTUARY_M": [200.0],
            "WATER_NETWORK_DISTANCE_TO_ESTUARY_M": [np.nan],
            "WATER_COMPONENT_ID": ["component-b"],
            "NETWORK_CONNECTOR_METHOD": [None],
            "NETWORK_CONNECTOR_DISTANCE_M": [np.nan],
            "NETWORK_DISTANCE_QC_REASON": [None],
        },
        columns=ESTUARY_COLUMNS,
    )
    estuaries = pd.DataFrame(
        [
            {
                "ESTUARY_ID": "bc-1",
                "SOURCE_DATASET": BC_SOURCE,
                "MARINE_GRAPH_H3_INDEX": "graph-a",
                "MARINE_GRAPH_SNAP_DISTANCE_M": 10.0,
            },
            {
                "ESTUARY_ID": "us-1",
                "SOURCE_DATASET": US_SOURCE,
                "MARINE_GRAPH_H3_INDEX": "graph-b",
                "MARINE_GRAPH_SNAP_DISTANCE_M": 20.0,
            },
        ]
    ).reindex(columns=MAPPED_ESTUARY_COLUMNS)

    with pytest.raises(ValueError, match="preserve a network QC reason"):
        validate_estuarine_connectivity(
            features,
            estuaries,
            SimpleNamespace(expected_h3_cell_count=1, estuary_graph_snap_max_km=15.0),
        )


def test_materialized_network_consumers_match_producer_contracts():
    root = project_root()
    contracts = {
        Path(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "shoreline_proximity/SHORELINE_PROXIMITY_RES_8.parquet"
        ): SHORELINE_COLUMNS,
        Path(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "exposure_and_enclosure/EXPOSURE_AND_ENCLOSURE_RES_8.parquet"
        ): EXPOSURE_COLUMNS,
        Path(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "waterbody_morphometry/WATERBODY_MORPHOMETRY_RES_8.parquet"
        ): MORPHOMETRY_COLUMNS,
        Path(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
            "estuarine_connectivity/ESTUARINE_CONNECTIVITY_RES_8.parquet"
        ): ESTUARY_COLUMNS,
    }
    if not all((root / path).exists() for path in contracts):
        pytest.skip("materialized seascape artifacts are not part of a clean checkout")
    for relative_path, columns in contracts.items():
        assert set(pq.read_schema(root / relative_path).names) == set(columns), relative_path


def test_canonical_workflow_rebuilds_network_consumers_after_water_graph():
    names = stage_names()
    graph_index = names.index("h3-marine-spatial-support")
    catalog_index = names.index("environment-feature-catalog")
    for name in (
        "seascape-shoreline-proximity",
        "seascape-exposure-and-enclosure",
        "seascape-waterbody-morphometry",
        "seascape-estuarine-connectivity",
        "seascape-anthropogenic",
    ):
        consumer_index = names.index(name)
        assert graph_index < consumer_index < catalog_index


def test_dataset_catalog_registers_reproducible_seascape_dependencies():
    for dataset_id in (
        "environment.seascape.bathymetry_r8",
        "environment.seascape.geomorphometry_r8",
        "environment.seascape.shoreline_proximity_r8",
        "environment.seascape.exposure_and_enclosure_r8",
        "environment.seascape.waterbody_morphometry_r8",
        "environment.seascape.estuarine_connectivity_r8",
        "environment.seascape.anthropogenic_r8",
    ):
        DATASETS.get(dataset_id)
    reef_dependencies = {
        str(value) for value in DATASETS.get("environment.seascape.reef_habitat_r8").dependencies
    }
    assert "environment.seascape.bathymetry_r8" in reef_dependencies
    assert "environment.seascape.geomorphometry_r8" in reef_dependencies
    for name in ("seagrass_habitat", "kelp_habitat", "reef_habitat"):
        for resolution in (6, 8):
            dependencies = {
                str(value)
                for value in DATASETS.get(f"environment.seascape.{name}_r{resolution}").dependencies
            }
            assert "environment.seascape.h3_marine_support_r8" in dependencies
            assert "environment.seascape.h3_water_edges_r8" in dependencies
            if resolution == 6:
                assert "environment.seascape.h3_marine_support_r6" in dependencies
                assert "environment.seascape.h3_parent_child_r8_to_r6" in dependencies
