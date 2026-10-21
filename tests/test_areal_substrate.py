import geopandas as gpd
import h3
import pytest
from shapely.geometry import Polygon, box

from seascape.benthic_substrate.areal import build_areal_class_fractions


def fixture():
    key = h3.latlng_to_cell(49, -125, 8)
    other = next(iter(h3.grid_ring(key, 2)))
    support = gpd.GeoDataFrame(
        {"H3_INDEX": [key, other], "H3_RESOLUTION": [8, 8]},
        geometry=[
            Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(k)])
            for k in (key, other)
        ],
        crs=4326,
    ).to_crs(6933)
    geometry = support.geometry.iloc[0]
    xmin, ymin, xmax, ymax = geometry.bounds
    split = xmin + (xmax - xmin) * 0.75
    hard = geometry.intersection(box(xmin, ymin, split, ymax))
    soft = geometry.intersection(box(split, ymin, xmax, ymax))
    inventory = gpd.GeoDataFrame(
        {"RECORD_ID": ["a", "b", "c"], "CLASS_CODE": ["1", "1", "3"]},
        geometry=[hard, hard, soft],
        crs=6933,
    )
    return key, other, support, inventory


def test_common_areal_denominator_unions_duplicates_and_preserves_missing_coverage():
    key, other, support, inventory = fixture()
    result = (
        build_areal_class_fractions(
            inventory,
            support,
            classes={"1": "HARD", "3": "SOFT"},
            source_context={"rights": "synthetic"},
        )
        .to_pandas()
        .set_index("H3_INDEX")
    )
    row = result.loc[key]
    assert row.MAPPED_SUBSTRATE_AREA_M2 == pytest.approx(support.geometry.iloc[0].area)
    assert row.HARD_CLASS_AREA_M2 == pytest.approx(inventory.geometry.iloc[0].area)
    assert (
        row.HARD_CLASS_FRAC_OF_MAPPED_AREA + row.SOFT_CLASS_FRAC_OF_MAPPED_AREA
        == pytest.approx(1)
    )
    assert row.AREAL_CLASS_QC == "mapped_source_classes"
    assert result.loc[other, "AREAL_CLASS_QC"] == "no_mapped_source_coverage"
    assert (
        result.loc[other].MAPPED_SUBSTRATE_AREA_M2
        != result.loc[other].MAPPED_SUBSTRATE_AREA_M2
    )


def test_conflicting_classes_withhold_fractions_and_unknown_codes_reject():
    key, _other, support, inventory = fixture()
    inventory.loc[2, "geometry"] = inventory.geometry.iloc[0]
    table = build_areal_class_fractions(
        inventory,
        support,
        classes={"1": "HARD", "3": "SOFT"},
        source_context={"rights": "synthetic"},
    )
    row = next(r for r in table.to_pylist() if r["H3_INDEX"] == key)
    assert row["AREAL_CLASS_QC"] == "source_class_conflict"
    assert (
        row["HARD_CLASS_FRAC_OF_MAPPED_AREA"] is None
        and row["SOFT_CLASS_FRAC_OF_MAPPED_AREA"] is None
    )
    inventory.loc[0, "CLASS_CODE"] = "unmapped"
    with pytest.raises(ValueError, match="explicit mapping"):
        build_areal_class_fractions(
            inventory,
            support,
            classes={"1": "HARD", "3": "SOFT"},
            source_context={"rights": "synthetic"},
        )
