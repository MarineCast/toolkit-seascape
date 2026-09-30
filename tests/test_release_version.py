"""Software release identity checks."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_release_version", ROOT / "scripts/check_release_version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_and_project_versions_match():
    import seascape

    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]
    assert declared == "0.1.1"
    assert seascape.__version__ == declared
    assert importlib.metadata.version("toolkit-seascape") == declared


def test_release_tag_must_match_static_project_version():
    checker = load_checker()
    assert checker.validate("v0.1.1", ROOT / "pyproject.toml") == "0.1.1"
    with pytest.raises(ValueError, match="does not match"):
        checker.validate("v0.1.0", ROOT / "pyproject.toml")
    with pytest.raises(ValueError, match="form vX.Y.Z"):
        checker.validate("0.1.0", ROOT / "pyproject.toml")
    with pytest.raises(ValueError, match="form vX.Y.Z"):
        checker.validate("v0.1", ROOT / "pyproject.toml")
