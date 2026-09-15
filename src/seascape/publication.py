"""Stable-path publication and consistent snapshot reads for seascape artifacts."""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import pandas as pd

from seascape.core.artifacts import TransactionalFamilyPublisher
from seascape.core.config.paths import project_root

SEASCAPE_RELEASE_MANIFEST = "seascape_release_manifest.json"
SEASCAPE_RELEASE_LOCK = ".seascape-release.lock"


def _same_filesystem(first: Path, second: Path) -> bool:
    """Return whether existing ancestors of both paths share one device."""

    def existing_ancestor(path: Path) -> Path:
        candidate = path.resolve()
        while not candidate.exists():
            if candidate.parent == candidate:
                raise FileNotFoundError(path)
            candidate = candidate.parent
        return candidate

    return os.stat(existing_ancestor(first)).st_dev == os.stat(existing_ancestor(second)).st_dev


class TransactionalSeascapePublisher(TransactionalFamilyPublisher):
    """Publish one canonical family while holding the global seascape writer lock."""

    def __init__(self, parent: str | Path, run_id: str | None = None):
        super().__init__(parent, run_id=run_id)
        self._release_lock: Any | None = None

    def _publishes_canonical_seascape(self) -> bool:
        if os.environ.get("SEASCAPE_CANDIDATE_ROOT"):
            return False
        canonical_roots = (
            project_root() / "data/processed/domain/environmental_layer/seascape",
            project_root() / "data/processed/environment/seascape",
        )
        for canonical in canonical_roots:
            try:
                self.parent.relative_to(canonical.resolve())
                return True
            except ValueError:
                continue
        return False

    def __enter__(self) -> "TransactionalSeascapePublisher":
        if self._publishes_canonical_seascape():
            lock_path = project_root() / SEASCAPE_RELEASE_LOCK
            self._release_lock = lock_path.open("a+")
            fcntl.flock(self._release_lock.fileno(), fcntl.LOCK_EX)
        try:
            super().__enter__()
        except Exception:
            self._release_writer_lock()
            raise
        return self

    def _release_writer_lock(self) -> None:
        if self._release_lock is not None:
            fcntl.flock(self._release_lock.fileno(), fcntl.LOCK_UN)
            self._release_lock.close()
            self._release_lock = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self._release_writer_lock()


class SeascapeSnapshot(AbstractContextManager["SeascapeSnapshot"]):
    """Hold a consistent shared lock while official artifacts are read.

    Entering first takes the writer lock long enough to roll back any interrupted
    release, then downgrades it to a shared lock without closing the descriptor.
    """

    def __init__(self, canonical_root: str | Path):
        self.canonical_root = Path(canonical_root).resolve()
        self.lock_path = self.canonical_root / SEASCAPE_RELEASE_LOCK
        self._handle: Any | None = None

    def __enter__(self) -> "SeascapeSnapshot":
        self.canonical_root.mkdir(parents=True, exist_ok=True)
        self._handle = self.lock_path.open("a+")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        TransactionalFamilyPublisher.recover(self.canonical_root)
        TransactionalFamilyPublisher.recover_tree(
            self.canonical_root / "data/processed/domain/environmental_layer/seascape"
        )
        TransactionalFamilyPublisher.recover_tree(
            self.canonical_root / "data/processed/environment/seascape"
        )
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_SH)
        return self

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        return candidate.resolve() if candidate.is_absolute() else self.canonical_root / candidate

    def read_json(self, path: str | Path) -> dict[str, Any]:
        payload = json.loads(self.resolve(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON mapping: {path}")
        return payload

    def read_parquet(self, path: str | Path, **kwargs: Any) -> pd.DataFrame:
        return pd.read_parquet(self.resolve(path), **kwargs)

    def read_geoparquet(self, path: str | Path, **kwargs: Any):
        import geopandas as gpd

        return gpd.read_parquet(self.resolve(path), **kwargs)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


class SeascapeReleasePublisher(AbstractContextManager["SeascapeReleasePublisher"]):
    """Promote a same-filesystem candidate release under the global writer lock."""

    def __init__(
        self,
        canonical_root: str | Path,
        candidate_root: str | Path,
        *,
        run_id: str | None = None,
    ):
        self.canonical_root = Path(canonical_root).resolve()
        self.candidate_root = Path(candidate_root).resolve()
        if not _same_filesystem(self.canonical_root, self.candidate_root):
            raise ValueError("Seascape publication requires a same-filesystem candidate root.")
        self.lock_path = self.canonical_root / SEASCAPE_RELEASE_LOCK
        self.publisher = TransactionalFamilyPublisher(self.canonical_root, run_id=run_id)
        self._handle: Any | None = None

    def __enter__(self) -> "SeascapeReleasePublisher":
        self.canonical_root.mkdir(parents=True, exist_ok=True)
        self._handle = self.lock_path.open("a+")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        self.publisher.__enter__()
        return self

    def stage_candidate(self, relative_path: str | Path, *, manifest: bool = False) -> Path:
        """Copy a candidate into transaction staging for recoverable promotion."""

        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Candidate release paths must be relative: {relative}")
        source = self.candidate_root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = self.canonical_root / relative
        staged = (
            self.publisher.stage_manifest_path(destination)
            if manifest
            else self.publisher.stage_path(destination)
        )
        staged.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, staged.open("wb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        return staged

    def publish(self) -> tuple[Path, ...]:
        return self.publisher.publish()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.publisher.__exit__(exc_type, exc, traceback)
        finally:
            if self._handle is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                self._handle.close()
                self._handle = None


def read_seascape_parquet(
    path: str | Path,
    *,
    canonical_root: str | Path | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Read one official table under a recovered, shared release snapshot."""

    root = Path(canonical_root).resolve() if canonical_root else project_root()
    with SeascapeSnapshot(root) as snapshot:
        return snapshot.read_parquet(path, **kwargs)


def read_seascape_geoparquet(
    path: str | Path,
    *,
    canonical_root: str | Path | None = None,
    **kwargs: Any,
):
    """Read one official geometry table under a shared release snapshot."""

    root = Path(canonical_root).resolve() if canonical_root else project_root()
    with SeascapeSnapshot(root) as snapshot:
        return snapshot.read_geoparquet(path, **kwargs)


__all__ = [
    "SEASCAPE_RELEASE_LOCK",
    "SEASCAPE_RELEASE_MANIFEST",
    "SeascapeReleasePublisher",
    "SeascapeSnapshot",
    "TransactionalSeascapePublisher",
    "read_seascape_geoparquet",
    "read_seascape_parquet",
]
