import json

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import box

from seascape.biogenic_habitat.seagrass.extents import (
    ALL_TIME,
    build_seagrass_extents,
)
from seascape.biogenic_habitat.seagrass.native import native_cell_geometries


def fixture():
    key = h3.latlng_to_cell(49, -125, 8)
    keys = [key, next(iter(h3.grid_ring(key, 2))), next(iter(h3.grid_ring(key, 3)))]
    geo, projected = native_cell_geometries(keys)
    full = gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [8] * 3}, geometry=geo, crs=4326
    )
    g = projected[0]
    x0, y0, x1, y1 = g.bounds
    left = g.intersection(box(x0, y0, x0 + 0.7 * (x1 - x0), y1))
    right = g.intersection(box(x0 + 0.3 * (x1 - x0), y0, x1, y1))
    records = gpd.GeoDataFrame(
        {
            "RECORD_ID": [
                "a",
                "duplicate_geometry",
                "b",
                "bc",
                "satellite",
                "negative",
            ],
            "SOURCE_DATASET": ["WA_DNR_INTERTIDAL_EELGRASS_1995"] * 2
            + [
                "WA_DNR_INTERTIDAL_EELGRASS_1996",
                "BC_CRIMS_EELGRASS",
                "GLOBAL_SENTINEL2_SEAGRASS_2023_2024",
                "BC_CRIMS_EELGRASS",
            ],
            "OBSERVATION_YEAR": pd.array(
                [1995, 1995, 1996, None, None, None], dtype="Int16"
            ),
            "HABITAT_TYPE": ["eelgrass"] * 4 + ["seagrass", "eelgrass"],
            "OBSERVATION_STATUS": ["present"] * 5 + ["absent"],
            "OBSERVED_VS_MODELED": ["observed"] * 4 + ["modeled", "observed"],
            "SURVEY_METHOD": ["mapped_inventory"] * 4 + ["satellite_model", "legacy"],
            "SPECIES": ["eelgrass unspecified"] * 4 + ["generic seagrass", "eelgrass"],
            "SOURCE_PERIOD": [
                "1995",
                "1995",
                "1996",
                "unknown",
                "2023-2024 composite",
                "unknown",
            ],
            "SOURCE_MAP_DATE": [None, None, None, "1998-01-01Z", None, None],
            "GEOMETRY_PROCESSING": ["source_geometry_valid"] * 6,
        },
        geometry=[left, left, right, projected[1].buffer(-1), left, projected[2]],
        crs=6933,
    )
    return full, records, left, right


def test_geometric_union_overlaps_sources_and_years_not_sum_or_max():
    full, records, left, right = fixture()
    r = build_seagrass_extents(records, full, source_context={"rights": "fixture"})
    static = r.tables.static.to_pandas().set_index("H3_INDEX")
    assert r.tables.dynamic is None
    k, bc, unknown = full.H3_INDEX
    assert static.loc[k, ALL_TIME] == pytest.approx(left.union(right).area, rel=1e-6)
    assert max(left.area, right.area) < static.loc[k, ALL_TIME] < left.area + right.area
    assert pd.isna(static.loc[unknown, ALL_TIME])
    assert static.loc[unknown, "QC"] == "no_positive_evidence_unknown_absence"
    assert json.loads(static.loc[k, "OBSERVATION_YEARS_JSON"]) == [1995, 1996]
    assert "date" not in r.tables.static.column_names
    assert json.loads(static.loc[k, "OBSERVED_VS_MODELED_JSON"]) == [
        "modeled",
        "observed",
    ]
    assert json.loads(static.loc[bc, "SOURCE_MAP_DATES_JSON"]) == ["1998-01-01Z"]
    fields = json.loads(r.tables.static.schema.metadata[b"seascape_domain"])["fields"]
    assert {key for key, value in fields.items() if value["picker_visible"]} == {
        ALL_TIME
    }


