"""Canonical checksums for files and directory artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path


def checksum_path(
    path: str | Path,
    *,
    logical_name: str | None = None,
) -> str:
    """Return the repository-standard checksum for a file or directory tree.

    ``logical_name`` lets a transaction checksum a staged file under its final
    destination name. Directory checksums always use paths relative to the
    directory root and therefore do not require an override.
    """

    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if logical_name is not None and resolved.is_dir():
        raise ValueError("logical_name is supported only for file artifacts.")
    if logical_name is not None and Path(logical_name).name != logical_name:
        raise ValueError("logical_name must be a file name, not a path.")
    digest = hashlib.sha256()
    paths = (
        sorted(item for item in resolved.rglob("*") if item.is_file())
        if resolved.is_dir()
        else [resolved]
    )
    for item in paths:
        relative = (
            item.relative_to(resolved) if resolved.is_dir() else Path(logical_name or item.name)
        )
        digest.update(str(relative).encode("utf-8"))
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


__all__ = ["checksum_path"]
