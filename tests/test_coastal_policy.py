import math

import geopandas as gpd
import h3
import numpy as np
import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, box

from seascape.spatial_support.coastal_policy import (
    CoastalMask,
    build_coastal_mask,
    geodesic_coastal_corridor,
    native_mask_membership,
)


def source(geometry, **columns):
    return gpd.GeoDataFrame(
        {
            "SOURCE_ID": ["fixture"],
            "SOURCE_VERSION": ["1"],
            "RIGHTS": ["synthetic"],
            **columns,
        },
        geometry=[geometry],
        crs=4326,
    )


def test_ellipsoidal_corridor_reaches_requested_distance_in_every_direction():
    geod = Geod(ellps="WGS84")
    # A short source line tends to a point; check bearings independently with Geod.
    coast = LineString([(-125, 49), (-125, 49.000001)])
    corridor, report = geodesic_coastal_corridor(coast)
    for bearing in np.arange(0, 360, 5):
        lon, lat, _ = geod.fwd(-125, 49, bearing, 22223)
        assert corridor.covers(Point(lon, lat)), bearing
        lon, lat, _ = geod.fwd(-125, 49, bearing, 22231)
        assert not corridor.covers(Point(lon, lat)), bearing
    assert report["minimum_checked_geodesic_distance_m"] >= 22224
    assert report["maximum_checked_geodesic_distance_m"] <= 22229
    assert not report["source_position_accuracy_established"]


def test_coastal_mask_keeps_typed_inland_water_and_excludes_source_land():
    coast = source(LineString([(-125, 48.8), (-125, 49.2)]))
    context = source(box(-126, 48, -123, 50))
    marine = source(box(-126, 48, -125, 50).union(box(-125, 49.04, -123.8, 49.08)))
    inland = source(
        box(-125, 49.04, -123.8, 49.08),
        WATERBODY_ID=["fixture-inlet"],
        WATERBODY_TYPE=["inlet"],
    )
    mask = build_coastal_mask(coast, marine, inland, context)
    assert mask.geometry.covers(Point(-123.9, 49.06))
    assert not mask.geometry.covers(Point(-123.9, 49.1))
    assert not mask.geometry.covers(Point(-125.8, 49))
    assert mask.report["membership"] == "positive_area_intersection"
    assert not mask.report["acquisition_bbox_used_as_reporting_selector"]
    assert not mask.report["physical_full_catalog_qualified"]
    assert coast.geometry.iloc[0].equals(LineString([(-125, 48.8), (-125, 49.2)]))


def test_truncated_source_context_and_untyped_inland_water_fail():
    coast = source(LineString([(-125, 48.8), (-125, 49.2)]))
    inland = source(
        box(-125, 49.04, -124.8, 49.08), WATERBODY_ID=["a"], WATERBODY_TYPE=["inlet"]
    )
    marine = source(box(-126, 48, -123, 50))
    with pytest.raises(ValueError, match="context truncates"):
        build_coastal_mask(
            coast, marine, inland, source(box(-125.01, 48.7, -124.9, 49.3))
        )
    inland["WATERBODY_TYPE"] = "acquisition_rectangle"
    with pytest.raises(ValueError, match="explicit marine waterbody"):
        build_coastal_mask(coast, marine, inland, marine)


def test_native_membership_keeps_positive_slivers_whose_centres_are_outside():
    key = h3.latlng_to_cell(49, -125, 8)
    lat, lon = h3.cell_to_latlng(key)
    tiny = box(lon + 0.0001, lat + 0.0001, lon + 0.0002, lat + 0.0002)
    mask = CoastalMask(tiny, {"mask_geometry_sha256": "synthetic"})
    full, clipped = native_mask_membership(mask, 8, max_cells=100)
    assert full.H3_INDEX.tolist() == [key]
    assert 0 < full.WATER_FRACTION.iloc[0] < 0.01
    assert clipped.crs.to_epsg() == 6933
    assert clipped.to_crs(4326).geometry.iloc[0].symmetric_difference(tiny).area < 1e-15
    assert not tiny.covers(Point(lon, lat))
    with pytest.raises(ValueError, match="cell bound"):
        native_mask_membership(
            CoastalMask(box(-126, 48, -124, 50), mask.report), 8, max_cells=1
        )


def test_native_membership_partitions_water_across_source_tile_seams():
    from pyproj import Transformer
    from shapely import segmentize, transform

    geometry = box(-125.1, 49.49, -124.9, 49.51)
    full, wet = native_mask_membership(
        CoastalMask(geometry, {"mask_geometry_sha256": "synthetic"}), 6, max_cells=100
    )
    project = Transformer.from_crs(4326, 6933, always_xy=True)
    expected = transform(
        segmentize(geometry, 0.001), project.transform, interleaved=False
    )
    assert full.geometry.is_valid.all() and wet.geometry.is_valid.all()
    assert wet.WATER_FRACTION.between(0, 1).all()
    assert wet.WATER_AREA_M2.sum() == pytest.approx(expected.area, rel=1e-8)
    assert wet.geometry.union_all().symmetric_difference(expected).area < 0.01


@pytest.mark.parametrize(
    "distance,tolerance", [(0, 5), (22224, 0), (math.inf, 5), (22224, 100)]
)
def test_invalid_geometry_resource_contracts_fail(distance, tolerance):
    with pytest.raises(ValueError, match="bounds are invalid"):
        geodesic_coastal_corridor(
            LineString([(-125, 49), (-125, 49.1)]),
            distance_m=distance,
            tolerance_m=tolerance,
        )


