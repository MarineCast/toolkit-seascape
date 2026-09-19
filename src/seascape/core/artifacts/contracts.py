from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERIFIED_SOURCE_COVERAGE_STATUSES = frozenset({"configured_verified", "request_complete"})
VERIFIED_SNAPSHOT_COVERAGE_STATUSES = frozenset({"verified_intersection"})


@dataclass(frozen=True)
class SourceWatermark:
    """Verified coverage, observed bounds, and identity for one source snapshot."""

    source: str
    retrieval_id: str
    coverage_start: str | None
    coverage_through: str | None
    checksum: str
    retrieved_at: str
    observed_start: str | None = None
    observed_through: str | None = None
    requested_start: str | None = None
    requested_through: str | None = None
    coverage_status: str = "unverified"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceWatermark":
        payload = dict(value)
        payload.setdefault("observed_start", None)
        payload.setdefault("observed_through", None)
        payload.setdefault("requested_start", None)
        payload.setdefault("requested_through", None)
        coverage_status = str(payload.get("coverage_status") or "legacy_unverified")
        if coverage_status not in VERIFIED_SOURCE_COVERAGE_STATUSES:
            if coverage_status in {"legacy_asserted", "legacy_unverified"}:
                # Schema-v1 manifests used these fields for asserted/requested bounds.
                if payload.get("requested_start") is None:
                    payload["requested_start"] = payload.get("coverage_start")
                if payload.get("requested_through") is None:
                    payload["requested_through"] = payload.get("coverage_through")
                coverage_status = "legacy_unverified"
            payload["coverage_start"] = None
            payload["coverage_through"] = None
        payload["coverage_status"] = coverage_status
        return cls(**payload)


@dataclass(frozen=True)
class DataSnapshotMetadata:
    """Source coverage envelope retained for artifact-schema compatibility."""

    snapshot_id: str
    snapshot_created_at: str
    coverage_start: str | None
    coverage_through: str | None
    source_watermarks: tuple[SourceWatermark, ...]
    imputation_as_of: str | None = None
    duplicate_resolution_as_of: str | None = None
    coverage_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_watermarks"] = [asdict(item) for item in self.source_watermarks]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DataSnapshotMetadata":
        payload = dict(value)
        payload["source_watermarks"] = tuple(
            SourceWatermark.from_dict(item) for item in payload.get("source_watermarks", ())
        )
        coverage_status = str(payload.get("coverage_status") or "legacy_unverified")
        if coverage_status not in VERIFIED_SNAPSHOT_COVERAGE_STATUSES:
            payload["coverage_start"] = None
            payload["coverage_through"] = None
            if coverage_status in {"legacy_asserted", "legacy_unverified"}:
                coverage_status = "legacy_unverified"
        payload["coverage_status"] = coverage_status
        return cls(**payload)


@dataclass(frozen=True)
class ArtifactRef:
    """Portable identity and lineage for a generated Seascape Toolkit artifact."""

    kind: str
    path: Path
    producer: str
    dataset_id: str | None = None
    schema_version: str = "1"
    run_id: str | None = None
    config_hash: str | None = None
    code_revision: str | None = None
    inputs: tuple[str, ...] = ()
    checksum: str | None = None
    row_count: int | None = None
    file_count: int | None = None
    processing_mode: str | None = None
    knowledge_cutoff: str | None = None
    freshness: str = "current"
    spatial_coverage: Mapping[str, Any] | None = None
    temporal_coverage: Mapping[str, Any] | None = None
    data_snapshot: DataSnapshotMetadata | None = None
    sensitivity: str = "internal"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["data_snapshot"] = (
            self.data_snapshot.to_dict() if self.data_snapshot is not None else None
        )
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRef":
        payload = dict(value)
        payload["path"] = Path(payload["path"])
        payload["inputs"] = tuple(payload.get("inputs", ()))
        if payload.get("data_snapshot") is not None:
            payload["data_snapshot"] = DataSnapshotMetadata.from_dict(payload["data_snapshot"])
        return cls(**payload)


@dataclass(frozen=True)
class RunManifest:
    """Resolved configuration and artifact lineage for one workflow run."""

    run_id: str
    workflow: str
    config_hash: str
    resolved_config: Mapping[str, Any]
    inputs: tuple[ArtifactRef, ...] = ()
    outputs: tuple[ArtifactRef, ...] = ()
    source_snapshots: tuple[ArtifactRef, ...] = ()
    stages: tuple[Mapping[str, Any], ...] = ()
    status: str = "complete"
    failure: Mapping[str, Any] | None = None
    code_revision: str | None = None
    schema_version: str = "1"
    stage_signature: str | None = None
    data_snapshot: DataSnapshotMetadata | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = {
            **asdict(self),
            "inputs": [item.to_dict() for item in self.inputs],
            "outputs": [item.to_dict() for item in self.outputs],
            "source_snapshots": [item.to_dict() for item in self.source_snapshots],
        }
        payload["data_snapshot"] = (
            self.data_snapshot.to_dict() if self.data_snapshot is not None else None
        )
        return payload

    def write(self, path: str | Path, *, overwrite: bool = False) -> Path:
        return atomic_write_json(path, self.to_dict(), overwrite=overwrite)


def atomic_write_json(
    path: str | Path,
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically write JSON without silently replacing an existing product."""

    from .confinement import validate_candidate_destination

    destination = validate_candidate_destination(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
        os.replace(temporary, destination)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return destination


def atomic_write_text(
    path: str | Path, text: str, *, overwrite: bool = False, encoding: str = "utf-8"
) -> Path:
    from .confinement import validate_candidate_destination

    destination = validate_candidate_destination(path)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
        os.replace(temporary, destination)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return destination
