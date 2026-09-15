from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

import seascape as seascape
from seascape.core.artifacts import TransactionalFamilyPublisher
from seascape.utils import artifacts as artifact_utils
from seascape.utils.artifacts import (
    atomic_write_parquet,
    build_manifest,
    load_manifest,
    portable_artifact_path,
    validate_manifest,
)
from seascape.utils.config import stable_config_hash
from seascape.utils.spatial import (
    align_to_model_support,
    expanded_bbox_polygon,
    h3_cell_set_hash,
)


def test_every_seascape_module_imports() -> None:
    package_root = Path(seascape.__file__).parent
    modules = []
    for source in package_root.rglob("*.py"):
        relative = source.relative_to(package_root)
        parts = relative.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        module = ".".join((seascape.__name__, *parts))
        if module != seascape.__name__:
            modules.append(module)
    modules = sorted(set(modules))
    assert modules
    for module in modules:
        importlib.import_module(module)


def test_h3_hash_is_order_independent_and_alignment_preserves_missingness() -> None:
    support = pd.DataFrame({"H3_INDEX": ["b", "a"], "H3_RESOLUTION": [8, 8]})
    features = pd.DataFrame({"H3_INDEX": ["a"], "VALUE": [2.0]})
    aligned = align_to_model_support(
        support,
        features,
        feature_label="fixture",
        support_columns=("H3_INDEX", "H3_RESOLUTION"),
    )
    assert aligned["H3_INDEX"].tolist() == ["b", "a"]
    assert pd.isna(aligned.loc[0, "VALUE"])
    assert h3_cell_set_hash(["a", "b"]) == h3_cell_set_hash(["b", "a", "a"])


def test_alignment_rejects_cells_outside_support() -> None:
    support = pd.DataFrame({"H3_INDEX": ["a"]})
    features = pd.DataFrame({"H3_INDEX": ["outside"], "VALUE": [1.0]})
    with pytest.raises(ValueError, match="outside canonical"):
        align_to_model_support(support, features, feature_label="fixture")


def test_common_manifest_detects_checksum_tampering(tmp_path) -> None:
    artifact = tmp_path / "artifact.parquet"
    pd.DataFrame({"H3_INDEX": ["a"], "VALUE": [1.0]}).to_parquet(artifact, index=False)
    payload = build_manifest(
        dataset_family="environment.seascape.fixture",
        run_id="fixture",
        resolved_config={"path": artifact},
        artifacts=[artifact],
        project_root=tmp_path,
        sources=[{"name": "fixture", "license": "test"}],
        upstream_artifacts=[],
        attribution=[{"text": "fixture", "license": "test"}],
        source_completeness="complete",
    )
    assert payload["sources"][0]["observation_period"].startswith("Not documented")
    assert payload["sources"][0]["redistribution_restrictions"]
    assert payload["sources"][0]["source_warning"]
    validate_manifest(payload, project_root=tmp_path, verify_artifacts=True)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_manifest(payload, project_root=tmp_path, verify_artifacts=True)


def test_portable_artifact_path_preserves_external_disposable_roots(tmp_path) -> None:
    repository_root = tmp_path / "repository"
    internal = repository_root / "data" / "artifact.parquet"
    external = tmp_path / "disposable" / "artifact.parquet"
    assert portable_artifact_path(internal, root=repository_root) == "data/artifact.parquet"
    assert portable_artifact_path(external, root=repository_root) == str(external.resolve())


def test_atomic_family_publisher_does_not_publish_incomplete_family(tmp_path) -> None:
    destination = tmp_path / "published.txt"
    with pytest.raises(FileNotFoundError):
        with TransactionalFamilyPublisher(tmp_path, run_id="fixture") as publisher:
            publisher.stage_path(destination)
            publisher.publish()
    assert not destination.exists()


def test_incomplete_family_preserves_previous_artifacts(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("previous", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        with TransactionalFamilyPublisher(tmp_path, run_id="fixture-incomplete") as publisher:
            publisher.stage_path(first).write_text("replacement", encoding="utf-8")
            publisher.stage_path(second)
            publisher.publish()
    assert first.read_text(encoding="utf-8") == "previous"
    assert not second.exists()


def test_family_transaction_promotes_manifest_last(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "artifact.parquet"
    manifest_path = tmp_path / "manifest.json"
    promoted: list[str] = []
    original_replace = artifact_utils.os.replace

    def observe(source, destination):
        source_path = Path(source)
        if (
            source_path.parent.parent.name == ".staging"
            and Path(destination).parent != source_path.parent
        ):
            promoted.append(Path(destination).name)
        return original_replace(source, destination)

    monkeypatch.setattr(artifact_utils.os, "replace", observe)
    with TransactionalFamilyPublisher(tmp_path, run_id="fixture-transaction") as publisher:
        publisher.stage_parquet(pd.DataFrame({"H3_INDEX": ["new"]}), artifact)
        publisher.stage_manifest(manifest_path, {"replacement": True})
        publisher.publish()
    assert promoted == ["artifact.parquet", "manifest.json"]
    assert load_manifest(manifest_path) == {"replacement": True}


def test_atomic_parquet_failure_preserves_previous_artifact(tmp_path) -> None:
    destination = tmp_path / "artifact.parquet"
    original = pd.DataFrame({"H3_INDEX": ["old"]})
    atomic_write_parquet(original, destination)

    class BrokenFrame:
        def to_parquet(self, path, **_kwargs):
            Path(path).write_bytes(b"partial")
            raise RuntimeError("serialization failed")

    with pytest.raises(RuntimeError, match="serialization failed"):
        atomic_write_parquet(BrokenFrame(), destination)
    assert pd.read_parquet(destination).equals(original)
    assert not list(tmp_path.glob(".*.part"))


def test_shared_expanded_bbox_matches_family_formula() -> None:
    bbox = {"min_lon": -124.0, "min_lat": 48.0, "max_lon": -123.0, "max_lat": 49.0}
    expanded = expanded_bbox_polygon(bbox, 10.0)
    assert expanded.bounds[0] < bbox["min_lon"]
    assert expanded.bounds[1] < bbox["min_lat"]
    assert expanded.bounds[2] > bbox["max_lon"]
    assert expanded.bounds[3] > bbox["max_lat"]


def test_stable_config_hash_normalizes_mapping_order_and_paths(tmp_path) -> None:
    left = {"b": [2, 1], "a": tmp_path / "x"}
    right = {"a": str(tmp_path / "x"), "b": (2, 1)}
    assert stable_config_hash(left) == stable_config_hash(right)
