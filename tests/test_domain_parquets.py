from __future__ import annotations

import json
from datetime import date

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from seascape.domain_parquets import (
    AreaTables,
    export_domain_parquets,
    label_annual_dates,
    list_areas,
    read_area,
    write_areas,
)


def fixture_table(*, dynamic=False, resolution=6):
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123.0, resolution), 1))[:2]
    data = {
        "H3_INDEX": cells,
        "H3_RESOLUTION": [resolution, resolution],
        "depth_m": [0.0, None],
    }
    if dynamic:
        data["date"] = pa.array([date(2024, 1, 1)] * 2, type=pa.date32())
    return pa.table(data)


def test_flat_layout_updates_and_removes_stale_variant(tmp_path):
    root = tmp_path / "Data/Seascape"
    initial = write_areas(
        {
            "kelp": AreaTables(fixture_table(), fixture_table(dynamic=True)),
            "bathymetry": AreaTables(fixture_table()),
        },
        output=root,
    )
    assert {p.name for p in root.iterdir()} == {
        "catalog.json",
        "bathymetry-r6-static.parquet",
        "kelp-r6-static.parquet",
        "kelp-r6-dynamic.parquet",
    }
    assert list_areas(output=root) == ("bathymetry", "kelp")
    before = (root / "bathymetry-r6-static.parquet").read_bytes()
    (root / ".DS_Store").write_bytes(b"Finder bookkeeping")
    updated = write_areas({"kelp": AreaTables(fixture_table())}, output=root)
    assert not (root / ".DS_Store").exists()
    assert initial["bathymetry"] == updated["bathymetry"]
    assert before == (root / "bathymetry-r6-static.parquet").read_bytes()
    assert not (root / "kelp-r6-dynamic.parquet").exists()
    assert "date" not in read_area("kelp", output=root).column_names
    assert read_area("bathymetry", output=root)["depth_m"].to_pylist() == [0.0, None]
    with pytest.raises(KeyError, match="no dynamic"):
        read_area("kelp", dynamic=True, output=root)


def test_failed_serialization_keeps_previous_files_and_timestamp(tmp_path, monkeypatch):
    root = tmp_path / "Data/Seascape"
    write_areas({"bathymetry": AreaTables(fixture_table())}, output=root)
    before = {p.name: p.read_bytes() for p in root.iterdir()}

    def fail(*args, **kwargs):
        raise OSError("synthetic full disk")

    monkeypatch.setattr(pq, "write_table", fail)
    with pytest.raises(OSError, match="full disk"):
        write_areas({"kelp": AreaTables(fixture_table())}, output=root)
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_flat_rebuild_preserves_separately_keyed_research_objects(tmp_path):
    root = tmp_path / "Seascape"
    write_areas({"depth": AreaTables(fixture_table())}, output=root)
    research = root / "research"
    research.mkdir()
    payload = pa.table({"OUTLET_ID": ["named-outlet"], "unknown_distance_m": [None]})
    pq.write_table(payload, research / "outlets.parquet")
    original = (research / "outlets.parquet").read_bytes()
    write_areas({"depth": AreaTables(fixture_table())}, output=root)
    assert list_areas(output=root) == ("depth",)
    assert (research / "outlets.parquet").read_bytes() == original
    (root / "unexpected").mkdir()
    with pytest.raises(ValueError, match="unexpected files"):
        list_areas(output=root)


def test_research_directory_rejects_external_symbolic_links(tmp_path):
    root = tmp_path / "Seascape"
    write_areas({"depth": AreaTables(fixture_table())}, output=root)
    external = tmp_path / "external"
    external.mkdir()
    (root / "research").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="local directory"):
        write_areas({"depth": AreaTables(fixture_table())}, output=root)


def test_resolution_files_preserve_native_rows_and_require_explicit_reads(tmp_path):
    static = pa.concat_tables([fixture_table(), fixture_table(resolution=8)])
    dynamic = pa.concat_tables(
        [fixture_table(dynamic=True), fixture_table(dynamic=True, resolution=8)]
    )
    catalog = write_areas({"kelp": AreaTables(static, dynamic)}, output=tmp_path)
    assert {path.name for path in tmp_path.iterdir()} == {
        "catalog.json",
        "kelp-r6-static.parquet",
        "kelp-r8-static.parquet",
        "kelp-r6-dynamic.parquet",
        "kelp-r8-dynamic.parquet",
    }
    assert catalog["kelp"]["static"] == {
        "6": "kelp-r6-static.parquet",
        "8": "kelp-r8-static.parquet",
    }
    for resolution in (6, 8):
        for dated in (False, True):
            result = read_area(
                "kelp", resolution=resolution, dynamic=dated, output=tmp_path
            )
            assert result.equals(
                fixture_table(resolution=resolution, dynamic=dated),
                check_metadata=False,
            )
            assert (
                json.loads(result.schema.metadata[b"seascape_domain"])["resolution"]
                == resolution
            )
    with pytest.raises(ValueError, match="exact resolution"):
        read_area("kelp", output=tmp_path)
    with pytest.raises(KeyError, match="no R7"):
        read_area("kelp", resolution=7, output=tmp_path)


