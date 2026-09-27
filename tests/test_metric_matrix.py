from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from seascape import metric_matrix
from seascape.core.artifacts.checksums import checksum_path
from seascape.core.data.registry import DATASETS
from seascape.metric_matrix import build_metric_matrix
from seascape.products import resolve_product
from seascape.release import publish_candidate_release
from tests.test_products import _candidate_fixture


def _fixture(
    tmp_path: Path, *, duplicate: bool = False
) -> tuple[Path, Path, Path, list[str]]:
    workspace = tmp_path / "source"
    support_rel = Path(
        "data/processed/domain/environmental_layer/seascape/support.parquet"
    )
    bathy_rel = Path(
        "data/processed/domain/environmental_layer/seascape/bathymetry.parquet"
    )
    support = workspace / support_rel
    bathy = workspace / bathy_rel
    support.parent.mkdir(parents=True)
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123.0, 6), 1))[:2]
    pq.write_table(
        pa.table(
            {
                "H3_INDEX": cells,
                "H3_RESOLUTION": pa.array([6, 6], type=pa.int8()),
                "WATER_AREA_M2": [0.0, 10.0],
            }
        ),
        support,
    )
    pq.write_table(
        pa.table(
            {
                "H3_INDEX": [cells[1], cells[1] if duplicate else cells[0]],
                "H3_RESOLUTION": pa.array([6, 6], type=pa.int8()),
                "BATHYMETRY": pa.array([12.0, None], type=pa.float64()),
                "BATHYMETRY_QC": ["observed", "unavailable"],
            }
        ),
        bathy,
    )
    catalog = {
        "products": {
            "h3_marine_support": {
                "collection": {"paths": {6: str(support_rel)}},
                "features": {
                    "WATER_AREA_M2": {
                        "collection_paths": {6: str(support_rel)},
                        "available_resolutions": [6],
                        "unit": "m2",
                        "role": "predictor",
                        "variable_kind": "metadata",
                    }
                },
            },
            "bathymetry": {
                "collection": {"paths": {6: str(bathy_rel)}},
                "features": {
                    "BATHYMETRY": {
                        "collection_paths": {6: str(bathy_rel)},
                        "available_resolutions": [6],
                        "unit": "m",
                        "role": "predictor",
                        "variable_kind": "feature_variable",
                    },
                    "BATHYMETRY_QC": {
                        "collection_paths": {6: str(bathy_rel)},
                        "available_resolutions": [6],
                        "unit": "category_or_text",
                        "role": "evidence",
                        "variable_kind": "metadata",
                    },
                },
            },
        }
    }
    catalog_path = tmp_path / "feature_catalog.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    release = workspace / (
        "data/processed/domain/environmental_layer/seascape/"
        "seascape_release_manifest.json"
    )
    release.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_release_passed": True,
                "model_policy_complete": False,
                "family_manifest_checksums": {"missing.json": "old-checksum"},
            }
        ),
        encoding="utf-8",
    )
    return workspace, catalog_path, tmp_path / "matrix.parquet", cells


def test_matrix_aligns_by_h3_and_preserves_zero_null_and_qc(tmp_path: Path) -> None:
    workspace, catalog, output, cells = _fixture(tmp_path)

    result = build_metric_matrix(
        workspace=workspace,
        output=output,
        resolutions=(6,),
        legacy_unverified=True,
        catalog_path=catalog,
    )

    table = pq.read_table(output)
    metadata = json.loads(table.schema.metadata[b"seascape_metric_matrix"])
    assert result.row_count == 2
    assert result.field_count == 3
    assert table.column("H3_INDEX").to_pylist() == cells
    assert table.column("h3_marine_support__WATER_AREA_M2").to_pylist() == [0.0, 10.0]
    assert table.column("bathymetry__BATHYMETRY").to_pylist() == [None, 12.0]
    assert table.column("bathymetry__BATHYMETRY_QC").to_pylist() == [
        "unavailable",
        "observed",
    ]
    assert metadata["source_validation"] == "legacy_structural_only"
    assert metadata["legacy_family_manifest_mismatches"] == ["missing.json"]
    assert metadata["fields"]["bathymetry__BATHYMETRY"]["unit"] == "m"
    assert metadata["fields"]["bathymetry__BATHYMETRY"][
        "source_types_by_resolution"
    ] == {"6": "double"}
    with pytest.raises(FileExistsError):
        build_metric_matrix(
            workspace=workspace,
            output=output,
            resolutions=(6,),
            legacy_unverified=True,
            catalog_path=catalog,
        )


