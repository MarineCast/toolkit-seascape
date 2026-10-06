"""Small native island/hole partition adoption tests; no download or regional fill."""

import json

import geopandas as gpd
import pytest
from shapely.geometry import box

from seascape.spatial_support.water_geometry.partition import (
    load_source_partition,
    raw_sha256,
)


def partition(tmp_path):
    file = tmp_path / "land-water.gpkg"
    land = box(-123.01, 48.49, -123.0, 48.50)
    rectangle = box(-123.02, 48.48, -122.99, 48.51)
    water = rectangle.difference(land)
    for layer, geometry in [
        ("land_area", land),
        ("water_area", water),
        ("reporting_water", water),
    ]:
        gpd.GeoDataFrame(geometry=[geometry], crs=4326).to_file(
            file, layer=layer, driver="GPKG"
        )
    record = {
        "geometry_file": file.name,
        "geometry_sha256": raw_sha256(file),
        "water_equation": "study_rectangle minus land_area; valid nonoverlapping tile pieces with union semantics",
        "coverage": "Pinned global baseline covers the whole rectangle",
        "topology_checks": {
            "valid_land_water": True,
            "positive_area_overlap": False,
            "partition_gaps": False,
        },
    }
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(record))
    return path, record


def test_adoption_preserves_island_holes_and_native_cells(tmp_path):
    path, _ = partition(tmp_path)
    source = load_source_partition(path)
    water = source.pieces().geometry.iloc[0]
    assert len(water.interiors) == 1
    assert water.area == pytest.approx(
        box(-123.02, 48.48, -122.99, 48.51).area
        - box(-123.01, 48.49, -123.0, 48.50).area
    )
    assert source.native_reporting_cells() == sorted(
        set(source.native_reporting_cells())
    )


@pytest.mark.parametrize("change", ["coverage", "topology", "hash"])
def test_no_unknown_coverage_or_unbound_geometry(tmp_path, change):
    path, record = partition(tmp_path)
    if change == "coverage":
        record["coverage"] = ""
    elif change == "topology":
        record["topology_checks"]["partition_gaps"] = True
    else:
        record["geometry_sha256"] = "0" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        load_source_partition(path)
