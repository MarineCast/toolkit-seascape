import json

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from seascape.biogenic_habitat.kelp.extents import ALL_TIME, ANNUAL, build_kelp_extents


def fixture():
    key = h3.latlng_to_cell(49, -125, 8)
    keys = [key, next(iter(h3.grid_ring(key, 2))), next(iter(h3.grid_ring(key, 3)))]
    full = gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [8] * 3},
        geometry=[
            Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(c)]) for c in keys
        ],
        crs=4326,
    ).to_crs(6933)
    geom = full.geometry.iloc[0]
    x0, y0, x1, y1 = geom.bounds
    left = geom.intersection(box(x0, y0, x0 + 0.7 * (x1 - x0), y1))
    right = geom.intersection(box(x0 + 0.3 * (x1 - x0), y0, x1, y1))
    records = gpd.GeoDataFrame(
        {
            "RECORD_ID": ["a", "b", "c", "bc", "negative"],
            "SOURCE_DATASET": [
                "WA_DNR_FLOATING_KELP_2020",
                "WA_DNR_FLOATING_KELP_2020",
                "WA_DNR_FLOATING_KELP_2021",
                "BC_CRIMS_KELP_BEDS",
                "BC_CRIMS_KELP_BEDS",
            ],
            "OBSERVATION_YEAR": pd.array([2020, 2020, 2021, None, None], dtype="Int16"),
            "OBSERVATION_STATUS": ["present"] * 4 + ["absent"],
            "HABITAT_TYPE": ["floating_kelp"] * 5,
            "OBSERVED_VS_MODELED": ["observed"] * 5,
            "GEOMETRY_PROCESSING": ["source_geometry_valid"] * 5,
        },
        geometry=[left, left, right, full.geometry.iloc[1], full.geometry.iloc[2]],
        crs=6933,
    )
    return full, records, left, right


def test_all_time_unions_years_sources_and_overlaps_without_inferred_absence():
    full, records, left, right = fixture()
    result = build_kelp_extents(records, full, source_context={"rights": "fixture"})
    static = result.tables.static.to_pandas().set_index("H3_INDEX")
    annual = result.tables.dynamic.to_pandas()
    key, bc_key, unknown = full.H3_INDEX
    assert static.loc[key, ALL_TIME] == pytest.approx(left.union(right).area)
    assert static.loc[key, ALL_TIME] < left.area + right.area
    assert static.loc[bc_key, ALL_TIME] == pytest.approx(full.geometry.iloc[1].area)
    assert static.loc[bc_key, "UNDATED_EVIDENCE_INCLUDED"]
    assert pd.isna(static.loc[unknown, ALL_TIME])
    assert static.loc[unknown, "QC"] == "no_positive_evidence_unknown_absence"
    assert annual.loc[
        annual.H3_INDEX.eq(key) & annual.date.map(lambda x: x.year).eq(2020), ANNUAL
    ].iloc[0] == pytest.approx(left.area)
    assert annual.loc[annual.H3_INDEX.eq(bc_key), ANNUAL].isna().all()
    assert result.report["actual_annual_years"] == [2020, 2021]
    assert result.report["undated_records_included"] == 1
    context = json.loads(result.tables.static.schema.metadata[b"seascape_domain"])
    assert {
        name for name, info in context["fields"].items() if info["picker_visible"]
    } == {ALL_TIME}


def test_explicit_date_range_excludes_unknown_dates_and_reports_native_years():
    full, records, left, right = fixture()
    result = build_kelp_extents(
        records,
        full,
        source_context={"rights": "fixture"},
        start_year=2021,
        end_year=2021,
    )
    assert result.report["actual_annual_years"] == [2021]
    assert result.report["undated_records_included"] == 0
    assert result.tables.static[ALL_TIME].null_count == 2
    assert result.tables.static.to_pandas().set_index("H3_INDEX").loc[
        full.H3_INDEX.iloc[0], ALL_TIME
    ] == pytest.approx(right.area)


def test_line_evidence_and_modeled_habitat_never_add_extent():
    full, records, _, _ = fixture()
    line = records.iloc[[0]].copy()
    line.RECORD_ID = "line"
    line.SOURCE_DATASET = "WA_DNR_SHOREZONE_FLOATING_KELP"
    line.geometry = line.geometry.boundary
    mixed = gpd.GeoDataFrame(
        pd.concat([records, line], ignore_index=True), crs=records.crs
    )
    result = build_kelp_extents(mixed, full, source_context={"rights": "fixture"})
    assert "WA_DNR_SHOREZONE_FLOATING_KELP" not in result.report["source_datasets"]
    records.OBSERVED_VS_MODELED = "modeled"
    with pytest.raises(ValueError, match="nonempty valid audited"):
        build_kelp_extents(records, full, source_context={"rights": "fixture"})


def test_invalid_identity_dates_geometry_and_resource_bounds_fail():
    full, records, _, _ = fixture()
    duplicate = pd.concat([records, records.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique"):
        build_kelp_extents(duplicate, full, source_context={"rights": "fixture"})
    with pytest.raises(ValueError, match="cell-year budget"):
        build_kelp_extents(
            records, full, source_context={"rights": "fixture"}, max_cell_years=1
        )
    with pytest.raises(ValueError, match="reversed"):
        build_kelp_extents(
            records,
            full,
            source_context={"rights": "fixture"},
            start_year=2022,
            end_year=2020,
        )


def test_explicit_replay_publishes_one_family_with_common_manifest(tmp_path):
    import pyarrow.parquet as pq
    from shapely.geometry import Polygon

    from seascape.biogenic_habitat.kelp.build import build_kelp_habitat
    from seascape.utils.artifacts import REQUIRED_MANIFEST_KEYS, load_manifest

    full, records, _, _ = fixture()
    parents = sorted({h3.cell_to_parent(c, 6) for c in full.H3_INDEX})
    parent = gpd.GeoDataFrame(
        {"H3_INDEX": parents, "H3_RESOLUTION": [6] * len(parents)},
        geometry=[
            Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(c)])
            for c in parents
        ],
        crs=4326,
    )
    records["GEOMETRY_PROCESSING"] = "source_geometry_valid"
    paths = build_kelp_habitat(
        "/missing/config.yaml",
        inventory=records,
        full_cells={6: parent, 8: full},
        output=tmp_path / "kelp",
        source_context={"rights": "fixture"},
    )
    assert {p.name for p in paths} == {
        "KELP_RES_6.parquet",
        "KELP_RES_8.parquet",
        "KELP_ANNUAL_RES_6.parquet",
        "KELP_ANNUAL_RES_8.parquet",
        "KELP_SOURCE_INVENTORY.parquet",
        "kelp_habitat_manifest.json",
    }
    manifest = load_manifest(tmp_path / "kelp/kelp_habitat_manifest.json")
    assert REQUIRED_MANIFEST_KEYS <= manifest.keys()
    assert manifest["metadata"]["scientific_features"] == [
        "Annual Kelp Extent",
        "Kelp Extent (All Time)",
    ]
    assert pq.read_table(tmp_path / "kelp/KELP_RES_8.parquet")[ALL_TIME].null_count == 1
