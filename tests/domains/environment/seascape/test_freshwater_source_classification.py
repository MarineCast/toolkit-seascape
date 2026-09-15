from __future__ import annotations

from seascape.hydrologic_connectivity.freshwater_sources.source_classification import (
    source_classification,
)


def test_nhd_source_documented_type_and_permanence_are_normalized() -> None:
    natural = source_classification("US_NHD_SMALL_SCALE", {"FTYPE": "StreamRiver", "FCODE": 46006})
    assert natural["MOUTH_SOURCE_TYPE"] == "natural_channel"
    assert natural["MOUTH_PERMANENCE_CLASS"] == "perennial"
    assert natural["MOUTH_SOURCE_TYPE_SOURCE_FIELD"] == "FTYPE"
    assert natural["MOUTH_PERMANENCE_SOURCE_CODE"] == "46006"

    artificial = source_classification(
        "US_NHD_SMALL_SCALE", {"FTYPE": "CanalDitch", "FCODE": 46007}
    )
    assert artificial["MOUTH_SOURCE_TYPE"] == "artificial_channel"
    assert artificial["MOUTH_PERMANENCE_CLASS"] == "ephemeral"


def test_permanence_is_not_inferred_from_morphology() -> None:
    result = source_classification(
        "BC_FWA_STREAM_NETWORK",
        {
            "FEATURE_CODE": "stream",
            "EDGE_TYPE": "not-a-documented-permanence-code",
            "STREAM_ORDER": 9,
            "UPSTREAM_AREA_KM2": 100000,
            "WIDTH_M": 500,
            "DISCHARGE": 9999,
        },
    )
    assert result["MOUTH_SOURCE_TYPE"] == "unknown"
    assert result["MOUTH_PERMANENCE_CLASS"] == "unknown"
    assert result["MOUTH_SOURCE_TYPE_SOURCE_CODE"] == "stream"
    assert result["MOUTH_PERMANENCE_SOURCE_CODE"] == "not-a-documented-permanence-code"
