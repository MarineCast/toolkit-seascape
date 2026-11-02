"""Compact delivery must retain exact native missingness and recover on failure."""

import json
from datetime import date

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from seascape.domain_parquets import AreaTables, read_area, write_areas
from seascape.reviewed_delivery import KEY, compact_existing, restore_native


def native(area="seagrass"):
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123.0, 6), 1))[:3]
    return pa.table(
        {
            "H3_INDEX": cells,
            "H3_RESOLUTION": [6] * 3,
            f"{area.upper()}_EXTENT_ALL_TIME_M2": pa.array([None, 0.0, 12.5]),
            "QC": ["unknown", "no_positive_evidence", "mapped"],
        }
    ).replace_schema_metadata(
        {
            b"seascape_domain": json.dumps(
                {
                    "fields": {"QC": {"picker_visible": False}},
                    "temporal_support": {"precision": "all_time"},
                    "model_eligible": False,
                }
            ).encode()
        }
    )


@pytest.mark.parametrize("area", ["seagrass", "bivalve", "kelp"])
def test_normal_writer_compacts_and_recovers_original_nulls(tmp_path, area):
    root = tmp_path / "Data/Seascape"
    write_areas({area: AreaTables(native(area))}, output=root)
    public = read_area(area, output=root)
    field = f"{area.upper()}_EXTENT_ALL_TIME_M2"
    flag = f"{area.upper()}_EXTENT_BOOL"
    assert public.column_names == ["H3_INDEX", field, flag]
    assert public[field].to_pylist() == [None, 0.0, 12.5]
    assert public[flag].to_pylist() == [None, 0, 1]
    assert KEY not in public.schema.metadata
    assert not list(tmp_path.rglob("audit/*.parquet"))


def legacy_root(tmp_path):
    root = tmp_path / "Data/Seascape"
    root.mkdir(parents=True)
    pq.write_table(native(), root / "seagrass-r6-static.parquet")
    dynamic = native("kelp").append_column(
        "date", pa.array([date(2024, 1, 1)] * 3, type=pa.date32())
    )
    pq.write_table(dynamic, root / "kelp-r6-dynamic.parquet")
    catalog = {
        "seagrass": {
            "last_updated_utc": "2026-10-20",
            "static": {"6": "seagrass-r6-static.parquet"},
        },
        "kelp": {
            "last_updated_utc": "2026-10-20",
            "dynamic": {"6": "kelp-r6-dynamic.parquet"},
        },
    }
    (root / "catalog.json").write_text(json.dumps(catalog))
    (root / "REVIEW.txt").write_text("user notes remain exactly intact")
    return root


def test_migration_is_exact_idempotent_and_preserves_dates_dynamic_notes(tmp_path):
    root = legacy_root(tmp_path)
    original = pq.read_table(root / "seagrass-r6-static.parquet")
    dynamic = (root / "kelp-r6-dynamic.parquet").read_bytes()
    result = compact_existing(root)
    assert len(result["changed"]) == 1
    public = pq.read_table(root / "seagrass-r6-static.parquet")
    assert restore_native(public).equals(original, check_metadata=True)
    assert (root / "REVIEW.txt").read_text() == "user notes remain exactly intact"
    assert (root / "kelp-r6-dynamic.parquet").read_bytes() == dynamic
    assert (
        json.loads((root / "catalog.json").read_text())["seagrass"]["last_updated_utc"]
        == "2026-10-20"
    )
    before = (root / "seagrass-r6-static.parquet").read_bytes()
    assert compact_existing(root)["changed"] == []
    assert (root / "seagrass-r6-static.parquet").read_bytes() == before


@pytest.mark.parametrize("damage", ["public", "metadata", "audit", "missing"])
def test_tampering_or_missing_audit_fails(tmp_path, damage):
    root = legacy_root(tmp_path)
    compact_existing(root)
    public = pq.read_table(root / "seagrass-r6-static.parquet")
    from pathlib import Path

    audit = Path(json.loads(public.schema.metadata[KEY])["audit_path"])
    if damage == "public":
        public = public.set_column(
            1, "SEAGRASS_EXTENT_ALL_TIME_M2", pa.array([0.0, 0.0, 99.0])
        )
    elif damage == "metadata":
        metadata = dict(public.schema.metadata)
        metadata[b"seascape_domain"] = b'{"model_eligible": true}'
        public = public.replace_schema_metadata(metadata)
    elif damage == "audit":
        audit.write_bytes(b"corrupt audit")
    else:
        audit.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        restore_native(public)


def test_failed_audit_serialization_preserves_entire_delivery(tmp_path, monkeypatch):
    root = legacy_root(tmp_path)
    before = {p.name: p.read_bytes() for p in root.iterdir()}

    def fail(*args, **kwargs):
        raise OSError("synthetic audit write failure")

    monkeypatch.setattr(pq, "write_table", fail)
    with pytest.raises(OSError, match="audit write"):
        compact_existing(root)
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_audit_cannot_be_placed_in_public_delivery(tmp_path):
    root = tmp_path / "Data/Seascape"
    with pytest.raises(ValueError, match="outside public delivery"):
        write_areas(
            {"seagrass": AreaTables(native())}, output=root, audit_root=root / "audit"
        )


def test_concurrent_note_edit_is_preserved_and_compaction_aborts(tmp_path, monkeypatch):
    root = legacy_root(tmp_path)
    before = (root / "seagrass-r6-static.parquet").read_bytes()
    original_write = pq.write_table

    def concurrent_edit(*args, **kwargs):
        (root / "REVIEW.txt").write_text("new user review during migration")
        return original_write(*args, **kwargs)

    monkeypatch.setattr(pq, "write_table", concurrent_edit)
    with pytest.raises(ValueError, match="Concurrent source change"):
        compact_existing(root)
    assert (root / "REVIEW.txt").read_text() == "new user review during migration"
    assert (root / "seagrass-r6-static.parquet").read_bytes() == before


@pytest.mark.parametrize("area", ["bathymetry", "freshwater"])
def test_resolution_is_external_but_native_h3_values_and_nulls_survive(tmp_path, area):
    root = tmp_path / "Data/Seascape"
    write_areas({area: AreaTables(native())}, output=root)
    public = read_area(area, output=root)
    assert "H3_RESOLUTION" not in public.column_names
    assert public["H3_INDEX"].equals(native()["H3_INDEX"])
    assert public["SEAGRASS_EXTENT_ALL_TIME_M2"].to_pylist() == [None, 0.0, 12.5]
    assert KEY not in public.schema.metadata
