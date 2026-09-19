from __future__ import annotations

import importlib
import json
import shutil
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
                "schema_version": 3,
                "release_id": "a" * 64,
                "storage_root": ".seascape/releases/" + "a" * 64,
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
    generation = workspace / ".seascape/releases" / ("a" * 64)
    for source in (artifact, family_manifest, release_manifest):
        target = generation / source.relative_to(workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return workspace, generation / artifact.relative_to(workspace), release_manifest


def test_discovery_and_exact_resolution_resolution(tmp_path: Path) -> None:
    workspace, artifact, _manifest = _release_fixture(tmp_path)

    assert list_products(workspace=workspace) == ("bathymetry",)
    assert list_resolutions("bathymetry", workspace=workspace) == (6,)
    resolved = resolve_product(
        workspace=workspace, product="bathymetry", resolution=6
    )

    assert resolved.path == artifact
    assert resolved.dataset_id == "environment.seascape.bathymetry_r6"
    assert resolved.release_id == "a" * 64
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


def _candidate_fixture(root: Path, value: bytes) -> Path:
    """Minimal audited candidate to exercise the real publisher/resolver boundary."""
    from seascape.release import PROCESSED_ROOT
    artifact = root / PROCESSED_ROOT / "seafloor_physiography/bathymetry/BATHYMETRY_RES_6.parquet"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(value)
    family = artifact.with_name("bathymetry_manifest.json")
    family.write_text(json.dumps({
        "schema_version": "3.0.0",
        "artifacts": [{"path": str(artifact.relative_to(root))}],
    }))
    for relative in ("config/feature_catalog.yaml", "config/feature_eligibility.yaml",
                     "docs/products.md", "config/data/environment_seascape.yaml"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    audit = root / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({"artifact_release_passed": True, "feature_eligibility_complete": True}))
    return artifact


def test_two_publications_retain_prior_product_and_manifest_bytes(tmp_path):
    from seascape.release import publish_candidate_release
    workspace, candidate = tmp_path / "workspace", tmp_path / "candidate"
    source = _candidate_fixture(candidate, b"release A")
    publish_candidate_release(canonical_project_root=workspace, candidate_project_root=candidate)
    first = resolve_product(workspace=workspace, product="bathymetry", resolution=6)
    manifest_bytes = first.manifest_path.read_bytes()
    source.write_bytes(b"release B")
    publish_candidate_release(canonical_project_root=workspace, candidate_project_root=candidate)
    second = resolve_product(workspace=workspace, product="bathymetry", resolution=6)
    assert first.release_id != second.release_id
    assert first.path.read_bytes() == b"release A"
    assert first.manifest_path.read_bytes() == manifest_bytes
    assert second.path.read_bytes() == b"release B"
    assert checksum_path(first.path) == first.checksum
    old = resolve_product(workspace=workspace, product="bathymetry", resolution=6,
                          release_id=first.release_id)
    assert old == first
    assert list_products(workspace=workspace, release_id=first.release_id) == ("bathymetry",)
    assert list_resolutions("bathymetry", workspace=workspace, release_id=first.release_id) == (6,)
    # Identical publication must preserve the archived generation, including timestamp.
    publish_candidate_release(canonical_project_root=workspace, candidate_project_root=candidate)
    assert resolve_product(workspace=workspace, product="bathymetry", resolution=6) == second


def test_generation_is_rolled_back_when_canonical_promotion_fails(tmp_path, monkeypatch):
    import os
    from seascape.release import publish_candidate_release
    workspace, candidate = tmp_path / "workspace", tmp_path / "candidate"
    source = _candidate_fixture(candidate, b"release A")
    publish_candidate_release(canonical_project_root=workspace, candidate_project_root=candidate)
    first = resolve_product(workspace=workspace, product="bathymetry", resolution=6)
    source.write_bytes(b"release B")
    original_replace = os.replace
    canonical_artifact = workspace / source.relative_to(candidate)
    def fail_new_artifact(source_path, destination):
        if Path(destination) == canonical_artifact and ".staging" in Path(source_path).parts:
            raise OSError("injected canonical failure")
        return original_replace(source_path, destination)
    with monkeypatch.context() as scoped:
        scoped.setattr(os, "replace", fail_new_artifact)
        with pytest.raises(OSError, match="injected"):
            publish_candidate_release(canonical_project_root=workspace, candidate_project_root=candidate)
    assert resolve_product(workspace=workspace, product="bathymetry", resolution=6) == first
    assert sorted(p.name for p in (workspace / ".seascape/releases").iterdir()) == [first.release_id]


def test_legacy_mutable_release_requires_republication(tmp_path):
    workspace, _, manifest = _release_fixture(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["schema_version"] = 2
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="republish"):
        resolve_product(workspace=workspace, product="bathymetry", resolution=6)


@pytest.mark.parametrize("release_id", ["../outside", "x" * 64, ""])
def test_historical_release_id_is_validated(tmp_path, release_id):
    with pytest.raises(ValueError, match="SHA-256"):
        list_products(workspace=tmp_path, release_id=release_id)
