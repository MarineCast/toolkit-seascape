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
    _, spec, _, save = setup_job("freshwater")
    path = save()
    assert main(["regional", "--spec", str(path), "--preflight"]) == 0
    assert json.loads(capsys.readouterr().out)["network_bytes"] == 0
    assert not (tmp_path / "candidate").exists()
    Path(spec["inputs"]["reporting"]["path"]).write_text("tampered")
    with pytest.raises(RegionalError, match="changed"):
        run_spec(path, preflight=True)


@pytest.mark.parametrize("operator", ["freshwater", "estuary"])
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


def test_terrain_null_qc_streaming_and_no_r6(setup_job, tmp_path):
    keys, spec, pin, save = setup_job("terrain-form", 8)
    path = tmp_path / "terrain.parquet"
    pq.write_table(
        pa.table(
            {
                "H3_INDEX": keys,
                "BATHYMETRY": [100.0] * len(keys),
                "SLOPE_MEAN_NATIVE_RASTER": [10.0] * len(keys),
                "TERRAIN_POSITION_RING_4_Z": [2.0] * len(keys),
                "FOCAL_NATIVE_MARINE_DEPTH_PRESENT": [True] * len(keys),
                "CONTEXT_HOP4_COMPLETE": [True] * (len(keys) - 1) + [False],
                "TERRAIN_POSITION_RING_4_Z_QC_REASON": pa.nulls(
                    len(keys), type=pa.string()
                ),
            }
        ),
        path,
    )
    pin("terrain", path)
    run_spec(save())
    result = pq.read_table(tmp_path / "candidate/metrics.parquet").to_pydict()
    assert result["TERRAIN_FORM_PROXY"][:-1] == ["ELEVATED_TERRAIN_PROXY"] * (
        len(keys) - 1
    )
    assert result["TERRAIN_FORM_PROXY"][-1] is None
    assert result["INPUT__TERRAIN_POSITION_RING_4_Z_QC_REASON"] == [None] * len(keys)
    verify_candidate(tmp_path / "candidate")
    spec["output"] = "rejected"
    spec["resolution"] = 6
    with pytest.raises(RegionalError, match="native R8"):
        run_spec(save())
    assert (tmp_path / "rejected/FAILED.json").exists()
    assert not (tmp_path / "rejected/MANIFEST.json").exists()


def test_consolidation_preserves_old_metadata_types_and_nulls(setup_job, tmp_path):
    keys, spec, pin, save = setup_job(
        "consolidate",
        settings={
            "append": [
                {
                    "input": "source",
                    "prefix": "NEW__",
                    "immutable_release_id": "fixture-v1",
                }
            ]
        },
    )
    old = pa.table(
        {
            "H3_INDEX": keys,
            "value": pa.array([None] + list(range(len(keys) - 1)), type=pa.int16()),
        }
    ).replace_schema_metadata({b"identity": b"old"})
    new = pa.table(
        {
            "H3_INDEX": keys,
            "flag": pa.array([None] + [True] * (len(keys) - 1), type=pa.bool_()),
        }
    )
    for name, table in [("base", old), ("source", new)]:
        path = tmp_path / (name + ".parquet")
        pq.write_table(table, path)
        pin(name, path)
    run_spec(save())
    out = pq.read_table(tmp_path / "candidate/metrics.parquet")
    assert out.schema.metadata == old.schema.metadata and out.select(
        old.column_names
    ).equals(old)
    assert out["NEW__flag"].equals(new["flag"])
    verify_candidate(tmp_path / "candidate")
    spec["output"] = "bad"
    path = tmp_path / "source.parquet"
    pq.write_table(new.take(pa.array(list(reversed(range(len(keys)))))), path)
    pin("source", path)
    with pytest.raises(RegionalError, match="H3 order"):
        run_spec(save())


