"""Seascape model-matrix governance and diagnostic policies."""

from __future__ import annotations

from typing import Any

__all__ = ["apply_feature_policy", "build_feature_policy"]


def __getattr__(name: str) -> Any:
    """Load policy helpers lazily so the feature-policy module remains CLI-safe."""

    if name not in __all__:
        raise AttributeError(name)
    from . import feature_policy

    return getattr(feature_policy, name)
