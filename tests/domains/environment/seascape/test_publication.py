from __future__ import annotations

import json
import multiprocessing
import queue
from pathlib import Path

import pytest

from seascape.core.artifacts import TransactionalFamilyPublisher, checksum_path
from seascape.publication import (
    SeascapeReleasePublisher,
    SeascapeSnapshot,
)
from seascape.release import publish_candidate_release


def _acquire_release_lock(canonical: str, candidate: str, messages) -> None:
    messages.put("attempting")
    with SeascapeReleasePublisher(canonical, candidate, run_id="lock-child"):
        messages.put("acquired")


def test_published_artifact_uses_canonical_checksum_contract(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.txt"
    with TransactionalFamilyPublisher(tmp_path, run_id="checksum-fixture") as publisher:
        staged = publisher.stage_path(destination)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("artifact")
        artifact = publisher.staged_artifact(destination)
        expected = checksum_path(staged, logical_name=destination.name)
        staged_name_checksum = checksum_path(staged)

    assert artifact.checksum == expected
    assert artifact.checksum != staged_name_checksum


def test_release_publisher_promotes_manifest_last(tmp_path: Path, monkeypatch) -> None:
    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "artifact.txt").write_text("new-artifact")
    (candidate / "seascape_release_manifest.json").write_text('{"generation": 2}')
    canonical.mkdir()
    (canonical / "artifact.txt").write_text("old-artifact")
    (canonical / "seascape_release_manifest.json").write_text('{"generation": 1}')

    promoted: list[str] = []
    import os

    replace = os.replace

    def observe(source, destination):
        source_path = Path(source)
        if source_path.parent.parent.name == ".staging":
            promoted.append(Path(destination).name)
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", observe)
    with SeascapeReleasePublisher(canonical, candidate, run_id="release-fixture") as publisher:
        publisher.stage_candidate("seascape_release_manifest.json", manifest=True)
        publisher.stage_candidate("artifact.txt")
        publisher.publish()

    assert canonical.joinpath("artifact.txt").read_text() == "new-artifact"
    assert json.loads(canonical.joinpath("seascape_release_manifest.json").read_text()) == {
        "generation": 2
    }
    assert promoted[-1] == "seascape_release_manifest.json"


def test_repeated_release_does_not_self_catalog_prior_release_manifest(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"
    processed = candidate / "data/processed/domain/environmental_layer/seascape"
    processed.mkdir(parents=True)
    (processed / "fixture_manifest.json").write_text('{"schema_version": "3.0.0"}')
    (processed / "seascape_release_manifest.json").write_text('{"generation": "prior"}')
    audit = candidate / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    audit.parent.mkdir(parents=True)
    audit.write_text('{"artifact_release_passed": true, "model_policy_complete": false}')
    governed = (
        "config/feature_catalog.yaml",
        "config/model_feature_policy.yaml",
        "src/orcacast/domains/environment/meteorological/model_feature_policy.yaml",
        "docs/products.md",
        "config/data/environment_seascape.yaml",
        "config/data/environment_meteorological.yaml",
        "data/raw/environment/meteorological/surface_weather/hrrr/HRRR_R5_SOURCE_INVENTORY.parquet",
        "data/raw/environment/meteorological/surface_weather/hrrr/R5_DOWNLOAD_MANIFEST.json",
    )
    for relative in governed:
        path = candidate / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative)

    release_path = publish_candidate_release(
        canonical_project_root=canonical,
        candidate_project_root=candidate,
    )
    payload = json.loads(release_path.read_text())

    assert set(payload["family_manifest_checksums"]) == {
        "data/processed/domain/environmental_layer/seascape/fixture_manifest.json"
    }