def test_matrix_rejects_duplicate_h3_keys(tmp_path: Path) -> None:
    workspace, catalog, output, _ = _fixture(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="Duplicate H3_INDEX"):
        build_metric_matrix(
            workspace=workspace,
            output=output,
            resolutions=(6,),
            legacy_unverified=True,
            catalog_path=catalog,
        )
    assert not output.exists()


def test_matrix_resolves_one_validated_release(tmp_path: Path) -> None:
    workspace, catalog, output, cells = _fixture(tmp_path)
    release_id = "a" * 64
    generation = workspace / ".seascape/releases" / release_id
    archived_catalog = generation / "config/feature_catalog.yaml"
    archived_catalog.parent.mkdir(parents=True)
    shutil.copyfile(catalog, archived_catalog)
    products = {}
    for product_id, filename in (
        ("h3_marine_support", "support.parquet"),
        ("bathymetry", "bathymetry.parquet"),
    ):
        relative = Path("data/processed/domain/environmental_layer/seascape") / filename
        source = workspace / relative
        target = generation / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        dataset_id = f"environment.seascape.{product_id}_r6"
        products[dataset_id] = {
            "product_id": (
                "seafloor_bathymetry" if product_id == "bathymetry" else product_id
            ),
            "dataset_id": dataset_id,
            "path": str(relative),
            "checksum": checksum_path(target),
            "checksum_algorithm": "sha256",
            "schema_version": "1",
            "producer": "synthetic_fixture",
            "resolution": 6,
            "grain": ["H3_INDEX"],
        }
    payload = {
        "schema_version": 3,
        "release_id": release_id,
        "storage_root": f".seascape/releases/{release_id}",
        "artifact_release_passed": True,
        "family_manifest_checksums": {},
        "governed_artifacts": {
            "catalog": {
                "path": "config/feature_catalog.yaml",
                "checksum": checksum_path(archived_catalog),
            }
        },
        "products": products,
    }
    relative_manifest = Path(
        "data/processed/domain/environmental_layer/seascape/"
        "seascape_release_manifest.json"
    )
    (workspace / relative_manifest).write_text(json.dumps(payload), encoding="utf-8")
    (generation / relative_manifest).write_text(json.dumps(payload), encoding="utf-8")

    result = build_metric_matrix(
        workspace=workspace,
        output=output,
        resolutions=(6,),
    )

    assert result.source_validation == "schema3_release_verified"
    assert result.source_release_id == release_id
    table = pq.read_table(output)
    assert table.column("H3_INDEX").to_pylist() == cells
    assert table.column("bathymetry__BATHYMETRY").to_pylist() == [None, 12.0]
    metadata = json.loads(table.schema.metadata[b"seascape_metric_matrix"])
    assert {record["dataset_id"] for record in metadata["source_tables"]} == set(
        products
    )


def _export(workspace, catalog, output, **kwargs):
    return build_metric_matrix(
        workspace=workspace,
        catalog_path=catalog,
        output=output,
        resolutions=(6,),
        legacy_unverified=True,
        **kwargs,
    )


def _collections(workspace, catalog):
    products = yaml.safe_load(catalog.read_text())["products"]
    return {
        name: workspace / product["collection"]["paths"][6]
        for name, product in products.items()
    }


@pytest.mark.parametrize(
    "case, message",
    [
        ("null", "Null or invalid H3_INDEX"),
        ("wrong_cell_resolution", "wrong-resolution H3_INDEX"),
        ("declared_resolution", "H3_RESOLUTION mismatch"),
        ("missing_support", "H3 support mismatch"),
        ("extra_support", "H3 support mismatch"),
    ],
)
def test_matrix_rejects_invalid_identity_without_replacing_output(
    tmp_path, case, message
):
    workspace, catalog, output, cells = _fixture(tmp_path)
    _export(workspace, catalog, output)
    previous = output.read_bytes()
    path = _collections(workspace, catalog)["bathymetry"]
    table = pq.read_table(path)
    if case == "null":
        table = table.set_column(0, "H3_INDEX", pa.array([None, cells[0]]))
    elif case == "wrong_cell_resolution":
        table = table.set_column(
            0, "H3_INDEX", pa.array([h3.cell_to_parent(cells[1], 5), cells[0]])
        )
    elif case == "declared_resolution":
        table = table.set_column(1, "H3_RESOLUTION", pa.array([8, 6]))
    elif case == "missing_support":
        table = table.slice(0, 1)
    else:
        extra = next(iter(set(h3.grid_disk(cells[0], 1)) - set(cells)))
        table = pa.concat_tables(
            [table, table.slice(0, 1).set_column(0, "H3_INDEX", pa.array([extra]))]
        )
    pq.write_table(table, path)
    with pytest.raises(ValueError, match=message):
        _export(workspace, catalog, output, overwrite=True)
    assert output.read_bytes() == previous


