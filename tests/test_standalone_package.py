"""Regression checks for extraction, workspace ownership and installed entry points."""
from __future__ import annotations

import ast
from importlib.resources import files
from pathlib import Path

import pytest

from seascape.cli import DOWNLOAD_FAMILIES, FAMILIES, initialize_workspace, main
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.core.data.registry import DATASETS
from seascape.workflow import selected_stages


def test_source_has_no_application_imports():
    source = Path(__file__).parents[1] / "src/seascape"
    for path in source.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            assert not any(m == "orcacast" or m.startswith("orcacast.") for m in modules), path


def test_dataset_dependencies_are_owned_by_toolkit():
    specs = tuple(DATASETS)
    assert specs
    assert all(str(spec.dataset_id).startswith("environment.seascape.") for spec in specs)
    for spec in specs:
        for dependency in spec.dependencies:
            DATASETS.get(dependency)
    for resolution in (4, 5, 6):
        DATASETS.get(f"environment.seascape.h3_full_counting_universe_r{resolution}")


def test_workspace_init_is_portable_and_preserves_edits(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    initialize_workspace(workspace)
    config = workspace / "config/data/project.yaml"
    documentation = workspace / "docs/products.md"
    assert config.is_file()
    assert documentation.is_file()
    from seascape.maintenance.update_seascape_docs import START_MARKER, END_MARKER
    assert documentation.read_text().count(START_MARKER) == 1
    assert documentation.read_text().count(END_MARKER) == 1
    config.write_text(config.read_text() + "# user edit\n")
    documentation.write_text(documentation.read_text() + "\nUser note.\n")
    initialize_workspace(workspace)
    assert config.read_text().endswith("# user edit\n")
    assert documentation.read_text().endswith("User note.\n")
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(workspace))
    monkeypatch.chdir(tmp_path)
    assert project_root() == workspace
    assert resolve_config_path("config/data/project.yaml") == config
    from seascape.seafloor_physiography.bathymetry.pipeline import load_bathymetry_config
    assert load_bathymetry_config(config).raw_path.is_relative_to(workspace)


def test_packaged_templates_match_editable_checkout():
    root = Path(__file__).parents[1]
    editable_templates = [root / "config/common.yaml", *(root / "config/data").glob("*.yaml")]
    for path in editable_templates:
        assert files("seascape").joinpath("resources", str(path.relative_to(root))).read_bytes() == path.read_bytes()
    assert not files("seascape").joinpath("resources/config/feature_catalog.yaml").is_file()
    assert not files("seascape").joinpath("resources/config/model_feature_policy.yaml").is_file()


def test_required_modules_and_editable_templates_are_in_installed_package():
    from seascape.core.data import catalog, registry, validation

    assert catalog.register_builtin_datasets
    assert registry.DATASETS
    assert validation.validate_path
    resources = files("seascape").joinpath("resources/config/data")
    for name in (
        "project.yaml",
        "environment_seascape.yaml",
        "presentation_settings.yaml",
    ):
        assert resources.joinpath(name).is_file(), name


def test_release_plan_is_seascape_only():
    stages = selected_stages(only=["seascape-release"])
    assert len(stages) == 26
    assert stages[-1].name == "seascape-release"
    assert any(stage.name == "seascape-feature-eligibility" for stage in stages)
    assert not any(stage.name == "seascape-model-policy" for stage in stages)
    assert not any("meteorological" in output for stage in stages for output in stage.declared_outputs)


@pytest.mark.parametrize("family", DOWNLOAD_FAMILIES)
def test_download_command_help_is_available(family, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["download", family, "--help"])
    assert exc.value.code == 0
    assert "--config" in capsys.readouterr().out


@pytest.mark.parametrize("family", FAMILIES)
def test_inspection_command_help_is_available(family, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["inspect", family, "--help"])
    assert exc.value.code == 0
    assert "--config" in capsys.readouterr().out
