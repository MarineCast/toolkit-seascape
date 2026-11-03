import json

import h3
import pyarrow as pa

from seascape.delivery_projection import (
    SPATIAL_SUPPORT_OMITTED_FIELDS,
    project_delivery_table,
)


def test_public_projection_preserves_native_support_and_other_arrays(tmp_path):
    values = {
        "H3_INDEX": [h3.latlng_to_cell(49, -124, 6)],
        "H3_RESOLUTION": [6],
        "h3_marine_support__GRAPH_DEGREE": [3],
        "h3_marine_support__WATER_FRACTION": [None],
    }
    values.update(
        {
            "h3_marine_support__" + name: ["native context"]
            for name in SPATIAL_SUPPORT_OMITTED_FIELDS
        }
    )
    context = {
        "source_context": {"native": "retained"},
        "fields": {name: {"6": {"qualifiers": list(values)}} for name in values},
    }
    native = pa.table(values).replace_schema_metadata(
        {b"seascape_domain": json.dumps(context).encode()}
    )
    actual = project_delivery_table("spatial-support", native)
    assert actual.equals(native.select(list(values)[:4]), check_metadata=False)
    assert native.num_columns == 14
    result = json.loads(actual.schema.metadata[b"seascape_domain"])
    assert result["source_context"] == context["source_context"]
    assert all(
        set(info["6"]["qualifiers"]) <= set(actual.column_names)
        for info in result["fields"].values()
    )
    assert project_delivery_table("shoreline", native) is native
    assert project_delivery_table("spatial-support", actual).equals(
        actual, check_metadata=True
    )
