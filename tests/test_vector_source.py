"""Bounded source selection must preserve native attributes and clipped geometry."""

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box, mapping

from seascape.utils.vector_source import read_vector_source

BBOX = {"min_lon": -125, "min_lat": 48, "max_lon": -123, "max_lat": 50}


def test_nonempty_flowline_source_without_qualified_terminals_is_available(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from seascape.hydrologic_connectivity.freshwater_sources import build

    frame = gpd.GeoDataFrame(
        {
            "TERMINALFL": [None],
            "TERMINAL_QC": ["unknown"],
            "FTYPE": [460],
            "FCODE": [46006],
            "NEXT_DOWN": [1],
            "ENDORHEIC": [0],
        },
        geometry=[LineString([(-124, 49), (-124, 49.1)])],
        crs=4326,
    )
    path = tmp_path / "source.parquet"
    frame.to_parquet(path)
    config = SimpleNamespace(
        raw_paths={
            name: path
            for name in (
                "bc_stream_network",
                "bc_river_polygons",
                "us_network_flowlines",
                "us_river_polygons",
            )
        },
        context_bbox=BBOX,
    )
    monkeypatch.setattr(build, "_hydrorivers_path", lambda config: path)
    frames = build._load_source_frames(config)
    assert frames["us_network_flowlines"].empty
    assert frames["hydrorivers"].empty
    assert frames["us_network_flowlines"].attrs["terminal_availability"] == {
        "unknown": 1
    }


@pytest.mark.parametrize("suffix", ["geojson", "parquet", "gpkg"])
@pytest.mark.parametrize("crs", [4326, 32610])
def test_streamed_context_matches_full_geospatial_selection(tmp_path, suffix, crs):
    source = gpd.GeoDataFrame(
        {"ID": [1, 2, 3], "NAME": ["crossing", None, "outside"]},
        geometry=[
            LineString([(-126, 49), (-124, 49)]),
            LineString([(-124, 48.5), (-124, 49.5)]),
            LineString([(-122, 47), (-121, 47)]),
        ],
        crs=4326,
    ).to_crs(crs)
    path = tmp_path / ("source." + suffix)
    if suffix == "parquet":
        source.to_parquet(path)
        full = gpd.read_parquet(path)
    else:
        source.to_file(path, driver="GeoJSON" if suffix == "geojson" else "GPKG")
        full = gpd.read_file(path)
    expected = gpd.clip(full.to_crs(4326), box(-125, 48, -123, 50)).set_index("ID")
    actual = read_vector_source(path, bbox=BBOX, clip=True, batch_size=1).set_index(
        "ID"
    )
    assert set(actual.index) == set(expected.index)
    for key in expected.index:
        assert actual.loc[key].geometry.equals_exact(expected.loc[key].geometry, 1e-10)
    assert pd.isna(actual.loc[2, "NAME"])
    assert read_vector_source(path, bbox=BBOX, clip=True, batch_size=2).ID.tolist() == [
        1,
        2,
    ]


def test_geojson_streaming_preserves_nullable_large_integer_identity(tmp_path):
    path = tmp_path / "source.geojson"
    identities = [9007199254740993, None, 9007199254740995]
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "ID": key,
                            **({"LATE_FIELD": 1} if key is None else {}),
                        },
                        "geometry": mapping(LineString([(-124, 49), (-124, 49.1)])),
                    }
                    for key in identities
                ],
            }
        )
    )
    result = read_vector_source(path, bbox=BBOX, clip=True, batch_size=2)
    assert result.ID.iloc[0] == identities[0]
    assert pd.isna(result.ID.iloc[1])
    assert result.ID.iloc[2] == identities[2]
    assert result.LATE_FIELD.iloc[1] == 1
    assert pd.isna(result.LATE_FIELD.iloc[0])


def test_empty_selection_retains_schema_and_requires_known_crs(tmp_path):
    source = gpd.GeoDataFrame(
        {"ID": [1]}, geometry=[LineString([(0, 0), (1, 1)])], crs=4326
    )
    path = tmp_path / "source.parquet"
    source.to_parquet(path)
    selected = read_vector_source(path, bbox=BBOX, clip=True, batch_size=1)
    assert selected.empty and selected.crs.to_epsg() == 4326
    assert "ID" in selected
    with pytest.raises(ValueError, match="positive"):
        read_vector_source(path, batch_size=0)


def test_river_system_stream_preserves_inventory_and_global_part_ids(tmp_path):
    from seascape.hydrologic_connectivity.freshwater_sources.river_system_aggregation import (
        StreamedRiverSystems,
        build_river_systems,
    )

    frames = {
        "bc_stream_network": gpd.GeoDataFrame(
            {
                "LINEAR_FEATURE_ID": [1, 2],
                "GNIS_NAME": [None, "river"],
                "EDGE_TYPE": [1000, 1000],
            },
            geometry=[
                LineString([(-124, 49), (-124, 49.1)]),
                LineString([(-124, 49.2), (-124, 49.3)]),
            ],
            crs=4326,
        ),
        "us_network_flowlines": gpd.GeoDataFrame(
            {
                "COMID": [11, 12],
                "GNIS_NAME": ["creek", None],
                "FTYPE": [460, 558],
                "FCODE": [46006, 55800],
            },
            geometry=[
                LineString([(-124, 48.1), (-124, 48.2)]),
                LineString([(-124, 48.3), (-124, 48.4)]),
            ],
            crs=4326,
        ),
        "hydrorivers": gpd.GeoDataFrame(
            {"HYRIV_ID": [21]},
            geometry=[LineString([(-124, 48.5), (-124, 48.6)])],
            crs=4326,
        ),
    }
    specs = []
    for name, dataset, identity, label in [
        (
            "bc_stream_network",
            "BC_FWA_STREAM_NETWORK",
            "LINEAR_FEATURE_ID",
            "GNIS_NAME",
        ),
        ("us_network_flowlines", "US_NHD_SMALL_SCALE", "COMID", "GNIS_NAME"),
        ("hydrorivers", "HYDRORIVERS_V10", "HYRIV_ID", None),
    ]:
        path = tmp_path / (name + ".parquet")
        frames[name].to_parquet(path)
        specs.append((path, dataset, identity, label))
    expected = build_river_systems(frames).set_index("RIVER_SEGMENT_ID").sort_index()
    for batch_size in (1, 2):
        output = tmp_path / f"systems-{batch_size}.parquet"
        writer = StreamedRiverSystems(specs, BBOX, batch_size=batch_size)
        writer.to_parquet(output)
        actual = gpd.read_parquet(output).set_index("RIVER_SEGMENT_ID").sort_index()
        assert len(writer) == len(expected)
        assert actual.index.tolist() == expected.index.tolist()
        for column in expected.columns:
            if column == "geometry":
                assert actual.geometry.geom_equals(expected.geometry).all()
            else:
                pd.testing.assert_series_equal(
                    actual[column].astype("string"),
                    expected[column].astype("string"),
                    check_index_type=False,
                )
