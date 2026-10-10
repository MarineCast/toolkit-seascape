"""Pinned portable contract, fail-closed planning, and unchanged standalone routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seascape import cli
from seascape.core.config.common_areas import bbox_for_area
from seascape.core.config.data import load_data_config
from seascape.study import (
    StudyConfigError,
    current_study,
    load_study_config,
    study_context,
)
from seascape.workflow import _configuration_identity, run_domain_layer_build


@pytest.fixture
def study_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MARINECAST_STUDY_CONFIG", raising=False)
    path = tmp_path / "portable" / "config" / "study.v1.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        (Path(__file__).parent / "fixtures/study.coastal.v1.json").read_bytes()
    )
    return path


def test_exact_pin_and_relative_root(study_file):
    study = load_study_config(study_file, planning=True)
    assert (
        study.config_sha256
        == "bacf22ea2b0beb32d1ef5607f52b2f6104419dd329edf25657bca196acc8018c"
    )
    assert (
        study.provenance()["geometry_sha256"]
        == "6d79e4dfd29a4ada66625e20fdcd01e7bfe6076bf6ebb4c449581eb3a0cdfb68"
    )
    assert study.data_root == study_file.parent.parent / "Data"
    assert study.provenance()["requested_time"]["end_exclusive"] == "2027-01-01"
    assert study.provenance()["contract"] == json.loads(study_file.read_text())
    mutable = study.payload
    mutable["time"]["start"] = "2026-01-01"
    assert study.payload["time"]["start"] == "2009-01-01"


def test_selection_precedence_and_no_guess(study_file, monkeypatch):
    assert load_study_config() is None
    monkeypatch.setenv(
        "MARINECAST_STUDY_CONFIG", str(study_file.parent / "missing.json")
    )
    assert load_study_config(study_file, planning=True).source == study_file
    with pytest.raises(StudyConfigError):
        load_study_config(planning=True)
    monkeypatch.setenv("MARINECAST_STUDY_CONFIG", str(study_file))
    assert load_study_config(planning=True).source == study_file


@pytest.mark.parametrize(
    "change",
    [
        "geometry",
        "dates",
        "unknown",
        "absolute_root",
        "boolean_resolution",
        "validated_registry",
    ],
)
def test_invalid_contract_before_outputs(study_file, change):
    value = json.loads(study_file.read_text())
    if change == "geometry":
        value["domain"]["bbox_wgs84"][0] -= 1
    elif change == "dates":
        value["time"]["start"] = value["time"]["end_exclusive"]
    elif change == "unknown":
        value["unrecognized"] = True
    elif change == "absolute_root":
        value["storage"]["data_root"] = "/tmp/unapproved-data"
    elif change == "boolean_resolution":
        value["products"]["seascape"]["h3_resolution"] = True
    else:
        value["grid_registry"]["status"] = "validated"
    study_file.write_text(json.dumps(value))
    with pytest.raises(StudyConfigError):
        load_study_config(study_file, planning=True)
    assert not (study_file.parent.parent / "Data").exists()


@pytest.mark.parametrize(
    "text", ['{"schema_version":1,"schema_version":1}', '{"value":NaN}']
)
def test_noncanonical_json_rejected(study_file, text):
    study_file.write_text(text)
    with pytest.raises(StudyConfigError):
        load_study_config(study_file, planning=True)


def test_proposed_and_approved_production_both_fail_closed(
    study_file, tmp_path, capsys
):
    workspace = tmp_path / "unwritten"
    assert (
        cli.main(
            ["--workspace", str(workspace), "--study-config", str(study_file), "build"]
        )
        == 1
    )
    assert "proposed" in capsys.readouterr().err
    assert not workspace.exists()
    value = claimed_validated_coastal_config()
    study_file.write_text(json.dumps(value))
    assert (
        cli.main(
            [
                "--workspace",
                str(workspace),
                "--study-config",
                str(study_file),
                "download",
                "bathymetry",
            ]
        )
        == 1
    )
    assert "production integration is not enabled" in capsys.readouterr().err
    assert not workspace.exists()


def test_planning_effective_config_and_identity(study_file, tmp_path, monkeypatch):
    workspace = tmp_path / "inputs"
    cli.initialize_workspace(workspace)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(workspace))
    source = workspace / "config/data/project.yaml"
    baseline = _configuration_identity(source)
    study = load_study_config(study_file, planning=True)
    with study_context(study, planning=True):
        with pytest.raises(StudyConfigError, match="acquisition envelope"):
            bbox_for_area("model_area")
        config = load_data_config(source)
        assert config["marinecast_study"]["config_sha256"] == study.config_sha256
        assert config["marinecast_study_contract"] == study.payload
        assert (
            config["shoreline_proximity"]["processing"]["network_context_buffer_km"]
            == 60
        )
        assert config["water_network"]["resolutions"] == [6, 8]
        assert _configuration_identity(source) != baseline
        with pytest.raises(StudyConfigError, match="production integration"):
            run_domain_layer_build(config_path=source)
        assert not (workspace / ".seascape").exists()
    assert current_study() is None
    assert _configuration_identity(source) == baseline


def test_readonly_cli_plan_has_full_identity_and_never_claims_ready(
    study_file, tmp_path, monkeypatch, capsys
):
    workspace = tmp_path / "inputs"
    cli.initialize_workspace(workspace)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", "original-selection")
    assert (
        cli.main(
            [
                "--workspace",
                str(workspace),
                "--study-config",
                str(study_file),
                "build",
                "--dry-run",
                "--json",
                "--only",
                "seascape-bathymetry",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["study_production_ready"] is False
    assert report["marinecast_study"]["contract"] == json.loads(study_file.read_text())
    assert not (workspace / ".seascape").exists()
    assert current_study() is None
    import os

    assert os.environ["SEASCAPE_WORKSPACE"] == "original-selection"


def test_buffer_and_date_changes_invalidate_effective_identity(
    study_file, tmp_path, monkeypatch
):
    workspace = tmp_path / "inputs"
    cli.initialize_workspace(workspace)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(workspace))
    source = workspace / "config/data/project.yaml"
    with study_context(load_study_config(study_file, planning=True), planning=True):
        baseline = _configuration_identity(source)
    config = json.loads(study_file.read_text())
    config["producer_buffers"]["seascape"]["coastal_network_m"] += 1000
    config["time"]["start"] = "2010-01-01"
    study_file.write_text(json.dumps(config))
    with study_context(load_study_config(study_file, planning=True), planning=True):
        assert _configuration_identity(source) != baseline


def test_manifest_fixture_retains_full_identity(study_file, tmp_path):
    from seascape.utils.artifacts import build_manifest

    artifact = tmp_path / "fixture.txt"
    artifact.write_text("synthetic provenance fixture")
    study = load_study_config(study_file, planning=True)
    with study_context(study, planning=True):
        manifest = build_manifest(
            dataset_family="environment.seascape.fixture",
            run_id="study-metadata-fixture",
            resolved_config={"fixture": True},
            artifacts=[artifact],
            project_root=tmp_path,
            sources=[],
            upstream_artifacts=[],
            attribution=[{"text": "Synthetic fixture only"}],
            source_completeness="unavailable",
        )
        assert manifest["metadata"]["marinecast_study"] == study.provenance()
        with pytest.raises(ValueError, match="conflicts"):
            build_manifest(
                dataset_family="environment.seascape.fixture",
                run_id="study-metadata-fixture",
                resolved_config={},
                artifacts=[artifact],
                project_root=tmp_path,
                sources=[],
                upstream_artifacts=[],
                attribution=[{"text": "Fixture"}],
                source_completeness="unavailable",
                metadata={"marinecast_study": {}},
            )


def test_current_shared_contract_compatibility(study_file):
    import hashlib
    from importlib.resources import files

    study = load_study_config(study_file, planning=True)
    assert (
        study.config_sha256
        == "bacf22ea2b0beb32d1ef5607f52b2f6104419dd329edf25657bca196acc8018c"
    )
    assert study.payload["domain"]["approval"] is None
    assert study.provenance()["production_ready"] is False
    schema = (
        files("seascape").joinpath("resources/contracts/study.schema.json").read_bytes()
    )
    assert (
        hashlib.sha256(schema).hexdigest()
        == "77110ba989c47e621fcf1a4cb598f059dcc79a250b36e9a77b5154480cb89c5c"
    )


@pytest.mark.parametrize("fixture", ["study.v1.json", "study.current.v1.json"])
def test_superseded_selected_rectangular_contract_rejected(study_file, fixture):
    study_file.write_bytes((Path(__file__).parent / "fixtures" / fixture).read_bytes())
    with pytest.raises(StudyConfigError, match="selection_policy"):
        load_study_config(study_file, planning=True)


@pytest.mark.parametrize(
    "approval",
    [
        None,
        {
            "approved_at": "2026-10-06T01:00:00",
            "source_message_id": "fixture",
            "scope": "rectangular_selection_only",
            "statement": "Synthetic fixture",
        },
    ],
)
def test_approval_provenance_required_and_timestamp_zoned(study_file, approval):
    config = json.loads(study_file.read_text())
    config["domain"]["status"] = "approved"
    config["domain"]["approval"] = approval
    study_file.write_text(json.dumps(config))
    with pytest.raises(StudyConfigError, match="approval"):
        load_study_config(study_file, planning=True)


def test_one_source_snapshot_controls_all_provenance(study_file, monkeypatch):
    import hashlib

    from seascape._study_contract import canonical_bytes

    original = study_file.read_bytes()
    replacement = json.loads(original)
    replacement["time"]["start"] = "2011-01-01"
    real_read = Path.read_bytes
    reads = []

    def changing_read(path):
        captured = real_read(path)
        if path == study_file:
            reads.append(captured)
            path.write_text(json.dumps(replacement))
        return captured

    monkeypatch.setattr(Path, "read_bytes", changing_read)
    study = load_study_config(study_file, planning=True)
    assert reads == [original]
    assert study.payload["time"]["start"] == "2009-01-01"
    assert json.loads(study_file.read_text())["time"]["start"] == "2011-01-01"
    assert study.raw_file_sha256 == hashlib.sha256(original).hexdigest()
    assert (
        study.config_sha256
        == hashlib.sha256(canonical_bytes(json.loads(original))).hexdigest()
    )
    assert study.provenance()["contract"] == json.loads(original)


def coastal_config():
    return json.loads(
        (Path(__file__).parent / "fixtures/study.coastal.v1.json").read_text()
    )


def claimed_validated_coastal_config():
    """Synthetic claims only; never materialize or authorize any support."""
    config = coastal_config()
    config["domain"]["status"] = "approved"
    config["domain"]["approval"] = {
        "approved_at": "2026-10-06T02:00:00Z",
        "source_message_id": "synthetic-fixture",
        "scope": "rectangular_selection_only",
        "statement": "Synthetic envelope metadata",
    }
    config["domain"]["geometry_status"] = "source_relative_validated"
    config["domain"]["selection_policy"]["mask_status"] = "source_relative_validated"
    config["grid_registry"].update(
        {
            "status": "validated",
            "mask_revision": "fixture-only",
            "mask_sha256": "0" * 64,
            "memberships": [
                {
                    "resolution": 6,
                    "role": "water_reporting",
                    "relative_path": "never-materialized-fixture.txt",
                    "count": 0,
                    "sha256": "0" * 64,
                }
            ],
        }
    )
    return config


def test_current_coastal_policy_identity_and_bbox_role(
    study_file, tmp_path, monkeypatch
):
    study_file.write_text(json.dumps(coastal_config()))
    study = load_study_config(study_file, planning=True)
    assert (
        study.config_sha256
        == "bacf22ea2b0beb32d1ef5607f52b2f6104419dd329edf25657bca196acc8018c"
    )
    provenance = study.provenance()
    assert provenance["reporting_bbox_wgs84"] is None
    assert provenance["acquisition_planning_bbox_wgs84"] == [-129.7, 45.9, -121.5, 51.5]
    assert provenance["geometry_sha256_role"] == "acquisition_envelope_identity"
    assert provenance["reporting_selection_policy"]["offshore_distance_m"] == 22224
    assert provenance["reporting_selection_policy"]["status"] == "approved"
    assert (
        provenance["reporting_selection_policy"]["mask_status"]
        == "pending_source_qualified_build"
    )
    with study_context(study, planning=True):
        with pytest.raises(StudyConfigError, match="acquisition envelope"):
            bbox_for_area("model_area")
    workspace = tmp_path / "planning-inputs"
    cli.initialize_workspace(workspace)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(workspace))
    with study_context(study, planning=True):
        effective = load_data_config(workspace / "config/data/project.yaml")
        assert effective["marinecast_study"]["reporting_bbox_wgs84"] is None
        assert effective["marinecast_study_contract"] == coastal_config()


@pytest.mark.parametrize("pending", ["geometry", "mask", "registry"])
def test_approved_policy_cannot_bypass_any_pending_support(study_file, pending):
    config = claimed_validated_coastal_config()
    if pending == "geometry":
        config["domain"]["geometry_status"] = "pending_qualified_coastline_validation"
    elif pending == "mask":
        config["domain"]["selection_policy"]["mask_status"] = (
            "pending_source_qualified_build"
        )
    else:
        config["grid_registry"]["status"] = "pending_validated_marine_mask"
    study_file.write_text(json.dumps(config))
    assert (
        load_study_config(study_file, planning=True).payload["domain"][
            "selection_policy"
        ]["status"]
        == "approved"
    )
    with pytest.raises(
        StudyConfigError, match="validated coastal mask, geometry and registry"
    ):
        load_study_config(study_file, planning=False)


def test_all_certification_claims_still_do_not_enable_adapter_production(
    study_file, tmp_path, capsys
):
    study_file.write_text(json.dumps(claimed_validated_coastal_config()))
    study = load_study_config(study_file, planning=False)
    with pytest.raises(StudyConfigError, match="production integration is not enabled"):
        with study_context(study):
            pytest.fail("production context must never open")
    destination = tmp_path / "unwritten"
    assert (
        cli.main(
            [
                "--workspace",
                str(destination),
                "--study-config",
                str(study_file),
                "download",
                "bathymetry",
            ]
        )
        == 1
    )
    assert "production integration is not enabled" in capsys.readouterr().err
    assert not destination.exists()


@pytest.mark.parametrize("missing", ["bbox_role", "geometry_status", "policy_approval"])
def test_coastal_policy_requires_role_status_and_approval(study_file, missing):
    config = coastal_config()
    if missing == "policy_approval":
        config["domain"]["selection_policy"]["approval"] = None
    else:
        config["domain"].pop(missing)
    study_file.write_text(json.dumps(config))
    with pytest.raises(StudyConfigError):
        load_study_config(study_file, planning=True)


def test_coastal_readonly_cli_plan_never_calls_bbox_reporting(
    study_file, tmp_path, capsys
):
    study_file.write_text(json.dumps(coastal_config()))
    workspace = tmp_path / "inputs"
    cli.initialize_workspace(workspace)
    assert (
        cli.main(
            [
                "--workspace",
                str(workspace),
                "--study-config",
                str(study_file),
                "build",
                "--dry-run",
                "--json",
                "--only",
                "seascape-bathymetry",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["study_production_ready"] is False
    assert report["marinecast_study"]["reporting_bbox_wgs84"] is None
    assert "acquisition envelope" in report["study_support_warning"]
    assert not (workspace / ".seascape").exists()


@pytest.mark.parametrize("planning", [True, False])
@pytest.mark.parametrize(
    "policy", ["omit", None, {}, [], "approved", {"status": "approved"}]
)
def test_policy_cannot_be_omitted_null_or_malformed(tmp_path, planning, policy):
    config = claimed_validated_coastal_config()
    if policy == "omit":
        config["domain"].pop("selection_policy")
    else:
        config["domain"]["selection_policy"] = policy
    path = tmp_path / "study.json"
    path.write_text(json.dumps(config))
    with pytest.raises(StudyConfigError):
        load_study_config(path, planning=planning)


@pytest.mark.parametrize("planning", [True, False])
@pytest.mark.parametrize("field", ["bbox_role", "geometry_status", "selection_policy"])
def test_complete_coastal_field_group_required(tmp_path, planning, field):
    config = claimed_validated_coastal_config()
    config["domain"].pop(field)
    path = tmp_path / "study.json"
    path.write_text(json.dumps(config))
    with pytest.raises(StudyConfigError):
        load_study_config(path, planning=planning)


@pytest.mark.parametrize("command", [["build"], ["download", "bathymetry"]])
def test_omitted_policy_entrypoints_fail_before_writes(tmp_path, command, capsys):
    config = claimed_validated_coastal_config()
    config["domain"].pop("selection_policy")
    path = tmp_path / "study.json"
    path.write_text(json.dumps(config))
    destination = tmp_path / "unwritten"
    assert (
        cli.main(
            ["--workspace", str(destination), "--study-config", str(path), *command]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "Invalid study config" in error
    assert "missing=" in error
    assert "production integration is not enabled" not in error
    assert not destination.exists()