@pytest.mark.parametrize(
    "operator", ["coastal", "bivalve", "kelp", "anthropogenic", "shoreline"]
)
def test_direct_polygon_and_physical_commands(setup_job, tmp_path, operator):
    settings = {"bearings_degrees": [0, 90], "maximum_distance_m": 100}
    keys, _, pin, save = setup_job(
        operator, 8 if operator == "coastal" else 6, settings=settings
    )
    polygon = shapely.union_all(cells(keys).geometry.to_numpy()).buffer(0.01)
    water = tmp_path / "water.parquet"
    gpd.GeoDataFrame({"name": ["water"]}, geometry=[polygon], crs=4326).to_parquet(
        water
    )
    pin("water", water)
    pin("extent", water)
    if operator == "coastal":
        import pandas as pd

        from seascape.regional.coastal_origin import origin_record

        locations = np.asarray([h3.cell_to_latlng(key) for key in keys])
        support = pd.DataFrame(
            {
                "H3_INDEX": keys,
                "GRAPH_NODE_ELIGIBLE": [True] * len(keys),
                "CONNECTOR_TARGET_H3_INDEX": [None] * len(keys),
                "REPRESENTATIVE_POINT_LONGITUDE": locations[:, 1],
                "REPRESENTATIVE_POINT_LATITUDE": locations[:, 0],
                "FULL_H3_WITHIN_SOURCE_RECTANGLE": [True] * len(keys),
            }
        ).set_index("H3_INDEX")
        origin_path = tmp_path / "origins.parquet"
        pq.write_table(
            pa.Table.from_pylist([origin_record(key, support) for key in keys]),
            origin_path,
        )
        pin("origins", origin_path)
    source = tmp_path / "source.parquet"
    if operator == "bivalve":
        frame = gpd.GeoDataFrame(
            {"EVIDENCE_CLASS": ["WA_bed"]},
            geometry=[cells(keys).geometry.iloc[0]],
            crs=4326,
        )
    elif operator == "kelp":
        frame = gpd.GeoDataFrame(
            {"OBSERVATION_YEAR": [2009]},
            geometry=[cells(keys).geometry.iloc[0]],
            crs=4326,
        )
    elif operator == "anthropogenic":
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
    if operator == "kelp":
        # The returned settings dict is retained by the specification.
        settings["annual_layers"] = [{"year": 2009, "input": "inventory"}]
    run_spec(save())
    manifest = verify_candidate(tmp_path / "candidate")
    assert manifest["details"]["rows"] >= len(keys)


def test_block_streamed_positive_footprints(setup_job, tmp_path):
    keys, _, pin, save = setup_job("seagrass")
    bounds = cells(keys).total_bounds
    dx = (bounds[2] - bounds[0]) / 64
    dy = (bounds[3] - bounds[1]) / 64
    raster = tmp_path / "tile.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        height=64,
        width=64,
        count=1,
        dtype="uint8",
        crs=4326,
        transform=from_origin(bounds[0], bounds[3], dx, dy),
        tiled=True,
        blockxsize=16,
        blockysize=16,
    ) as source:
        source.write(np.ones((64, 64), dtype=np.uint8), 1)
    pin("tile_1", raster)
    run_spec(save())
    table = pq.read_table(tmp_path / "candidate/metrics.parquet").to_pydict()
    assert sum(table["POSITIVE_PIXEL_CENTER_COUNT"]) > 0
    assert all(
        a == b
        for a, b in zip(
            table["EXPECTED_SOURCE_BLOCKS"], table["COMPLETED_SOURCE_BLOCKS"]
        )
    )
    verify_candidate(tmp_path / "candidate")