def test_water_network_reporting_geometry_uses_mask_and_rejects_missing_context(
    tmp_path,
):
    from types import SimpleNamespace

    from seascape.spatial_support.water_network.build import _model_reporting_geometry

    mask = box(-125, 49, -124.9, 49.1)
    path = tmp_path / "mask.parquet"
    source(mask).to_parquet(path, index=False)
    config = SimpleNamespace(
        reporting_mask_path=path,
        model_bbox=dict(min_lon=-130, min_lat=45, max_lon=-120, max_lat=54),
    )
    assert _model_reporting_geometry(config, box(-126, 48, -124, 50)).equals(mask)
    with pytest.raises(ValueError, match="outside the canonical water context"):
        _model_reporting_geometry(config, box(-126, 48, -125, 49))
    config.reporting_mask_path = None
    assert _model_reporting_geometry(config, box(-126, 48, -124, 50)).equals(
        box(-130, 45, -120, 54)
    )


def test_tiled_reporting_membership_matches_unpartitioned_projected_geometry():
    from seascape.spatial_support.water_network.build import _positive_reporting_overlap

    reporting = box(-125.7, 49, -124.4, 49.8).difference(box(-125.3, 49.2, -125, 49.5))
    cells = gpd.GeoDataFrame(
        geometry=[
            box(-125.8, 49.1, -125.7, 49.2),
            box(-125.701, 49.1, -125.699, 49.2),
            box(-125.2, 49.3, -125.1, 49.4),
            box(-125.6, 49.1, -125.5, 49.2),
        ],
        crs=4326,
    )
    projected_mask = gpd.GeoSeries([reporting], crs=4326).to_crs(6933).iloc[0]
    expected = cells.to_crs(6933).geometry.intersection(projected_mask).area.gt(0)
    assert _positive_reporting_overlap(cells, reporting).tolist() == expected.tolist()


def test_canonical_candidates_keep_wet_cell_surrounding_a_small_land_hole():
    from shapely.geometry import Polygon

    from seascape.spatial_support.water_network.build import _tiled_overlap_cells

    key = "881299481dfffff"
    cell = Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(key)])
    lat, lon = h3.cell_to_latlng(key)
    water = cell.buffer(0.02).difference(Point(lon, lat).buffer(0.0001))
    assert cell.intersection(water).area > cell.area * 0.9
    assert key in _tiled_overlap_cells(water, 8)


def test_public_coastal_builder_publishes_bound_provenance_and_memberships(
    tmp_path, monkeypatch
):
    import json

    from seascape.spatial_support.coastal_policy_build import build_coastal_policy
    from seascape.spatial_support.provenance import water_geometry_provenance

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    frames = {
        "coastline_path": source(LineString([(-125, 49), (-125, 49.02)])),
        "marine_water_path": source(box(-126, 48, -124, 50)),
        "inland_water_path": source(
            box(-125, 49, -124.99, 49.02),
            WATERBODY_ID=["synthetic-inlet"],
            WATERBODY_TYPE=["inlet"],
        ),
        "source_context_path": source(box(-126, 48, -124, 50)),
    }
    section = {
        "output_dir": "processed",
        "resolutions": [6],
        "offshore_distance_m": 1000,
        "graph_context_buffer_m": 2000,
        "max_cells": 100,
    }
    for name, frame in frames.items():
        path = inputs / (name + ".parquet")
        frame.to_parquet(path, index=False)
        section[name] = str(path)
    config = tmp_path / "project.json"
    config.write_text(json.dumps({"coastal_policy": section}))
    paths = build_coastal_policy(config)
    assert len(paths) == 5 and all(p.exists() for p in paths)
    lineage = water_geometry_provenance(
        tmp_path / "processed/COASTAL_CONTEXT_WATER.parquet", tmp_path
    )
    assert lineage is not None and len(lineage["sources"]) == 4
    manifest = json.loads(
        (tmp_path / "processed/water_geometry_manifest.json").read_text()
    )
    assert manifest["metadata"]["native_memberships"]["6"]["native_cells"] > 0
    assert manifest["metadata"]["reporting_membership"] == "positive_area_intersection"
    assert not manifest["metadata"]["coastal_policy"]["physical_full_catalog_qualified"]
    # A changed source cannot keep passing the same manifest check.
    with paths[0].open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError):
        water_geometry_provenance(
            tmp_path / "processed/COASTAL_CONTEXT_WATER.parquet", tmp_path
        )


def test_reporting_geometry_loader_excludes_context_and_checks_identity(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import pandas as pd

    from seascape.spatial_support.water_network import load as module

    path = tmp_path / "geometry.parquet"
    frame = gpd.GeoDataFrame(
        {"H3_INDEX": ["context", "target"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs=6933,
    )
    frame.to_parquet(path, index=False)
    monkeypatch.setattr(
        module,
        "load_water_network_config",
        lambda _: SimpleNamespace(
            clipped_geometry_path=lambda r: path, full_geometry_path=lambda r: path
        ),
    )
    monkeypatch.setattr(
        module,
        "load_model_area_support",
        lambda *a, **k: pd.DataFrame({"H3_INDEX": ["target"]}),
    )
    loaded = module.load_model_area_geometry(8, "unused", verify_checksum=False)
    assert loaded.H3_INDEX.tolist() == ["target"]
    frame.loc[0, "H3_INDEX"] = "target"
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="unique H3"):
        module.load_model_area_geometry(8, "unused", verify_checksum=False)