def test_matrix_rejects_empty_support_without_resolution_column(tmp_path):
    workspace, catalog, output, _ = _fixture(tmp_path)
    for path in _collections(workspace, catalog).values():
        pq.write_table(pq.read_table(path).drop(["H3_RESOLUTION"]).slice(0, 0), path)
    with pytest.raises(ValueError, match="Empty H3 support"):
        _export(workspace, catalog, output)
    assert not output.exists()


def test_matrix_row_order_invariance_and_collision_free_field_names(tmp_path):
    workspace, catalog, output, cells = _fixture(tmp_path)
    products = yaml.safe_load(catalog.read_text())
    paths = _collections(workspace, catalog)
    for name, path in paths.items():
        table = pq.read_table(path).append_column("SHARED", pa.array([1, 2]))
        pq.write_table(table, path)
        products["products"][name]["features"]["SHARED"] = {
            "collection_paths": {6: str(path.relative_to(workspace))},
            "unit": "count",
            "role": "evidence",
        }
    catalog.write_text(yaml.safe_dump(products))
    _export(workspace, catalog, output)
    first = pq.read_table(output)
    for path in paths.values():
        pq.write_table(pq.read_table(path).take([1, 0]), path)
    _export(workspace, catalog, output, overwrite=True)
    second = pq.read_table(output)
    # Source checksums and creation times change; keyed scientific values do not.
    assert first.equals(second, check_metadata=False)
    assert second["H3_INDEX"].to_pylist() == cells
    assert second["h3_marine_support__SHARED"].to_pylist() == [1, 2]
    assert second["bathymetry__SHARED"].to_pylist() == [2, 1]
    metadata = json.loads(second.schema.metadata[b"seascape_metric_matrix"])
    assert metadata["source_release_id"] is None
    assert metadata["source_validation"] == "legacy_structural_only"
    qc = metadata["fields"]["bathymetry__BATHYMETRY_QC"]
    assert qc["role"] == "evidence" and qc["unit"] == "category_or_text"
    assert qc["source_types_by_resolution"] == {"6": "string"}
    assert len(second.column_names) == len(set(second.column_names))


@pytest.mark.parametrize("failure", ["serialization", "replacement"])
def test_matrix_failed_write_preserves_valid_destination(
    tmp_path, monkeypatch, failure
):
    workspace, catalog, output, _ = _fixture(tmp_path)
    _export(workspace, catalog, output)
    before = output.read_bytes()

    def fail(*args, **kwargs):
        if failure == "serialization":
            Path(args[1]).write_bytes(b"partial serialization")
        raise OSError(f"injected {failure} failure")

    monkeypatch.setattr(
        pq if failure == "serialization" else os,
        "write_table" if failure == "serialization" else "replace",
        fail,
    )
    with pytest.raises(OSError, match=f"injected {failure}"):
        _export(workspace, catalog, output, overwrite=True)
    assert output.read_bytes() == before
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))


@pytest.mark.parametrize("alias", ["table", "symlink", "catalog", "release_manifest"])
def test_matrix_output_cannot_replace_input(tmp_path, alias):
    workspace, catalog, output, _ = _fixture(tmp_path)
    table = _collections(workspace, catalog)["bathymetry"]
    if alias == "table":
        output = table
    elif alias == "symlink":
        output.symlink_to(table)
    elif alias == "catalog":
        output = catalog
    else:
        output = workspace / metric_matrix._RELEASE_MANIFEST
    previous = output.read_bytes()
    with pytest.raises(ValueError, match="cannot replace an input"):
        _export(workspace, catalog, output, overwrite=True)
    assert output.read_bytes() == previous


