from dataclasses import replace

import pandas as pd
import pytest
from shapely.geometry import box

from seascape.core.geo.h3 import grid_disk, latlng_to_cell
from seascape.spatial_support.water_network.build import (
    _build_geometry_and_base_support,
)
from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.spatial_support.water_network.geometry import water_path_metrics
from seascape.spatial_support.water_network.graph import (
    _iter_edge_batches,
    _iter_neighborhood_batches,
)
from seascape.spatial_support.water_network.validation import validate_neighborhoods


def test_source_batches_keep_full_graph_context_and_hop_distance():
    config = replace(load_water_network_config(), maximum_neighborhood_hops=2)
    cells = [latlng_to_cell(48.2, -123.2 + offset, 8) for offset in (0, 0.02, 0.04)]
    support = pd.DataFrame(
        {
            "H3_INDEX": cells,
            "GRAPH_CONNECTION_STATUS": "graph_node",
            "GRAPH_QC_REASON": None,
            "WATER_MASK_VERSION": "fixture",
            "SPATIAL_SUPPORT_VERSION": "fixture",
        }
    )
    edges = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": cells[:2],
            "TARGET_H3_INDEX": cells[1:],
            "EDGE_DISTANCE_M": [10.0, 20.0],
            "EDGE_IS_WATER_PASSABLE": [True, True],
        }
    )
    batches = list(
        _iter_neighborhood_batches(
            support,
            edges,
            pd.DataFrame(),
            8,
            config,
            source_cells=[cells[0]],
            batch_sources=1,
        )
    )
    assert len(batches) == 1
    row = batches[0].set_index("TARGET_H3_INDEX").loc[cells[2]]
    assert row.MINIMUM_HOP_COUNT == 2
    assert row.NETWORK_DISTANCE_M == 30.0
    assert set(batches[0].SOURCE_H3_INDEX) == {cells[0]}
    validate_neighborhoods(
        batches[0], support, 8, maximum_hops=2, source_cells=[cells[0]]
    )
    outside = batches[0].copy()
    outside.loc[outside.TARGET_H3_INDEX == cells[2], "TARGET_H3_INDEX"] = "outside"
    with pytest.raises(ValueError, match="target lies outside"):
        validate_neighborhoods(
            outside, support, 8, maximum_hops=2, source_cells=[cells[0]]
        )


def test_neighbor_source_validation_rejects_duplicates_and_missing_context():
    config = load_water_network_config()
    cell = latlng_to_cell(48.2, -123.2, 8)
    support = pd.DataFrame({"H3_INDEX": [cell]})
    for sources in ([cell, cell], ["outside"]):
        with pytest.raises(ValueError, match="unique cells"):
            list(
                _iter_neighborhood_batches(
                    support,
                    pd.DataFrame(),
                    pd.DataFrame(),
                    8,
                    config,
                    source_cells=sources,
                )
            )


def test_edge_batches_bound_rows_and_keep_land_barrier_checks():
    config = replace(load_water_network_config(), edge_chunk_size=2, max_workers=1)
    water = box(-123.3, 48.1, -123.0, 48.3).difference(
        box(-123.155, 48.1, -123.145, 48.3)
    )
    cells = grid_disk(latlng_to_cell(48.2, -123.15, 8), 2)
    _, _, support = _build_geometry_and_base_support(
        water, box(-123.3, 48.1, -123.0, 48.3), 8, config, cells=cells
    )
    calls = []

    def evaluate(source_lon, source_lat, target_lon, target_lat):
        calls.append((source_lon, source_lat, target_lon, target_lat))
        return water_path_metrics(
            source_lon,
            source_lat,
            target_lon,
            target_lat,
            water,
            maximum_segment_m=100,
            outside_tolerance_m=1,
        )

    batches = list(_iter_edge_batches(support, None, 8, config, path_metrics=evaluate))
    assert all(len(batch) <= 2 for batch in batches)
    edges = pd.concat(batches, ignore_index=True)
    assert len(calls) == len(edges)
    assert edges.EDGE_IS_WATER_PASSABLE.any()
    assert (~edges.EDGE_IS_WATER_PASSABLE).any()
    assert (edges.loc[~edges.EDGE_IS_WATER_PASSABLE, "WATER_PATH_FRACTION"] < 1).all()
