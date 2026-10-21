import geopandas as gpd
import h3
import pytest
from shapely.geometry import Polygon, box

from seascape.biogenic_habitat.kelp.native import build_native_annual_footprints


def native(keys):
    return gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [h3.get_resolution(key) for key in keys]},
        geometry=[
            Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(key)])
            for key in keys
        ],
        crs=4326,
    ).to_crs(6933)


def test_annual_polygon_union_keeps_unknown_cells_and_missing_years():
    key = h3.latlng_to_cell(49, -125, 8)
    neighbor = next(cell for cell in h3.grid_ring(key, 2))
    full = native([key, neighbor])
    wet = full.copy()
    geometry = full.geometry.iloc[0]
    xmin, ymin, xmax, ymax = geometry.bounds
    positive = geometry.intersection(box(xmin, ymin, (xmin + xmax) / 2, ymax))
    wet.loc[0, "geometry"] = geometry.intersection(
        box(xmin + (xmax - xmin) / 4, ymin, xmax, ymax)
    )
    records = gpd.GeoDataFrame(
        {
            "RECORD_ID": ["a", "b"],
            "SOURCE_DATASET": ["synthetic"] * 2,
            "OBSERVATION_YEAR": [2020] * 2,
            "OBSERVATION_STATUS": ["present"] * 2,
        },
        geometry=[positive, positive],
        crs=6933,
    )
    result = build_native_annual_footprints(
        records,
        full,
        wet,
        start_year=2020,
        end_year=2021,
        source_context={"rights": "synthetic"},
    )
    table = result.table.to_pandas().set_index("H3_INDEX")
    assert result.report["missing_requested_years"] == [2021]
    assert table.loc[key, "MAPPED_BED_EXTENT_IN_FULL_H3_M2"] == pytest.approx(
        positive.area
    )
    assert table.loc[key, "MAPPED_BED_EXTENT_IN_STATIC_WATER_M2"] == pytest.approx(
        positive.intersection(wet.geometry.iloc[0]).area
    )
    assert table.loc[neighbor, "QC"] == "no_positive_mapped_evidence"
    assert result.table["ANNUAL_SURVEY_ABSENCE"].null_count == 2
    assert result.table["MAPPED_BED_EXTENT_IN_FULL_H3_M2"].null_count == 1
    import json
    from datetime import date

    from seascape.domain_parquets import METADATA_KEY
    from seascape.historical import HistoricalRequest, _select_dynamic

    context = json.loads(result.table.schema.metadata[METADATA_KEY])
    request = HistoricalRequest(
        date(2020, 6, 1), date(2020, 7, 1), "fixture", "synthetic", "synthetic"
    )
    selected, periods, precision = _select_dynamic(result.table, context, request)
    assert (
        selected.num_rows == 2
        and precision == "year"
        and periods == [(date(2020, 1, 1), date(2021, 1, 1))]
    )
    parent = native([h3.cell_to_parent(key, 6)])
    coarse = build_native_annual_footprints(
        records,
        parent,
        parent,
        start_year=2020,
        end_year=2020,
        source_context={"rights": "synthetic"},
    )
    assert coarse.table["H3_RESOLUTION"].to_pylist() == [6]
    assert coarse.table["MAPPED_BED_EXTENT_IN_FULL_H3_M2"][0].as_py() == pytest.approx(
        positive.intersection(parent.geometry.iloc[0]).area
    )
    with pytest.raises(ValueError, match="cell-year budget"):
        build_native_annual_footprints(
            records,
            full,
            wet,
            start_year=2020,
            end_year=2021,
            source_context={"rights": "synthetic"},
            max_cell_years=1,
        )


def test_annual_absence_and_fractional_years_are_rejected():
    full = native([h3.latlng_to_cell(49, -125, 8)])
    records = gpd.GeoDataFrame(
        {
            "RECORD_ID": ["a"],
            "SOURCE_DATASET": ["synthetic"],
            "OBSERVATION_YEAR": [2020.5],
            "OBSERVATION_STATUS": ["present"],
        },
        geometry=full.geometry.to_numpy(),
        crs=6933,
    )
    with pytest.raises(ValueError, match="integer observation years"):
        build_native_annual_footprints(
            records,
            full,
            full,
            start_year=2020,
            end_year=2021,
            source_context={"rights": "synthetic"},
        )
    records.OBSERVATION_YEAR = 2020
    records["OBSERVATION_STATUS"] = "absent"
    with pytest.raises(ValueError, match="only explicit positive"):
        build_native_annual_footprints(
            records,
            full,
            full,
            start_year=2020,
            end_year=2021,
            source_context={"rights": "synthetic"},
        )
