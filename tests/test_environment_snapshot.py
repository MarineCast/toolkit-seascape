"""Dependency closure evidence must include active extras and exclude install locations."""

from __future__ import annotations

import importlib.util
import json
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "environment_snapshot",
    Path(__file__).parents[1] / "scripts/environment_snapshot.py",
)
assert SPEC is not None and SPEC.loader is not None
SNAPSHOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SNAPSHOT)


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text(
        """[project]
dependencies = ["engine", "engine[plot]", "remote @ https://user:secret@example.invalid/private.whl", "absent; python_version < '2'"]
[project.optional-dependencies]
test = ["tester"]
quality = ["checker"]
"""
    )
    return path


@pytest.fixture
def installed(monkeypatch):
    distributions = {
        "engine": SimpleNamespace(
            version="1.0", requires=["shared", "plotter; extra == 'plot'"]
        ),
        "shared": SimpleNamespace(
            version="2.0", requires=["engine", "excluded; extra == 'unused'"]
        ),
        "plotter": SimpleNamespace(version="3.0", requires=["shared[render]"]),
        "renderer": SimpleNamespace(version="4.0", requires=[]),
        "remote": SimpleNamespace(version="5.0", requires=[]),
        "tester": SimpleNamespace(version="6.0", requires=[]),
        "checker": SimpleNamespace(version="7.0", requires=[]),
    }
    distributions["shared"].requires.append("renderer; extra == 'render'")

    def distribution(name):
        if name not in distributions:
            raise PackageNotFoundError(name)
        return distributions[name]

    monkeypatch.setattr(SNAPSHOT.metadata, "distribution", distribution)
    return distributions


def test_default_closure_includes_transitive_extras_and_cycles(project, installed):
    assert SNAPSHOT.dependency_versions(project) == {
        "engine": "1.0",
        "plotter": "3.0",
        "remote": "5.0",
        "renderer": "4.0",
        "shared": "2.0",
        "tester": "6.0",
    }


def test_selected_extras_are_reproducible_without_install_paths(project, installed):
    lines, evidence = SNAPSHOT.snapshot(project, ("test", "quality", "test"))
    assert lines == sorted(lines)
    assert "checker==7.0" in lines
    assert evidence["extras"] == ["quality", "test"]
    assert evidence["dependencies"]["renderer"] == "4.0"
    assert all(
        evidence[name]
        for name in ("python", "platform", "machine", "gdal", "proj", "geos")
    )
    serialized = json.dumps(evidence) + "\n".join(lines)
    for private in ("secret", "https:", "private.whl", str(project.parent)):
        assert private not in serialized


def test_runtime_only_does_not_require_unselected_extras(project, installed):
    del installed["tester"]
    versions = SNAPSHOT.dependency_versions(project, ())
    assert "tester" not in versions and "checker" not in versions


def test_undeclared_extra_is_rejected(project, installed):
    with pytest.raises(ValueError, match="Unknown project extra"):
        SNAPSHOT.dependency_versions(project, ("unknown",))


def test_missing_active_distribution_is_not_a_partial_success(project, installed):
    del installed["renderer"]
    with pytest.raises(PackageNotFoundError):
        SNAPSHOT.dependency_versions(project)


def test_invalid_version_cannot_leak_a_private_location(project, installed):
    installed["engine"].version = "https://user:secret@example.invalid/private.whl"
    with pytest.raises(ValueError, match="^Invalid installed distribution version$"):
        SNAPSHOT.dependency_versions(project)
