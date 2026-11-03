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
    (tmp_path / "catalog.json").write_text(
        json.dumps({"kelp": {"last_updated_utc": "fixture", "static": {"6": filename}}})
    )
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


@pytest.mark.parametrize("placement", ["workspace", "cwd", "absolute"])
def test_metric_preflight_uses_workspace(tmp_path, monkeypatch, placement):
    from seascape.metric_rebuild import preflight_metrics

    workspace, cwd, external = (
        tmp_path / name for name in ("workspace", "cwd", "external")
    )
    for path in (workspace, cwd, external):
        path.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(workspace))
    {"workspace": workspace, "cwd": cwd, "absolute": external}[placement].joinpath(
        "input"
    ).write_text("fixture")
    source = str(external / "input") if placement == "absolute" else "input"
    config = workspace / "project.yaml"
    config.write_text(
        yaml.safe_dump({"metric_rebuild": {"sources": [{"path": source}]}})
    )
    report = preflight_metrics(config_path=config, check_inputs=True)
    assert report["status"] == ("failed" if placement == "cwd" else "ready")
    assert not (workspace / ".seascape").exists()


def test_source_registry_covers_direct_inputs_and_producer_receipts(
    tmp_path, monkeypatch
):
    from seascape.metric_rebuild import BASE
    from seascape.metric_rebuild_stages import acquire_sources, verify_sources

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    pinned = tmp_path / "pinned"
    pinned.write_text("source")
    unpinned = tmp_path / "unpinned"
    unpinned.write_text("source")
    config = tmp_path / "project.yaml"
    cfg = {
        "sources": [{"path": str(pinned), "sha256": digest(pinned)}],
        "mapped_substrate": {"source": str(unpinned)},
    }
    config.write_text(yaml.safe_dump({"metric_rebuild": cfg}))
    ctx = SimpleNamespace(config_path=config, candidate_root=tmp_path / "work")
    with pytest.raises(ValueError, match="not registered"):
        acquire_sources(ctx)
    assert not (ctx.candidate_root / ".seascape/metric-sources.json").exists()
    cfg["mapped_substrate"]["source"] = str(pinned)
    config.write_text(yaml.safe_dump({"metric_rebuild": cfg}))
    acquire_sources(ctx)
    assert len(verify_sources(ctx)["sources"]) == 1
    directory = ctx.candidate_root / BASE / "anthropogenic"
    directory.mkdir(parents=True)
    manifest = directory / "producer_manifest.json"
    manifest.write_text(json.dumps({"sources": [{"path": str(unpinned)}]}))
    with pytest.raises(ValueError, match="not registered"):
        verify_sources(ctx)
    generated = directory / "generated"
    generated.write_text("derived")
    from seascape.core.artifacts.checksums import checksum_path

    record = {
        "path": str(generated.relative_to(ctx.candidate_root)),
        "checksum": checksum_path(generated),
    }
    manifest.write_text(json.dumps({"sources": [record], "artifacts": [record]}))
    verify_sources(ctx)
    manifest.write_text(
        json.dumps({"sources": [{"path": str(pinned), "checksum": "wrong"}]})
    )
    with pytest.raises(ValueError, match="producer receipt"):
        verify_sources(ctx)


def test_registry_directory_pins_do_not_cover_symlink_escapes(tmp_path):
    from seascape.metric_rebuild_stages import require_registered

    directory = tmp_path / "tree"
    directory.mkdir()
    child = directory / "source"
    child.write_text("source")
    sources = [{"path": str(directory)}]
    require_registered([child], sources)
    outside = tmp_path / "outside"
    outside.write_text("external")
    link = directory / "link"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="not registered"):
        require_registered([link], sources)


