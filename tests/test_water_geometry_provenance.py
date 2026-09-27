"""Exploratory lineage through real production publishers, with offline fixtures."""

from __future__ import annotations

import importlib.util
import json
import socket
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import box

from seascape import demo
from seascape.core.artifacts.checksums import checksum_path
from seascape.seafloor_physiography.bathymetry import pipeline
from seascape.spatial_support.h3_geometry.build import build_h3_grid_layers
from seascape.spatial_support.provenance import water_geometry_provenance
from seascape.spatial_support.water_network.build import build_marine_spatial_support
from seascape.utils.artifacts import load_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[1]
BOUNDS = (-123.20, 48.40, -123.10, 48.50)
spec = importlib.util.spec_from_file_location(
    "san_juan_test_helper", ROOT / "notebooks/_san_juan_workflow.py"
)
assert spec and spec.loader
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Provenance regression must not acquire sources")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(workflow.requests, "get", deny)
    monkeypatch.setattr(pipeline, "download_gebco_geotiff", deny)
    for key in ("SEASCAPE_COMMON_CONFIG", "SEASCAPE_CANDIDATE_ROOT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", "/unused")


def mask(workspace, tmp_path):
    """A synthetic shapefile ZIP with the explorer's expected input layout."""
    source = tmp_path / "synthetic-land"
    source.mkdir(exist_ok=True)
    gpd.GeoDataFrame(geometry=[box(-123.20, 48.40, -123.19, 48.50)], crs=4326).to_file(
        source / "ne_10m_land.shp"
    )
    (source / "ne_10m_land.VERSION.txt").write_text("SYNTHETIC_TEST\n")
    archive = workspace / "data/raw/natural_earth/ne_10m_land.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zipped:
        for path in source.iterdir():
            zipped.write(path, path.name)
    return workflow.build_exploratory_water_mask(
        workspace, BOUNDS, force_downloads=False
    )


def test_exploratory_mask_has_verified_partial_lineage(tmp_path):
    workspace = tmp_path / "workspace"
    water = mask(workspace, tmp_path)
    payload = load_manifest(water.with_name("water_geometry_manifest.json"))
    validate_manifest(payload, project_root=workspace, verify_artifacts=True)
    observed = water_geometry_provenance(water, workspace)
    assert observed["metadata"]["support_kind"] == "exploratory"
    assert observed["metadata"]["model_eligible"] is False
    assert observed["source_completeness"] == "partial"
    assert observed["sources"][0]["release"] == "SYNTHETIC_TEST"
    assert observed["sources"][0]["checksum"] == checksum_path(
        Path(observed["sources"][0]["path"])
    )
    assert "not canonical" in observed["sources"][0]["source_warning"]
    geometry = gpd.read_parquet(water)
    assert geometry.crs.to_epsg() == 4326
    assert geometry.geometry.iloc[0].equals(box(-123.19, 48.40, -123.10, 48.50))


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("checksum", "checksum mismatch"),
        ("path", "selected mask"),
        ("family", "dataset family"),
        ("eligibility", "model-ineligible"),
        ("kind", "model-ineligible"),
        ("metadata", "must be an object"),
        ("sources", "source records"),
    ],
)
def test_bad_declared_provenance_fails_before_publication(tmp_path, mutation, match):
    workspace = tmp_path / "workspace"
    workflow.prepare_workspace(ROOT, workspace, BOUNDS, (6, 8), force_downloads=False)
    water = mask(workspace, tmp_path)
    manifest = water.with_name("water_geometry_manifest.json")
    payload = load_manifest(manifest)
    if mutation == "checksum":
        payload["artifacts"][0]["checksum"] = "0" * 64
    elif mutation == "path":
        other = water.with_name("other.parquet")
        other.write_bytes(water.read_bytes())
        payload["artifacts"][0]["path"] = str(other)
        payload["artifacts"][0]["checksum"] = checksum_path(other)
    elif mutation == "family":
        payload["dataset_family"] = "unrelated"
    elif mutation == "eligibility":
        payload["metadata"]["model_eligible"] = True
    elif mutation == "kind":
        payload["metadata"]["support_kind"] = "canonical"
    elif mutation == "metadata":
        payload["metadata"] = []
    else:
        payload["sources"] = []
    manifest.write_text(json.dumps(payload))
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    for build in (build_h3_grid_layers, build_marine_spatial_support):
        with pytest.raises(ValueError, match=match):
            build(workspace / "config/data/project.yaml")
    assert {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()} == before


