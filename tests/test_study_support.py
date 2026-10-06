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
