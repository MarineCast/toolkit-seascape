"""Approved core schemas must preserve support, nulls and original audit data."""

import json

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from seascape.domain_parquets import AreaTables, read_area, write_areas
from seascape.reviewed_delivery import (
    CORE_SCHEMAS,
    compact_existing,
    project,
    restore_native,
)


def core_native(area, resolution):
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123, resolution), 1))[:3]
    values = {"H3_INDEX": cells, "H3_RESOLUTION": [resolution] * 3}
    for metric in CORE_SCHEMAS[area]["metrics"]:
        if resolution in metric["resolutions"]:
            values[metric["source_column"]] = (
                pa.array([True, None, False])
                if metric["units"] == "0/1"
                else pa.array([0.0, None, 0.5])
            )
    values["SOURCE_QC"] = ["mapped", "unknown", "mapped"]
    return pa.table(values).replace_schema_metadata(
        {b"seascape_domain": json.dumps({"model_eligible": False}).encode()}
    )


VARIANTS = [
    (area, res)
    for area, spec in CORE_SCHEMAS.items()
    for res in sorted({r for m in spec["metrics"] for r in m["resolutions"]})
]


@pytest.mark.parametrize("area,resolution", VARIANTS)
def test_normal_writer_applies_core_and_restores_all_native_nulls(
    tmp_path, area, resolution
):
    original = core_native(area, resolution)
    # Production Anthropogenic presentation also retains original nullable flags.
    write_areas({area: AreaTables(original)}, output=tmp_path / "Data/Seascape")
    public = read_area(area, resolution=resolution, output=tmp_path / "Data/Seascape")
    from seascape.metric_export import _DIAGNOSTIC

    metrics = [
        m
        for m in CORE_SCHEMAS[area]["metrics"]
        if resolution in m["resolutions"]
        and not _DIAGNOSTIC.search(m["proposed_column"])
    ]
    assert public.column_names == ["h3_index", *(m["proposed_column"] for m in metrics)]
    assert public["h3_index"].equals(original["H3_INDEX"])
    assert b"seascape_review" not in public.schema.metadata
    for metric in metrics:
        expected = original[metric["source_column"]]
        if pa.types.is_boolean(expected.type):
            expected = expected.cast(pa.int64())
        assert public[metric["proposed_column"]].equals(expected)
    assert not list(tmp_path.rglob("audit/*.parquet"))


def test_core_projection_does_not_create_r6_shoreline_distance():
    r6 = project("shoreline", core_native("shoreline", 6))
    r8 = project("shoreline", core_native("shoreline", 8))
    assert r6.num_columns == 10
    assert r8.num_columns == 11
    assert "distance_to_mapped_shoreline_m" not in r6.column_names


def test_nearshore_constants_move_to_metadata_and_varying_threshold_fails():
    table = core_native("nearshore-transitions", 8)
    table = table.append_column("DEPTH_THRESHOLD_M", pa.array([100.0] * 3))
    table = table.append_column("NEARSHORE_BAND_WIDTH_M", pa.array([1000.0] * 3))
    public = project("nearshore-transitions", table)
    context = json.loads(public.schema.metadata[b"seascape_domain"])
    assert context["core_schema"]["parameters"] == {
        "depth_threshold_m": 100.0,
        "nearshore_band_width_m": 1000.0,
    }
    assert public.num_columns == 4
    changed = table.set_column(
        table.schema.get_field_index("DEPTH_THRESHOLD_M"),
        "DEPTH_THRESHOLD_M",
        pa.array([100.0, 200.0, 100.0]),
    )
    with pytest.raises(ValueError, match="parameter must be uniform"):
        project("nearshore-transitions", changed)


def test_missing_required_field_and_ambiguous_alias_fail():
    table = core_native("substrate", 6)
    source = CORE_SCHEMAS["substrate"]["metrics"][0]["source_column"]
    with pytest.raises(ValueError, match="requires unambiguous source"):
        project("substrate", table.drop([source]))
    missing = table.drop([source])
    suffix = source.rsplit("__", 1)[-1]
    missing = missing.append_column("a__" + suffix, table[source])
    missing = missing.append_column("b__" + suffix, table[source])
    with pytest.raises(ValueError, match="requires unambiguous source"):
        project("substrate", missing)


def test_external_audit_retains_exact_original_during_migration(tmp_path):
    root = tmp_path / "Data/Seascape"
    root.mkdir(parents=True)
    original = core_native("spatial-support", 8)
    name = "spatial-support-r8-static.parquet"
    pq.write_table(original, root / name)
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "spatial-support": {
                    "last_updated_utc": "2026-10-25",
                    "static": {"8": name},
                }
            }
        )
    )
    changes = compact_existing(root)
    assert len(changes["changed"]) == 1
    public = pq.read_table(root / name)
    assert restore_native(public).equals(original, check_metadata=True)
    # New production never consults the old audit binding.
    with pytest.raises(ValueError, match="scientific inputs"):
        write_areas({"spatial-support": AreaTables(public)}, output=root)
    write_areas({"spatial-support": AreaTables(original)}, output=root)
    assert read_area("spatial-support", output=root)[
        "intersects_shoreline"
    ].to_pylist() == [1, None, 0]


@pytest.mark.parametrize(
    "area,field",
    [
        ("substrate", "SUBSTRATE_MODEL__SOURCE_OBSERVATION_PERIOD"),
        ("spatial-support", "h3_marine_support__GRAPH_QC_REASON"),
    ],
)
def test_core_audit_retains_fields_omitted_by_older_flat_policy(tmp_path, area, field):
    resolution = 6
    original = core_native(area, resolution).append_column(
        field, pa.array(["qualified", None, "unknown"])
    )
    write_areas({area: AreaTables(original)}, output=tmp_path / "Data/Seascape")
    public = read_area(area, resolution=resolution, output=tmp_path / "Data/Seascape")
    assert field not in public.column_names
    assert b"seascape_review" not in public.schema.metadata
    assert not list(tmp_path.rglob("audit/*.parquet"))