def test_support_products_unchanged_when_lineage_is_present(tmp_path):
    workspace = tmp_path / "workspace"
    config = workspace / "config/data/project.yaml"
    workflow.prepare_workspace(ROOT, workspace, BOUNDS, (6, 8), force_downloads=False)
    domain = yaml.safe_load(
        (workspace / "config/data/environment_seascape.yaml").read_text()
    )
    assert "exploratory" in domain["water_network"]["water_mask_version"]
    assert "exploratory" in domain["water_network"]["spatial_support_version"]
    water = mask(workspace, tmp_path)
    manifest = water.with_name("water_geometry_manifest.json")
    saved = manifest.read_bytes()
    saved_water = water.read_bytes()
    manifest.unlink()
    with pytest.raises(ValueError, match="requires water_geometry_manifest"):
        water_geometry_provenance(water, workspace)
    legacy = gpd.read_parquet(water)
    legacy["AREA"] = "controlled legacy fixture"
    legacy.to_parquet(water, index=False)
    assert water_geometry_provenance(water, workspace) is None
    build_h3_grid_layers(config, max_workers=1)
    build_marine_spatial_support(config)
    paths = [p for p in (workspace / "data/processed").rglob("*.parquet") if p != water]
    before = {p: pd.read_parquet(p) for p in paths}
    water.write_bytes(saved_water)
    manifest.write_bytes(saved)
    build_h3_grid_layers(config, max_workers=1)
    build_marine_spatial_support(config, overwrite=True)
    for path, frame in before.items():
        pd.testing.assert_frame_equal(frame, pd.read_parquet(path), check_exact=True)
    generated = list((workspace / "data/processed").rglob("*manifest.json"))
    assert len(generated) == 3
    for path in generated:
        payload = load_manifest(path)
        validate_manifest(payload, project_root=workspace, verify_artifacts=True)
        assert payload["source_completeness"] == "partial"
        assert payload["sources"][0]["release"] == "SYNTHETIC_TEST"
        if path != manifest:
            assert (
                payload["metadata"]["water_geometry_provenance"]["model_eligible"]
                is False
            )
            assert any(
                i["checksum"] == checksum_path(manifest)
                for i in payload["upstream_artifacts"]
            )
            assert "Canonical territorial-water geometry" not in json.dumps(payload)


def test_bathymetry_retains_mask_lineage_without_numerical_change(tmp_path):
    result = demo.run_demo(tmp_path / "demo-workspace")
    before = pd.read_parquet(result.parquet_path)
    water = mask(result.workspace, tmp_path)
    config_path = result.workspace / "config/demo.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["bathymetry"]["processing"]["water_polygon_path"] = str(water)
    config_path.write_text(yaml.safe_dump(config))
    with demo._environment(result.workspace):
        pipeline.run_pipeline(config_path, skip_download=True, skip_map=True)
    payload = load_manifest(result.manifest_path)
    validate_manifest(payload, project_root=result.workspace, verify_artifacts=True)
    assert payload["source_completeness"] == "partial"
    assert payload["metadata"]["synthetic"] is True
    assert payload["metadata"]["water_geometry_provenance"]["model_eligible"] is False
    assert payload["sources"][0]["name"] == "SYNTHETIC seascape-demo-v1"
    assert any(
        i["checksum"] == checksum_path(water.with_name("water_geometry_manifest.json"))
        for i in payload["upstream_artifacts"]
    )
    pd.testing.assert_frame_equal(
        before, pd.read_parquet(result.parquet_path), check_exact=True
    )


def test_canonical_declared_sources_and_completeness_remain_intact(tmp_path):
    workspace = tmp_path / "workspace"
    water = mask(workspace, tmp_path)
    manifest = water.with_name("water_geometry_manifest.json")
    payload = load_manifest(manifest)
    payload["dataset_family"] = "environment.seascape.territorial_water_geometry"
    payload["metadata"] = {"support_kind": "controlled canonical fixture"}
    payload["source_completeness"] = "complete"
    payload["sources"][0].update(
        name="SYNTHETIC canonical-source declaration",
        provider="fixture",
        release="controlled-test",
    )
    payload["attribution"] = [
        {
            "text": "Controlled canonical metadata fixture",
            "license": "Apache-2.0 synthetic fixture",
        }
    ]
    manifest.write_text(json.dumps(payload))
    observed = water_geometry_provenance(water, workspace)
    assert observed["source_completeness"] == "complete"
    assert observed["sources"] == [
        {
            **payload["sources"][0],
            "path": str(workspace / payload["sources"][0]["path"]),
        }
    ]
    assert observed["attribution"] == payload["attribution"]


def test_bad_mask_lineage_preserves_existing_bathymetry(tmp_path):
    result = demo.run_demo(tmp_path / "demo-workspace")
    water = mask(result.workspace, tmp_path)
    config_path = result.workspace / "config/demo.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["bathymetry"]["processing"]["water_polygon_path"] = str(water)
    config_path.write_text(yaml.safe_dump(config))
    manifest = water.with_name("water_geometry_manifest.json")
    payload = load_manifest(manifest)
    payload["artifacts"][0]["checksum"] = "0" * 64
    manifest.write_text(json.dumps(payload))
    before = {p: p.read_bytes() for p in (result.parquet_path, result.manifest_path)}
    with (
        demo._environment(result.workspace),
        pytest.raises(ValueError, match="checksum mismatch"),
    ):
        pipeline.run_pipeline(config_path, skip_download=True, skip_map=True)
    assert {p: p.read_bytes() for p in before} == before
