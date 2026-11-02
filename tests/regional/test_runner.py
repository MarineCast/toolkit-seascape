"""Installed regional contract and bounded synthetic end-to-end producers."""

import json
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import rasterio
import shapely
from pyproj import Transformer
from rasterio.transform import from_origin

from seascape.cli import main
from seascape.regional.contract import RegionalError, digest
from seascape.regional.geometry import cells
from seascape.regional.runner import run_spec


@pytest.fixture
def setup_job(tmp_path):
    def prepare(operator, resolution=6, settings=None):
        keys = sorted(h3.grid_disk(h3.latlng_to_cell(48.2, -123.2, resolution), 1))
        reporting = tmp_path / "reporting.txt"
        reporting.write_text("\n".join(keys) + "\n")
        positions = np.asarray([h3.cell_to_latlng(k) for k in keys])
        support = tmp_path / "support.parquet"
        pq.write_table(
            pa.table(
                {
                    "H3_INDEX": keys,
                    "REPRESENTATIVE_POINT_LONGITUDE": positions[:, 1],
                    "REPRESENTATIVE_POINT_LATITUDE": positions[:, 0],
                    "HAS_WATER_OVERLAP": [True] * len(keys),
                    "IS_HIERARCHY_ONLY_PARENT": [False] * len(keys),
                }
            ),
            support,
        )
        spec = {
            "schema": 1,
            "operator": operator,
            "resolution": resolution,
            "domain": {
                "id": "synthetic",
                "revision": "fixture-v1",
                "support": "native_full_hex",
                "coverage_status": "fixture_not_regional",
            },
            "output": "candidate",
            "inputs": {},
            "settings": settings or {},
            "limits": {
                "memory_bytes": 1536 * 1024**2,
                "staging_bytes": 8 * 1024**2,
                "seconds": 30,
                "batch_rows": 2,
            },
        }

        def pin(name, path):
            spec["inputs"][name] = {
                "path": str(path),
                "sha256": digest(path),
                "qualification": {
                    "rights": "synthetic fixture",
                    "spatial_support": "explicit fixture",
                    "coverage_status": "synthetic_not_regional",
                    "observation_period": None,
                },
            }

        pin("reporting", reporting)
        pin("support", support)
        path = tmp_path / "spec.json"

        def save():
            path.write_text(json.dumps(spec))
            return path

        return keys, spec, pin, save

    return prepare


def verify_candidate(path):
    for line in (path / "CHECKSUMS.sha256").read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert digest(path / name) == expected
    manifest = json.loads((path / "MANIFEST.json").read_text())
    assert (
        manifest["schema"] == 3
        and not manifest["published"]
        and not manifest["complete_toolkit"]
    )
    assert (
        manifest["source_acquisition_bytes"] == 0
        and len(manifest["code_identity"]["source_tree_sha256"]) == 64
    )
    return manifest


def test_preflight_cli_tamper_and_existing_output(setup_job, tmp_path, capsys):
    _, spec, _, save = setup_job("estuary")
    path = save()
    assert main(["regional", "--spec", str(path), "--preflight"]) == 0
    assert json.loads(capsys.readouterr().out)["network_bytes"] == 0
    assert not (tmp_path / "candidate").exists()
    Path(spec["inputs"]["reporting"]["path"]).write_text("tampered")
    with pytest.raises(RegionalError, match="changed"):
        run_spec(path, preflight=True)


@pytest.mark.parametrize("operator", ["estuary"])
def test_point_proximity_bound_inventory(setup_job, tmp_path, operator):
    keys, spec, pin, save = setup_job(operator, 8)
    x, y = Transformer.from_crs(4326, 32610, always_xy=True).transform(-123.2, 48.2)
    path = tmp_path / "points.parquet"
    pq.write_table(
        pa.table({"SOURCE_ID": ["a", "b"], "X_M": [x, x + 100.0], "Y_M": [y, y]}), path
    )
    pin("inventory", path)
    run_spec(save())
    table = pq.read_table(tmp_path / "candidate/metrics.parquet")
    assert table["H3_INDEX"].to_pylist() == keys and all(
        v >= 0 for v in table["MINIMUM_DISTANCE_M"].to_pylist()
    )
    verify_candidate(tmp_path / "candidate")
    with pytest.raises(RegionalError, match="must be new"):
        run_spec(tmp_path / "spec.json")


@pytest.mark.parametrize("operator", ["anthropogenic", "shoreline"])
def test_direct_polygon_and_physical_commands(setup_job, tmp_path, operator):
    settings = {"bearings_degrees": [0, 90], "maximum_distance_m": 100}
    keys, _, pin, save = setup_job(operator, 6, settings=settings)
    polygon = shapely.union_all(cells(keys).geometry.to_numpy()).buffer(0.01)
    water = tmp_path / "water.parquet"
    gpd.GeoDataFrame({"name": ["water"]}, geometry=[polygon], crs=4326).to_parquet(
        water
    )
    pin("water", water)
    pin("extent", water)
    source = tmp_path / "source.parquet"
    if operator == "anthropogenic":
        frame = gpd.GeoDataFrame(
            {
                "FEATURE_CLASS": ["aquaculture"],
                "IS_CANONICAL": [True],
                "SUPPORTS_AREA": [True],
                "SUPPORTS_SHORELINE_DENOMINATOR": [False],
                "ARMORING_FRACTION_ESTIMATE": [np.nan],
                "SOURCE_DATASET": ["synthetic"],
            },
            geometry=[cells(keys).geometry.iloc[0]],
            crs=4326,
        )
    else:
        from seascape.coastal_configuration.shoreline_characterization.build import (
            CLASS_TOKENS,
        )

        frame = gpd.GeoDataFrame(
            {
                "SEGMENT_ID": ["s"],
                "IS_PHYSICALLY_CLASSIFIED": [True],
                **{
                    "IS_" + token + "_SHORE": [token == "ROCKY"]
                    for token in CLASS_TOKENS
                },
            },
            geometry=[shapely.LineString([(-123.3, 48.2), (-123.1, 48.2)])],
            crs=4326,
        )
    frame.to_parquet(source)
    pin("inventory", source)
    run_spec(save())
    manifest = verify_candidate(tmp_path / "candidate")
    assert manifest["details"]["rows"] >= len(keys)


