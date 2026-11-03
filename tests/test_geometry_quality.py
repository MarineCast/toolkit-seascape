from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon, box

from seascape.utils.geometry_quality import (
    audit_polygon_inventory,
    prepare_mixed_habitat_inventory,
)


def fixture_frame():
    return gpd.GeoDataFrame(
        {
            "RECORD_ID": ["good", "crossed", "line"],
            "OBSERVATION_YEAR": [2009, 2010, None],
        },
        geometry=[
            box(0, 0, 1, 1),
            Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)]),
            LineString([(0, 0), (1, 0)]),
        ],
        crs=4326,
    )


def test_invalid_source_is_rejected_by_default_and_never_modified():
    frame = fixture_frame()
    original = frame.geometry.to_wkb().tolist()
    with pytest.raises(ValueError, match="crossed"):
        audit_polygon_inventory(frame)
    assert frame.geometry.to_wkb().tolist() == original
    assert "GEOMETRY_PROCESSING" not in frame


def test_explicit_repair_preserves_identity_and_quarantines_non_polygon():
    frame = fixture_frame()
    result = audit_polygon_inventory(frame, policy="make_valid")
    assert result.frame.RECORD_ID.tolist() == ["good", "crossed"]
    assert result.frame.OBSERVATION_YEAR.tolist() == [2009, 2010]
    assert result.frame.geometry.is_valid.all()
    assert (
        result.frame.loc[1, "GEOMETRY_PROCESSING"] == "made_valid_not_source_certified"
    )
    assert result.report["repaired_records"] == 1
    assert result.report["quarantined_records"] == 1
    repaired = result.report["records"][0]
    assert repaired["original_geometry_sha256"] != repaired["result_geometry_sha256"]
    assert result.report["records"][1]["discarded_component_types"] == ["LineString"]
    assert not result.report["source_completeness_established"]
    assert not result.report["absence_established"]


def test_quarantine_never_makes_an_implicit_repair():
    result = audit_polygon_inventory(fixture_frame(), policy="quarantine")
    assert result.frame.RECORD_ID.tolist() == ["good"]
    assert result.report["quarantined_records"] == 2
    assert result.report["repaired_records"] == 0


def test_identity_collisions_and_missing_crs_fail():
    frame = fixture_frame()
    frame.loc[1, "RECORD_ID"] = "good"
    with pytest.raises(ValueError, match="unique"):
        audit_polygon_inventory(frame, policy="make_valid")
    frame = fixture_frame().set_crs(None, allow_override=True)
    with pytest.raises(ValueError, match="explicit CRS"):
        audit_polygon_inventory(frame)


def test_mixed_inventory_keeps_non_areal_support_and_records_repairs():
    frame = fixture_frame()
    frame["SUPPORTS_AREA"] = [True, True, False]
    result = prepare_mixed_habitat_inventory(frame, policy="make_valid")
    assert result.frame.RECORD_ID.tolist() == ["good", "crossed", "line"]
    assert result.frame.SUPPORTS_AREA.tolist() == [True, True, False]
    assert (
        result.frame.GEOMETRY_PROCESSING.iloc[-1] == "valid_non_areal_source_geometry"
    )
    assert result.report["repaired_records"] == 1
    assert result.report["retained_non_areal_records"] == 1
    frame.loc[2, "RECORD_ID"] = "good"
    with pytest.raises(ValueError, match="unique"):
        prepare_mixed_habitat_inventory(frame)


def test_areal_claim_with_non_polygon_geometry_is_not_silently_preserved():
    frame = fixture_frame().iloc[[2]].copy()
    frame["SUPPORTS_AREA"] = True
    with pytest.raises(ValueError, match="line"):
        prepare_mixed_habitat_inventory(frame)
    result = prepare_mixed_habitat_inventory(frame, policy="quarantine")
    assert result.frame.empty
    assert result.report["quarantined_records"] == 1


def test_habitat_build_rejects_invalid_geometry_before_loading_spatial_support(
    monkeypatch,
):
    from seascape.utils import habitat_publication

    frame = fixture_frame()
    frame["AVAILABLE_YEAR"] = None
    monkeypatch.setattr(habitat_publication, "normalize_inventory", lambda value: value)
    with pytest.raises(ValueError, match="crossed"):
        habitat_publication.build_habitat_products(
            frame, SimpleNamespace(invalid_geometry_policy="reject"), "unused.yaml"
        )


def test_reef_build_rejects_invalid_geometry_before_loading_spatial_support(
    monkeypatch,
):
    from seascape.biogenic_habitat.reef import build

    monkeypatch.setattr(
        build,
        "load_habitat_surface_config",
        lambda *args: SimpleNamespace(invalid_geometry_policy="reject"),
    )
    monkeypatch.setattr(build, "_reef_processing", lambda *args: {})
    monkeypatch.setattr(build, "load_reef_inventory", lambda *args: fixture_frame())
    with pytest.raises(ValueError, match="crossed"):
        build.build_reef_habitat("unused.yaml")
