from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any

from seascape.core.config.document import ConfigDocument
from seascape.core.config.paths import resolve_config_include, resolve_config_path

DEFAULT_DOMAIN_CONFIG_KEYS = ("SEASCAPE_LAYER",)
DOMAIN_CONFIG_KEYS = DEFAULT_DOMAIN_CONFIG_KEYS
_PREVIEW_CONFIG: ContextVar[tuple[Path, dict[str, Any]] | None] = ContextVar(
    "seascape_preview_config", default=None
)


@contextmanager
def _preview_data_config(path: Path, data: dict[str, Any]):
    """Let existing read-only loaders inspect a rendered config without writing it.

    The override is confined to this execution context and one resolved entry point;
    common-area and other documents still use normal loading. Each load gets a copy.
    """
    token = _PREVIEW_CONFIG.set((path.resolve(), deepcopy(data)))
    try:
        yield
    finally:
        _PREVIEW_CONFIG.reset(token)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    return dict(ConfigDocument.load(path).data)


def _resolve_include_path(config_path: Path, include_path: str | Path) -> Path:
    return resolve_config_include(config_path, include_path)


def _normalize_domain_keys(domains: str | Iterable[str] | None) -> tuple[str, ...]:
    if domains is None:
        return DEFAULT_DOMAIN_CONFIG_KEYS
    if isinstance(domains, str):
        return (domains,)
    return tuple(domains)


def load_data_config(
    config_path: str | Path,
    *,
    domains: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    """Load data_config.yaml and merge referenced domain configs into a flat dict."""
    preview = _PREVIEW_CONFIG.get()
    if preview is not None and resolve_config_path(config_path).resolve() == preview[0]:
        return deepcopy(preview[1])
    document = ConfigDocument.load(config_path)
    path = document.source
    raw = dict(document.data)
    merged = dict(raw)

    for key in _normalize_domain_keys(domains):
        include = raw.get(key)
        if not include:
            continue
        include_path = _resolve_include_path(path, include)
        domain_cfg = _read_yaml_mapping(include_path)
        merged.update(domain_cfg)

    from seascape.core.geo.crs import validate_metric_crs_settings

    validate_metric_crs_settings(merged)
    return merged