def native_fixture(keys, tmp_path, pin):
    from importlib.resources import files

    for name, relative in [
        ("config", "config/data/environment_seascape.yaml"),
        ("common", "config/common.yaml"),
    ]:
        destination = tmp_path / (name + ".yaml")
        destination.write_bytes(
            files("seascape").joinpath("resources", relative).read_bytes()
        )
        pin(name, destination)

    from seascape.seafloor_physiography.bathymetry.build import (
        _latlngs_to_h3,
        _pixel_centers,
    )

    west, south, east, north = cells(keys).total_bounds
    step = 1 / 240
    width = int(np.ceil((east - west) / step)) + 6
    height = int(np.ceil((north - south) / step)) + 6
    raster = tmp_path / "native.tif"
    affine = from_origin(west - 3 * step, north + 3 * step, step, step)
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="int16",
        crs=4326,
        transform=affine,
        nodata=-32767,
    ) as source:
        source.write(-np.full((height, width), 100, dtype=np.int16), 1)
        source.set_band_unit(1, "m")
    pin("raster", raster)
    compute = tmp_path / "compute.txt"
    compute.write_text("\n".join(keys) + "\n")
    pin("compute", compute)
    latitude, longitude = _pixel_centers(affine, (height, width))
    pixels = _latlngs_to_h3(
        latitude.ravel(), longitude.ravel(), h3.get_resolution(keys[0])
    )
    counts = [int(np.sum(np.asarray(pixels, dtype=object) == key)) for key in keys]
    depth = tmp_path / "depth.parquet"
    pq.write_table(
        pa.table(
            {
                "H3_INDEX": keys,
                "BATHYMETRY": [100.0] * len(keys),
                "NATIVE_EXPECTED_PIXEL_COUNT": counts,
                "NATIVE_VALID_MARINE_SAMPLE_COUNT": counts,
                "NATIVE_FULL_H3_SOURCE_COVERAGE": [True] * len(keys),
                "NATIVE_NODATA_PIXEL_COUNT": [0] * len(keys),
            }
        ),
        depth,
    )
    pin("depth", depth)