@pytest.mark.parametrize(
    "failure", [None, "layout", "source", "unregistered", "candidate-unregistered"]
)
def test_export_validation_precedes_replacement(tmp_path, monkeypatch, failure):
    from seascape import metric_rebuild_stages as stages
    from seascape.domain_parquets import write_areas

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    cell = h3.latlng_to_cell(48.5, -123.5, 6)
    table = pa.table({"H3_INDEX": [cell], "H3_RESOLUTION": [6], "DEPTH_M": [1.0]})
    output = tmp_path / "Data/Seascape"
    write_areas({"bathymetry": AreaTables(table)}, output=output)
    (output / "research").mkdir()
    (output / "research/object.txt").write_text("retain research")
    (output / "review.md").write_text("retain notes")
    before = {
        str(p.relative_to(output)): p.read_bytes()
        for p in output.rglob("*")
        if p.is_file()
    }
    filename = "bathymetry-r6-static.parquet"
    expected = ["H3_INDEX", "DEPTH_M"] + (["MISSING"] if failure == "layout" else [])
    resource = SimpleNamespace(
        read_text=lambda: json.dumps({"files": {filename: expected}})
    )
    monkeypatch.setattr(
        stages, "files", lambda package: SimpleNamespace(joinpath=lambda path: resource)
    )
    source = tmp_path / "source"
    source.write_text("original")
    config = tmp_path / "project.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "metric_rebuild": {
                    "sources": [{"path": str(source), "sha256": digest(source)}]
                }
            }
        )
    )
    ctx = SimpleNamespace(config_path=config, candidate_root=tmp_path / "work")
    stages.acquire_sources(ctx)
    if failure == "source":
        source.write_text("changed after acquisition")
    if failure in {"unregistered", "candidate-unregistered"}:
        directory = ctx.candidate_root / stages.BASE
        directory.mkdir(parents=True)
        extra = (
            ctx.candidate_root if failure == "candidate-unregistered" else tmp_path
        ) / "extra"
        extra.write_text("unregistered")
        (directory / "test_manifest.json").write_text(
            json.dumps({"sources": [{"path": str(extra)}]})
        )
    catalog = tmp_path / "features.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {"products": {"h3_marine_support": {"collection": {"paths": {}}}}}
        )
    )
    visited = []

    def validate(staged):
        assert staged != output
        assert before == {
            str(p.relative_to(output)): p.read_bytes()
            for p in output.rglob("*")
            if p.is_file()
        }
        stages.verify_metrics(staged)
        stages.verify_sources(ctx)
        visited.append(staged)

    def run():
        return export_domain_parquets(
            workspace=tmp_path,
            output=output,
            catalog_path=catalog,
            additional_areas={
                "bathymetry": AreaTables(
                    table.set_column(2, "DEPTH_M", pa.array([2.0]))
                )
            },
            _validate_staged=validate,
        )

    if failure:
        with pytest.raises(ValueError):
            run()
        assert before == {
            str(p.relative_to(output)): p.read_bytes()
            for p in output.rglob("*")
            if p.is_file()
        }
    else:
        run()
        assert len(visited) == 1
        assert pq.read_table(output / filename)["DEPTH_M"].to_pylist() == [2.0]
        assert (output / "research/object.txt").read_text() == "retain research"
        assert (output / "review.md").read_text() == "retain notes"
        stages.verify_metrics(output)
        (output / "unexpected").mkdir()
        with pytest.raises(ValueError, match="unexpected files"):
            stages.verify_metrics(output)


def test_every_direct_profile_input_requires_registration(tmp_path, monkeypatch):
    from seascape.metric_rebuild_stages import (
        configured_source_paths,
        require_registered,
    )

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    cfg = {
        "habitats": {
            family: {
                "inventory": f"{family}-inventory",
                "source_context": f"{family}-context",
                "reporting_keys": {6: f"{family}-r6", 8: f"{family}-r8"},
                "additional_crims_pages": ["kelp-page"] if family == "kelp" else [],
            }
            for family in ("kelp", "seagrass", "bivalve")
        },
        "mapped_substrate": {"source": "substrate"},
        "artificial_reefs": {"wdfw_pdf": "wdfw", "noaa_archive": "noaa"},
    }
    paths = configured_source_paths(cfg)
    assert len(paths) == 16
    for path in paths:
        path.write_text("fixture")
    sources = [{"path": str(path)} for path in paths]
    require_registered(paths, sources)
    for index in range(len(paths)):
        with pytest.raises(ValueError, match="not registered"):
            require_registered(paths, sources[:index] + sources[index + 1 :])


