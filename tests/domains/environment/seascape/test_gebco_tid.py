from __future__ import annotations

import h3
import numpy as np
import pytest
import rasterio
import yaml
from rasterio.transform import from_origin

from seascape.seafloor_physiography.bathymetry.tid import aggregate_tid


def _raster(path, values, transform, *, nodata=None):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype=values.dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as target:
        target.write(values, 1)


def test_tid_counts_are_categorical_on_direct_depth_pixel_support(tmp_path):
    depth = tmp_path / "GEBCO_2026_depth.tif"
    tid = tmp_path / "GEBCO_2026_TID.tif"
    transform = from_origin(-123.001, 48.001, 0.001, 0.001)
    _raster(depth, np.full((2, 2), -20, dtype="int16"), transform)
    _raster(tid, np.array([[11, 40], [71, 255]], dtype="uint8"), transform, nodata=255)
    cell = h3.latlng_to_cell(48.0, -123.0, 6)
    other = (set(h3.grid_disk(cell, 1)) - {cell}).pop()

    table = aggregate_tid(
        depth_path=depth,
        tid_path=tid,
        cells=[cell, other],
        resolution=6,
        depth_release="2026",
        tid_release="2026",
    ).set_index("H3_INDEX")
    row = table.loc[cell]
    assert row["GEBCO_TID_DEPTH_PIXEL_COUNT"] == 4
    assert row["GEBCO_TID_KNOWN_PIXEL_COUNT"] == 3
    assert row["GEBCO_TID_COUNT_11"] == 1
    assert row["GEBCO_TID_COUNT_40"] == 1
    assert row["GEBCO_TID_COUNT_71"] == 1
    assert row["GEBCO_TID_DIRECT_FRAC_OF_KNOWN"] == pytest.approx(1 / 3)
    assert row["GEBCO_TID_STATUS"] == "partial_tid"
    assert table.loc[other, "GEBCO_TID_STATUS"] == "no_depth_pixels"
    assert np.isnan(table.loc[other, "GEBCO_TID_DIRECT_FRAC_OF_KNOWN"])


def test_tid_rejects_version_grid_and_unknown_codes(tmp_path):
    depth = tmp_path / "depth.tif"
    tid = tmp_path / "tid.tif"
    transform = from_origin(-123.001, 48.001, 0.001, 0.001)
    _raster(depth, np.full((2, 2), -20, dtype="int16"), transform)
    _raster(tid, np.full((2, 2), 11, dtype="uint8"), transform)
    kwargs = dict(depth_path=depth, tid_path=tid, cells=[], resolution=6)
    with pytest.raises(ValueError, match="releases must match"):
        aggregate_tid(**kwargs, depth_release="2026", tid_release="2025")
    _raster(
        tid,
        np.full((2, 2), 11, dtype="uint8"),
        from_origin(-123.002, 48.001, 0.001, 0.001),
    )
    with pytest.raises(ValueError, match="pixel grids must align"):
        aggregate_tid(**kwargs, depth_release="2026", tid_release="2026")
    _raster(tid, np.full((2, 2), 99, dtype="uint8"), transform)
    with pytest.raises(ValueError, match="unsupported marine codes"):
        aggregate_tid(
            **{**kwargs, "cells": [h3.latlng_to_cell(48.0, -123.0, 6)]},
            depth_release="2026",
            tid_release="2026",
        )


def test_optional_tid_is_transactionally_published_with_depth(tmp_path):
    import pandas as pd

    from seascape import demo
    from seascape.seafloor_physiography.bathymetry.pipeline import run_pipeline
    from seascape.utils.artifacts import load_manifest, validate_manifest

    result = demo.run_demo(tmp_path / "demo-workspace")
    config_path = result.workspace / "config/demo.yaml"
    config = yaml.safe_load(config_path.read_text())
    tid_path = result.workspace / "input/SYNTHETIC_TID.tif"
    tid_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(result.workspace / "input/synthetic_bathymetry.tif") as depth:
        profile = depth.profile.copy()
        for key in ("blockxsize", "blockysize", "tiled"):
            profile.pop(key, None)
        profile.update(dtype="uint8", nodata=255)
        with rasterio.open(tid_path, "w", **profile) as tid:
            tid.write(np.full(depth.shape, 11, dtype="uint8"), 1)
    config["bathymetry"]["source"].update(
        tid_raw_filename=tid_path.name,
        tid_release=config["bathymetry"]["source"]["release"],
    )
    config_path.write_text(yaml.safe_dump(config))
    with demo._environment(result.workspace):
        run_pipeline(config_path, skip_download=True, skip_map=True)
    tid_output = result.parquet_path.with_name("GEBCO_TID_RES_8.parquet")
    assert tid_output.exists()
    assert set(pd.read_parquet(tid_output)["GEBCO_TID_STATUS"]) == {
        "complete",
        "no_depth_pixels",
    }
    manifest = load_manifest(result.manifest_path)
    validate_manifest(manifest, project_root=result.workspace, verify_artifacts=True)
    assert any("GEBCO_TID_RES_8" in item["path"] for item in manifest["artifacts"])
    assert "synthetic categorical software fixture" == manifest["sources"][1][
        "evidence_type"
    ]