@pytest.mark.parametrize(
    "operator", ["bathymetry", "distance", "watergraph", "native-terrain"]
)
def test_native_commands_keep_compute_support_and_censoring(
    setup_job, tmp_path, operator
):
    keys, spec, pin, save = setup_job(operator, 8)
    native_fixture(keys, tmp_path, pin)
    cols = {"H3_INDEX": keys}
    for field in (
        "REGULAR_NEIGHBOR_CENSUS_COMPLETE",
        "INCOMING_CONNECTOR_CANDIDATE_CENSUS_COMPLETE",
        "OUTGOING_CONNECTOR_GLOBAL16_SEARCH_COMPLETE",
        "FULL_H3_WITHIN_SOURCE_RECTANGLE",
        "GENERALIZED_FALLBACK",
        "NATIVE_LAND_FOOTPRINT_UNKNOWN",
        "POLICY_EDGE_REVIEW",
    ):
        cols[field] = [field == "FULL_H3_WITHIN_SOURCE_RECTANGLE"] * len(keys)
    context = tmp_path / "context.parquet"
    pq.write_table(pa.table(cols), context)
    pin("context", context)
    if operator == "native-terrain":
        pin("support", context)
        edges = tmp_path / "edges.parquet"
        pq.write_table(
            pa.table(
                {
                    "SOURCE_H3_INDEX": keys[:-1],
                    "TARGET_H3_INDEX": keys[1:],
                    "EDGE_IS_WATER_PASSABLE": [True] * (len(keys) - 1),
                }
            ),
            edges,
        )
        pin("edges", edges)
        conn = tmp_path / "connectors.parquet"
        pq.write_table(
            pa.table(
                {
                    "H3_INDEX": pa.array([], type=pa.string()),
                    "TARGET_H3_INDEX": pa.array([], type=pa.string()),
                    "CONNECTOR_IS_WATER_PASSABLE": pa.array([], type=pa.bool_()),
                }
            ),
            conn,
        )
        pin("connectors", conn)
    if operator == "watergraph":
        water = tmp_path / "water.gpkg"
        polygon = shapely.union_all(cells(keys).geometry.to_numpy()).buffer(0.01)
        gpd.GeoDataFrame({"kind": ["water"]}, geometry=[polygon], crs=4326).to_file(
            water, layer="water_area", driver="GPKG"
        )
        pin("water", water)
        pin("extent", water)
    if operator == "bathymetry":
        graph = tmp_path / "neighbors.parquet"
        pq.write_table(
            pa.table(
                {
                    "SOURCE_H3_INDEX": keys,
                    "TARGET_H3_INDEX": keys,
                    "MINIMUM_HOP_COUNT": [0] * len(keys),
                    "NETWORK_DISTANCE_M": [0.0] * len(keys),
                }
            ),
            graph,
        )
        pin("neighborhoods", graph)
    if operator == "distance":
        extent_path = tmp_path / "extent.parquet"
        gpd.GeoDataFrame(
            {"source": ["fixture"]},
            geometry=[shapely.union_all(cells(keys).geometry.to_numpy()).buffer(0.01)],
            crs=4326,
        ).to_parquet(extent_path)
        pin("extent", extent_path)
        lines = tmp_path / "lines.parquet"
        gpd.GeoDataFrame(
            {"id": ["a"]},
            geometry=[shapely.LineString([(-123.3, 48.2), (-123.1, 48.2)])],
            crs=4326,
        ).to_parquet(lines)
        pin("shoreline", lines)
    if operator in ("watergraph", "native-terrain"):
        certificate = "context" if operator == "watergraph" else "support"
        dependencies = (
            ("compute", "water", "extent", "config", "common")
            if operator == "watergraph"
            else ("compute", "edges", "connectors", "raster", "config", "common")
        )
        from seascape.regional.contract import Job
        from seascape.regional.native import _certificate_binding

        with pytest.raises(RegionalError, match="certificate binding"):
            _certificate_binding(Job.load(save()), certificate, dependencies)
        binding = {name: spec["inputs"][name]["sha256"] for name in dependencies}
        spec["inputs"][certificate]["qualification"]["certificate_input_sha256"] = (
            binding
        )
        _certificate_binding(Job.load(save()), certificate, dependencies)
        spec["inputs"][certificate]["qualification"]["certificate_input_sha256"] = dict(
            binding, compute="0" * 64
        )
        with pytest.raises(RegionalError, match="certificate binding"):
            _certificate_binding(Job.load(save()), certificate, dependencies)
        spec["inputs"][certificate]["qualification"]["certificate_input_sha256"] = (
            binding
        )
    run_spec(save())
    verify_candidate(tmp_path / "candidate")
    output = pq.read_table(tmp_path / "candidate/metrics.parquet")
    assert output["H3_INDEX"].to_pylist() == keys
    if operator == "watergraph":
        assert output["BATHYMETRY_LOCAL_ANOMALY"].null_count == len(keys)
        assert all(
            value == "context_incomplete_primary_anomaly_null"
            for value in output["LOCAL_ANOMALY_STATUS"].to_pylist()
        )


def test_directory_pin_and_changed_spec_rejected(setup_job, tmp_path):
    from seascape.regional.contract import Job

    _, spec, pin, save = setup_job("freshwater")
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


def test_archive_block_processing_without_extraction(setup_job, tmp_path):
    from zipfile import ZipFile

    settings = {"raster_tiles": [{"input": "archive", "member": "native/tile.tif"}]}
    keys, _, pin, save = setup_job("seagrass", settings=settings)
    west, south, east, north = cells(keys).total_bounds
    path = tmp_path / "tile.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=16,
        width=16,
        count=1,
        dtype="uint8",
        crs=4326,
        transform=from_origin(west, north, (east - west) / 16, (north - south) / 16),
    ) as source:
        source.write(np.ones((16, 16), dtype=np.uint8), 1)
    archive = tmp_path / "source.zip"
    with ZipFile(archive, "w") as output:
        output.write(path, "native/tile.tif")
    pin("archive", archive)
    run_spec(save())
    verify_candidate(tmp_path / "candidate")
    assert not (tmp_path / "native").exists()


def test_resource_alarm_restores_handler_and_preserves_failed_candidate(
    setup_job, tmp_path, monkeypatch
):
    import signal
    import time

    from seascape.regional import point_products

    _, spec, _, save = setup_job("freshwater", 8)
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
