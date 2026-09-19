from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from seascape.core.config.document import ConfigDocument
from seascape.core.config.paths import resolve_config_include

DEFAULT_DOMAIN_CONFIG_KEYS = ("SEASCAPE_LAYER",)
DOMAIN_CONFIG_KEYS = DEFAULT_DOMAIN_CONFIG_KEYS


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
