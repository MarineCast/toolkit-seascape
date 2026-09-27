"""CLI-only presentation, real validation failures and boundary compatibility."""

from __future__ import annotations

import fcntl
import json
import os
import sys
from types import SimpleNamespace

import pytest
import yaml
from pyproj.exceptions import CRSError

from seascape import cli, metric_matrix, workflow
from seascape.core.artifacts import TransactionalFamilyPublisher
from seascape.core.config.document import ConfigDocument
from seascape.publication import SeascapeReleasePublisher
from seascape.release import publish_candidate_release
from seascape.seafloor_physiography.bathymetry import load_bathymetry_config


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    cli.initialize_workspace(root)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", "previous-workspace")
    return root


def invoke(workspace, *arguments):
    result = cli.main(["--workspace", str(workspace), *arguments])
    assert os.environ["SEASCAPE_WORKSPACE"] == "previous-workspace"
    return result


def assert_guidance(capsys, reason, operation):
    err = capsys.readouterr().err
    assert operation in err
    assert reason in err
    assert "Action:" in err
    assert "Guide: docs/" in err
    assert "Traceback" not in err
    return err


@pytest.mark.parametrize("operation", ["download", "inspect"])
def test_family_missing_config(workspace, capsys, operation):
    old_argv = sys.argv
    assert invoke(workspace, operation, "bathymetry", "--config", "missing.yaml") == 1
    err = assert_guidance(
        capsys, "Configuration is missing", f"{operation} / bathymetry"
    )
    assert "missing.yaml" in err and " init" in err
    assert sys.argv is old_argv
    with pytest.raises(FileNotFoundError):
        load_bathymetry_config(workspace / "missing.yaml")


def test_build_missing_config_before_writes(workspace, capsys):
    (workspace / "config/data/project.yaml").unlink()
    assert invoke(workspace, "build", "--only", "seascape-bathymetry") == 1
    assert_guidance(capsys, "Configuration is missing", "build")
    assert not (workspace / ".seascape").exists()


def test_missing_inspection_source(workspace, capsys):
    missing = workspace / "missing.parquet"
    assert invoke(workspace, "inspect", "bathymetry", "--input", str(missing)) == 1
    err = assert_guidance(
        capsys, "Required local input is missing", "inspect / bathymetry"
    )
    assert str(missing) in err and "source guide" in err


@pytest.mark.parametrize(
    ("section", "key", "value", "setting"),
    [
        (
            "processing",
            "bathymetry_sign",
            "upwards",
            "bathymetry.processing.bathymetry_sign",
        ),
        ("processing", "h3_resolution", 16, "bathymetry.processing.h3_resolution"),
        (
            "processing",
            "h3_resolution",
            "password=DO_NOT_PRINT",
            "Invalid numeric configuration",
        ),
        ("map", "smoothing_projected_crs", "EPSG:4326", "horizontal axes in meters"),
        (
            "map",
            "smoothing_projected_crs",
            "invalid-crs",
            "Invalid declared scientific projected CRS",
        ),
    ],
)
def test_invalid_scientific_configuration(
    workspace, monkeypatch, capsys, section, key, value, setting
):
    config = workspace / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(config.read_text())
    raw["bathymetry"][section][key] = value
    config.write_text(yaml.safe_dump(raw))
    assert invoke(workspace, "download", "bathymetry") == 1
    err = assert_guidance(capsys, setting, "download / bathymetry")
    assert "DO_NOT_PRINT" not in err
    with monkeypatch.context() as api_context:
        api_context.setenv("SEASCAPE_WORKSPACE", str(workspace))
        with pytest.raises(CRSError if value == "invalid-crs" else ValueError):
            load_bathymetry_config(workspace / "config/data/project.yaml")


def test_yaml_syntax_diagnostic_does_not_echo_source_secrets(workspace, capsys):
    config = workspace / "config/data/project.yaml"
    config.write_text("password: [DO_NOT_PRINT\n")
    assert invoke(workspace, "build", "--only", "seascape-bathymetry") == 1
    err = assert_guidance(capsys, "Invalid configuration YAML", "build")
    assert "line" in err and "DO_NOT_PRINT" not in err
    with pytest.raises(yaml.YAMLError):
        ConfigDocument.load(config)


