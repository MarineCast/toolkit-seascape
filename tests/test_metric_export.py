"""Final metric exports preserve missingness without historical audit inputs."""

import json
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

from seascape.domain_parquets import AreaTables, read_area, write_areas
from seascape.metric_export import native_keys


def test_native_identity_conversion_preserves_metadata():
    original = pa.table({"h3_index": ["8628d542fffffff"]}).replace_schema_metadata(
        {b"definition": b"retained"}
    )
    assert native_keys(original).schema.metadata == original.schema.metadata


def test_dynamic_metric_only_preserves_nulls_without_audit(tmp_path):
    table = pa.table(
        {
            "H3_INDEX": ["8628d542fffffff"] * 2,
            "H3_RESOLUTION": [6, 6],
            "date": pa.array([date(2023, 1, 1), date(2024, 1, 1)], type=pa.date32()),
            "KELP_EXTENT_M2": [None, 0.0],
            "KELP_COVERAGE_FRACTION": [0.0, 1.0],
            "NONANNUAL_EVIDENCE_INCLUDED": [False, True],
            "REPAIRED_GEOMETRY_INCLUDED": [False, False],
            "INTERSECTING_SOURCE_RECORD_COUNT": [0, 2],
        }
    ).replace_schema_metadata(
        {
            b"seascape_domain": json.dumps(
                {"temporal_support": {"precision": "year"}}
            ).encode()
        }
    )
    output = tmp_path / "Data" / "Seascape"
    write_areas({"kelp": AreaTables(dynamic=table)}, output=output)
    result = read_area("kelp", resolution=6, dynamic=True, output=output)
    assert result.column_names == ["H3_INDEX", "KELP_EXTENT_M2", "date"]
    assert result["KELP_EXTENT_M2"].to_pylist() == [None, 0.0]
    assert not list(tmp_path.rglob("audit"))
    assert (
        pq.read_table(output / "kelp-r6-dynamic.parquet").column_names
        == result.column_names
    )


def test_bathymetry_count_is_diagnostic_but_depth_fraction_is_metric(tmp_path):
    table = pa.table(
        {
            "H3_INDEX": ["8628d542fffffff"],
            "H3_RESOLUTION": [6],
            "BATHYMETRY": [None],
            "BATHYMETRY_PIXEL_COUNT": [0],
            "DEPTH_0_10M_PIXEL_COUNT": [0],
            "DEPTH_0_10M_FRAC": pa.array([None], type=pa.float64()),
        }
    ).set_column(2, "BATHYMETRY", pa.array([None], type=pa.float64()))
    write_areas({"bathymetry": AreaTables(table)}, output=tmp_path / "data")
    result = read_area("bathymetry", resolution=6, output=tmp_path / "data")
    assert result.column_names == ["H3_INDEX", "BATHYMETRY", "DEPTH_0_10M_FRAC"]
    assert result["BATHYMETRY"].null_count == 1


def test_lineage_stays_in_metadata_without_adding_diagnostic_columns(tmp_path):
    source = {"sha256": "a" * 64, "rights": "synthetic", "version": "fixture-v1"}
    context = {
        "source_context": source,
        "model_eligible": False,
        "code_sha256": "b" * 64,
        "limits": {"coverage": "partial"},
        "fields": {"DEPTH_M": {"unit": "m", "source_sha256": "a" * 64}},
    }
    table = pa.table(
        {
            "H3_INDEX": ["8628d542fffffff"],
            "H3_RESOLUTION": [6],
            "DEPTH_M": [1.0],
            "QC": ["partial"],
        }
    ).replace_schema_metadata({b"seascape_domain": json.dumps(context).encode()})
    write_areas({"bathymetry": AreaTables(table)}, output=tmp_path / "data")
    result = read_area("bathymetry", output=tmp_path / "data")
    assert result.column_names == ["H3_INDEX", "DEPTH_M"]
    retained = json.loads(result.schema.metadata[b"seascape_domain"])
    for name in ("source_context", "model_eligible", "code_sha256", "limits"):
        assert retained[name] == context[name]
    assert retained["fields"]["DEPTH_M"]["source_sha256"] == "a" * 64


def test_numeric_diagnostics_and_declared_nonmetrics_are_omitted(tmp_path):
    data = {
        "H3_INDEX": ["8628d542fffffff"],
        "H3_RESOLUTION": [6],
        "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M": [1.0],
        "BARRIER_EVIDENCE_CONFIDENCE": [2],
        "BARRIER_LATEST_ASSESSMENT_YEAR": [2020],
        "STRUCTURAL_DISCONTINUITY_FLAG": [True],
        "UNCERTAIN_RECORD": [1],
    }
    table = pa.table(data).replace_schema_metadata(
        {
            b"seascape_domain": json.dumps(
                {"fields": {"UNCERTAIN_RECORD": {"role": "evidence"}}}
            ).encode()
        }
    )
    write_areas({"fluvial-barriers": AreaTables(table)}, output=tmp_path / "data")
    assert read_area("fluvial-barriers", output=tmp_path / "data").column_names == [
        "h3_index",
        "water_network_distance_to_fluvial_mouth_m",
    ]


def test_namespaced_habitat_extent_keeps_existing_metric_names(tmp_path):
    table = pa.table(
        {
            "H3_INDEX": ["8628d542fffffff"],
            "H3_RESOLUTION": [6],
            "kelp__KELP_EXTENT_ALL_TIME_M2": pa.array([None], type=pa.float64()),
            "kelp__QC": ["unknown"],
        }
    )
    write_areas({"kelp": AreaTables(table)}, output=tmp_path / "data")
    result = read_area("kelp", output=tmp_path / "data")
    assert result.column_names == [
        "H3_INDEX",
        "KELP_EXTENT_ALL_TIME_M2",
        "KELP_EXTENT_BOOL",
    ]
    assert (
        result["KELP_EXTENT_ALL_TIME_M2"].null_count
        == result["KELP_EXTENT_BOOL"].null_count
        == 1
    )
