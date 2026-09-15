from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the data workspace selected by SEASCAPE_WORKSPACE or the caller."""
    import os

    return Path(os.environ.get("SEASCAPE_WORKSPACE", Path.cwd())).expanduser().resolve()


def resolve_project_path(
    path: str | Path, *, base_dir: str | Path | None = None
) -> Path:
    """Resolve a path without depending on the process working directory."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate

    root_candidate = project_root() / candidate
    if root_candidate.exists():
        return root_candidate.resolve()

    if base_dir is not None:
        return (Path(base_dir).expanduser() / candidate).resolve()

    return root_candidate.resolve()


def resolve_config_path(path: str | Path) -> Path:
    """Resolve a config path relative to the repository root."""
    return resolve_project_path(path)


def resolve_config_include(config_path: str | Path, include_path: str | Path) -> Path:
    """Resolve a config include path with stable project-root semantics."""
    include = Path(include_path).expanduser()
    if include.is_absolute():
        return include

    root_candidate = project_root() / include
    if root_candidate.exists():
        return root_candidate.resolve()

    return (Path(config_path).expanduser().resolve().parent / include).resolve()
