import json

import pyarrow as pa
import pytest

from seascape.anthropogenic.presentation import (
    PRESENCE_LABELS,
    anthropogenic_presentation,
)


def fixture():
    return pa.table(
        {
            "AQUACULTURE_MAPPED_POSITIVE_EVIDENCE": [True, False, None, None],
            "ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE": pa.array(
                [None] * 4, type=pa.bool_()
            ),
            "DISPOSAL_SITE_MAPPED_AREA_M2": [2.0, 0.0, 3.0, None],
            "DISPOSAL_SITE_AREA_QC": [
                "positive_mapped_polygon_inventory",
                "no_positive_mapped_polygon_unknown_absence",
                "unqualified",
                None,
            ],
            "DREDGED_CHANNEL_MAPPED_AREA_M2": [0.0, 4.0, None, 2.0],
            "DREDGED_CHANNEL_AREA_QC": [
                "no_positive_mapped_polygon_unknown_absence",
                "positive_mapped_polygon_inventory",
                None,
                "positive_mapped_polygon_inventory",
            ],
            "SOURCE_COVERAGE": ["partial"] * 4,
            "DISTANCE_TO_AQUACULTURE_M": [1.0, 2.0, None, None],
            "KEEP": [7, 8, 9, 10],
        }
    )


def test_boolean_policy_preserves_source_and_unknowns():
    old = fixture()
    new = anthropogenic_presentation(old)
    assert new.select([c for c in old.column_names if c not in PRESENCE_LABELS]).equals(
        old.select([c for c in old.column_names if c not in PRESENCE_LABELS]),
        check_metadata=False,
    )
    for c in PRESENCE_LABELS:
        if c in old.column_names:
            assert new[c + "_SOURCE_NULLABLE"].equals(old[c])
        assert new[c].null_count == 0
    assert new["DISPOSAL_SITE_MAPPED_POSITIVE_EVIDENCE"].to_pylist() == [
        True,
        False,
        False,
        False,
    ]
    assert new["DREDGED_CHANNEL_MAPPED_POSITIVE_EVIDENCE"].to_pylist() == [
        False,
        True,
        False,
        True,
    ]
    metadata = json.loads(new.schema.metadata[b"seascape_domain"])["fields"]
    assert {k for k, v in metadata.items() if v.get("picker_visible")} == set(
        PRESENCE_LABELS
    )
    assert metadata["SOURCE_COVERAGE"]["picker_visible"] is False
    assert metadata["DISTANCE_TO_AQUACULTURE_M"]["picker_visible"] is False
    assert anthropogenic_presentation(new).equals(new, check_metadata=True)


def test_presence_requires_boolean_and_area_qc():
    with pytest.raises(ValueError, match="nullable boolean"):
        anthropogenic_presentation(
            pa.table({"AQUACULTURE_MAPPED_POSITIVE_EVIDENCE": [1.0]})
        )
    with pytest.raises(ValueError, match="linked polygon QC"):
        anthropogenic_presentation(pa.table({"DISPOSAL_SITE_MAPPED_AREA_M2": [1.0]}))


def test_eight_qc_selectors_are_hidden_without_removing_values_or_provenance():
    fields = [
        "COMPREHENSIVE_SURVEY_COVERAGE_ESTABLISHED",
        "FULL_H3_WITHIN_SOURCE_RECTANGLE",
        "GENERALIZED_FALLBACK",
        "GLOBAL_INVENTORY_COMPLETE",
        "NATIVE_LAND_FOOTPRINT_UNKNOWN",
        "NETWORK_DISTANCE_QC_REASON",
        "OBSERVATION_PERIOD",
        "OVERWATER_QC",
    ]
    original = pa.table(
        {"ANTHROPOGENIC__" + c: ["retained", None] for c in fields}
    ).replace_schema_metadata(
        {
            b"seascape_domain": json.dumps(
                {"source_context": {"observation_period": "unknown"}}
            ).encode()
        }
    )
    result = anthropogenic_presentation(original)
    assert result.equals(original, check_metadata=False)
    context = json.loads(result.schema.metadata[b"seascape_domain"])
    assert context["source_context"] == {"observation_period": "unknown"}
    assert all(
        context["fields"][c]["picker_visible"] is False for c in original.column_names
    )