def test_resolution_split_drops_only_declared_unavailable_padding(tmp_path):
    table = pa.concat_tables([fixture_table(), fixture_table(resolution=8)])
    table = table.append_column(
        "native_r6", pa.array([None, None, None, None], type=pa.float64())
    )
    metadata = {"fields": {"native_r6": {"available_resolutions": [6]}}}
    table = table.replace_schema_metadata(
        {b"seascape_domain": json.dumps(metadata).encode()}
    )
    write_areas({"bathymetry": AreaTables(table)}, output=tmp_path)
    assert (
        "native_r6"
        in read_area("bathymetry", resolution=6, output=tmp_path).column_names
    )
    assert (
        "native_r6"
        not in read_area("bathymetry", resolution=8, output=tmp_path).column_names
    )


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "resolution",
        "null_date",
        "date_type",
        "static_date",
        "nonfinite",
        "area_escape",
    ],
)
def test_bad_grains_and_metrics_fail_before_writing(tmp_path, failure):
    table = fixture_table(dynamic=failure in {"null_date", "date_type", "static_date"})
    dynamic = failure in {"null_date", "date_type"}
    area = "bathymetry"
    if failure == "duplicate":
        table = pa.concat_tables([table, table])
    elif failure == "resolution":
        table = table.set_column(1, "H3_RESOLUTION", pa.array([8, 8]))
    elif failure == "null_date":
        table = table.set_column(
            table.schema.get_field_index("date"),
            "date",
            pa.array([None, None], type=pa.date32()),
        )
    elif failure == "date_type":
        table = table.set_column(
            table.schema.get_field_index("date"), "date", pa.array(["2024", "2024"])
        )
    elif failure == "nonfinite":
        table = table.set_column(2, "depth_m", pa.array([float("inf"), None]))
    elif failure == "area_escape":
        area = "../../escape"
    with pytest.raises(ValueError):
        write_areas(
            {area: AreaTables(dynamic=table) if dynamic else AreaTables(static=table)},
            output=tmp_path / "out",
        )
    assert not (tmp_path / "out").exists()


