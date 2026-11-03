import json
from dataclasses import replace

import pytest

from seascape.hydrologic_connectivity.freshwater_sources.download import (
    ArcGISSource,
    _download_arcgis_geojson,
    _query_tiles,
)


class Response:
    def __init__(self, document):
        self.document = document

    def raise_for_status(self):
        pass

    def json(self):
        return self.document


class Session:
    def __init__(self, documents):
        self.documents = iter(documents)

    def get(self, *args, **kwargs):
        return Response(next(self.documents))


def fixture(tmp_path):
    source = ArcGISSource(
        "test",
        "https://fixture.invalid/0",
        tmp_path / "source.geojson",
        "1=1",
        ("*",),
        0,
        1,
    )
    options = dict(
        bbox=dict(min_lon=-125, min_lat=49, max_lon=-124, max_lat=50),
        tile_degrees=1,
        timeout=1,
        overwrite=False,
    )
    return source, options


def features(ids):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"objectid": value},
                "geometry": {"type": "Point", "coordinates": [-124.5, 49.5]},
            }
            for value in ids
        ],
    }


def test_reuse_requires_same_source_query_extent_and_bytes(tmp_path):
    source, options = fixture(tmp_path)
    path, count = _download_arcgis_geojson(
        Session([{"objectIds": [1], "objectIdFieldName": "OBJECTID"}, features([1])]),
        source,
        **options,
    )
    assert count == 1
    assert _download_arcgis_geojson(Session([]), source, **options) == (path, 1)
    with pytest.raises(ValueError, match="differs"):
        _download_arcgis_geojson(
            Session([]), replace(source, where="changed"), **options
        )
    path.write_text(json.dumps(features([2])))
    with pytest.raises(ValueError, match="differs"):
        _download_arcgis_geojson(Session([]), source, **options)


def test_duplicate_or_incomplete_service_response_never_publishes(tmp_path):
    source, options = fixture(tmp_path)
    with pytest.raises(RuntimeError, match="duplicate, missing"):
        _download_arcgis_geojson(
            Session([{"objectIds": [1, 2]}, features([1, 1])]), source, **options
        )
    assert not source.raw_path.exists()
    with pytest.raises(RuntimeError, match="inventory is incomplete"):
        _download_arcgis_geojson(
            Session([{"objectIds": [1], "exceededTransferLimit": True}]),
            source,
            **options,
        )
    assert not source.raw_path.exists()


def test_unbound_existing_file_and_unbounded_tiling_are_rejected(tmp_path):
    source, options = fixture(tmp_path)
    source.raw_path.write_text(json.dumps(features([1])))
    with pytest.raises(ValueError, match="no bound source identity"):
        _download_arcgis_geojson(Session([]), source, **options)
    with pytest.raises(ValueError, match="tile budget"):
        _query_tiles(options["bbox"], 0.000001)
