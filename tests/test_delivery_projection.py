from __future__ import annotations

import json

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from seascape.delivery_projection import (
    SUBSTRATE_OMITTED_FIELDS,
    project_delivery_table,
)
from seascape.domain_parquets import (
    AreaTables,
    export_domain_parquets,
    read_area,
    write_areas,
)


def substrate():
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123, 6), 1))[:2]
    values = {
        "H3_INDEX": cells,
        "H3_RESOLUTION": [6, 6],
        "SUBSTRATE_MODEL__MODELED_SEDIMENT_SAND_FRACTION": [0.0, None],
        "SUBSTRATE_MODEL__ROCK_VALID_NEIGHBOR_WEIGHT": [1.0, 0.0],
        "SUBSTRATE_MODEL__PHYSICAL_HARDNESS": pa.array([None, None], type=pa.float64()),
    }
    for name in SUBSTRATE_OMITTED_FIELDS:
        values["SUBSTRATE_MODEL__" + name] = ["source qualification", None]
    context = {
        "fields": {
            name: {
                "6": {
                    "source_column": name.rsplit("__", 1)[-1],
                    "row_quality_and_coverage_columns": list(values)[3:],
                    "source_observation_period_columns": [
                        "SUBSTRATE_MODEL__SOURCE_OBSERVATION_PERIOD"
                    ],
                }
            }
            for name in values
        },
        "source_context": {
            "native": {
                "manifest.json": {"source_grid_degrees": 0.1},
                "METHOD_SCOPE.json": {
                    "SOURCE_OBSERVATION_PERIOD": "unknown",
                    "sampling": "bilinear point",
                },
            }
        },
    }
    return pa.table(values).replace_schema_metadata(
        {b"seascape_domain": json.dumps(context).encode()}
    )


def test_projection_retains_all_other_arrays_nulls_types_keys_and_source_context(
    tmp_path,
):
    original = substrate()
    source_context = json.loads(original.schema.metadata[b"seascape_domain"])[
        "source_context"
    ]
    write_areas({"substrate": AreaTables(original)}, output=tmp_path / "Seascape")
    result = read_area("substrate", output=tmp_path / "Seascape")
    retained = original.column_names[:5]
    assert result.equals(original.select(retained), check_metadata=False)
    assert result.num_columns == original.num_columns - 15
    context = json.loads(result.schema.metadata[b"seascape_domain"])
    assert context["source_context"] == source_context
    assert set(context["fields"]) == set(retained)
    assert len(context["delivery_projection"]["omitted_columns"]) == 15
    for entry in context["fields"].values():
        assert not set(entry["6"]["row_quality_and_coverage_columns"]) - set(retained)
        assert entry["6"]["source_observation_period_columns"] == []
    assert project_delivery_table("substrate", result).equals(
        result, check_metadata=True
    )
    assert original.num_columns == 20


def test_projection_is_scoped_and_matches_only_exact_native_names():
    original = substrate().append_column(
        "SUBSTRATE_MODEL__SAND_MASK_STATUS_DETAIL", pa.array(["keep", None])
    )
    assert project_delivery_table("mapped-substrate-classes", original) is original
    result = project_delivery_table("substrate", original)
    assert result["SUBSTRATE_MODEL__SAND_MASK_STATUS_DETAIL"].equals(
        original["SUBSTRATE_MODEL__SAND_MASK_STATUS_DETAIL"]
    )


def test_validation_runs_before_projection_and_preserves_last_product(tmp_path):
    root = tmp_path / "Seascape"
    original = substrate()
    write_areas({"substrate": AreaTables(original)}, output=root)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    index = original.column_names.index("SUBSTRATE_MODEL__SOURCE_GRID_DEGREES")
    invalid = original.set_column(
        index, original.field(index).name, pa.array([float("nan"), 0.1])
    )
    with pytest.raises(ValueError, match="Nonfinite metric"):
        write_areas({"substrate": AreaTables(invalid)}, output=root)
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}


def test_export_keeps_native_required_field_validation_and_projects_producer_alias(
    tmp_path,
):
    table = (
        substrate()
        .select(["H3_INDEX", "H3_RESOLUTION"])
        .append_column(
            "SUBSTRATE_SEDIMENT_TEXTURE_STATUS", pa.array(["available", "missing"])
        )
    )
    table = table.append_column("SUBSTRATE_SAND_FRAC", pa.array([0.0, None]))
    pq.write_table(
        table.select(["H3_INDEX", "H3_RESOLUTION"]), tmp_path / "support.parquet"
    )
    pq.write_table(table, tmp_path / "native.parquet")
    config = {
        "products": {
            "h3_marine_support": {
                "collection": {"paths": {6: "support.parquet"}},
                "features": {},
            },
            "benthic_substrate": {
                "collection": {"paths": {6: "native.parquet"}},
                "features": {
                    name: {"collection_paths": {6: "native.parquet"}}
                    for name in table.column_names[2:]
                },
            },
        }
    }
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(config))
    output = tmp_path / "Seascape"
    export_domain_parquets(workspace=tmp_path, output=output, catalog_path=path)
    result = read_area("substrate", output=output)
    assert result.column_names == [
        "H3_INDEX",
        "H3_RESOLUTION",
        "benthic_substrate__SUBSTRATE_SAND_FRAC",
    ]
    assert result.column(2).to_pylist() == [0.0, None]
    before = (output / "catalog.json").read_bytes()
    pq.write_table(
        table.drop(["SUBSTRATE_SEDIMENT_TEXTURE_STATUS"]), tmp_path / "native.parquet"
    )
    with pytest.raises(ValueError, match="Missing cataloged columns"):
        export_domain_parquets(workspace=tmp_path, output=output, catalog_path=path)
    assert (output / "catalog.json").read_bytes() == before