def test_export_aligns_rows_and_rejects_support_mismatch(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    table = fixture_table()
    support = workspace / "support.parquet"
    source = workspace / "bathymetry.parquet"
    pq.write_table(table.select(["H3_INDEX", "H3_RESOLUTION"]), support)
    pq.write_table(table.take(pa.array([1, 0])), source)
    catalog = {
        "products": {
            "h3_marine_support": {
                "collection": {"paths": {6: "support.parquet"}},
                "features": {},
            },
            "bathymetry": {
                "collection": {"paths": {6: "bathymetry.parquet"}},
                "features": {
                    "depth_m": {
                        "collection_paths": {6: "bathymetry.parquet"},
                        "unit": "m",
                    }
                },
            },
        }
    }
    config = workspace / "catalog.yaml"
    config.write_text(yaml.safe_dump(catalog))
    output = tmp_path / "out"
    export_domain_parquets(workspace=workspace, output=output, catalog_path=config)
    result = read_area("bathymetry", output=output)
    assert result["bathymetry__depth_m"].to_pylist() == [0.0, None]
    context = json.loads(result.schema.metadata[b"seascape_domain"])
    assert context["fields"]["bathymetry__depth_m"]["unit"] == "m"
    write_areas(
        {"bathymetry": AreaTables(result, fixture_table(dynamic=True))}, output=output
    )
    dated_bytes = (output / "bathymetry-r6-dynamic.parquet").read_bytes()
    export_domain_parquets(workspace=workspace, output=output, catalog_path=config)
    assert dated_bytes == (output / "bathymetry-r6-dynamic.parquet").read_bytes()
    before = (output / "catalog.json").read_bytes()
    pq.write_table(table.slice(0, 1), source)
    with pytest.raises(ValueError, match="support mismatch"):
        export_domain_parquets(workspace=workspace, output=output, catalog_path=config)
    assert (output / "catalog.json").read_bytes() == before


def test_normal_plan_has_no_data_release_stages(tmp_path, monkeypatch):
    from seascape.workflow import plan_domain_layer_build

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    plan = plan_domain_layer_build(config_path="config/data/project.yaml")
    assert plan.candidate_root == tmp_path / ".seascape/work/seascape"
    assert plan.stages[-1].name == "seascape-parquets"
    assert not any("release" in stage.name for stage in plan.stages)


def test_export_annual_source_keeps_year_precision_and_nulls(tmp_path):
    table = fixture_table()
    annual = table.append_column(
        "OBSERVATION_YEAR", pa.array([2021, 2021], type=pa.int16())
    )
    pq.write_table(
        table.select(["H3_INDEX", "H3_RESOLUTION"]), tmp_path / "support.parquet"
    )
    pq.write_table(annual, tmp_path / "annual.parquet")
    catalog = {
        "products": {
            "h3_marine_support": {
                "collection": {"paths": {6: "support.parquet"}},
                "features": {},
            },
            "kelp": {
                "temporal_column": "OBSERVATION_YEAR",
                "collection": {"paths": {6: "annual.parquet"}},
                "features": {
                    "depth_m": {"collection_paths": {6: "annual.parquet"}, "unit": "m"}
                },
            },
        }
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(catalog))
    export_domain_parquets(
        workspace=tmp_path, output=tmp_path / "out", catalog_path=path
    )
    result = read_area("kelp", dynamic=True, output=tmp_path / "out")
    assert result["date"].to_pylist() == [date(2021, 1, 1)] * 2
    assert result["kelp__depth_m"].to_pylist() == [0.0, None]
    assert (
        json.loads(result.schema.metadata[b"seascape_domain"])["temporal_support"][
            "precision"
        ]
        == "year"
    )
    assert not (tmp_path / "out/kelp-r6-static.parquet").exists()
    with pytest.raises(ValueError, match="integer survey years"):
        label_annual_dates(
            annual.set_column(
                3, "OBSERVATION_YEAR", pa.array([None, None], type=pa.int16())
            )
        )


def test_publication_work_is_outside_delivery_parent(tmp_path):
    from seascape.domain_parquets import _io_root

    root = tmp_path / "Data/Seascape"
    write_areas({"bathymetry": AreaTables(fixture_table())}, output=root)
    assert {p.name for p in root.parent.iterdir()} == {"Seascape"}
    assert _io_root(root).is_relative_to(tmp_path / ".marinecast-work/seascape")
    assert not any(p.is_file() for p in (_io_root(root) / ".staging").rglob("*"))


def test_named_area_retirement_is_transactional_and_preserves_unrelated_bytes(
    tmp_path, monkeypatch
):
    root = tmp_path / "Data/Seascape"
    initial = write_areas(
        {
            "annual-kelp-footprints": AreaTables(dynamic=fixture_table(dynamic=True)),
            "mapped-kelp-mosaic": AreaTables(fixture_table()),
            "bathymetry": AreaTables(fixture_table()),
        },
        output=root,
    )
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    original_write = pq.write_table

    def fail(*args, **kwargs):
        raise OSError("synthetic failed consolidation")

    monkeypatch.setattr(pq, "write_table", fail)
    with pytest.raises(OSError, match="failed consolidation"):
        write_areas(
            {"kelp": AreaTables(fixture_table(), fixture_table(dynamic=True))},
            output=root,
            retire_areas=("annual-kelp-footprints", "mapped-kelp-mosaic"),
        )
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    monkeypatch.setattr(pq, "write_table", original_write)
    final = write_areas(
        {"kelp": AreaTables(fixture_table(), fixture_table(dynamic=True))},
        output=root,
        retire_areas=("annual-kelp-footprints", "mapped-kelp-mosaic"),
    )
    assert set(final) == {"kelp", "bathymetry"}
    assert final["bathymetry"] == initial["bathymetry"]
    assert (root / "bathymetry-r6-static.parquet").read_bytes() == before[
        "bathymetry-r6-static.parquet"
    ]
    assert not any(
        path.name.startswith(("annual-kelp-footprints", "mapped-kelp-mosaic"))
        for path in root.iterdir()
    )


@pytest.mark.parametrize(
    "area,family",
    [
        ("mapped-substrate-classes", "Substrate"),
        ("shoreline", "Coastal Environment"),
        ("coast-complexity", "Coastal Environment"),
        ("nearshore-transitions", "Coastal Environment"),
    ],
)
def test_presentation_family_preserves_native_values_and_units(tmp_path, area, family):
    table = fixture_table().replace_schema_metadata(
        {
            b"seascape_domain": json.dumps(
                {
                    "fields": {
                        "depth_m": {
                            "unit": "m",
                            "6": {"unit": "m", "available_resolutions": [6]},
                        }
                    }
                }
            ).encode()
        }
    )
    root = tmp_path / "Data/Seascape"
    write_areas({area: AreaTables(table)}, output=root)
    actual = pq.read_table(root / f"{area}-r6-static.parquet")
    assert actual.equals(table, check_metadata=False)
    field = json.loads(actual.schema.metadata[b"seascape_domain"])["fields"]["depth_m"]
    assert field == {
        "unit": "m",
        "family": family,
        "6": {"unit": "m", "available_resolutions": [6], "family": family},
    }
