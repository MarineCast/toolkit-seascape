import hashlib
import json
from datetime import date

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from seascape.cli import main
from seascape.domain_parquets import METADATA_KEY, AreaTables, read_area, write_areas
from seascape.historical import HistoricalRequest, export_history


def request(tmp_path, start="2009-01-01", end="2027-01-01"):
    path = tmp_path / "study.json"
    path.write_text(
        json.dumps(
            {
                "study_id": "fixture",
                "time": {"start": start, "end_exclusive": end, "timezone": "UTC"},
            }
        )
    )
    return path


def table(resolution=6, *, dates=None, context=None):
    cell = h3.latlng_to_cell(48.5, -122.6, resolution)
    n = len(dates) if dates is not None else 1
    values = {
        "H3_INDEX": [cell] * n,
        "H3_RESOLUTION": [resolution] * n,
        "amount": [0.0, None, 2.0][:n] if n <= 3 else list(map(float, range(n))),
    }
    if dates is not None:
        values["date"] = pa.array(dates, type=pa.date32())
    return pa.table(values).replace_schema_metadata(
        {METADATA_KEY: json.dumps(context or {}).encode()}
    )


def test_request_rejects_duplicate_keys_invalid_dates_and_non_utc(tmp_path):
    p = request(tmp_path)
    assert HistoricalRequest.from_study(p).end_exclusive == date(2027, 1, 1)
    for text in (
        '{"time":{},"time":{}}',
        "{",
        '{"time":{"start":"20090101","end_exclusive":"2027-01-01","timezone":"UTC"}}',
        '{"time":{"start":"2009-01-01","end_exclusive":"2008-01-01","timezone":"UTC"}}',
        '{"time":{"start":"2009-01-01","end_exclusive":"2027-01-01","timezone":"PST"}}',
    ):
        p.write_text(text)
        with pytest.raises(ValueError):
            HistoricalRequest.from_study(p)


def test_export_preserves_native_values_and_reports_missing_years_and_static_role(
    tmp_path,
):
    source = tmp_path / "input"
    annual = table(
        dates=[date(2008, 1, 1), date(2009, 1, 1), date(2024, 1, 1)],
        context={
            "temporal_support": {"precision": "year"},
            "limits": {"coverage": "positive_only"},
        },
    )
    write_areas(
        {"kelp": AreaTables(dynamic=annual), "depth": AreaTables(static=table(8))},
        output=source,
    )
    original = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()
    }
    result = export_history(
        study_config=request(tmp_path), input_dir=source, output_dir=tmp_path / "output"
    )
    retained = read_area("kelp", resolution=6, dynamic=True, output=result.output_dir)
    assert retained["amount"].to_pylist() == [None, 2.0]
    assert retained["date"].to_pylist() == [date(2009, 1, 1), date(2024, 1, 1)]
    dated = next(v for v in result.report["variants"] if v["kind"] == "dynamic")
    assert dated["years_with_source_time_support"] == [2009, 2024]
    assert {2025, 2026}.issubset(dated["requested_years_without_source_time_support"])
    static = next(v for v in result.report["variants"] if v["kind"] == "static")
    assert static["role"] == "static_reference_context_not_historical_observations"
    assert static["years_with_source_time_support"] is None
    assert dated["historical_availability"] == "unknown_retrospective_only"
    assert not result.report["model_readiness_established"]
    assert original == {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()
    }
    assert {p.name for p in result.output_dir.iterdir()} == {
        "catalog.json",
        "kelp-r6-dynamic.parquet",
        "depth-r8-static.parquet",
    }


def test_partial_year_selection_keeps_native_year_labels(tmp_path):
    source = tmp_path / "input"
    write_areas(
        {
            "kelp": AreaTables(
                dynamic=table(
                    dates=[date(2009, 1, 1), date(2010, 1, 1)],
                    context={"temporal_support": {"precision": "year"}},
                )
            )
        },
        output=source,
    )
    result = export_history(
        study_config=request(tmp_path, "2009-07-01", "2010-07-01"),
        input_dir=source,
        output_dir=tmp_path / "output",
    )
    assert read_area("kelp", resolution=6, dynamic=True, output=result.output_dir)[
        "date"
    ].to_pylist() == [date(2009, 1, 1), date(2010, 1, 1)]


def composite():
    result = table(
        dates=[date(2019, 1, 1)],
        context={
            "temporal_support": {
                "precision": "multi_year_composite",
                "start_column": "period_start",
                "end_exclusive_column": "period_end_exclusive",
            }
        },
    )
    return result.append_column(
        "period_start", pa.array([date(2019, 1, 1)], type=pa.date32())
    ).append_column(
        "period_end_exclusive", pa.array([date(2021, 1, 1)], type=pa.date32())
    )


