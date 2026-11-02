"""Bounded exact graph dependency closure for terrain production."""

from __future__ import annotations

import gc

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from seascape.spatial_support.water_network.config import load_water_network_config
from seascape.spatial_support.water_network.load import (
    _manifest,
    _verify_artifact,
    load_model_area_support,
)
from seascape.spatial_support.water_network.validation import validate_neighborhoods
from seascape.utils.spatial import water_neighborhood_lookup


def derive_bounded(source, config, config_path, *, chunk_size=1024):
    from .build import _derive_metrics

    if chunk_size < 1:
        raise ValueError("Terrain chunk size must be positive")
    network = load_water_network_config(config_path)
    path = network.neighborhood_path(config.h3_resolution)
    _verify_artifact(path, _manifest(network))
    support = load_model_area_support(config.h3_resolution, config_path)
    canonical = sorted(support.H3_INDEX.astype(str))
    # Validate all rows by complete source groups; uniqueness cannot cross groups.
    for first in range(0, len(canonical), chunk_size):
        keys = canonical[first : first + chunk_size]
        frame = pq.read_table(
            path,
            filters=[("SOURCE_H3_INDEX", "in", keys)],
            use_threads=False,
            pre_buffer=False,
        ).to_pandas()
        validate_neighborhoods(
            frame,
            support,
            config.h3_resolution,
            maximum_hops=network.maximum_neighborhood_hops,
            source_cells=set(keys),
        )
        del frame
        gc.collect()
        pa.default_memory_pool().release_unused()
    hops = set(
        (config.neighbor_ring, config.openness_radius_rings, *config.neighborhood_rings)
    )
    if max(hops) > network.maximum_neighborhood_hops:
        raise ValueError("Terrain radius exceeds materialized graph support")
    targets = sorted(source.H3_INDEX.astype(str))
    if set(targets) - set(canonical):
        raise ValueError("Terrain source keys lie outside canonical support")

    def rows(keys, radius):
        return pq.read_table(
            path,
            columns=["SOURCE_H3_INDEX", "TARGET_H3_INDEX", "MINIMUM_HOP_COUNT"],
            use_threads=False,
            pre_buffer=False,
            filters=[
                ("SOURCE_H3_INDEX", "in", sorted(keys)),
                ("MINIMUM_HOP_COUNT", "<=", radius),
            ],
        ).to_pandas()

    results = []
    for first in range(0, len(targets), chunk_size):
        keys = targets[first : first + chunk_size]
        near = rows(keys, max(hops))
        core = set(keys) | set(near.TARGET_H3_INDEX)
        slope_near = rows(core, config.neighbor_ring)
        halo = core | set(slope_near.TARGET_H3_INDEX)
        selected = pd.concat([near, slope_near], ignore_index=True).drop_duplicates(
            ["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]
        )
        lookups = {n: water_neighborhood_lookup(selected, maximum_hops=n) for n in hops}
        result = _derive_metrics(
            source.loc[source.H3_INDEX.isin(halo)], config, lookups
        )
        results.append(result.loc[result.H3_INDEX.isin(keys)].copy())
        del near, slope_near, selected, lookups, result
        gc.collect()
        pa.default_memory_pool().release_unused()
    return (
        pd.concat(results, ignore_index=True)
        .sort_values("H3_INDEX")
        .reset_index(drop=True)
    )
