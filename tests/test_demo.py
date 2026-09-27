"""Portable demo acceptance through production APIs; no live data required."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from seascape import demo
from seascape.cli import main
from seascape.core.artifacts.checksums import checksum_path
from seascape.seafloor_physiography.bathymetry import pipeline


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise RuntimeError("Outbound network denied by demo test")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(pipeline, "download_gebco_geotiff", deny)


@pytest.fixture
def result(tmp_path):
    return demo.run_demo(tmp_path / "workspace")


def test_normal_run_nonempty_expected_values_and_provenance(result):
    report = json.loads(result.report_path.read_text())
    assert report["status"] == "PASS"
    assert report["checks"] and all(report["checks"].values())
    frame = pd.read_parquet(result.parquet_path).set_index("H3_INDEX")
    flat = frame.loc[report["controls"]["flat"]]
    assert flat["BATHYMETRY"] == pytest.approx(5.0, abs=1e-6, rel=0)
    assert flat["BATHYMETRY_STD"] == 0.0
    assert flat["BATHYMETRY_RANGE"] == 0.0
    assert flat["BATHYMETRY_FRAC_0_10_M"] == 1.0
    assert flat["BATHYMETRY_FRAC_10_30_M"] == 0.0
    gradient = frame.loc[report["controls"]["gradient"]]
    assert gradient["BATHYMETRY_PIXEL_COUNT"] == 18
    assert gradient["BATHYMETRY"] == pytest.approx(5680 / 47, abs=3e-5, rel=0)
    assert gradient["BATHYMETRY_MIN"] == pytest.approx(5280 / 47, abs=3e-5, rel=0)
    assert gradient["BATHYMETRY_MAX"] == pytest.approx(6085 / 47, abs=3e-5, rel=0)
    assert gradient["BATHYMETRY_RANGE"] == pytest.approx(805 / 47, abs=3e-5, rel=0)
    assert frame["BATHYMETRY_PIXEL_COUNT"].sum() == 2016
    for name in ("sea_level", "nodata", "outside"):
        assert pd.isna(frame.loc[report["controls"][name], "BATHYMETRY"])
        assert pd.isna(frame.loc[report["controls"][name], "BATHYMETRY_PIXEL_COUNT"])
    assert result.metadata["units"] == "m"
    assert result.metadata["vertical_datum"].startswith("synthetic")
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["sources"][0]["name"] == "SYNTHETIC seascape-demo-v1"
    assert "GEBCO" not in json.dumps(manifest)
    assert "CC BY" not in json.dumps(manifest)
    for path in result.figure_paths:
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_arbitrary_cwd_environment_restoration_and_confinement(tmp_path, monkeypatch):
    outside = tmp_path / "arbitrary"
    outside.mkdir()
    monkeypatch.chdir(outside)
    previous = {
        "SEASCAPE_WORKSPACE": "/unused/workspace",
        "SEASCAPE_CANDIDATE_ROOT": "/unused/candidate",
        "SEASCAPE_COMMON_CONFIG": "/unused/common.yaml",
        "MPLCONFIGDIR": "/unused/mpl",
    }
    for name, value in previous.items():
        monkeypatch.setenv(name, value)
    result = demo.run_demo(tmp_path / "workspace")
    assert all(os.environ[name] == value for name, value in previous.items())
    assert not list(outside.iterdir())
    root = result.workspace
    manifest = json.loads(result.manifest_path.read_text())
    for item in [
        *manifest["sources"],
        *manifest["upstream_artifacts"],
        *manifest["artifacts"],
    ]:
        assert (root / item["path"]).resolve().is_relative_to(root)
        assert checksum_path(root / item["path"]) == item["checksum"]
    config = yaml.safe_load((root / "config/demo.yaml").read_text())
    for path in (
        config["base_directory"],
        config["bathymetry"]["source"]["raw_dir"],
        config["bathymetry"]["processing"]["processed_path"],
        config["bathymetry"]["processing"]["water_polygon_path"],
        config["water_network"]["output_dir"],
    ):
        assert Path(path).is_relative_to(root)
    assert not (tmp_path / "workspace/config").exists()
    assert not (tmp_path / "workspace/data").exists()
    assert not (tmp_path / "workspace/.seascape/releases").exists()


def test_existing_refusal_repeatability_and_preservation(result, tmp_path):
    root = result.workspace
    unrelated = [
        root / "notes.txt",
        root / "input/user.csv",
        root / "output/user.parquet",
        root.parent / "releases/retained.bin",
        root.parents[1] / "config/data/project.yaml",
        root.parents[1] / "data/processed/canonical.parquet",
    ]
    for path in unrelated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"user sentinel")
    before = {path: path.read_bytes() for path in unrelated}
    report_before = result.report_path.read_bytes()
    with pytest.raises(demo.DemoWorkspaceError, match="already exists"):
        demo.run_demo(root.parents[1])
    assert result.report_path.read_bytes() == report_before
    initial = pd.read_parquet(result.parquet_path)
    second = demo.run_demo(root.parents[1], overwrite=True)
    pd.testing.assert_frame_equal(
        initial, pd.read_parquet(second.parquet_path), check_exact=True
    )
    third = demo.run_demo(tmp_path / "second-workspace")
    pd.testing.assert_frame_equal(
        initial, pd.read_parquet(third.parquet_path), check_exact=True
    )
    assert before == {path: path.read_bytes() for path in unrelated}


@pytest.mark.parametrize(
    "mode",
    [
        "unowned",
        "wrong_marker",
        "known_directory",
        "ancestor_symlink",
        "file_symlink",
        "directory_symlink",
        "transactions",
    ],
)
def test_unsafe_overwrite_is_refused_without_writes(tmp_path, mode):
    workspace = tmp_path / "workspace"
    root = workspace / ".seascape/demo"
    root.mkdir(parents=True)
    (root / ".owner").write_text(demo._OWNER)
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"do not touch")
    if mode == "unowned":
        (root / ".owner").unlink()
    elif mode == "wrong_marker":
        (root / ".owner").write_text("user directory")
    elif mode == "known_directory":
        (root / "report.json").mkdir()
    elif mode == "ancestor_symlink":
        workspace = tmp_path / "alias"
        workspace.symlink_to(root.parents[1], target_is_directory=True)
    elif mode == "file_symlink":
        (root / "report.json").symlink_to(sentinel)
    elif mode == "directory_symlink":
        (root / "input").symlink_to(tmp_path, target_is_directory=True)
    elif mode == "transactions":
        (root / "output/.transactions/foreign").mkdir(parents=True)
        (root / "output/.transactions/foreign/journal.json").write_text("{}")
    with pytest.raises(demo.DemoWorkspaceError):
        demo.run_demo(workspace, overwrite=True)
    assert sentinel.read_bytes() == b"do not touch"
    assert not (root / "config/demo.yaml").exists()


@pytest.mark.parametrize(
    "stage", ["fixture", "metadata", "pipeline", "validation", "figure", "network"]
)
def test_failure_invalidates_previous_pass_and_restores_environment(
    result, monkeypatch, stage
):
    previous = dict(os.environ)

    def fail(*args, **kwargs):
        if stage == "network":
            socket.create_connection(("example.com", 443))
        raise RuntimeError("injected demo failure")

    target = {
        "fixture": "_prepare_fixture",
        "metadata": "version",
        "pipeline": "run_pipeline",
        "validation": "_validate",
        "figure": "_figures",
        "network": "run_pipeline",
    }[stage]
    monkeypatch.setattr(demo, target, fail)
    with pytest.raises(RuntimeError, match="demo failure|network denied"):
        demo.run_demo(result.workspace.parents[1], overwrite=True)
    assert dict(os.environ) == previous
    report = json.loads(result.report_path.read_text())
    assert report["status"] == "FAIL"
    assert "error" in report


def test_empty_or_all_null_output_cannot_pass(result, monkeypatch):
    frame = pd.read_parquet(result.parquet_path)
    fixture = {
        "cells": list(frame["H3_INDEX"]),
        "controls": json.loads(result.report_path.read_text())["controls"],
        "flat_count": 10,
    }
    # Keep the published artifact intact so checksum validation still runs.
    real_read = pd.read_parquet
    monkeypatch.setattr(
        demo.pd,
        "read_parquet",
        lambda path: frame.iloc[:0] if path == result.parquet_path else real_read(path),
    )
    with pytest.raises(AssertionError, match="nonempty"):
        demo._validate(result.workspace, fixture)
    frame["BATHYMETRY"] = np.nan
    monkeypatch.setattr(demo.pd, "read_parquet", lambda path: frame)
    checks = demo._validate(result.workspace, fixture)
    assert not checks["nonempty_valid_depth"]
    assert not checks["known_constant_depth_m"]
    assert not checks["valid_depth_band_partition"]


@pytest.mark.parametrize(
    "column", ["BATHYMETRY", "BATHYMETRY_RANGE", "BATHYMETRY_PIXEL_COUNT"]
)
def test_demo_rejects_corrupted_gradient_values(result, monkeypatch, column):
    frame = pd.read_parquet(result.parquet_path)
    controls = json.loads(result.report_path.read_text())["controls"]
    fixture = {
        "cells": list(frame["H3_INDEX"]),
        "controls": controls,
        "flat_count": int(
            frame.set_index("H3_INDEX").loc[controls["flat"], "BATHYMETRY_PIXEL_COUNT"]
        ),
    }
    frame.loc[frame["H3_INDEX"] == controls["gradient"], column] += 1
    monkeypatch.setattr(demo.pd, "read_parquet", lambda path: frame)
    assert not demo._validate(result.workspace, fixture)["known_gradient_depth_m"]


def test_demo_finite_policy_rejects_infinity(result, monkeypatch):
    frame = pd.read_parquet(result.parquet_path)
    controls = json.loads(result.report_path.read_text())["controls"]
    fixture = {
        "cells": list(frame["H3_INDEX"]),
        "controls": controls,
        "flat_count": int(
            frame.set_index("H3_INDEX").loc[controls["flat"], "BATHYMETRY_PIXEL_COUNT"]
        ),
    }
    frame.loc[frame["H3_INDEX"] == controls["gradient"], "BATHYMETRY"] = np.inf
    monkeypatch.setattr(demo.pd, "read_parquet", lambda path: frame)
    checks = demo._validate(result.workspace, fixture)
    assert not checks["finite_or_null_numeric_values"]
    assert not checks["positive_down_meters_and_bounds"]


def test_synthetic_acquisition_is_rejected(result):
    with pytest.raises(ValueError, match="requires skip_download=True"):
        pipeline.run_pipeline(result.workspace / "config/demo.yaml")
    with pytest.raises(ValueError, match="requires skip_map=True"):
        pipeline.run_pipeline(result.workspace / "config/demo.yaml", skip_download=True)


def test_cli_reports_paths_and_expected_failure(tmp_path, capsys):
    workspace = tmp_path / "cli"
    assert main(["--workspace", str(workspace), "demo"]) == 0
    output = capsys.readouterr().out
    assert "Synthetic software acceptance: PASS" in output
    assert "not a regional release" in output
    assert str(workspace / ".seascape/demo/report.json") in output
    assert main(["--workspace", str(workspace), "demo"]) == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert not captured.out
    assert main(["--workspace", str(workspace), "demo", "--overwrite"]) == 0


def test_overlapping_writer_is_refused_without_invalidating_report(result):
    import fcntl

    before = result.report_path.read_bytes()
    with (result.workspace / ".demo.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(demo.DemoWorkspaceError, match="busy"):
            demo.run_demo(result.workspace.parents[1], overwrite=True)
    assert result.report_path.read_bytes() == before


def test_real_provider_manifest_defaults_are_preserved(result):
    config_path = result.workspace / "config/demo.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["bathymetry"]["source"]["provider"] = "GEBCO"
    config["bathymetry"]["source"]["release"] = "2026"
    config_path.write_text(yaml.safe_dump(config))
    pipeline.run_pipeline(config_path, skip_download=True, skip_map=True)
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["sources"][0]["name"] == "GEBCO 2026"
    assert (
        manifest["sources"][0]["license"]
        == "GEBCO data are distributed under the CC BY 4.0 license."
    )
    assert manifest["attribution"][0]["license"] == "CC BY 4.0"
    assert "synthetic" not in manifest["metadata"]
    assert "validation_scope" not in manifest["metadata"]
