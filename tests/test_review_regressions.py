"""Behavioral regressions for the architecture review's scientific boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from seascape.biogenic_habitat.composite.build import _build_resolution
from seascape.cli import initialize_workspace
from seascape.core.geo.crs import require_metric_crs
from seascape.seafloor_physiography.geomorphometry.build import (
    _native_raster_slope_summary,
    load_geomorphometry_config,
)
from seascape.workflow import (
    DomainBuildStage,
    _candidate_environment,
    _prepare_candidate_config,
    run_domain_layer_build,
)


def _composite_inputs(tmp_path):
    keys = {"H3_INDEX": ["A", "B"], "H3_RESOLUTION": [8, 8]}
    features = {
        "seagrass": pd.DataFrame(
            keys
            | {
                "SEAGRASS_FRAC": [1.0, 0.0],
                "SEAGRASS_MAX_LOCAL_FRAC": [1.0, 0.0],
                "SEAGRASS_DISTANCE_M": [0.0, 1.0],
                "SEAGRASS_AREA_WITHIN_5KM_M2": [1.0, 0.0],
                "SEAGRASS_EDGE_DENSITY_M_PER_KM2": [1.0, 0.0],
            }
        ),
        "kelp": pd.DataFrame(
            keys
            | {
                column: [0.0, 0.0]
                for column in (
                    "KELP_FRAC",
                    "KELP_MAX_LOCAL_FRAC",
                    "KELP_DISTANCE_M",
                    "KELP_AREA_WITHIN_5KM_M2",
                    "KELP_PERSISTENCE_RATIO",
                    "KELP_EDGE_DENSITY_M_PER_KM2",
                )
            }
        ),
        "reef": pd.DataFrame(
            keys
            | {
                column: [0.0, 0.0]
                for column in (
                    "ROCKY_REEF_FRAC",
                    "ROCKY_REEF_DISTANCE_M",
                    "ROCKY_REEF_AREA_WITHIN_5KM_M2",
                    "BIOGENIC_REEF_FRAC",
                )
            }
        ),
    }
    configs = {}
    paths = []
    for name, prefixes in {
        "seagrass": ["SEAGRASS"],
        "kelp": ["KELP"],
        "reef": ["ROCKY_REEF", "BIOGENIC_REEF", "DEEP_CORAL_SPONGE"],
        "substrate": ["SUBSTRATE"],
    }.items():
        confidence = pd.DataFrame(keys)
        for prefix in prefixes:
            confidence[prefix + "_CONFIDENCE"] = [1, 1]
            confidence[prefix + "_UNMAPPED_AREA"] = [False, False]
            confidence[prefix + "_SURVEYED_AREA_FRAC"] = [1.0, 1.0]
        if name == "seagrass":
            confidence["SEAGRASS_UNMAPPED_AREA"] = [False, True]
        feature_path = tmp_path / f"{name}.parquet"
        confidence_path = tmp_path / f"{name}_confidence.parquet"
        confidence.to_parquet(confidence_path)
        paths.append(confidence_path)
        if name in features:
            features[name].to_parquet(feature_path)
            paths.append(feature_path)
        configs[name] = SimpleNamespace(
            feature_path=lambda resolution, path=feature_path: path,
            confidence_path=lambda resolution, path=confidence_path: path,
        )
    return configs, paths


def test_composite_is_invariant_to_each_input_order(tmp_path):
    configs, paths = _composite_inputs(tmp_path)
    expected = _build_resolution(configs, 8)
    assert expected[0]["BENTHIC_HABITAT_RICHNESS"].iloc[0] == 1
    assert pd.isna(expected[0]["BENTHIC_HABITAT_RICHNESS"].iloc[1])
    for path in paths:
        frame = pd.read_parquet(path)
        frame.iloc[::-1].reset_index(drop=True).to_parquet(path)
        actual = _build_resolution(configs, 8)
        for left, right in zip(expected, actual, strict=True):
            pd.testing.assert_frame_equal(
                left.sort_values("H3_INDEX").reset_index(drop=True),
                right.sort_values("H3_INDEX").reset_index(drop=True),
            )
        frame.to_parquet(path)


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "null", "resolution"])
def test_composite_rejects_incompatible_identity(tmp_path, invalid):
    configs, paths = _composite_inputs(tmp_path)
    path = paths[0]
    table = pd.read_parquet(path)
    if invalid == "missing":
        table = table.iloc[:1]
    elif invalid == "duplicate":
        table = pd.concat([table, table.iloc[:1]])
    elif invalid == "null":
        table.loc[0, "H3_INDEX"] = None
    else:
        table.loc[0, "H3_RESOLUTION"] = 6
    table.to_parquet(path)
    with pytest.raises(ValueError, match="support|keys"):
        _build_resolution(configs, 8)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    initialize_workspace(tmp_path)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    "crs", ["EPSG:4326", "+proj=utm +zone=10 +datum=WGS84 +units=ft +type=crs"]
)
def test_scientific_configuration_rejects_nonmetric_crs(workspace, crs):
    with pytest.raises(ValueError, match="meters"):
        require_metric_crs(crs)
    path = workspace / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["geomorphometry"]["processing"]["projected_crs"] = crs
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="meters"):
        load_geomorphometry_config(path)
    assert require_metric_crs("EPSG:32610").is_projected


@pytest.mark.parametrize("sign", [None, "negative_elevation"])
def test_terrain_rejects_unsupported_depth_sign_before_io(workspace, sign):
    from seascape.seafloor_physiography.geomorphic_units.build import (
        load_geomorphic_units_config,
    )
    from seascape.coastal_configuration.waterbody_morphometry.build import (
        load_waterbody_morphometry_config,
    )

    path = workspace / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["bathymetry"]["processing"]["bathymetry_sign"] = sign
    path.write_text(yaml.safe_dump(raw))
    for loader in (
        load_geomorphometry_config,
        load_geomorphic_units_config,
        load_waterbody_morphometry_config,
    ):
        with pytest.raises(ValueError, match="positive_down"):
            loader(path)


def test_q90_schema_rejects_other_quantiles(workspace):
    path = workspace / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["geomorphometry"]["processing"]["slope_upper_quantile"] = 0.95
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="Q90"):
        load_geomorphometry_config(path)


def _raster(tmp_path, *, rotate=False, coastal=False):
    import rasterio
    from rasterio.transform import Affine, from_origin
    import h3

    transform = from_origin(-123, 48.5, 0.001, 0.001)
    if rotate:
        transform = transform * Affine.rotation(10)
    data = np.full((8, 8), -100.0, dtype="float64")
    if coastal:
        data[:, 0] = 1000.0  # no land contribution to marine slope
        data[3, 3] = -9999.0
    path = tmp_path / "slope.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=8,
        height=8,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as target:
        target.write(data, 1)
    cells = {
        h3.latlng_to_cell(48.5 - (row + 0.5) * 0.001, -123 + (col + 0.5) * 0.001, 8)
        for row in range(8)
        for col in range(8)
    }
    return path, cells


def test_native_slope_masks_land_nodata_and_preserves_flat_edges(tmp_path):
    path, cells = _raster(tmp_path, coastal=True)
    result = _native_raster_slope_summary(path, cells, 8, 0.9)
    assert not result.empty
    np.testing.assert_allclose(
        result[["SLOPE_MEAN_NATIVE_RASTER", "SLOPE_Q90_NATIVE_RASTER"]], 0.0
    )


def test_native_slope_rejects_rotated_affine(tmp_path):
    path, cells = _raster(tmp_path, rotate=True)
    with pytest.raises(ValueError, match="unrotated"):
        _native_raster_slope_summary(path, cells, 8, 0.9)


@pytest.mark.parametrize(
    "escape", ["absolute", "custom_relative", "dotdot", "symlink", "filename"]
)
def test_candidate_rejects_output_escape_before_writes(workspace, escape):
    candidate = workspace / "candidate"
    path = workspace / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(path.read_text())
    processing = raw["bathymetry"]["processing"]
    sentinel = workspace / "keep.parquet"
    sentinel.write_bytes(b"canonical")
    if escape == "absolute":
        processing["processed_path"] = str(sentinel)
    elif escape == "custom_relative":
        processing["processed_path"] = "keep.parquet"
    elif escape == "dotdot":
        processing["processed_path"] = str(candidate / ".." / "keep.parquet")
    elif escape == "filename":
        raw["water_geometry"]["build"]["output_filename"] = "../keep.parquet"
    else:
        candidate.mkdir()
        (candidate / "data").symlink_to(workspace, target_is_directory=True)
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValueError, match="escapes|basename"):
        _prepare_candidate_config(
            workspace / "config/data/project.yaml",
            canonical_root=workspace,
            candidate_root=candidate,
        )
    assert sentinel.read_bytes() == b"canonical"
    assert not (candidate / ".seascape/config/project.yaml").exists()


def test_resume_tracks_common_extends_and_environment(workspace, monkeypatch):
    project = workspace / "small.yaml"
    base = workspace / "base.yaml"
    base.write_text("value: '${env:SEASCAPE_TEST_VALUE}'\n")
    project.write_text("extends: base.yaml\n")
    monkeypatch.setenv("SEASCAPE_TEST_VALUE", "first")
    calls = []

    def runner(context):
        calls.append(True)
        (context.candidate_root / "result.txt").write_text("result")

    stages = (
        DomainBuildStage(
            "fixture", "fixture", runner, declared_outputs=("result.txt",)
        ),
    )

    def run():
        return run_domain_layer_build(
            config_path=project,
            candidate_root=workspace / "candidate",
            publish=False,
            resume=True,
            stage_definitions=stages,
        )[0].status

    assert run() == "complete"
    assert run() == "reused"
    common = workspace / "config/common.yaml"
    raw = yaml.safe_load(common.read_text())
    raw["areas"]["model_area"]["bbox_wgs84"]["max_lon"] -= 0.01
    common.write_text(yaml.safe_dump(raw))
    assert run() == "complete"
    monkeypatch.setenv("SEASCAPE_TEST_VALUE", "second")
    assert run() == "complete"
    base.write_text(base.read_text() + "other: 1\n")
    assert run() == "complete"
    assert run() == "reused"


def test_candidate_uses_same_composed_values_and_frozen_common(workspace):
    from seascape.core.config.data import load_data_config
    from seascape.core.config.common_areas import bbox_for_area

    base = workspace / "base.yaml"
    base.write_text("value: 12\nnested:\n  a: 1\n")
    project = workspace / "small.yaml"
    project.write_text("extends: base.yaml\ncopy: '${value}'\nnested:\n  b: 2\n")
    rendered = _prepare_candidate_config(
        project, canonical_root=workspace, candidate_root=workspace / "candidate"
    )
    actual = load_data_config(rendered)
    expected = load_data_config(project)
    assert all(actual[k] == v for k, v in expected.items())
    bbox = bbox_for_area("model_area")
    common = workspace / "config/common.yaml"
    common.write_text("areas: {}\n")
    with _candidate_environment(workspace / "candidate"):
        assert bbox_for_area("model_area") == bbox
    assert json.loads(
        (workspace / "candidate/.seascape/config/identity.json").read_text()
    )["effective_sha256"]


def test_native_slope_matches_north_south_plane_including_edges(tmp_path):
    import rasterio

    path, cells = _raster(tmp_path)
    # 10 m per latitude pixel; north/south spacing is the documented 110574 m/degree.
    with rasterio.open(path, "r+") as raster:
        plane = -100.0 - 10.0 * np.indices((8, 8))[0]
        raster.write(plane, 1)
    actual = _native_raster_slope_summary(path, cells, 8, 0.9)
    expected = np.degrees(np.arctan(10.0 / 110.574))
    np.testing.assert_allclose(
        actual[["SLOPE_MEAN_NATIVE_RASTER", "SLOPE_Q90_NATIVE_RASTER"]], expected
    )


def test_depth_values_reject_contradiction_and_preserve_missingness():
    from seascape.seafloor_physiography.depth import validate_positive_depth

    with pytest.raises(ValueError, match="negative"):
        validate_positive_depth(pd.Series([10.0, -10.0, np.nan]))
    values = pd.Series([10.0, 0.0, np.nan])
    validate_positive_depth(values)
    assert pd.isna(values.iloc[2])


def test_candidate_writer_rejects_external_destination(workspace):
    from seascape.core.artifacts.contracts import atomic_write_json
    from seascape.publication import TransactionalSeascapePublisher

    outside = workspace / "keep.json"
    outside.write_text("original")
    candidate = workspace / "candidate"
    candidate.mkdir()
    with _candidate_environment(candidate):
        with pytest.raises(ValueError, match="escapes"):
            atomic_write_json(outside, {"changed": True}, overwrite=True)
        with pytest.raises(ValueError, match="escapes"):
            TransactionalSeascapePublisher(workspace)
    assert outside.read_text() == "original"


def test_config_reference_cycles_fail_explicitly(tmp_path):
    from seascape.core.config.document import ConfigDocument

    path = tmp_path / "cycle.yaml"
    path.write_text("a: '${b}'\nb: '${a}'\n")
    with pytest.raises(ValueError, match="[Cc]ycl"):
        ConfigDocument.load(path)


def test_candidate_preserves_custom_input_base(workspace):
    from seascape.core.config.data import load_data_config

    project = workspace / "small.yaml"
    project.write_text("base_directory: inputs\nsource: data/raw/test.tif\n")
    rendered = _prepare_candidate_config(
        project, canonical_root=workspace, candidate_root=workspace / "candidate"
    )
    assert load_data_config(rendered)["source"] == str(
        workspace / "inputs/data/raw/test.tif"
    )