def test_composite_endpoint_or_map_date_never_becomes_annual_year():
    full, records, _, _ = fixture()
    records.loc[
        records.SOURCE_DATASET.str.startswith("GLOBAL_"), "OBSERVATION_YEAR"
    ] = 2024
    with pytest.raises(ValueError, match="masquerade"):
        build_seagrass_extents(records, full, source_context={"rights": "fixture"})
    records.loc[
        records.SOURCE_DATASET.str.startswith("GLOBAL_"), "OBSERVATION_YEAR"
    ] = None
    records.loc[records.SOURCE_DATASET.eq("BC_CRIMS_EELGRASS"), "OBSERVATION_YEAR"] = (
        1998
    )
    with pytest.raises(ValueError, match="masquerade"):
        build_seagrass_extents(records, full, source_context={"rights": "fixture"})


def test_composite_only_preserves_period_without_fabricated_observation_year():
    full, records, _, _ = fixture()
    r = build_seagrass_extents(
        records.loc[records.SOURCE_DATASET.str.startswith("GLOBAL_")],
        full,
        source_context={"rights": "fixture"},
    )
    assert r.tables.dynamic is None
    assert r.report["all_time_dated_years"] == []


def test_kelps_lines_points_unapproved_models_and_absence_are_excluded():
    full, records, _, _ = fixture()
    extra = records.iloc[[0, 0, 0, 0]].copy()
    extra.RECORD_ID = ["kelp", "point", "line", "model_site"]
    extra.HABITAT_TYPE = ["kelp", "seagrass", "seagrass", "seagrass"]
    g = full.to_crs(6933).geometry.iloc[2]
    extra.geometry = [g, g.centroid, g.boundary, g]
    extra.SOURCE_DATASET = [
        "WA_DNR_FLOATING_KELP_1995",
        "WA_DNR_MONITORING_SITES",
        "SHOREZONE",
        "HABITAT_SUITABILITY_MODEL",
    ]
    mixed = gpd.GeoDataFrame(
        pd.concat([records.to_crs(4326), extra.to_crs(4326)], ignore_index=True),
        crs=4326,
    )
    r = build_seagrass_extents(mixed, full, source_context={"rights": "fixture"})
    assert r.report["excluded_input_records"] == 5
    assert r.tables.static[ALL_TIME].null_count == 1


def test_invalid_identity_survey_year_and_budget_fail():
    full, records, _, _ = fixture()
    with pytest.raises(ValueError, match="unique"):
        build_seagrass_extents(
            pd.concat([records, records.iloc[[0]]]),
            full,
            source_context={"rights": "fixture"},
        )
    with pytest.raises(ValueError, match="budget"):
        build_seagrass_extents(
            records, full, source_context={"rights": "fixture"}, max_pairs=1
        )
    records.loc[0, "OBSERVATION_YEAR"] = 1996
    with pytest.raises(ValueError, match="survey year"):
        build_seagrass_extents(records, full, source_context={"rights": "fixture"})


def test_family_publisher_manifest_and_old_confidence_retired(tmp_path):
    from seascape.biogenic_habitat.seagrass.build import build_seagrass_habitat
    from seascape.utils.artifacts import REQUIRED_MANIFEST_KEYS, load_manifest

    full, records, _, _ = fixture()
    parents = sorted({h3.cell_to_parent(k, 6) for k in full.H3_INDEX})
    geographic, _ = native_cell_geometries(parents)
    coarse = gpd.GeoDataFrame(
        {"H3_INDEX": parents, "H3_RESOLUTION": [6] * len(parents)},
        geometry=geographic,
        crs=4326,
    )
    out = tmp_path / "seagrass"
    out.mkdir()
    (out / "SEAGRASS_CONFIDENCE_RES_8.parquet").write_bytes(b"obsolete")
    (out / "SEAGRASS_ANNUAL_RES_8.parquet").write_bytes(b"retired annual")
    paths = build_seagrass_habitat(
        "/missing/config.yaml",
        inventory=records,
        full_cells={6: coarse, 8: full},
        output=out,
        source_context={"rights": "fixture"},
    )
    assert len(paths) == 4
    assert not (out / "SEAGRASS_CONFIDENCE_RES_8.parquet").exists()
    m = load_manifest(out / "seagrass_habitat_manifest.json")
    assert REQUIRED_MANIFEST_KEYS <= m.keys()
    assert m["metadata"]["scientific_features"] == ["Seagrass Extent (All Time)"]
    assert not list(out.glob("*ANNUAL*"))


