"""Full-profile dependencies, scientific inputs, resource guards and final readback."""

import json
import sys
from types import SimpleNamespace

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from seascape import cli
from seascape.domain_parquets import AreaTables, export_domain_parquets
from seascape.metric_rebuild import PRODUCERS, metric_stages, monitor_command
from seascape.metric_rebuild_stages import digest, verify_metrics, verify_source
from seascape.workflow import selected_stages


def test_current_profile_dependency_closure_covers_all_producers():
    stages = selected_stages(only=("seascape-parquets",), stages=metric_stages())
    assert [s.name for s in stages] == [
        "metric-sources",
        "metric-water-geometry",
        "metric-water-network",
        "metric-bathymetry",
        "metric-producers",
        "seascape-parquets",
    ]
    assert {
        "mapped-substrate",
        "kelp",
        "seagrass",
        "bivalve",
        "nearshore",
        "coast-complexity",
    } <= set(PRODUCERS)
    assert len(PRODUCERS) == len(set(PRODUCERS)) == 16


def test_profile_preflight_is_path_only_and_does_not_create_work(tmp_path, capsys):
    source = tmp_path / "source.json"
    source.write_text("{}")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"metric_rebuild": {"sources": [{"path": str(source), "sha256": "0" * 64}]}}
        )
    )
    work = tmp_path / "candidate"
    assert (
        cli.main(
            [
                "--workspace",
                str(tmp_path),
                "build",
                "--profile",
                "metrics",
                "--config",
                str(config),
                "--work-root",
                str(work),
                "--dry-run",
                "--check-inputs",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready"
    assert "Path inspection only" in report["checks"][0]["detail"]
    assert not work.exists()
    # A path-only preflight is not falsely promoted into checksum acceptance.
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_source({"path": str(source), "sha256": "0" * 64})


def test_sources_reject_metric_inputs_but_accept_a_pinned_identity_grid(tmp_path):
    path = tmp_path / "source.parquet"
    cell = h3.latlng_to_cell(48.5, -123.5, 6)
    pq.write_table(pa.table({"H3_INDEX": [cell], "DEPTH_M": [20.0]}), path)
    with pytest.raises(ValueError, match="Computed H3 measurements"):
        verify_source(
            {"path": str(path), "sha256": digest(path), "role": "source_inventory"}
        )
    with pytest.raises(ValueError, match="Computed H3 measurements"):
        verify_source(
            {"path": str(path), "sha256": digest(path), "role": "reporting_keys"}
        )
    pq.write_table(pa.table({"H3_INDEX": [cell]}), path)
    assert verify_source(
        {"path": str(path), "sha256": digest(path), "role": "reporting_keys"}
    )["sha256"] == digest(path)


def test_worker_timeout_terminates_and_records_failure(tmp_path, monkeypatch):
    import psutil

    # The guard decision is deterministic without depending on host process permissions.
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=100), children=lambda recursive: []
        ),
    )
    with pytest.raises(RuntimeError, match="worker time limit"):
        monitor_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            directory=tmp_path / "worker",
            limits={"seconds": 0.1, "disk_reserve_gib": 0},
        )
    result = json.loads((tmp_path / "worker/status.json").read_text())
    assert result["active"] is False
    assert result["returncode"] != 0
    assert result["stop_reason"] == "worker time limit"


def test_worker_log_budget_preserves_bounded_failure_evidence(tmp_path, monkeypatch):
    import psutil

    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=100), children=lambda recursive: []
        ),
    )
    with pytest.raises(RuntimeError, match="worker log limit"):
        monitor_command(
            [
                sys.executable,
                "-c",
                "import time; print('a'*20000, flush=True); time.sleep(30)",
            ],
            directory=tmp_path / "worker",
            limits={"log_mib": 0.001, "disk_reserve_gib": 0},
        )
    assert (
        json.loads((tmp_path / "worker/status.json").read_text())["stop_reason"]
        == "worker log limit"
    )


def test_extra_native_families_are_included_in_one_export_transaction(
    tmp_path, monkeypatch
):
    from seascape import domain_parquets

    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {"products": {"h3_marine_support": {"collection": {"paths": {}}}}}
        )
    )
    expected = {"kelp": AreaTables(static=pa.table({"example": [1]}))}
    writes = []
    monkeypatch.setattr(
        domain_parquets,
        "write_areas",
        lambda pairs, **kwargs: writes.append(pairs) or {},
    )
    export_domain_parquets(
        workspace=tmp_path, catalog_path=catalog, additional_areas=expected
    )
    assert len(writes) == 1 and writes[0] == expected


@pytest.mark.parametrize(
    "failure", [None, "duplicate", "nonfinite", "extra_column", "empty"]
)
def test_complete_row_readback_rejects_bad_layout_and_values(
    tmp_path, monkeypatch, failure
):
    from seascape import metric_rebuild_stages

    names = ["H3_INDEX", "KELP_EXTENT_ALL_TIME_M2"]
    filename = "kelp-r6-static.parquet"
    resource = SimpleNamespace(
        read_text=lambda: json.dumps({"files": {filename: names}})
    )
    monkeypatch.setattr(
        metric_rebuild_stages,
        "files",
        lambda package: SimpleNamespace(joinpath=lambda path: resource),
    )
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123.5, 6), 1))[:2]
    values = [1.0, None]
    if failure == "duplicate":
        cells[1] = cells[0]
    if failure == "nonfinite":
        values[0] = float("nan")
    if failure == "empty":
        cells, values = [], []
    table = pa.table(
        {
            "H3_INDEX": pa.array(cells, type=pa.string()),
            "KELP_EXTENT_ALL_TIME_M2": pa.array(values, type=pa.float64()),
        }
    )
    if failure == "extra_column":
        table = table.append_column("EXTRA_COVERAGE", pa.array([1.0, 1.0]))
    table = table.replace_schema_metadata(
        {b"seascape_domain": b'{"delivery_projection":{"policy":"fixture"}}'}
    )
    pq.write_table(table, tmp_path / filename)
    (tmp_path / "catalog.json").write_text("{}")
    if failure:
        with pytest.raises(ValueError):
            verify_metrics(tmp_path)
    else:
        assert verify_metrics(tmp_path)["files"][filename]["rows"] == 2


def test_native_profile_publication_retains_standard_source_manifest(
    tmp_path, monkeypatch
):
    from seascape.metric_rebuild_stages import _publish_tables
    from seascape.utils.artifacts import validate_manifest

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SEASCAPE_CANDIDATE_ROOT", str(tmp_path))
    source = tmp_path / "raw.json"
    source.write_text("{}")
    cell = h3.latlng_to_cell(48.5, -123.5, 6)
    table = pa.table(
        {"H3_INDEX": [cell], "H3_RESOLUTION": [6], "KELP_EXTENT_ALL_TIME_M2": [1.0]}
    )
    directory = tmp_path / "native"
    _publish_tables(
        directory,
        {"kelp-r6-static.parquet": table},
        context={"rights": "synthetic fixture"},
        source_paths=[source],
    )
    manifest = json.loads((directory / "metric_profile_manifest.json").read_text())
    validate_manifest(manifest, project_root=tmp_path, verify_artifacts=True)
    assert manifest["sources"][0]["name"] == "raw.json"
    assert manifest["source_completeness"] == "partial"
