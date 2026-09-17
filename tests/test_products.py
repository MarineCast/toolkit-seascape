from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from seascape.core.artifacts.checksums import checksum_path
from seascape.products import list_products, list_resolutions, resolve_product


def _release_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    artifact = (
        workspace
        / "data/processed/domain/environmental_layer/seascape/"
        "seafloor_physiography/bathymetry/BATHYMETRY_RES_6.parquet"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"synthetic parquet fixture")
    family_manifest = artifact.with_name("bathymetry_manifest.json")
    family_manifest.write_text('{"schema_version": "3.0.0"}', encoding="utf-8")
    release_manifest = (
        workspace
        / "data/processed/domain/environmental_layer/seascape/"
        "seascape_release_manifest.json"
    )
    relative_artifact = str(artifact.relative_to(workspace))
    relative_family = str(family_manifest.relative_to(workspace))
    release_manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "release_id": "fixture-release",
                "artifact_release_passed": True,
                "family_manifest_checksums": {
                    relative_family: checksum_path(family_manifest)
                },
                "governed_artifacts": {},
                "products": {
                    "environment.seascape.bathymetry_r6": {
                        "product_id": "bathymetry",
                        "dataset_id": "environment.seascape.bathymetry_r6",
                        "path": relative_artifact,
                        "checksum": checksum_path(artifact),
                        "checksum_algorithm": "sha256",
                        "schema_version": "1",
                        "producer": "seascape.seafloor_physiography.bathymetry.build",
                        "producer_code_identity": {
                            "git_revision": "fixture",
                            "dirty": False,
                            "source_tree_sha256": "fixture",
                        },
                        "resolution": 6,
                        "grain": ["H3_INDEX"],
                        "spatial_support": {"kind": "h3", "resolution": 6},
                        "manifest_path": relative_family,
                        "coverage": {"h3_resolutions": [6]},
                        "source_vintage": [{"name": "synthetic"}],
                        "rights": {"licensing": [{"license": "fixture"}]},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return workspace, artifact, release_manifest


def test_discovery_and_exact_resolution_resolution(tmp_path: Path) -> None:
    workspace, artifact, _manifest = _release_fixture(tmp_path)

    assert list_products(workspace=workspace) == ("bathymetry",)
    assert list_resolutions("bathymetry", workspace=workspace) == (6,)
    resolved = resolve_product(
        workspace=workspace, product="bathymetry", resolution=6
    )

    assert resolved.path == artifact
    assert resolved.dataset_id == "environment.seascape.bathymetry_r6"
    assert resolved.release_id == "fixture-release"
    assert resolved.grain == ("H3_INDEX",)
    with pytest.raises(TypeError):
        resolved.coverage["changed"] = True  # type: ignore[index]


def test_missing_product_and_resolution_fail_without_fallback(tmp_path: Path) -> None:
    workspace, _artifact, _manifest = _release_fixture(tmp_path)

    with pytest.raises(KeyError, match="Unknown released"):
        resolve_product(workspace=workspace, product="kelp", resolution=6)
    with pytest.raises(KeyError, match=r"available resolutions: \[6\]"):
        resolve_product(workspace=workspace, product="bathymetry", resolution=8)


def test_checksum_mismatch_and_incomplete_release_fail(tmp_path: Path) -> None:
    workspace, artifact, release_manifest = _release_fixture(tmp_path)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        resolve_product(workspace=workspace, product="bathymetry", resolution=6)

    workspace, _artifact, release_manifest = _release_fixture(tmp_path / "second")
    payload = json.loads(release_manifest.read_text(encoding="utf-8"))
    payload["artifact_release_passed"] = False
    release_manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or unaudited"):
        list_products(workspace=workspace)


def test_resolver_works_outside_repository_and_imports_no_orcacast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _artifact, _manifest = _release_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    resolved = resolve_product(
        workspace=workspace, product="bathymetry", resolution=6
    )
    products_module = importlib.import_module("seascape.products")

    assert resolved.resolution == 6
    assert "orcacast" not in products_module.__dict__
