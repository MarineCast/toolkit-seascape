from __future__ import annotations

from seascape.spatial_support.water_geometry.download import (
    CONSUMED_WATER_GEOMETRY_SOURCE_NAMES,
    load_water_geometry_source_config,
)


def test_water_geometry_manifest_source_contract_lists_only_consumed_inputs() -> None:
    config = load_water_geometry_source_config("config/data/environment_seascape.yaml")

    assert set(config["sources"]) == set(CONSUMED_WATER_GEOMETRY_SOURCE_NAMES)
    assert "ca_bc_marine_geometries_path" not in config["sources"]