def test_composite_keeps_two_year_support_and_overwrite_removes_stale_areas(tmp_path):
    source = tmp_path / "input"
    write_areas(
        {
            "seagrass": AreaTables(dynamic=composite()),
            "depth": AreaTables(static=table()),
        },
        output=source,
    )
    study = request(tmp_path, "2020-01-01", "2021-01-01")
    result = export_history(
        study_config=study, input_dir=source, output_dir=tmp_path / "output"
    )
    kept = read_area("seagrass", resolution=6, dynamic=True, output=result.output_dir)
    assert kept["date"].to_pylist() == [date(2019, 1, 1)]
    assert kept["period_end_exclusive"].to_pylist() == [date(2021, 1, 1)]
    request(tmp_path, "2009-01-01", "2010-01-01")
    result = export_history(
        study_config=study,
        input_dir=source,
        output_dir=tmp_path / "output",
        overwrite=True,
    )
    assert not (result.output_dir / "seagrass-r6-dynamic.parquet").exists()
    assert list(json.loads((result.output_dir / "catalog.json").read_text())) == [
        "depth"
    ]


def test_missing_precision_and_unknown_availability_fail_before_replacement(tmp_path):
    source = tmp_path / "input"
    write_areas(
        {"kelp": AreaTables(dynamic=table(dates=[date(2009, 1, 1)]))}, output=source
    )
    output = tmp_path / "output"
    study = request(tmp_path)
    with pytest.raises(ValueError, match="precision"):
        export_history(study_config=study, input_dir=source, output_dir=output)
    assert not output.exists()
    with pytest.raises(ValueError, match="availability"):
        export_history(
            study_config=study,
            input_dir=source,
            output_dir=output,
            require_known_availability=True,
        )
    assert not output.exists()


def test_mixed_native_resolutions_and_metadata_are_preserved(tmp_path):
    source = tmp_path / "input"
    one, two = table(6), table(8)
    write_areas(
        {"depth": AreaTables(static=pa.concat_tables([one, two]))}, output=source
    )
    result = export_history(
        study_config=request(tmp_path), input_dir=source, output_dir=tmp_path / "output"
    )
    for resolution in (6, 8):
        kept = read_area("depth", resolution=resolution, output=result.output_dir)
        assert kept["H3_RESOLUTION"].to_pylist() == [resolution]
        context = json.loads(kept.schema.metadata[METADATA_KEY])
        assert str(resolution) in context["resolution_contexts"]
        assert context["historical_request"]["start"] == "2009-01-01"


def test_overlapping_destinations_and_report_sidecars_are_rejected(tmp_path):
    study = request(tmp_path)
    for source, output, report in [
        (tmp_path / "a", tmp_path / "a/b", None),
        (tmp_path / "a/b", tmp_path / "a", None),
        (tmp_path / "a", tmp_path / "b", tmp_path / "b/report.json"),
    ]:
        with pytest.raises(ValueError):
            export_history(
                study_config=study,
                input_dir=source,
                output_dir=output,
                report_path=report,
            )


def test_history_preserves_common_mask_identity_and_rejects_conflicts(tmp_path):
    source = tmp_path / "input"
    context = {
        "reporting_mask_file_sha256": "a" * 64,
        "reporting_mask_geometry_sha256": "b" * 64,
    }
    write_areas(
        {
            "depth": AreaTables(
                static=pa.concat_tables(
                    [table(6, context=context), table(8, context=context)]
                )
            )
        },
        output=source,
    )
    study = request(tmp_path)
    result = export_history(
        study_config=study, input_dir=source, output_dir=tmp_path / "output"
    )
    for resolution in (6, 8):
        kept = read_area("depth", resolution=resolution, output=result.output_dir)
        retained = json.loads(kept.schema.metadata[METADATA_KEY])
        for key, value in context.items():
            assert retained[key] == value
    path = source / "depth-r8-static.parquet"
    changed = pq.read_table(path)
    different = {
        **json.loads(changed.schema.metadata[METADATA_KEY]),
        "reporting_mask_file_sha256": "c" * 64,
    }
    pq.write_table(
        changed.replace_schema_metadata({METADATA_KEY: json.dumps(different).encode()}),
        path,
    )
    with pytest.raises(ValueError, match="different reporting mask"):
        export_history(
            study_config=study,
            input_dir=source,
            output_dir=tmp_path / "conflict",
            report_path=tmp_path / "conflict-coverage.json",
        )


def test_cli_reports_source_contract_failure_and_restores_workspace(
    tmp_path, capsys, monkeypatch
):
    p = request(tmp_path)
    p.write_text("{")
    monkeypatch.setenv("SEASCAPE_WORKSPACE", "previous")
    assert (
        main(
            [
                "--workspace",
                str(tmp_path),
                "history",
                "--study-config",
                str(p),
                "--input-dir",
                str(tmp_path / "input"),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 1
    )
    import os

    assert os.environ["SEASCAPE_WORKSPACE"] == "previous"
    error = capsys.readouterr().err
    assert "Invalid historical source/request contract" in error
    assert "docs/historical-data.md" in error


def test_historical_snapshot_replacement_preserves_existing_research(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    write_areas({"depth": AreaTables(static=table())}, output=source)
    write_areas({"stale": AreaTables(static=table())}, output=output)
    research = output / "research"
    research.mkdir()
    original = b'{"object_grain":"named passage","datum_qualified":false}\n'
    (research / "manifest.json").write_bytes(original)
    export_history(
        study_config=request(tmp_path),
        input_dir=source,
        output_dir=output,
        overwrite=True,
    )
    assert (research / "manifest.json").read_bytes() == original
    assert not (output / "stale-r6-static.parquet").exists()
