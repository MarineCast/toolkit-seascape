"""Shared configuration primitives for seascape product families."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import resolve_config_path


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    """Return ``value`` as a mutable mapping or raise a contextual error."""

    if not isinstance(value, Mapping):
        raise ValueError(f"Config section {name!r} must be a mapping.")
    return dict(value)


def resolve_project_path(value: str | Path, base_dir: Path) -> Path:
    """Resolve a configured path against the configured project base."""

    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def stable_config_hash(value: Any) -> str:
    """Return a deterministic SHA-256 hash for resolved configuration values."""

    def normalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): normalize(item[key]) for key in sorted(item, key=str)}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        return str(item)

    encoded = json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_processing_config(
    config_path: str | Path,
    section_name: str,
) -> dict[str, Any]:
    """Load one required seascape family processing mapping."""

    raw = load_data_config(resolve_config_path(config_path), domains="SEASCAPE_LAYER")
    section = require_mapping(raw.get(section_name), section_name)
    return require_mapping(section.get("processing"), f"{section_name}.processing")


__all__ = [
    "load_processing_config",
    "require_mapping",
    "resolve_project_path",
    "stable_config_hash",
]