def test_snapshot_recovers_interrupted_release_before_read(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    destination = canonical / "artifact.txt"
    destination.write_text("partial")
    transaction = canonical / ".transactions" / "interrupted"
    backup = transaction / "backups" / "000_artifact.txt"
    backup.parent.mkdir(parents=True)
    backup.write_text("complete")
    (transaction / "journal.json").write_text(
        json.dumps(
            {
                "phase": "promoting",
                "items": [
                    {
                        "destination": str(destination),
                        "candidate": str(canonical / ".staging/interrupted/000_artifact.txt"),
                        "backup": str(backup),
                        "had_destination": True,
                        "promoted": True,
                    }
                ],
            }
        )
    )

    with SeascapeSnapshot(canonical) as snapshot:
        assert snapshot.resolve("artifact.txt").read_text() == "complete"
    assert not transaction.exists()


def test_snapshot_recovers_nested_family_transaction_before_read(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    family = canonical / "data/processed/domain/environmental_layer/seascape/biogenic_habitat/kelp"
    family.mkdir(parents=True)
    destination = family / "kelp.parquet"
    destination.write_text("partial")
    transaction = family / ".transactions" / "interrupted"
    backup = transaction / "backups" / "000_kelp.parquet"
    backup.parent.mkdir(parents=True)
    backup.write_text("complete")
    (transaction / "journal.json").write_text(
        json.dumps(
            {
                "phase": "promoting",
                "items": [
                    {
                        "destination": str(destination),
                        "candidate": str(family / ".staging/interrupted/000_kelp.parquet"),
                        "backup": str(backup),
                        "had_destination": True,
                        "promoted": True,
                    }
                ],
            }
        )
    )

    with SeascapeSnapshot(canonical):
        assert destination.read_text() == "complete"
    assert not transaction.exists()


def test_shared_snapshot_blocks_release_writer(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"
    canonical.mkdir()
    candidate.mkdir()
    context = multiprocessing.get_context("spawn")
    messages = context.Queue()
    process = context.Process(
        target=_acquire_release_lock,
        args=(str(canonical), str(candidate), messages),
    )

    with SeascapeSnapshot(canonical):
        process.start()
        assert messages.get(timeout=5) == "attempting"
        with pytest.raises(queue.Empty):
            messages.get(timeout=0.2)
    assert messages.get(timeout=5) == "acquired"
    process.join(timeout=5)
    assert process.exitcode == 0


@pytest.mark.parametrize("failed_destination", ["first.txt", "second.txt", "manifest.json"])
def test_release_rolls_back_failure_at_each_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_destination: str,
) -> None:
    import os

    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"
    canonical.mkdir()
    candidate.mkdir()
    for name in ("first.txt", "second.txt", "manifest.json"):
        (canonical / name).write_text(f"old-{name}")
        (candidate / name).write_text(f"new-{name}")
    original_replace = os.replace

    def fail_selected_promotion(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            source_path.parent.parent.name == ".staging"
            and destination_path.name == failed_destination
        ):
            raise OSError(f"failed {failed_destination}")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_selected_promotion)
    with pytest.raises(OSError, match="failed"):
        with SeascapeReleasePublisher(
            canonical, candidate, run_id="promotion-failure"
        ) as publisher:
            publisher.stage_candidate("first.txt")
            publisher.stage_candidate("second.txt")
            publisher.stage_candidate("manifest.json", manifest=True)
            publisher.publish()
    for name in ("first.txt", "second.txt", "manifest.json"):
        assert (canonical / name).read_text() == f"old-{name}"


@pytest.mark.parametrize("failed_update", range(1, 7))
def test_release_rolls_back_failure_at_each_journal_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_update: int,
) -> None:
    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"
    canonical.mkdir()
    candidate.mkdir()
    destination = canonical / "artifact.txt"
    destination.write_text("old")
    (candidate / "artifact.txt").write_text("new")
    (candidate / "manifest.json").write_text("new-manifest")
    (canonical / "manifest.json").write_text("old-manifest")
    original = TransactionalFamilyPublisher._write_journal
    calls = 0

    def fail_selected_update(path, payload):
        nonlocal calls
        calls += 1
        if calls == failed_update:
            raise OSError(f"failed journal update {failed_update}")
        return original(path, payload)

    monkeypatch.setattr(
        TransactionalFamilyPublisher,
        "_write_journal",
        staticmethod(fail_selected_update),
    )
    with pytest.raises(OSError, match="failed journal update"):
        with SeascapeReleasePublisher(canonical, candidate, run_id="journal-failure") as publisher:
            publisher.stage_candidate("artifact.txt")
            publisher.stage_candidate("manifest.json", manifest=True)
            publisher.publish()
    assert destination.read_text() == "old"
    assert (canonical / "manifest.json").read_text() == "old-manifest"
