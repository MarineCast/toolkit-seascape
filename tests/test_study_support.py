"""Real consumer APIs with small synthetic pinned artifacts; no qualification claim."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon, box, mapping
from shapely.ops import unary_union

from seascape.core.geo.h3 import cell_to_polygon
from seascape.seafloor_physiography.bathymetry.build import load_h3_cells
from seascape.study import StudyConfigError, load_study_config, study_context
from seascape.study_support import (
    MembershipArtifact,
    _membership,
    _overlap,
    load_study_support,
)


def write_membership(root, filename, cells, resolution, role):
    raw = ("\n".join(sorted(cells)) + "\n").encode()
    (root / filename).write_bytes(raw)
    return MembershipArtifact(
        "../Data/" + filename,
        hashlib.sha256(raw).hexdigest(),
        len(cells),
        resolution,
        role,
    )


def independent_overlap(geometry, resolution):
    """Enumerate nearby cells and test actual polygon intersections, not H3 fill."""
    candidates = h3.grid_disk(h3.latlng_to_cell(48.5, -123.5, resolution), 12)
    return tuple(
        sorted(
            cell
            for cell in candidates
            if cell_to_polygon(cell).intersection(geometry).area > 0
        )
    )


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.delenv("MARINECAST_STUDY_CONFIG", raising=False)
    artifact_root = tmp_path / "Data"
    artifact_root.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # Narrow disconnected coastal and inland-shaped islands, including a dry hole.
    outer = box(-123.507, 48.497, -123.503, 48.503)
    hole = box(-123.506, 48.499, -123.504, 48.501)
    boundary = h3.cell_to_boundary(h3.latlng_to_cell(48.5, -123.5, 6))
    lat = (boundary[0][0] + boundary[1][0]) / 2
    lon = (boundary[0][1] + boundary[1][1]) / 2
    edge_sliver = box(lon - 0.0001, lat - 0.0001, lon + 0.0001, lat + 0.0001)
    geometry = unary_union(
        [outer.difference(hole), box(-123.499, 48.501, -123.496, 48.503), edge_sliver]
    )
    raw = json.dumps(mapping(geometry), separators=(",", ":")).encode()
    (artifact_root / "mask.geojson").write_bytes(raw)
    reporting = independent_overlap(geometry, 6)
    native = independent_overlap(geometry, 8)
    compute6 = set(reporting) | {h3.cell_to_parent(cell, 6) for cell in native}
    compute6.update(h3.grid_disk(next(iter(reporting)), 1))
    compute8 = {child for cell in compute6 for child in h3.cell_to_children(cell, 8)}
    r6spec = write_membership(
        artifact_root, "reporting-r6.txt", reporting, 6, "water_reporting"
    )
    halo = (
        write_membership(artifact_root, "compute-r6.txt", compute6, 6, "water_source"),
        write_membership(artifact_root, "compute-r8.txt", compute8, 8, "water_source"),
    )
    config = json.loads(
        (Path(__file__).parent / "fixtures/study.coastal.v1.json").read_bytes()
    )
    config["domain"].update(
        {
            "status": "approved",
            "geometry_status": "source_relative_validated",
            "approval": {
                "approved_at": "2026-10-06T02:00:00Z",
                "source_message_id": "synthetic-only",
                "scope": "rectangular_selection_only",
                "statement": "Synthetic test only.",
            },
        }
    )
    config["domain"]["selection_policy"]["mask_status"] = "source_relative_validated"
    config["grid_registry"].update(
        {
            "status": "validated",
            "mask_revision": "synthetic-only",
            "mask_sha256": hashlib.sha256(raw).hexdigest(),
            "memberships": [vars(r6spec)],
        }
    )
    path = config_dir / "study.json"
    path.write_text(json.dumps(config))
    return SimpleNamespace(
        root=artifact_root,
        path=path,
        geometry=geometry,
        reporting=reporting,
        native=native,
        halo=halo,
        config=config,
    )


def load(inputs, **kwargs):
    return load_study_support(
        load_study_config(inputs.path),
        producer="bathymetry",
        mask_relative_path="../Data/mask.geojson",
        compute_memberships=inputs.halo,
        **kwargs,
    )


def test_real_consumer_and_independent_overlap(inputs):
    support = load(inputs)
    assert support.reporting_r6 == inputs.reporting
    assert support.native_reporting_r8 == inputs.native
    assert set(support.reporting_r6) < set(support.compute_r6)
    assert set(support.compute_r6) == {
        h3.cell_to_parent(c, 6) for c in support.compute_r8
    }
    assert len(support.native_reporting_r8) < len(support.compute_r8)
    for resolution in (6, 8):
        config = SimpleNamespace(
            h3_resolution=resolution, h3_grid_path=inputs.root / "absent.parquet"
        )
        assert load_h3_cells(config, study_support=support) == list(
            support.cells(resolution, role="reporting")
        )
        assert load_h3_cells(
            config, study_support=support, support_role="compute"
        ) == list(support.cells(resolution, role="compute"))
    provenance = support.provenance()
    assert (
        provenance["reporting_mask_sha256"] != provenance["acquisition_envelope_sha256"]
    )
    assert provenance["production_ready"] is False
    assert provenance["halo_distance_completeness"] == "not_established_by_consumer"
    with pytest.raises(StudyConfigError, match="production integration"):
        with study_context(load_study_config(inputs.path)):
            pytest.fail("artifact consumer must not authorize production")


@pytest.mark.parametrize("resolution", [6, 8])
def test_consume_tables_preserves_null_zero_and_separates_context(inputs, resolution):
    support = load(inputs)
    cells = support.cells(resolution, role="compute")
    frame = pd.DataFrame(
        {
            "H3_INDEX": cells,
            "VALUE": [0.0] * len(cells),
            "STATUS": ["observed"] * len(cells),
        }
    )
    report_cell = support.cells(resolution, role="reporting")[0]
    frame.loc[frame.H3_INDEX == report_cell, ["VALUE", "STATUS"]] = [
        None,
        "source_unavailable",
    ]
    original = frame.copy(deep=True)
    reporting = support.consume_table(frame, resolution, role="reporting")
    assert reporting.H3_INDEX.tolist() == list(
        support.cells(resolution, role="reporting")
    )
    assert pd.isna(reporting.loc[0, "VALUE"])
    assert reporting.loc[0, "STATUS"] == "source_unavailable"
    assert support.consume_table(
        frame, resolution, role="compute"
    ).H3_INDEX.tolist() == list(cells)
    pd.testing.assert_frame_equal(original, frame)
    with pytest.raises(StudyConfigError, match="missing"):
        support.consume_table(reporting, resolution, role="compute")


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "null", "outside", "resolution"]
)
def test_bad_tables_fail(inputs, change):
    support = load(inputs)
    cells = list(support.compute_r6)
    frame = pd.DataFrame({"H3_INDEX": cells, "H3_RESOLUTION": [6] * len(cells)})
    if change == "missing":
        frame = frame[~frame.H3_INDEX.isin(support.reporting_r6)]
    elif change == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif change == "null":
        frame.loc[0, "H3_INDEX"] = None
    elif change == "outside":
        frame.loc[0, "H3_INDEX"] = h3.latlng_to_cell(0, 0, 6)
    else:
        frame.loc[0, "H3_RESOLUTION"] = 8
    with pytest.raises(StudyConfigError):
        support.consume_table(frame, 6, role="reporting")


@pytest.mark.parametrize(
    "change",
    [
        "sha",
        "count",
        "unsorted",
        "duplicate",
        "newline",
        "wrong_res",
        "outside_mask",
        "missing_overlap",
        "escape",
        "symlink",
    ],
)
def test_bad_registry_artifacts_fail(inputs, change, tmp_path):
    spec = inputs.config["grid_registry"]["memberships"][0]
    path = inputs.path.parent / spec["relative_path"]
    cells = list(inputs.reporting)
    if change == "sha":
        path.write_bytes(b"tampered\n")
    elif change == "count":
        spec["count"] += 1
    elif change in {"escape", "symlink"}:
        if change == "escape":
            spec["relative_path"] = "../reporting-r6.txt"
        else:
            (inputs.root / "external.txt").symlink_to(
                inputs.root.parent / "no-access.txt"
            )
            spec["relative_path"] = "../Data/external.txt"
    else:
        if change == "unsorted":
            cells.reverse()
        elif change == "duplicate":
            cells += cells[:1]
        elif change == "wrong_res":
            cells = [h3.cell_to_children(cells[0], 8)[0]]
        elif change == "outside_mask":
            cells = sorted(cells + [h3.latlng_to_cell(0, 0, 6)])
        elif change == "missing_overlap":
            cells = cells[:-1]
        raw = ("\n".join(cells) + ("" if change == "newline" else "\n")).encode()
        path.write_bytes(raw)
        spec.update({"sha256": hashlib.sha256(raw).hexdigest(), "count": len(cells)})
    inputs.path.write_text(json.dumps(inputs.config))
    with pytest.raises(StudyConfigError):
        load(inputs)


@pytest.mark.parametrize(
    "change", ["tamper", "invalid", "projected", "empty", "bbox_only"]
)
def test_bad_masks_fail(inputs, change):
    if change == "tamper":
        (inputs.root / "mask.geojson").write_bytes(b"{}")
    else:
        geometry = {
            "invalid": Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)]),
            "projected": box(1e6, 2e6, 1e6 + 10, 2e6 + 10),
            "empty": Polygon(),
        }.get(change)
        payload = (
            mapping(geometry)
            if geometry is not None
            else {"bbox": [-129.7, 45.9, -121.5, 51.5]}
        )
        raw = json.dumps(payload).encode()
        (inputs.root / "mask.geojson").write_bytes(raw)
        inputs.config["grid_registry"]["mask_sha256"] = hashlib.sha256(raw).hexdigest()
        inputs.path.write_text(json.dumps(inputs.config))
    with pytest.raises(StudyConfigError):
        load(inputs)


@pytest.mark.parametrize(
    "change", ["parent_union", "reporting_omitted", "r5", "duplicate_role"]
)
def test_invalid_compute_support_fails(inputs, change):
    if change == "parent_union":
        cells = list((inputs.root / "compute-r6.txt").read_text().splitlines())[1:]
        inputs.halo = (
            write_membership(inputs.root, "bad-r6.txt", cells, 6, "water_source"),
            inputs.halo[1],
        )
    elif change == "reporting_omitted":
        r6 = [h3.latlng_to_cell(0, 0, 6)]
        r8 = h3.cell_to_children(r6[0], 8)
        inputs.halo = (
            write_membership(inputs.root, "bad-r6.txt", r6, 6, "water_source"),
            write_membership(inputs.root, "bad-r8.txt", r8, 8, "water_source"),
        )
    elif change == "r5":
        inputs.halo = (replace(inputs.halo[0], resolution=5), inputs.halo[1])
    else:
        inputs.halo = (inputs.halo[0], inputs.halo[0])
    with pytest.raises(StudyConfigError):
        load(inputs)


def test_budgets_pending_status_and_identity(inputs):
    support = load(inputs)
    for kwargs in ({"max_cells": 1}, {"max_artifact_bytes": 1}, {"max_cells": True}):
        with pytest.raises(StudyConfigError):
            load(inputs, **kwargs)
    inputs.config["producer_buffers"]["seascape"]["coastal_network_m"] += 1
    inputs.path.write_text(json.dumps(inputs.config))
    assert (
        load(inputs).provenance()["consumer_identity_sha256"]
        != support.provenance()["consumer_identity_sha256"]
    )
    inputs.config["domain"]["geometry_status"] = (
        "pending_qualified_coastline_validation"
    )
    inputs.path.write_text(json.dumps(inputs.config))
    study = load_study_config(inputs.path, planning=True)
    with pytest.raises(StudyConfigError, match="before artifact reads"):
        load_study_support(
            study,
            producer="bathymetry",
            mask_relative_path="nonexistent-mask.geojson",
            compute_memberships=inputs.halo,
        )


def test_standalone_still_requires_grid_and_no_implicit_compute(inputs):
    config = SimpleNamespace(
        h3_resolution=6, h3_grid_path=inputs.root / "absent.parquet"
    )
    with pytest.raises(FileNotFoundError):
        load_h3_cells(config)
    with pytest.raises(ValueError, match="requires verified study"):
        load_h3_cells(config, support_role="compute")


def test_positive_area_excludes_touch_and_preserves_holes(monkeypatch):
    cell = h3.latlng_to_cell(48.5, -123.5, 6)
    polygon = cell_to_polygon(cell)
    west, south, east, north = polygon.bounds
    touching_mask = box(east, south, east + 0.001, north)
    monkeypatch.setattr(
        "seascape.study_support.polygon_to_cells_overlap", lambda *_: {cell}
    )
    assert _overlap(touching_mask, 6, 100_000) == ()
    # A hole excludes the entire cell even when a fill implementation supplies it.
    mask_with_hole = box(
        west - 0.001, south - 0.001, east + 0.001, north + 0.001
    ).difference(polygon)
    assert _overlap(mask_with_hole, 6, 100_000) == ()


def test_no_center_fill_fallback(inputs, monkeypatch):
    monkeypatch.delattr(h3, "polygon_to_cells_experimental")
    with pytest.raises(StudyConfigError, match="no center fallback"):
        load(inputs)


def test_config_relative_paths_independent_of_cwd(inputs, monkeypatch):
    expected = load(inputs)
    monkeypatch.chdir(inputs.root)
    assert load(inputs) == expected


def test_interface_empty_file_and_terminal_newline(inputs):
    path = inputs.root / "empty.txt"
    path.write_bytes(b"")
    spec = MembershipArtifact(
        "../Data/empty.txt", hashlib.sha256(b"").hexdigest(), 0, 6, "water_source"
    )
    assert _membership(inputs.path.parent, inputs.root, spec, 100, 1024) == ()
    path.write_bytes(b"\n")
    with pytest.raises(StudyConfigError):
        _membership(
            inputs.path.parent,
            inputs.root,
            replace(spec, sha256=hashlib.sha256(b"\n").hexdigest()),
            100,
            1024,
        )


def test_interface_exact_packaged_pin():
    from importlib.resources import files

    raw = (
        files("seascape")
        .joinpath("resources/contracts/registry-artifact-interface.v1.json")
        .read_bytes()
    )
    assert (
        hashlib.sha256(raw).hexdigest()
        == "38e3f84d8e7b0f59c188abb1da1ca354bb6271c328ac2a7e29504b0ca2f84d01"
    )


def test_compute_support_identity_is_producer_specific(inputs):
    bathymetry = load(inputs)
    other = load_study_support(
        load_study_config(inputs.path),
        producer="shoreline_proximity",
        mask_relative_path="../Data/mask.geojson",
        compute_memberships=inputs.halo,
    )
    assert (
        other.provenance()["consumer_identity_sha256"]
        != bathymetry.provenance()["consumer_identity_sha256"]
    )
    config = SimpleNamespace(
        h3_resolution=6, h3_grid_path=inputs.root / "absent.parquet"
    )
    with pytest.raises(ValueError, match="own producer support"):
        load_h3_cells(config, study_support=other)


def test_overlap_candidate_budget_is_explicit_soft_postcheck(monkeypatch):
    allocated = []

    def oversized(*_):
        candidates = set(range(89))
        allocated.append(len(candidates))
        return candidates

    monkeypatch.setattr("seascape.study_support.polygon_to_cells_overlap", oversized)
    with pytest.raises(StudyConfigError, match="Soft.*after enumeration"):
        _overlap(box(-123.50001, 48.50001, -123.5, 48.50002), 6, 20)
    assert allocated == [89]


@pytest.fixture
def producer_inputs(inputs):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from seascape.study_routes import PinnedInput

    support = load(inputs)
    focal = support.reporting_r6[0]
    halo = next(
        cell
        for cell in support.compute_r6
        if cell not in support.reporting_r6 and h3.grid_distance(focal, cell) == 1
    )
    bounds = unary_union([cell_to_polygon(cell) for cell in support.compute_r6]).bounds
    step = 1 / 240
    west, south, east, north = bounds
    width = int(np.ceil((east - west) / step)) + 2
    height = int(np.ceil((north - south) / step)) + 2
    transform = from_origin(west - step, north + step, step, step)
    data = np.full((height, width), -32767, dtype="float32")
    counts = {}
    for row in range(height):
        for column in range(width):
            lon, lat = transform * (column + 0.5, row + 0.5)
            cell = h3.latlng_to_cell(lat, lon, 6)
            if cell in (focal, halo):
                data[row, column] = -10 if cell == focal else -100
                counts[cell] = counts.get(cell, 0) + 1
    raster_path = inputs.root / "synthetic-depth.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-32767,
    ) as dst:
        dst.write(data, 1)
    metadata = json.dumps(
        {
            "version": "synthetic-test-v1",
            "observation_period": "none: synthetic fixture",
            "license": "Apache-2.0 synthetic fixture",
            "evidence_type": "synthetic software acceptance",
        }
    )

    def pin(filename):
        raw = (inputs.root / filename).read_bytes()
        return PinnedInput(
            "../Data/" + filename, hashlib.sha256(raw).hexdigest(), metadata
        )

    graphs = {}
    for resolution in (6, 8):
        cells = support.cells(resolution, role="compute")
        rows = []
        for cell in cells:
            targets = {cell}
            if resolution == 6 and cell == focal:
                targets.add(halo)
            elif resolution == 6 and cell == halo:
                targets.add(focal)
            elif resolution == 8:
                targets.update(set(h3.grid_disk(cell, 1)).intersection(cells))
            for target in sorted(targets):
                rows.append(
                    {
                        "SOURCE_H3_INDEX": cell,
                        "TARGET_H3_INDEX": target,
                        "H3_RESOLUTION": resolution,
                        "MINIMUM_HOP_COUNT": 0 if cell == target else 1,
                        "NETWORK_DISTANCE_M": 0.0 if cell == target else 100.0,
                        "CONNECTIVITY_STATUS": "synthetic",
                        "QC_REASON": "synthetic_not_qualified",
                        "WATER_MASK_VERSION": "synthetic-only",
                        "SPATIAL_SUPPORT_VERSION": "synthetic-only",
                    }
                )
        filename = f"synthetic-graph-r{resolution}.parquet"
        pd.DataFrame(rows).to_parquet(inputs.root / filename, index=False)
        base_pin = pin(filename)
        source_metadata = json.loads(base_pin.metadata_json)
        membership = next(
            m
            for m in support.provenance()["compute_memberships"]
            if m["resolution"] == resolution
        )
        source_metadata.update(
            {
                "study_config_sha256": inputs.config
                and load_study_config(inputs.path).config_sha256,
                "mask_sha256": support.mask_sha256,
                "compute_membership_sha256": membership["sha256"],
                "maximum_graph_hops": 1,
            }
        )
        graphs[resolution] = replace(
            base_pin, metadata_json=json.dumps(source_metadata)
        )
    config = SimpleNamespace(
        h3_resolution=6,
        bathymetry_sign="positive_down",
        depth_quantiles=(0.25, 0.75),
        local_depth_anomaly_neighborhood_rings=1,
        isobath_levels_m=(50.0,),
        isobath_distance_projected_crs="EPSG:32610",
    )
    return SimpleNamespace(
        inputs=inputs,
        study=load_study_config(inputs.path),
        support=support,
        focal=focal,
        halo=halo,
        counts=counts,
        raster=pin("synthetic-depth.tif"),
        graphs=graphs,
        config=config,
        pin=pin,
    )


def run_bathymetry(p, **kwargs):
    from seascape.study_routes import route_bathymetry

    return route_bathymetry(
        p.config,
        p.study,
        p.support,
        raster=p.raster,
        neighborhoods=p.graphs[p.config.h3_resolution],
        maximum_graph_hops=1,
        **kwargs,
    )


def test_actual_bathymetry_routing_computes_halo_before_reporting_trim(producer_inputs):
    p = producer_inputs
    result = run_bathymetry(p)
    frame = result.reporting.set_index("H3_INDEX")
    assert set(frame.index) == set(p.support.reporting_r6)
    assert p.halo not in frame.index
    assert frame.loc[p.focal, "BATHYMETRY"] == 10
    assert frame.loc[p.focal, "BATHYMETRY_PIXEL_COUNT"] == p.counts[p.focal]
    assert frame.loc[p.focal, "BATHYMETRY_LOCAL_ANOMALY"] == pytest.approx(-90)
    missing = frame.loc[frame.index != p.focal]
    assert missing.BATHYMETRY.isna().all()
    assert missing.BATHYMETRY_PIXEL_COUNT.isna().all()
    assert (missing.NATIVE_SAMPLE_STATUS == "no_valid_native_marine_pixels").all()
    assert result.compute.set_index("H3_INDEX").loc[p.halo, "BATHYMETRY"] == 100
    path = p.inputs.root / "reporting-depth.parquet"
    result.write_reporting(path)
    import pyarrow.parquet as pq

    embedded = json.loads(
        pq.ParquetFile(path).metadata.metadata[b"marinecast_study_route"]
    )
    assert embedded["artifact_role"] == "reporting"
    assert embedded["release_eligible"] is False
    assert embedded["sources"][0]["raw_sha256"] == p.raster.sha256
    assert embedded["missing_native_sample_count"] == len(missing)
    assert (
        embedded["sources"][0]["source_metadata"]["observation_period"]
        == "none: synthetic fixture"
    )
    with pytest.raises(FileExistsError):
        result.write_reporting(path)


def test_actual_native_r8_bathymetry_and_geomorphometry_route(producer_inputs):
    from seascape.seafloor_physiography.geomorphometry.build import (
        load_geomorphometry_config,
    )
    from seascape.study_routes import route_geomorphometry

    p = producer_inputs
    p.config.h3_resolution = 8
    bathymetry = run_bathymetry(p)
    assert bathymetry.reporting.H3_INDEX.tolist() == list(p.support.native_reporting_r8)
    bathymetry.write_compute(p.inputs.root / "compute-depth-r8.parquet")
    support = load_study_support(
        p.study,
        producer="geomorphometry",
        mask_relative_path="../Data/mask.geojson",
        compute_memberships=p.inputs.halo,
    )
    config = replace(
        load_geomorphometry_config(),
        neighbor_ring=1,
        neighborhood_rings=(1,),
        openness_radius_rings=1,
    )
    result = route_geomorphometry(
        config,
        p.study,
        support,
        bathymetry=p.pin("compute-depth-r8.parquet"),
        raster=p.raster,
        neighborhoods=p.graphs[8],
        maximum_graph_hops=1,
    )
    assert result.reporting.H3_INDEX.tolist() == list(support.native_reporting_r8)
    valid = result.compute.SLOPE_MEAN_NATIVE_RASTER.dropna()
    assert len(valid) > 0
    assert (valid == 0).any()  # Flat observed native stencils remain measured zero.
    assert (
        result.provenance()["sources"][0]["upstream_route_identity_sha256"]
        == bathymetry.provenance()["route_identity_sha256"]
    )
    assert result.provenance()["production_ready"] is False


@pytest.mark.parametrize(
    "bad",
    [
        "source_hash",
        "graph_keys",
        "graph_rows",
        "source_bytes",
        "source_pixels",
        "identity",
    ],
)
def test_routed_inputs_fail_before_output(producer_inputs, bad):
    p = producer_inputs
    kwargs = {}
    if bad == "source_hash":
        p.raster = replace(p.raster, sha256="0" * 64)
    elif bad == "graph_keys":
        filename = "invalid-graph.parquet"
        frame = pd.read_parquet(p.inputs.root / "synthetic-graph-r6.parquet")
        frame.loc[0, "TARGET_H3_INDEX"] = h3.latlng_to_cell(0, 0, 6)
        frame.to_parquet(p.inputs.root / filename, index=False)
        p.graphs[6] = replace(p.pin(filename), metadata_json=p.graphs[6].metadata_json)
    elif bad == "graph_rows":
        frame = pd.read_parquet(p.inputs.root / "synthetic-graph-r6.parquet").iloc[1:]
        frame.to_parquet(p.inputs.root / "invalid-graph.parquet", index=False)
        p.graphs[6] = replace(
            p.pin("invalid-graph.parquet"), metadata_json=p.graphs[6].metadata_json
        )
    elif bad == "source_bytes":
        kwargs["max_input_bytes"] = 1
    elif bad == "source_pixels":
        kwargs["max_pixels_and_rows"] = 1
    else:
        p.support = replace(p.support, config_sha256="0" * 64)
    with pytest.raises((StudyConfigError, ValueError)):
        run_bathymetry(p, **kwargs)


def test_reviewer_thin_strip_fails_at_soft_candidate_postcheck():
    with pytest.raises(StudyConfigError, match="Soft.*after enumeration"):
        _overlap(box(-125, 48.5, -124.9999999, 49), 8, 20)


def test_partial_native_footprint_retains_null_rows_and_coverage(producer_inputs):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    p = producer_inputs
    lat, lon = h3.cell_to_latlng(p.focal)
    step = 1 / 240
    with rasterio.open(
        p.inputs.root / "partial.tif",
        "w",
        driver="GTiff",
        width=3,
        height=3,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(lon - 1.5 * step, lat + 1.5 * step, step, step),
        nodata=-32767,
    ) as dst:
        dst.write(np.full((3, 3), -20, dtype="float32"), 1)
    p.raster = p.pin("partial.tif")
    result = run_bathymetry(p)
    frame = result.reporting.set_index("H3_INDEX")
    assert frame.loc[p.focal, "BATHYMETRY"] == 20
    assert frame.loc[p.focal, "BATHYMETRY_PIXEL_COUNT"] == 9
    assert (
        frame.loc[p.focal, "NATIVE_EXTENT_STATUS"]
        == "cell_extends_outside_native_extent"
    )
    assert result.provenance()["native_extent_partial_count"] == len(frame)
    assert frame.loc[frame.index != p.focal, "BATHYMETRY"].isna().all()


def test_graph_pins_bind_current_mask_and_context(producer_inputs):
    p = producer_inputs
    metadata = json.loads(p.graphs[6].metadata_json)
    metadata["mask_sha256"] = "0" * 64
    p.graphs[6] = replace(p.graphs[6], metadata_json=json.dumps(metadata))
    with pytest.raises(StudyConfigError, match="graph metadata"):
        run_bathymetry(p)


def test_geomorphometry_refuses_reporting_only_upstream(producer_inputs):
    from seascape.seafloor_physiography.geomorphometry.build import (
        load_geomorphometry_config,
    )
    from seascape.study_routes import route_geomorphometry

    p = producer_inputs
    p.config.h3_resolution = 8
    bathymetry = run_bathymetry(p)
    bathymetry.write_reporting(p.inputs.root / "reporting-only-r8.parquet")
    support = load_study_support(
        p.study,
        producer="geomorphometry",
        mask_relative_path="../Data/mask.geojson",
        compute_memberships=p.inputs.halo,
    )
    config = replace(
        load_geomorphometry_config(),
        neighbor_ring=1,
        neighborhood_rings=(1,),
        openness_radius_rings=1,
    )
    with pytest.raises(StudyConfigError, match="routed compute bathymetry provenance"):
        route_geomorphometry(
            config,
            p.study,
            support,
            bathymetry=p.pin("reporting-only-r8.parquet"),
            raster=p.raster,
            neighborhoods=p.graphs[8],
            maximum_graph_hops=1,
        )