@pytest.mark.parametrize("escape", ["dotdot", "absolute", "symlink"])
def test_matrix_rejects_unsafe_catalog_paths(tmp_path, escape):
    workspace, catalog, output, _ = _fixture(tmp_path)
    sentinel = tmp_path / "private.parquet"
    sentinel.write_bytes(b"must not consume or modify")
    value = "../private.parquet" if escape == "dotdot" else str(sentinel)
    if escape == "symlink":
        (workspace / "alias.parquet").symlink_to(sentinel)
        value = "alias.parquet"
    config = yaml.safe_load(catalog.read_text())
    config["products"]["bathymetry"]["collection"]["paths"][6] = value
    catalog.write_text(yaml.safe_dump(config))
    with pytest.raises(
        ValueError, match="Invalid catalog collection path|escapes workspace"
    ):
        _export(workspace, catalog, output)
    assert sentinel.read_bytes() == b"must not consume or modify"
    assert not output.exists()


def test_matrix_pins_real_publication_during_release_switch(tmp_path, monkeypatch):
    workspace, catalog, output, cells = _fixture(tmp_path)
    candidate = tmp_path / "candidate"
    bathy = _candidate_fixture(candidate, b"placeholder")
    support = DATASETS.get("environment.seascape.h3_marine_support_r6").path(
        data_root=candidate / "data",
        artifact_root=candidate / "artifacts",
        output_root=candidate / "outputs",
    )
    paths = _collections(workspace, catalog)
    config = yaml.safe_load(catalog.read_text())
    for name, target in (("h3_marine_support", support), ("bathymetry", bathy)):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths[name], target)
        relative = str(target.relative_to(candidate))
        config["products"][name]["collection"]["paths"][6] = relative
        for feature in config["products"][name]["features"].values():
            feature["collection_paths"][6] = relative
    archived_catalog = candidate / "config/feature_catalog.yaml"
    archived_catalog.write_text(yaml.safe_dump(config))
    # Reuse the existing pre-audited publisher fixture. This is a publisher/reader
    # contract, not a claim that a two-table fixture passed a full regional audit.
    publish_candidate_release(
        canonical_project_root=workspace, candidate_project_root=candidate
    )
    first = resolve_product(workspace=workspace, product="bathymetry", resolution=6)
    old_support = resolve_product(
        workspace=workspace, product="h3_marine_support", resolution=6
    )
    old_catalog_checksum = checksum_path(
        workspace
        / ".seascape/releases"
        / first.release_id
        / "config/feature_catalog.yaml"
    )
    real_resolve = metric_matrix.resolve_product
    calls = []

    def switch_after_selection(**kwargs):
        artifact = real_resolve(**kwargs)
        calls.append(kwargs.get("release_id"))
        if len(calls) == 1:
            table = pq.read_table(bathy)
            pq.write_table(
                table.set_column(2, "BATHYMETRY", pa.array([99.0, 88.0])), bathy
            )
            publish_candidate_release(
                canonical_project_root=workspace, candidate_project_root=candidate
            )
        return artifact

    monkeypatch.setattr(metric_matrix, "resolve_product", switch_after_selection)
    result = build_metric_matrix(workspace=workspace, output=output, resolutions=(6,))
    latest = resolve_product(workspace=workspace, product="bathymetry", resolution=6)
    assert latest.release_id != first.release_id
    assert calls == [None, first.release_id, first.release_id]
    assert result.source_release_id == first.release_id
    table = pq.read_table(output)
    assert table["H3_INDEX"].to_pylist() == cells
    assert table["bathymetry__BATHYMETRY"].to_pylist() == [None, 12.0]
    metadata = json.loads(table.schema.metadata[b"seascape_metric_matrix"])
    assert metadata["source_release_id"] == first.release_id
    assert metadata["catalog_checksum"] == old_catalog_checksum
    assert {row["checksum"] for row in metadata["source_tables"]} == {
        first.checksum,
        old_support.checksum,
    }
    assert all(first.release_id in row["path"] for row in metadata["source_tables"])
    # Overwrite cannot corrupt even an older, unselected release generation.
    before = first.manifest_path.read_bytes()
    with pytest.raises(ValueError, match="cannot replace an input release generation"):
        build_metric_matrix(
            workspace=workspace,
            output=first.manifest_path,
            resolutions=(6,),
            overwrite=True,
        )
    assert first.manifest_path.read_bytes() == before
    assert (
        resolve_product(
            workspace=workspace,
            product="bathymetry",
            resolution=6,
            release_id=first.release_id,
        )
        == first
    )