def test_remote_location_in_missing_config_is_redacted(workspace, capsys):
    assert (
        invoke(
            workspace,
            "download",
            "bathymetry",
            "--config=https://user:DO_NOT_PRINT@example.invalid/config.yaml",
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "DO_NOT_PRINT" not in captured.err + captured.out
    assert "<redacted sensitive detail>" in captured.err
    assert "Action:" in captured.err


def test_build_missing_source_keeps_stage_and_path(workspace, capsys):
    assert invoke(workspace, "build", "--only", "seascape-water-geometry") == 1
    err = assert_guidance(
        capsys, "Required local input is missing", "build / seascape-water-geometry"
    )
    assert "downloads are disabled" in err and "data/raw" in err
    assert not (workspace / "data/processed").exists()


def test_existing_export_is_preserved(workspace, tmp_path, capsys):
    output = tmp_path / "trusted.parquet"
    output.write_bytes(b"retained synthetic acceptance sentinel")
    assert invoke(workspace, "export-metric-matrix", "--output", str(output)) == 1
    err = assert_guidance(capsys, "Output already exists", "export-metric-matrix")
    assert str(output) in err and "distinct export destination" in err
    assert output.read_bytes() == b"retained synthetic acceptance sentinel"
    with pytest.raises(FileExistsError):
        metric_matrix.build_metric_matrix(workspace=workspace, output=output)


def test_skipped_dependency_has_actionable_failure(workspace, capsys):
    assert (
        invoke(
            workspace,
            "build",
            "--only",
            "seascape-bathymetry",
            "--skip",
            "seascape-water-geometry",
            "--dry-run",
        )
        == 1
    )
    err = assert_guidance(
        capsys, "incomplete dependency", "build / seascape-water-geometry"
    )
    assert "remove --skip" in err and "checksum/config/upstream-valid" in err
    assert not (workspace / ".seascape").exists()


@pytest.mark.parametrize("flags", [(), ("--debug",)])
def test_json_failures_keep_stdout_parseable(workspace, capsys, flags):
    assert (
        invoke(
            workspace,
            *flags,
            "build",
            "--only",
            "seascape-bathymetry",
            "--dry-run",
            "--check-inputs",
            "--json",
        )
        == 1
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "failed"
    assert "Action:" in captured.err and "Guide:" in captured.err
    assert "Traceback" not in captured.out
    assert not (workspace / ".seascape").exists()


def test_bad_selection_stays_a_python_value_error(workspace, capsys):
    assert invoke(workspace, "build", "--only", "missing-stage", "--dry-run") == 1
    assert_guidance(capsys, "Unknown build-domain-layers stage", "build")
    with pytest.raises(ValueError, match="Unknown build-domain-layers"):
        workflow.selected_stages(only=("missing-stage",))


@pytest.mark.parametrize("operation", ["download", "inspect"])
def test_family_help_and_parser_exit_are_forwarded(workspace, capsys, operation):
    old_argv = sys.argv
    with pytest.raises(SystemExit) as exc:
        invoke(workspace, operation, "bathymetry", "--help")
    assert exc.value.code == 0
    assert "--config" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        invoke(workspace, operation, "bathymetry", "--unknown-option")
    assert exc.value.code == 2
    assert sys.argv is old_argv
    assert os.environ["SEASCAPE_WORKSPACE"] == "previous-workspace"


def test_family_nonzero_result_is_preserved(workspace, monkeypatch):
    monkeypatch.setattr(
        cli.importlib, "import_module", lambda name: SimpleNamespace(main=lambda: 7)
    )
    assert invoke(workspace, "inspect", "bathymetry") == 7


def test_debug_position_and_chained_publication_failure(
    workspace, tmp_path, monkeypatch, capsys
):
    parent = tmp_path / "publication"
    parent.mkdir()

    def publish(**kwargs):
        with TransactionalFamilyPublisher(parent):
            pytest.fail("a locked publisher must refuse overlapping writes")

    monkeypatch.setattr(metric_matrix, "build_metric_matrix", publish)
    with (parent / ".publication.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert (
            invoke(
                workspace,
                "export-metric-matrix",
                "--output",
                str(tmp_path / "matrix.parquet"),
            )
            == 1
        )
        assert_guidance(capsys, "Publication failed", "export-metric-matrix")
        assert (
            invoke(
                workspace,
                "--debug",
                "export-metric-matrix",
                "--output",
                str(tmp_path / "matrix.parquet"),
            )
            == 1
        )
        err = capsys.readouterr().err
        assert "BlockingIOError" in err and "RuntimeError" in err
        assert "direct cause" in err
        with pytest.raises(RuntimeError) as raised:
            publish()
        assert isinstance(raised.value.__cause__, BlockingIOError)
    with pytest.raises(SystemExit) as raised:
        invoke(workspace, "build", "--debug")
    assert raised.value.code == 2


def test_failed_release_gate_keeps_stage_context_and_canonical_bytes(
    workspace, monkeypatch, capsys
):
    candidate = workspace / ".seascape/candidates/fixture"
    audit = (
        candidate
        / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    )
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {"artifact_release_passed": False, "provenance": "synthetic CLI fixture"}
        )
    )
    trusted = workspace / "data/processed/trusted.txt"
    trusted.parent.mkdir(parents=True)
    trusted.write_bytes(b"keep retained scientific products")
    real_build = workflow.run_domain_layer_build

    def runner(ctx):
        publish_candidate_release(
            canonical_project_root=ctx.canonical_root,
            candidate_project_root=ctx.candidate_root,
        )

    def build(**kwargs):
        return real_build(
            **kwargs,
            stage_definitions=(
                workflow.DomainBuildStage(
                    "seascape-release", "synthetic failing release", runner
                ),
            ),
        )

    monkeypatch.setattr(workflow, "run_domain_layer_build", build)
    assert (
        invoke(workspace, "build", "--candidate-root", str(candidate), "--publish") == 1
    )
    err = assert_guidance(
        capsys, "release audit has not passed", "build / seascape-release"
    )
    assert "Do not bypass validation" in err
    assert trusted.read_bytes() == b"keep retained scientific products"
    with pytest.raises(ValueError, match="audit has not passed"):
        publish_candidate_release(
            canonical_project_root=workspace, candidate_project_root=candidate
        )


def test_publication_path_refusal_does_not_create_a_transaction(
    workspace, monkeypatch, capsys
):
    def publish(**kwargs):
        publisher = SeascapeReleasePublisher(workspace, workspace / "candidate")
        publisher.stage_candidate("../trusted.parquet")

    monkeypatch.setattr(metric_matrix, "build_metric_matrix", publish)
    assert (
        invoke(
            workspace,
            "export-metric-matrix",
            "--output",
            str(workspace / "export.parquet"),
        )
        == 1
    )
    assert_guidance(
        capsys, "Candidate release paths must be relative", "export-metric-matrix"
    )
    assert not (workspace / ".staging").exists()
    assert not (workspace / ".transactions").exists()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("unlisted calculation defect"),
        RuntimeError("unexpected implementation defect"),
        KeyError("programmer key"),
        TypeError("programmer type"),
    ],
)
def test_unexpected_family_errors_are_not_translated(workspace, monkeypatch, error):
    def fail():
        raise error

    monkeypatch.setattr(
        cli.importlib, "import_module", lambda name: SimpleNamespace(main=fail)
    )
    old_argv = sys.argv
    with pytest.raises(type(error)) as raised:
        invoke(workspace, "inspect", "bathymetry")
    assert raised.value is error
    assert sys.argv is old_argv
    assert os.environ["SEASCAPE_WORKSPACE"] == "previous-workspace"


def test_unexpected_build_error_and_chain_are_preserved(workspace, monkeypatch):
    real_build = workflow.run_domain_layer_build
    error = ValueError("unlisted scientific calculation failure")

    def runner(ctx):
        try:
            raise RuntimeError("original cause")
        except RuntimeError as cause:
            raise error from cause

    def build(**kwargs):
        return real_build(
            **kwargs,
            stage_definitions=(
                workflow.DomainBuildStage(
                    "fixture", "synthetic programming failure", runner
                ),
            ),
        )

    monkeypatch.setattr(workflow, "run_domain_layer_build", build)
    with pytest.raises(ValueError) as raised:
        invoke(workspace, "build")
    assert raised.value is error
    assert str(raised.value.__cause__) == "original cause"
    assert os.environ["SEASCAPE_WORKSPACE"] == "previous-workspace"
