"""OSM extract identity, geometry closure and center semantics."""

import hashlib
import io
import json
import shutil
from types import SimpleNamespace

import pytest

from seascape.anthropogenic.sources import _normalize_osm
from seascape.utils.habitat_acquisition import _download_overpass
from seascape.utils.osm_extract import _elements, download_osm_extract

BOX = {"min_lon": -125, "min_lat": 48, "max_lon": -123, "max_lat": 50}
XML = b"""<osm version="0.6">
<node id="1" version="1" lon="-124.1" lat="49.0"/>
<node id="2" version="1" lon="-123.9" lat="49.2"/>
<way id="3" version="2"><nd ref="1"/><nd ref="2"/><tag k="man_made" v="pier"/></way>
<relation id="4" version="1"><member type="way" ref="3" role="platform"/><tag k="type" v="site"/><tag k="amenity" v="ferry_terminal"/></relation>
</osm>"""


def test_cached_extract_keeps_snapshot_lineage_without_network(tmp_path, monkeypatch):
    from seascape.utils import habitat_acquisition as acquisition
    from seascape.utils import osm_extract

    source = {
        "kind": "osm_pbf",
        "raw_filename": "source.json",
        "extracts": [{"url": "https://example.test/snapshot.pbf"}],
    }
    config = acquisition.HabitatDownloadConfig(
        "fixture", BOX, tmp_path, 1, 10, False, {"osm": source}
    )
    monkeypatch.setattr(
        acquisition, "load_habitat_download_config", lambda *args: config
    )
    evidence = {
        "method": "fixture",
        "extracts": [{"sha256": "a" * 64}],
        "downloaded_at_utc": "2026-01-01T00:00:00Z",
    }

    def download(session, source, destination, **kwargs):
        destination.write_text(
            json.dumps({"elements": [{"type": "node", "id": 1}], "_orcacast": evidence})
        )
        return 1, {"osm_extract": evidence}

    monkeypatch.setattr(osm_extract, "download_osm_extract", download)
    _, manifest = acquisition.download_habitat_sources("fixture", "unused")
    original = json.loads(manifest.read_text())["sources"][0]
    monkeypatch.setattr(
        osm_extract,
        "download_osm_extract",
        lambda *args, **kwargs: pytest.fail("unexpected acquisition"),
    )
    acquisition.download_habitat_sources("fixture", "unused")
    cached = json.loads(manifest.read_text())["sources"][0]
    assert cached["status"] == "existing"
    assert cached["osm_extract"] == evidence
    assert cached["retrieved_at_utc"] == original["retrieved_at_utc"]


def test_center_records_include_nonpolygon_relations_and_preserve_identity():
    records, stats = _elements(io.BytesIO(XML), BOX, max_nodes=10, max_elements=10)
    assert stats == {"referenced_nodes": 2, "tagged_objects": 2}
    assert [(r["type"], r["id"]) for r in records] == [("relation", 4), ("way", 3)]
    assert records[1]["version"] == 2
    for record in records:
        assert record["center"] == {"lon": -124.0, "lat": 49.1}


def test_incomplete_or_cyclic_references_never_become_guessed_centers():
    for xml in [
        b'<osm><way id="3"><nd ref="99"/><tag k="man_made" v="pier"/></way></osm>',
        b'<osm><relation id="4"><member type="relation" ref="4"/><tag k="amenity" v="ferry_terminal"/></relation></osm>',
    ]:
        with pytest.raises(ValueError, match="incomplete geometry references"):
            _elements(io.BytesIO(xml), BOX, max_nodes=10, max_elements=10)
    with pytest.raises(ValueError, match="node budget"):
        _elements(io.BytesIO(XML), BOX, max_nodes=1, max_elements=10)


def test_overpass_runtime_error_with_partial_elements_uses_next_endpoint(tmp_path):
    documents = iter(
        [
            {
                "elements": [{"type": "node", "id": 1}],
                "remark": "runtime error: timed out",
            },
            {"elements": [{"type": "node", "id": 2, "lon": -124, "lat": 49}]},
        ]
    )

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return next(documents)

    session = SimpleNamespace(post=lambda *args, **kwargs: Response())
    path = tmp_path / "osm.json"
    _download_overpass(
        session,
        {
            "endpoints": ["https://first.invalid", "https://second.invalid"],
            "attempts_per_endpoint": 1,
            "query_filters": ['["man_made"="pier"]'],
        },
        path,
        bbox=BOX,
        timeout=1,
    )
    assert [r["id"] for r in json.loads(path.read_text())["elements"]] == [2]


def test_coastal_water_without_country_polygons_keeps_cross_border_source(
    tmp_path, monkeypatch
):
    import geopandas as gpd
    from shapely.geometry import box

    from seascape.anthropogenic import sources

    path = tmp_path / "osm.json"
    path.write_text(
        json.dumps(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lon": -124,
                        "lat": 49,
                        "tags": {"man_made": "pier"},
                    }
                ]
            }
        )
    )
    water = tmp_path / "water.parquet"
    gpd.GeoDataFrame(
        {"AREA": ["coastal"]}, geometry=[box(-125, 48, -123, 50)], crs=4326
    ).to_parquet(water)
    monkeypatch.setattr(
        sources,
        "load_habitat_download_config",
        lambda *args: SimpleNamespace(
            raw_dir=tmp_path,
            sources={"osm": {"raw_filename": "osm.json", "normalizer": "osm"}},
        ),
    )
    monkeypatch.setattr(
        sources, "_processing", lambda *args: {"deduplication_tolerance_m": 100}
    )
    monkeypatch.setattr(
        sources,
        "load_water_network_config",
        lambda *args: SimpleNamespace(water_polygon_path=water),
    )
    result = sources.load_anthropogenic_inventory("unused")
    assert result.JURISDICTION.tolist() == ["CROSS_BORDER"]


@pytest.mark.skipif(
    shutil.which("osmium") is None, reason="native osmium-tool integration"
)
def test_native_extract_route_uses_bound_source_bytes_and_existing_normalizer(tmp_path):
    path = tmp_path / "fixture.osm"
    path.write_bytes(XML)
    source = {
        "extracts": [{"path": str(path), "sha256": hashlib.sha256(XML).hexdigest()}],
        "tag_filters": ["nwr/man_made=pier", "nwr/amenity=ferry_terminal"],
        "geometry_mode": "center",
    }
    output = tmp_path / "source.json"
    count, metadata = download_osm_extract(None, source, output, bbox=BOX, timeout=5)
    assert count == 2
    assert metadata["osm_extract"]["area_footprints_qualified"] is False
    assert json.loads(output.read_text())["elements"][0]["id"] == 4
    normalized = _normalize_osm(output, "osm_test", source)
    assert set(normalized.FEATURE_CLASS) == {"pier", "ferry_terminal"}
    assert normalized.geom_type.eq("Point").all()
    assert not normalized.SUPPORTS_AREA.any()
    original = output.read_bytes()
    with pytest.raises(ValueError, match="byte budget"):
        download_osm_extract(
            None, {**source, "maximum_bytes": 1}, output, bbox=BOX, timeout=5
        )
    assert output.read_bytes() == original
    assert not output.with_suffix(".json.part").exists()