@pytest.mark.parametrize("suffix", [".parquet", ".geoparquet"])
@pytest.mark.parametrize("role", ["source_inventory", "reporting_keys"])
def test_directory_pins_reject_nested_computed_h3(tmp_path, suffix, role):
    from seascape.core.artifacts.checksums import checksum_path

    tree = tmp_path / "sources"
    nested = tree / "nested"
    nested.mkdir(parents=True)
    path = nested / ("measurements" + suffix)
    pq.write_table(
        pa.table({"H3_INDEX": [h3.latlng_to_cell(48.5, -123.5, 6)], "DEPTH_M": [10.0]}),
        path,
    )
    with pytest.raises(ValueError, match="Computed H3 measurements"):
        verify_source({"path": str(tree), "sha256": checksum_path(tree), "role": role})


def test_directory_pin_accepts_scientific_sources_and_identity_only_grid(tmp_path):
    from seascape.core.artifacts.checksums import checksum_path

    tree = tmp_path / "sources"
    tree.mkdir()
    pq.write_table(
        pa.table({"SOURCE_ID": ["original"], "VALUE": [1.0]}),
        tree / "inventory.parquet",
    )
    (tree / "context.json").write_text("{}")
    verify_source(
        {"path": str(tree), "sha256": checksum_path(tree), "role": "source_inventory"}
    )
    pq.write_table(
        pa.table({"H3_INDEX": [h3.latlng_to_cell(48.5, -123.5, 6)]}),
        tree / "keys.parquet",
    )
    verify_source(
        {"path": str(tree), "sha256": checksum_path(tree), "role": "reporting_keys"}
    )
    with pytest.raises(ValueError, match="Computed H3 measurements"):
        verify_source(
            {
                "path": str(tree),
                "sha256": checksum_path(tree),
                "role": "source_inventory",
            }
        )
    (tree / "context.json").write_text("changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_source({"path": str(tree), "sha256": "0" * 64})


def test_directory_pin_rejects_symlink_members(tmp_path):
    tree = tmp_path / "sources"
    tree.mkdir()
    (tree / "escape.parquet").symlink_to(tmp_path / "missing.parquet")
    with pytest.raises(ValueError, match="symbolic links"):
        verify_source({"path": str(tree), "sha256": "0" * 64})


@pytest.mark.parametrize("location", ["raw", "declared-output"])
@pytest.mark.parametrize("registered", [False, True])
def test_work_root_location_does_not_exempt_raw_sources(
    tmp_path, monkeypatch, location, registered
):
    from seascape.core.artifacts.checksums import checksum_path
    from seascape.metric_rebuild import BASE
    from seascape.metric_rebuild_stages import acquire_sources, verify_sources

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    candidate = tmp_path / "work"
    producer = candidate / BASE / "anthropogenic"
    producer.mkdir(parents=True)
    source = (candidate if location == "raw" else producer) / "raw-source"
    source.write_text("scientific input")
    pin = tmp_path / "pin"
    pin.write_text("unrelated")
    pinned = source if registered else pin
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "metric_rebuild": {
                    "sources": [{"path": str(pinned), "sha256": digest(pinned)}]
                }
            }
        )
    )
    ctx = SimpleNamespace(config_path=config, candidate_root=candidate)
    acquire_sources(ctx)
    manifest = producer / "producer_manifest.json"
    manifest.write_text(
        json.dumps(
            {"sources": [{"path": str(source), "checksum": checksum_path(source)}]}
        )
    )
    if registered:
        verify_sources(ctx)
        manifest.write_text(
            json.dumps({"sources": [{"path": str(source), "checksum": "wrong"}]})
        )
        with pytest.raises(ValueError, match="producer receipt"):
            verify_sources(ctx)
    else:
        with pytest.raises(ValueError, match="not registered"):
            verify_sources(ctx)


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "missing-receipt",
        "missing-consumer-checksum",
        "changed",
        "conflict",
        "escape",
    ],
)
def test_generated_dependencies_need_exact_receipts(tmp_path, monkeypatch, failure):
    from seascape.core.artifacts.checksums import checksum_path
    from seascape.metric_rebuild import BASE
    from seascape.metric_rebuild_stages import acquire_sources, verify_sources

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    pin = tmp_path / "source"
    pin.write_text("raw")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"metric_rebuild": {"sources": [{"path": str(pin), "sha256": digest(pin)}]}}
        )
    )
    ctx = SimpleNamespace(config_path=config, candidate_root=tmp_path / "work")
    acquire_sources(ctx)
    directory = ctx.candidate_root / BASE / "anthropogenic"
    directory.mkdir(parents=True)
    path = (ctx.candidate_root if failure == "escape" else directory) / "generated"
    path.write_text("derived")
    record = {
        "path": str(path.relative_to(ctx.candidate_root)),
        "checksum": checksum_path(path),
    }
    producer = directory / "producer_manifest.json"
    producer.write_text(
        json.dumps({"artifacts": [] if failure == "missing-receipt" else [record]})
    )
    consumer_record = dict(record)
    if failure == "missing-consumer-checksum":
        consumer_record.pop("checksum")
    if failure == "changed":
        path.write_text("changed bytes")
    consumer = directory / "consumer_manifest.json"
    consumer.write_text(json.dumps({"upstream_artifacts": [consumer_record]}))
    if failure == "conflict":
        (directory / "conflict_manifest.json").write_text(
            json.dumps({"artifacts": [{**record, "checksum": "wrong"}]})
        )
    if failure:
        with pytest.raises(ValueError):
            verify_sources(ctx)
    else:
        verify_sources(ctx)
        consumer.write_text(
            json.dumps(
                {
                    "upstream_artifacts": [
                        {"path": str(producer), "checksum": checksum_path(producer)}
                    ]
                }
            )
        )
        verify_sources(ctx)


