import json

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import Point, box

from seascape.biogenic_habitat.bivalve.extents import ALL_TIME, build_bivalve_extents
from seascape.biogenic_habitat.seagrass.native import native_cell_geometries


def fixture():
    key = h3.latlng_to_cell(49, -125, 8)
    keys = [key, next(iter(h3.grid_ring(key, 3)))]
    geo, projected = native_cell_geometries(keys)
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [8, 8]}, geometry=geo, crs=4326
    )
    x0, y0, x1, y1 = projected[0].bounds
    a = projected[0].intersection(box(x0, y0, x0 + 0.7 * (x1 - x0), y1))
    b = projected[0].intersection(box(x0 + 0.3 * (x1 - x0), y0, x1, y1))
    records = gpd.GeoDataFrame(
        {
            "RECORD_ID": ["wa", "duplicate", "bc", "lease", "point"],
            "SOURCE_DATASET": ["WA_WDFW_MAPPED_OYSTER_BEDS"] * 2
            + ["BC_CRIMS_CLAM_BEDS"] * 3,
            "OBSERVATION_STATUS": ["present"] * 5,
            "OBSERVATION_YEAR": [None] * 5,
            "HABITAT_TYPE": ["mapped_bivalve_bed"] * 3
            + ["aquaculture_lease", "mapped_bivalve_bed"],
            "OBSERVED_VS_MODELED": ["observed"] * 5,
            "SURVEY_METHOD": ["legacy mapping"] * 5,
            "SPECIES": ["oyster", "oyster", "clam", "clam", "clam"],
            "SOURCE_PERIOD": ["unknown"] * 5,
            "SOURCE_MAP_DATE": ["1998-01-01"] * 5,
        },
        geometry=[a, a, b, projected[1], Point(projected[1].centroid)],
        crs=6933,
    )
    return cells, records, a, b


def test_union_dates_exclusions_and_positive_only_missingness():
    cells, records, a, b = fixture()
    result = build_bivalve_extents(records, cells, source_context={"rights": "fixture"})
    frame = result.tables.static.to_pandas().set_index("H3_INDEX")
    assert frame.loc[cells.H3_INDEX[0], ALL_TIME] == pytest.approx(
        a.union(b).area, rel=1e-6
    )
    assert (
        max(a.area, b.area) < frame.loc[cells.H3_INDEX[0], ALL_TIME] < a.area + b.area
    )
    assert pd.isna(frame.loc[cells.H3_INDEX[1], ALL_TIME])
    assert result.tables.dynamic is None
    assert frame.loc[cells.H3_INDEX[0], "OBSERVATION_YEARS_JSON"] == "[]"
    assert frame.loc[cells.H3_INDEX[0], "SOURCE_MAP_DATES_JSON"] == '["1998-01-01"]'
    metadata = json.loads(result.tables.static.schema.metadata[b"seascape_domain"])
    assert [k for k, v in metadata["fields"].items() if v["picker_visible"]] == [
        ALL_TIME
    ]
    assert metadata["fields"][ALL_TIME]["family"] == "Biogenic Habitats"
    assert metadata["dataset"] == "bivalve"
    assert result.report["excluded_input_records"] == 2


def test_rejects_invented_observation_dates_and_duplicate_ids():
    cells, records, _, _ = fixture()
    records.loc[0, "OBSERVATION_YEAR"] = 1998
    with pytest.raises(ValueError, match="observation year"):
        build_bivalve_extents(records, cells, source_context={"rights": "fixture"})
    records["OBSERVATION_YEAR"] = None
    records.loc[1, "RECORD_ID"] = "wa"
    with pytest.raises(ValueError, match="identities"):
        build_bivalve_extents(records, cells, source_context={"rights": "fixture"})


def test_resource_bounds_and_nonbed_only_inputs_fail():
    cells, records, _, _ = fixture()
    with pytest.raises(ValueError, match="budget"):
        build_bivalve_extents(
            records, cells, source_context={"rights": "fixture"}, max_records=1
        )
    records["HABITAT_TYPE"] = "growing_area"
    with pytest.raises(ValueError, match="positive polygon"):
        build_bivalve_extents(records, cells, source_context={"rights": "fixture"})
