"""Reproducible package-code identity for workflow and release provenance."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


def _git(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _source_tree_checksum(repository: Path | None, package_root: Path) -> str:
    digest = hashlib.sha256()
    paths: list[Path] = []
    if repository is not None and (repository / "pyproject.toml").is_file():
        paths.append(repository / "pyproject.toml")
    paths.extend(
        path
        for path in package_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    base = repository or package_root.parent
    for path in sorted(paths, key=lambda item: str(item.relative_to(base))):
        relative = path.relative_to(base)
        digest.update(relative.as_posix().encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def package_code_identity(root: str | Path) -> dict[str, Any]:
    """Return commit, tracked-dirty state, and an exact package source-tree hash."""

    workspace = Path(root).resolve()
    source_checkout = workspace / "src/seascape"
    if source_checkout.is_dir() and (workspace / "pyproject.toml").is_file():
        repository: Path | None = workspace
        package_root = source_checkout
    else:
        package_root = Path(__file__).resolve().parents[1]
        discovered = _git(package_root, "rev-parse", "--show-toplevel")
        repository = Path(discovered) if discovered else None
    revision = _git(repository, "rev-parse", "HEAD") if repository else None
    status = (
        _git(
            repository,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "pyproject.toml",
            "src/seascape",
        )
        if repository
        else None
    )
    return {
        "git_revision": revision,
        "dirty": status is None or bool(status),
        "source_tree_sha256": _source_tree_checksum(repository, package_root),
    }


__all__ = ["package_code_identity"]