def test_profile_records_generated_inventory_for_source_validation(
    tmp_path, monkeypatch
):
    from seascape.metric_rebuild import BASE
    from seascape.metric_rebuild_stages import (
        _publish_tables,
        acquire_sources,
        verify_sources,
    )

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    candidate = tmp_path / "work"
    monkeypatch.setenv("SEASCAPE_CANDIDATE_ROOT", str(candidate))
    raw = tmp_path / "raw"
    raw.write_text("source")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"metric_rebuild": {"sources": [{"path": str(raw), "sha256": digest(raw)}]}}
        )
    )
    ctx = SimpleNamespace(config_path=config, candidate_root=candidate)
    acquire_sources(ctx)
    directory = candidate / BASE / "anthropogenic"
    directory.mkdir(parents=True)
    inventory = directory / "inventory.parquet"
    pq.write_table(pa.table({"SOURCE_ID": ["derived"]}), inventory)
    output = pa.table(
        {"H3_INDEX": [h3.latlng_to_cell(48.5, -123.5, 6)], "VALUE": [1.0]}
    )
    _publish_tables(
        directory / "enriched",
        {"result.parquet": output},
        context={},
        source_paths=[raw, inventory],
        generated_paths=[inventory],
    )
    verify_sources(ctx)
    pq.write_table(pa.table({"SOURCE_ID": ["changed"]}), inventory)
    with pytest.raises(ValueError, match="producer receipt"):
        verify_sources(ctx)
