import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from seascape.regional.coastal_serialization import nullable_origin_h3


def test_nan_and_none_are_nullable_strings_in_streamed_parquet(tmp_path):
    cell = h3.latlng_to_cell(48, -123, 8)
    schema = pa.schema([("ORIGIN_SOURCE_H3_INDEX", pa.string())])
    table = pa.Table.from_pylist(
        [
            {"ORIGIN_SOURCE_H3_INDEX": nullable_origin_h3(value)}
            for value in [cell, float("nan"), None]
        ],
        schema=schema,
    )
    path = tmp_path / "origins.parquet"
    pq.write_table(table, path)
    assert pq.read_table(path).column(0).to_pylist() == [cell, None, None]


@pytest.mark.parametrize("value", [123, 1.0, float("inf"), "unknown"])
def test_invalid_finite_identifier_is_not_coerced(value):
    with pytest.raises(ValueError, match="valid"):
        nullable_origin_h3(value)
