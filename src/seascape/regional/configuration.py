"""Bind legacy kernel configuration to explicit byte-pinned documents."""

import os
from contextlib import contextmanager

import yaml

from seascape.study import current_study

from .contract import RegionalError


@contextmanager
def configuration(job):
    if current_study() is not None:
        raise RegionalError(
            "Regional spec execution requires independent explicit domain context"
        )
    path = job.source("config")
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict) or raw.get("SEASCAPE_LAYER"):
        raise RegionalError(
            "Regional config must be a flattened YAML without unpinned includes"
        )
    common = job.source("common")
    previous = os.environ.get("SEASCAPE_COMMON_CONFIG")
    os.environ["SEASCAPE_COMMON_CONFIG"] = str(common)
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("SEASCAPE_COMMON_CONFIG", None)
        else:
            os.environ["SEASCAPE_COMMON_CONFIG"] = previous
