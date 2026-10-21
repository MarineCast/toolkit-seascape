import json

import pytest

from seascape.study import load_study_membership


def test_exact_native_roles_and_read_only_loading(tmp_path, study_fixture):
    path, config, manifest, (a, b) = study_fixture(tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    assert load_study_membership(path, resolution=7)["cells"] == (a,)
    assert set(
        load_study_membership(path, resolution=7, role="land_source")["cells"]
    ) == {a, b}
    assert set(
        load_study_membership(path, resolution=7, role="water_source")["cells"]
    ) == {a, b}
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    "name", ["mask.parquet", "manifest.json", "water_reporting7.txt"]
)
def test_pinned_artifact_tamper_rejected(tmp_path, name, study_fixture):
    path, _, _, _ = study_fixture(tmp_path)
    with (tmp_path / "Data" / name).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="SHA256"):
        load_study_membership(path, resolution=7)


def test_source_extent_tamper_rejected(tmp_path, study_fixture):
    path, _, _, _ = study_fixture(tmp_path)
    (tmp_path / "Data/extent.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA256"):
        load_study_membership(path, resolution=7, role="land_source")


def test_pending_policy_rejected(tmp_path, study_fixture):
    path, config, _, _ = study_fixture(tmp_path)
    config["domain"]["selection_policy"]["mask_status"] = (
        "pending_source_qualified_build"
    )
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="validated coastal"):
        load_study_membership(path, resolution=7)


def test_no_outside_data_root_fallback(tmp_path, study_fixture):
    path, config, _, _ = study_fixture(tmp_path)
    config["grid_registry"]["mask_relative_path"] = "../outside.parquet"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="escapes"):
        load_study_membership(path, resolution=7)


def test_catalog_filter_preserves_structural_support_and_reports_missing(
    tmp_path, study_fixture
):
    import hashlib

    import h3
    import pyarrow as pa

    from seascape.domain_parquets import METADATA_KEY, AreaTables, write_areas
    from seascape.study import read_study_area

    path, config, _, (a, b) = study_fixture(tmp_path)
    native = h3.cell_to_parent(a, 6)
    outside = next(c for c in sorted(h3.grid_disk(native, 1)) if c != native)
    context = {
        "reporting_mask_file_sha256": hashlib.sha256(
            (tmp_path / "Data/mask.parquet").read_bytes()
        ).hexdigest(),
        "support": "hierarchical_r8_child_union",
    }
    table = pa.table(
        {"H3_INDEX": [native, outside], "H3_RESOLUTION": [6, 6], "VALUE_M": [2.0, 3.0]}
    ).replace_schema_metadata({METADATA_KEY: json.dumps(context).encode()})
    write_areas(
        {"example": AreaTables(static=table)}, output=tmp_path / "Data/Seascape"
    )
    result = read_study_area("example", study_config=path)
    assert result["H3_INDEX"].to_pylist() == [native]
    metadata = json.loads(result.schema.metadata[METADATA_KEY])
    assert metadata["support"] == "hierarchical_r8_child_union"
    assert metadata["study_selection"]["excluded_producer_ids"] == [outside]


def test_named_research_read_keeps_null_and_checks_captured_bytes(
    tmp_path, study_fixture
):
    import hashlib

    import h3
    import pyarrow as pa
    import pyarrow.parquet as pq

    from seascape import read_study_research

    path, config, manifest, (a, b) = study_fixture(tmp_path)
    native = h3.cell_to_parent(a, 6)
    outside = next(c for c in sorted(h3.grid_disk(native, 1)) if c != native)
    target = tmp_path / "Data/research.parquet"
    pq.write_table(
        pa.table(
            {
                "H3_INDEX": [native, outside],
                "H3_RESOLUTION": [6, 6],
                "OUTLET_ID": ["one", "one"],
                "DISTANCE_M": [None, 4.0],
            }
        ),
        target,
    )
    manifest["research_artifacts"] = {
        "outlet-example": {
            "relative_path": "Data/research.parquet",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "row_count": 2,
            "h3_resolution": 6,
            "support": "explicit fixture support",
        }
    }
    witness = tmp_path / "Data/manifest.json"
    witness.write_text(json.dumps(manifest))
    config["grid_registry"]["manifest_sha256"] = hashlib.sha256(
        witness.read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(config))
    table = read_study_research("outlet-example", study_config=path)
    assert table["H3_INDEX"].to_pylist() == [native]
    assert table["DISTANCE_M"].to_pylist() == [None]
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256"):
        read_study_research("outlet-example", study_config=path)
