import hashlib
import json
import zipfile
from datetime import date

import h3
import numpy as np
import pyarrow as pa
import pytest
import rasterio
from rasterio.transform import from_origin

from seascape.biogenic_habitat.seagrass.native import (
    PREFIX,
    build_native_positive_footprints,
    combine_native_composites,
    native_cell_geometries,
    positive_pixel_metrics,
)
from seascape.domain_parquets import METADATA_KEY


def archive_fixture(tmp_path, values=None, *, duplicate=False):
    key = h3.latlng_to_cell(48.5, -122.6, 8)
    lat, lon = h3.cell_to_latlng(key)
    pixels = np.ones((17, 19), dtype="uint8") if values is None else values
    affine = from_origin(lon - 0.0019, lat + 0.0017, 0.0002, 0.0002)
    tif = tmp_path / "source.tif"
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        width=pixels.shape[1],
        height=pixels.shape[0],
        count=1,
        dtype="uint8",
        nodata=0,
        crs=4326,
        transform=affine,
        tiled=True,
        blockxsize=16,
        blockysize=16,
    ) as ds:
        ds.write(pixels, 1)
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(tif, "source.tif")
        if duplicate:
            z.write(tif, "overlap.tif")
    return key, archive, affine


def test_native_r8_reads_partial_edge_blocks_and_preserves_unavailable_support(
    tmp_path,
):
    key, path, _ = archive_fixture(tmp_path)
    absent = h3.latlng_to_cell(50.8, -125, 8)
    keys = sorted([*h3.grid_disk(key, 1), absent])
    result = build_native_positive_footprints(
        path, keys, resolution=8, composite_start_year=2019, composite_end_year=2020
    )
    table = result.table.to_pydict()
    assert sum(v or 0 for v in table[PREFIX + "POSITIVE_PIXEL_CENTER_COUNT"]) == 17 * 19
    index = table["H3_INDEX"].index(absent)
    assert table[PREFIX + "POSITIVE_FOOTPRINT_OVERLAP_M2"][index] is None
    assert table[PREFIX + "POSITIVE_PIXEL_CENTER_COUNT"][index] is None
    assert not table[PREFIX + "ALL_AVAILABLE_SOURCE_BLOCKS_COMPLETE"][index]
    assert result.report["completed_blocks"] == 4
    assert result.report["source_completeness"] == "partial"
    assert (
        hashlib.sha256(path.read_bytes()).hexdigest() == result.report["source_sha256"]
    )


@pytest.mark.parametrize("resolution", [6, 8])
def test_crossing_pixel_area_is_split_while_its_centre_has_one_native_key(resolution):
    key = h3.latlng_to_cell(48.5, -122.6, resolution)
    keys = sorted(h3.grid_disk(key, 1))
    geographic, projected = native_cell_geometries(keys)
    lon, lat = list(geographic[keys.index(key)].exterior.coords)[0]
    affine = from_origin(lon - 0.00005, lat + 0.00005, 0.0001, 0.0001)
    result, stats = positive_pixel_metrics(
        np.ones((1, 1), dtype="uint8"),
        affine,
        0,
        0,
        list(range(len(keys))),
        keys,
        projected,
        resolution=resolution,
    )
    assert sum(count for count, _ in result.values()) == 1
    assert sum(area > 0 for _, area in result.values()) >= 2
    assert sum(area for _, area in result.values()) == pytest.approx(
        stats["source_area_m2"], rel=1e-7
    )


def test_zero_background_is_not_observed_absence(tmp_path):
    key, path, _ = archive_fixture(tmp_path, np.zeros((4, 4), dtype="uint8"))
    result = build_native_positive_footprints(
        path, [key], resolution=8, composite_start_year=2023, composite_end_year=2024
    )
    row = result.table.to_pylist()[0]
    assert row[PREFIX + "POSITIVE_FOOTPRINT_OVERLAP_M2"] == 0
    assert (
        row[PREFIX + "NEGATIVE_OBSERVATION_STATUS"]
        == "unavailable_background_nodata_not_absence"
    )


@pytest.mark.parametrize("failure", ["class", "overlap", "checksum", "bound"])
def test_bad_sources_and_resource_bounds_fail(tmp_path, failure):
    values = np.full((17, 19), 2, dtype="uint8") if failure == "class" else None
    key, path, _ = archive_fixture(tmp_path, values, duplicate=failure == "overlap")
    kwargs = (
        {"expected_sha256": "bad"}
        if failure == "checksum"
        else {"max_blocks": 1}
        if failure == "bound"
        else {}
    )
    with pytest.raises(ValueError):
        build_native_positive_footprints(
            path,
            [key],
            resolution=8,
            composite_start_year=2023,
            composite_end_year=2024,
            **kwargs,
        )


def test_composites_preserve_intervals_nulls_context_and_native_support(tmp_path):
    key, path, _ = archive_fixture(tmp_path)
    absent = h3.latlng_to_cell(50.8, -125, 8)
    tables = [
        build_native_positive_footprints(
            path,
            [key, absent],
            resolution=8,
            composite_start_year=start,
            composite_end_year=end,
        ).table
        for start, end in [(2019, 2020), (2023, 2024)]
    ]
    result = combine_native_composites(tables)
    assert set(result["date"].to_pylist()) == {date(2019, 1, 1), date(2023, 1, 1)}
    assert set(result["source_period_end_exclusive"].to_pylist()) == {
        date(2021, 1, 1),
        date(2025, 1, 1),
    }
    amount = PREFIX + "POSITIVE_FOOTPRINT_OVERLAP_M2"
    assert {(r["H3_INDEX"], r["date"]): r[amount] for r in result.to_pylist()} == {
        (r["H3_INDEX"], label): r[amount]
        for table, label in zip(
            tables, (date(2019, 1, 1), date(2023, 1, 1)), strict=True
        )
        for r in table.to_pylist()
    }
    context = json.loads(result.schema.metadata[METADATA_KEY])
    assert set(context["composite_contexts"]) == {"2019-2020:r8", "2023-2024:r8"}
    assert not context["availability_known"]
    assert context["temporal_support"]["precision"] == "multi_year_composite"
    with pytest.raises(ValueError, match="Duplicate native composite"):
        combine_native_composites([tables[0], tables[0]])
    with pytest.raises(ValueError, match="Native support differs"):
        combine_native_composites([tables[0], tables[1].slice(0, 1)])
    broken = tables[0].set_column(
        tables[0].schema.get_field_index(PREFIX + "SOURCE_COMPOSITE_START_YEAR"),
        PREFIX + "SOURCE_COMPOSITE_START_YEAR",
        pa.array([2018, 2019]),
    )
    with pytest.raises(ValueError, match="exactly one composite"):
        combine_native_composites([broken])
