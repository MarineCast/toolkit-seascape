from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Mapping, TypeVar

import yaml
from pydantic import BaseModel

from .paths import project_root, resolve_config_path

_ENV_PATTERN = re.compile(r"^\$\{env:([A-Z][A-Z0-9_]*)\}$")
_REF_PATTERN = re.compile(r"^\$\{([a-zA-Z_][a-zA-Z0-9_.-]*)\}$")
ModelT = TypeVar("ModelT", bound=BaseModel)


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key == "extends":
            continue
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _lookup(mapping: Mapping[str, Any], dotted: str) -> Any:
    value: Any = mapping
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ValueError(f"Unknown configuration reference: {dotted}")
        value = value[part]
    return value


def _resolve_values(value: Any, root: Mapping[str, Any], stack: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        return {key: _resolve_values(item, root, stack) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_values(item, root, stack) for item in value]
    if isinstance(value, str):
        env_match = _ENV_PATTERN.match(value)
        if env_match:
            name = env_match.group(1)
            if name not in os.environ:
                raise ValueError(f"Required environment variable is not set: {name}")
            return os.environ[name]
        ref_match = _REF_PATTERN.match(value)
        if ref_match:
            reference = ref_match.group(1)
            if reference in stack:
                raise ValueError(f"Configuration reference cycle: {' -> '.join((*stack, reference))}")
            return _resolve_values(_lookup(root, reference), root, (*stack, reference))
    return value


def _redact(value: Any, key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {item_key: _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if any(token in key.lower() for token in ("secret", "token", "password", "api_key")):
        return "<redacted>"
    return value


@dataclass(frozen=True)
class ConfigDocument:
    """A fully composed, validated, hashable Seascape Toolkit configuration."""

    source: Path
    data: Mapping[str, Any]
    include_chain: tuple[Path, ...]
    config_hash: str

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        allowed_keys: Collection[str] | None = None,
    ) -> "ConfigDocument":
        source = resolve_config_path(path)
        data, chain = _load_recursive(source, stack=())
        resolved = _resolve_values(data, data)
        if allowed_keys is not None:
            unknown = sorted(set(resolved) - set(allowed_keys))
            if unknown:
                raise ValueError(f"Unknown top-level configuration keys: {', '.join(unknown)}")
        canonical = json.dumps(
            _redact(resolved), sort_keys=True, separators=(",", ":"), default=str
        )
        return cls(
            source=source,
            data=resolved,
            include_chain=chain,
            config_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def resolve_path(self, value: str | Path) -> Path:
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else (project_root() / candidate).resolve()

    def validate_as(self, model: type[ModelT]) -> ModelT:
        """Validate the resolved document through a strict Pydantic model."""
        return model.model_validate(self.data)

    def redacted_data(self) -> dict[str, Any]:
        """Return manifest-safe configuration without secret values."""
        return _redact(self.data)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "include_chain": [str(path) for path in self.include_chain],
            "config_hash": self.config_hash,
            "resolved": self.redacted_data(),
        }


def _load_recursive(
    path: Path, *, stack: tuple[Path, ...]
) -> tuple[dict[str, Any], tuple[Path, ...]]:
    path = path.resolve()
    if path in stack:
        cycle = " -> ".join(str(item) for item in (*stack, path))
        raise ValueError(f"Configuration include cycle: {cycle}")
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"Configuration root must be a mapping: {path}")
    parent_value = raw.get("extends")
    if not parent_value:
        return dict(raw), (path,)
    parent = Path(parent_value).expanduser()
    if not parent.is_absolute():
        root_candidate = project_root() / parent
        parent = root_candidate if root_candidate.exists() else path.parent / parent
    base, chain = _load_recursive(parent, stack=(*stack, path))
    return _deep_merge(base, raw), (*chain, path)