def test_regional_armoring_uses_maximum_available_dataset(setup_job, tmp_path):
    from seascape.domain_parquets import AreaTables, read_area, write_areas

    keys, _, pin, save = setup_job("anthropogenic", 6)
    polygon = shapely.union_all(cells(keys).geometry.to_numpy()).buffer(0.01)
    water = tmp_path / "water.parquet"
    gpd.GeoDataFrame(geometry=[polygon], crs=4326).to_parquet(water)
    pin("water", water)
    lat, lon = h3.cell_to_latlng(keys[0])
    line = shapely.LineString([(lon - 0.001, lat), (lon + 0.001, lat)])
    inventory = gpd.GeoDataFrame(
        {
            "FEATURE_CLASS": ["shoreline_survey"] * 3,
            "IS_CANONICAL": [True] * 3,
            "SUPPORTS_AREA": [False] * 3,
            "SUPPORTS_SHORELINE_DENOMINATOR": [True] * 3,
            "ARMORING_FRACTION_ESTIMATE": [0.0, 1.0, np.nan],
            "SOURCE_DATASET": ["zero", "one", "missing"],
        },
        geometry=[line] * 3,
        crs=4326,
    )
    path = tmp_path / "inventory.parquet"
    inventory.to_parquet(path)
    pin("inventory", path)
    run_spec(save())
    native = pq.read_table(tmp_path / "candidate/metrics.parquet")
    values = native.to_pandas().set_index("H3_INDEX")
    assert values.loc[keys[0], "SHORELINE_ARMORING_FRAC"] == 1
    assert values.SHORELINE_ARMORING_FRAC.isna().sum() == len(keys) - 1
    write_areas({"anthropogenic": AreaTables(native)}, output=tmp_path / "public")
    result = read_area("anthropogenic", output=tmp_path / "public")
    assert result.num_columns == 6
    assert result["shoreline_armoring_fraction"].to_pylist()[0] == 1
    assert not any("qc" in name or "coverage" in name for name in result.column_names)


def test_directory_pin_and_changed_spec_rejected(setup_job, tmp_path):
    from seascape.regional.contract import Job

    _, spec, pin, save = setup_job("estuary")
    directory = tmp_path / "source-directory"
    directory.mkdir()
    (directory / "component").write_text("retained")
    pin("directory", directory)
    path = save()
    job = Job.load(path)
    (directory / "component").write_text("changed")
    with pytest.raises(RegionalError, match="changed"):
        job.verify_inputs()
    pin("directory", directory)
    job = Job.load(save())
    spec["settings"]["changed"] = True
    save()
    with pytest.raises(RegionalError, match="Spec changed"):
        job.verify_inputs()


def test_substrate_installed_contract_all_four_sources(setup_job, tmp_path):
    keys, _, pin, save = setup_job("substrate")
    for name, percent in [
        ("rock", 50.0),
        ("gravel", 20.0),
        ("sand", 30.0),
        ("mud", 50.0),
    ]:
        path = tmp_path / (name + ".tif")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=1800,
            width=3600,
            count=1,
            dtype="float32",
            crs=4326,
            nodata=-99.0,
            transform=from_origin(-180, 90, 0.1, 0.1),
            compress="deflate",
            tiled=True,
        ) as source:
            source.write(np.full((1800, 3600), percent, dtype=np.float32), 1)
        pin(name, path)
    run_spec(save())
    table = pq.read_table(tmp_path / "candidate/metrics.parquet")
    assert table["H3_INDEX"].to_pylist() == keys
    assert table["MODELED_ROCK_PRESENCE_SCORE"].to_pylist() == [0.5] * len(keys)
    assert table["SEDIMENT_TEXTURE_STATUS"].to_pylist() == ["valid_closed"] * len(keys)
    assert table["PHYSICAL_HARDNESS"].null_count == len(keys)
    verify_candidate(tmp_path / "candidate")


def test_resource_alarm_restores_handler_and_preserves_failed_candidate(
    setup_job, tmp_path, monkeypatch
):
    import signal
    import time

    from seascape.regional import point_products

    _, spec, _, save = setup_job("estuary", 8)
    spec["limits"]["seconds"] = 1
    before = signal.getsignal(signal.SIGALRM)

    def slow(job):
        time.sleep(2)
        return "never", {}

    monkeypatch.setattr(point_products, "proximity", slow)
    with pytest.raises(RegionalError, match="Resource limit"):
        run_spec(save())
    assert signal.getsignal(signal.SIGALRM) == before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert (tmp_path / "candidate/FAILED.json").is_file()
    assert not (tmp_path / "candidate/MANIFEST.json").exists()


def test_candidate_cannot_modify_input_directory(setup_job, tmp_path):
    _, spec, pin, save = setup_job("estuary", 8)
    source = tmp_path / "input-directory"
    source.mkdir()
    (source / "retained.txt").write_text("unique source")
    pin("directory", source)
    spec["output"] = str(source / "nested-output")
    with pytest.raises(RegionalError, match="overlaps"):
        run_spec(save())
    assert not (source / "nested-output").exists()
