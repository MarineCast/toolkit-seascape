import h3
import numpy as np
import pytest
from affine import Affine
from shapely.geometry import box

from seascape.regional.seagrass import (
    TO_AREA,
    cell_geometries,
    positive_metrics,
    select_blocks,
)


def test_selector_full_cell_edges_and_no_duplicate_blocks():
    headers = [
        {
            "bounds_wgs84": [0, 0, 4, 4],
            "resolution": [1, 1],
            "block_shapes": [[1, 1]],
            "shape": [4, 4],
        }
    ]
    cells = [box(0.2, 0.2, 1.2, 1.2), box(1.2, 0.2, 2.2, 1.2)]
    got = select_blocks(headers, cells)
    brute = []
    for r in range(4):
        for c in range(4):
            ids = [
                i
                for i, g in enumerate(cells)
                if g.intersects(box(c, 3 - r, c + 1, 4 - r))
            ]
            if ids:
                brute.append([0, r, c, *ids])
    assert got == brute
    assert len({tuple(x[:3]) for x in got}) == len(got)
    assert any(x[1] == 3 for x in got)  # full lower cell edge retained


def test_native_footprint_area_partition_and_center_counts():
    key = h3.latlng_to_cell(48.5, -122.6, 6)
    keys = sorted(h3.grid_disk(key, 1))
    geo, projected = cell_geometries(keys)
    lat, lon = h3.cell_to_latlng(key)
    a = Affine(0.002, 0, lon - 0.004, 0, -0.002, lat + 0.004)
    raw = np.ones((4, 4), dtype="uint8")
    metrics, summary = positive_metrics(
        raw, a, 0, 0, list(range(len(keys))), keys, projected
    )
    assert sum(v["positive_pixel_center_count"] for v in metrics.values()) == 16
    assert sum(
        v["modeled_positive_footprint_overlap_m2"] for v in metrics.values()
    ) == pytest.approx(summary["source_positive_area_m2"], rel=1e-9)
    x0, y0 = TO_AREA.transform(lon - 0.004, lat - 0.004)
    x1, y1 = TO_AREA.transform(lon + 0.004, lat + 0.004)
    assert summary["source_positive_area_m2"] == pytest.approx(
        (x1 - x0) * (y1 - y0), rel=1e-9
    )
    zero, stats = positive_metrics(
        np.zeros((4, 4), dtype="uint8"),
        a,
        0,
        0,
        list(range(len(keys))),
        keys,
        projected,
    )
    assert not zero and stats["positive_pixels"] == 0
    raw[0, 0] = 2
    with pytest.raises(ValueError, match="class"):
        positive_metrics(raw, a, 0, 0, [0], keys, projected)


def test_boundary_crossing_pixel_is_split_not_assigned_whole_area_to_center():
    key = h3.latlng_to_cell(48.5, -122.6, 6)
    keys = sorted(h3.grid_disk(key, 1))
    geo, proj = cell_geometries(keys)
    lon, lat = list(geo[keys.index(key)].exterior.coords)[0]
    a = Affine(0.002, 0, lon - 0.001, 0, -0.002, lat + 0.001)
    metrics, stats = positive_metrics(
        np.ones((1, 1), dtype="uint8"), a, 0, 0, list(range(7)), keys, proj
    )
    assert sum(v["positive_pixel_center_count"] for v in metrics.values()) == 1
    assert (
        sum(v["modeled_positive_footprint_overlap_m2"] > 0 for v in metrics.values())
        >= 2
    )
    assert stats["retained_overlap_area_m2"] == pytest.approx(
        stats["source_positive_area_m2"], rel=1e-7
    )
    _, fine = cell_geometries(keys, 0.0001)
    fine_metrics, _ = positive_metrics(
        np.ones((1, 1), dtype="uint8"), a, 0, 0, list(range(7)), keys, fine
    )
    for i, v in metrics.items():
        assert v["modeled_positive_footprint_overlap_m2"] == pytest.approx(
            fine_metrics[i]["modeled_positive_footprint_overlap_m2"], abs=0.1
        )


def test_adjacent_source_tiles_do_not_duplicate_pixel_footprints():
    key = h3.latlng_to_cell(48.5, -122.6, 6)
    keys = sorted(h3.grid_disk(key, 1))
    geo, proj = cell_geometries(keys)
    lat, lon = h3.cell_to_latlng(key)
    step = 0.00008983152841195215
    a = Affine(step, 0, lon - step, 0, -step, lat + step / 2)
    b = Affine(step, 0, lon, 0, -step, lat + step / 2)
    _, left = positive_metrics(
        np.ones((1, 1), dtype="uint8"), a, 0, 0, list(range(7)), keys, proj
    )
    _, right = positive_metrics(
        np.ones((1, 1), dtype="uint8"), b, 0, 0, list(range(7)), keys, proj
    )
    _, together = positive_metrics(
        np.ones((1, 2), dtype="uint8"), a, 0, 0, list(range(7)), keys, proj
    )
    assert left["retained_overlap_area_m2"] + right[
        "retained_overlap_area_m2"
    ] == pytest.approx(together["retained_overlap_area_m2"], abs=1e-6)
