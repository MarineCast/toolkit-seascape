from __future__ import annotations

import json
import shutil
from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from seascape.metric_matrix import build_metric_matrix
from seascape.core.artifacts.checksums import checksum_path


def _fixture(tmp_path: Path, *, duplicate: bool = False) -> tuple[Path, Path, Path, list[str]]:
    workspace = tmp_path / "source"
    support_rel = Path("data/processed/domain/environmental_layer/seascape/support.parquet")
    bathy_rel = Path("data/processed/domain/environmental_layer/seascape/bathymetry.parquet")
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
    assert metadata["fields"]["bathymetry__BATHYMETRY"]["source_types_by_resolution"] == {
        "6": "double"
    }
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
    assert {record["dataset_id"] for record in metadata["source_tables"]} == set(products)