def test_raster_polygons_preserve_partial_blocks_and_positive_pixel_union(tmp_path):
    import zipfile

    import rasterio
    from rasterio.transform import from_origin

    def archive_fixture(directory):
        key = h3.latlng_to_cell(48.5, -122.6, 8)
        lat, lon = h3.cell_to_latlng(key)
        affine = from_origin(lon - 0.0019, lat + 0.0017, 0.0002, 0.0002)
        tif = directory / "pixels.tif"
        with rasterio.open(
            tif,
            "w",
            driver="GTiff",
            width=19,
            height=17,
            count=1,
            dtype="uint8",
            nodata=0,
            crs=4326,
            transform=affine,
            tiled=True,
            blockxsize=16,
            blockysize=16,
        ) as ds:
            ds.write(np.ones((17, 19), dtype="uint8"), 1)
        archive = directory / "source.zip"
        with zipfile.ZipFile(archive, "w") as out:
            out.write(tif, "pixels.tif")
        return key, archive, affine

    from seascape.biogenic_habitat.seagrass.native import (
        build_native_positive_footprints,
    )
    from seascape.biogenic_habitat.seagrass.sources import raster_inventory

    key, archive, _ = archive_fixture(tmp_path)
    keys = sorted(h3.grid_disk(key, 1))
    geo, _ = native_cell_geometries(keys)
    west, south, east, north = shapely.total_bounds(geo)
    records = raster_inventory(
        archive,
        source="GLOBAL_SENTINEL2_SEAGRASS_2023_2024",
        period=(2023, 2024),
        bbox=dict(min_lon=west, min_lat=south, max_lon=east, max_lat=north),
    )
    full = gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [8] * len(keys)}, geometry=geo, crs=4326
    )
    actual = (
        build_seagrass_extents(records, full, source_context={"rights": "fixture"})
        .tables.static.to_pandas()
        .set_index("H3_INDEX")[ALL_TIME]
    )
    native = (
        build_native_positive_footprints(
            archive,
            keys,
            resolution=8,
            composite_start_year=2023,
            composite_end_year=2024,
        )
        .table.to_pandas()
        .set_index("H3_INDEX")["SEAGRASS_MODEL__POSITIVE_FOOTPRINT_OVERLAP_M2"]
    )
    assert np.allclose(
        actual.fillna(0).sort_index(),
        native.fillna(0).sort_index(),
        rtol=1e-7,
        atol=1e-4,
    )
    assert records.OBSERVATION_YEAR.isna().all()
    with pytest.raises(ValueError, match="block budget"):
        raster_inventory(
            archive,
            source="fixture",
            period=(2023, 2024),
            bbox=dict(min_lon=west, min_lat=south, max_lon=east, max_lat=north),
            max_blocks=1,
        )


def test_legacy_composite_never_reinterprets_extent_on_a_different_grid():
    from seascape.biogenic_habitat.composite.build import _unavailable_legacy_extent

    source = pd.DataFrame(
        {"H3_INDEX": ["historic-only"], "H3_RESOLUTION": [8], ALL_TIME: [12345.0]}
    )
    target = pd.DataFrame(
        {"H3_INDEX": ["current-grid-a", "current-grid-b"], "H3_RESOLUTION": [8, 8]}
    )
    values, confidence = _unavailable_legacy_extent(source, target, "SEAGRASS", 8)
    assert values.H3_INDEX.tolist() == target.H3_INDEX.tolist()
    assert values.SEAGRASS_FRAC.isna().all()
    assert values.SEAGRASS_DISTANCE_M.isna().all()
    assert confidence.SEAGRASS_UNMAPPED_AREA.all()
    assert confidence.SEAGRASS_SURVEYED_AREA_FRAC.isna().all()
    assert ALL_TIME not in values
    with pytest.raises(ValueError, match="unique"):
        _unavailable_legacy_extent(pd.concat([source, source]), target, "SEAGRASS", 8)
