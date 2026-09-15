import json
from pathlib import Path

import pytest

from seascape.utils import habitat_acquisition as module


def test_cache_requires_matching_query_bytes_and_preserves_retrieval(tmp_path, monkeypatch):
    source = {"kind": "arcgis", "layer_url": "https://example.test/0", "raw_filename": "data.json"}
    cfg = module.HabitatDownloadConfig(
        "fixture", {"west": 1.0}, tmp_path, 1.0, 10, False, {"a": source}
    )
    monkeypatch.setattr(module, "load_habitat_download_config", lambda *a: cfg)

    def download(session, source, destination, **kwargs):
        destination.write_text(json.dumps({"features": [{"id": 1}]}))
        return 1

    monkeypatch.setattr(module, "_download_arcgis", download)
    _, manifest = module.download_habitat_sources("fixture", Path("unused"))
    original = json.loads(manifest.read_text())
    module.download_habitat_sources("fixture", Path("unused"))
    reused = json.loads(manifest.read_text())
    assert reused["sources"][0]["retrieved_at_utc"] == original["sources"][0]["retrieved_at_utc"]
    assert reused["sources"][0]["status"] == "existing"
    source["layer_url"] = "https://example.test/1"
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="identity"):
        module.download_habitat_sources("fixture", Path("unused"))
    assert manifest.read_bytes() == before
    module.download_habitat_sources("fixture", Path("unused"), overwrite=True)
    assert json.loads(manifest.read_text())["sources"][0]["source_url"].endswith("/1")
    (tmp_path / "data.json").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        module.download_habitat_sources("fixture", Path("unused"))


def test_bbox_change_and_legacy_cache_are_not_silently_adopted(tmp_path):
    source = {"kind": "wfs", "url": "https://example.test", "raw_filename": "data.json"}
    first = module.acquisition_identity(source, {"west": 1})
    assert first != module.acquisition_identity(source, {"west": 2})
    path = tmp_path / "data.json"
    path.write_text("old")
    with pytest.raises(ValueError, match="unverified"):
        module.validate_cached_source(path, first, {})


def test_canonical_shoreline_collection_config_resolves_both_sources():
    cfg = module.load_habitat_download_config(
        "shoreline_characterization", "config/data/environment_seascape.yaml"
    )
    assert cfg.sources["wa_nwfsc_shoreline_typology"]["url"].endswith(".zip")
    assert cfg.sources["bc_shorezone_shore_units"]["kind"] == "wfs"


def test_shoreline_collector_installs_validated_acquired_files(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import LineString

    from seascape.coastal_configuration.shoreline_characterization import (
        download as shore,
    )

    cache = tmp_path / "cache"
    cache.mkdir()
    original = cache / "shore.geojson"
    gpd.GeoDataFrame({"x": [1]}, geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326").to_file(
        original, driver="GeoJSON"
    )
    target = tmp_path / "installed/shore.geojson"
    cfg = module.HabitatDownloadConfig(
        "shoreline_characterization",
        {},
        cache,
        1,
        10,
        False,
        {"test": {"raw_filename": original.name}},
    )
    monkeypatch.setattr(module, "download_habitat_sources", lambda *a, **k: None)
    monkeypatch.setattr(module, "load_habitat_download_config", lambda *a: cfg)
    monkeypatch.setattr(
        shore,
        "load_source_config",
        lambda *a: {"base_dir": tmp_path, "sources": {"test": {"path": str(target)}}},
    )
    result = shore.collect_shoreline_sources("unused")
    assert result["test"][0] == target and target.read_bytes() == original.read_bytes()
    shore.collect_shoreline_sources("unused")
    target.write_text("different")
    with pytest.raises(ValueError, match="differs"):
        shore.collect_shoreline_sources("unused")
    assert target.read_text() == "different"
