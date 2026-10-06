"""Native contract tests use synthetic sources only; no real qualification claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import rasterio

from seascape._study_contract import canonical_bytes
from seascape.study import StudyConfigError
from seascape.study_native import (
    NativeMonitor,
    NativeReceipt,
    _support_bindings,
    inspect_native_source,
    measured_native_header,
    run_native_source_probe,
    run_real_source_pilot,
    verify_graph_dependency_closure,
)
from tests import test_study_support as fixtures


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    return fixtures.inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def producer_inputs(inputs):
    return fixtures.producer_inputs.__wrapped__(inputs)


def artifact(path, root, role, encoding):
    return {
        "role": role,
        "relative_path": "../Data/" + str(path.relative_to(root)),
        "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "byte_size": path.stat().st_size,
        "encoding": encoding,
    }


def receipt_for(p):
    root = p.inputs.root
    raster = root / "synthetic-depth.tif"
    evidence = root / "source-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "synthetic": True,
                "rights": "test only",
                "vertical_reference": "synthetic metre elevations",
            }
        )
    )
    proof = artifact(evidence, root, "source_documentation", "JSON")
    with rasterio.open(raster) as source:
        header = measured_native_header(source)
    record = {
        "interface_version": 1,
        "scope": "native_source_probe",
        "source": artifact(raster, root, "native_elevation", "GeoTIFF"),
        "evidence": [proof],
        "source_identity": {
            "provider_asset_id": "synthetic-test",
            "evidence_type": "synthetic_software_acceptance",
            "archive_artifact": None,
            "member_name": "synthetic-depth.tif",
            "version": "synthetic-v1",
            "observation_period": None,
            "date_precision": "unknown",
            "retrieved_at": "2026-10-06T00:00:00Z",
            "as_of": "2026-10-06T00:00:00Z",
            "license_id": "synthetic-test-only",
            "license_evidence_sha256": proof["raw_sha256"],
            "interpretation_evidence_sha256": proof["raw_sha256"],
        },
        "measured_header": header,
        "interpretation": {
            "units": "m",
            "raw_sign": "negative_elevation",
            "output_sign": "positive_down",
            "vertical_reference": "synthetic-test-only",
            "vertical_reference_status": "documented_source_relative",
            "transformation": "none",
        },
        "probe_cells": list(p.support.compute_r6 + p.support.compute_r8),
        "execution_budget": {
            "network_bytes": 0,
            "workers": 1,
            "max_input_bytes_each": 16 * 1024**2,
            "max_total_staging_bytes": 128 * 1024**2,
            "max_decoded_pixels": 1_000_000,
            "max_rows": 100_000,
            "max_h3_candidates": 2000,
            "memory_stop_bytes": 2 * 1024**3,
            "elapsed_stop_seconds": 900,
        },
        "qualification": None,
    }
    path = p.inputs.path.parent / "native-receipt.json"
    path.write_bytes(canonical_bytes(record))
    return path, record


def test_probe_retains_exact_inputs_and_full_cell_coverage(producer_inputs, tmp_path):
    p = producer_inputs
    path, record = receipt_for(p)
    result = run_native_source_probe(path, p.inputs.root, tmp_path / "probe")
    assert result["shared_reporting_qualified"] is False
    assert result["production_ready"] is False
    generation = Path(result["generation"])
    coverage = pd.read_parquet(generation / "native-coverage.parquet")
    r6 = coverage[coverage.H3_RESOLUTION == 6].set_index("H3_INDEX")
    assert r6.loc[p.focal, "VALID_MARINE_PIXELS"] == p.counts[p.focal]
    assert all(
        coverage.EXPECTED_PIXELS
        == coverage[
            [
                "VALID_MARINE_PIXELS",
                "LAND_PIXELS",
                "NODATA_PIXELS",
                "OUTSIDE_CROP_PIXELS",
            ]
        ].sum(axis=1)
    )
    assert (coverage.NODATA_PIXELS > 0).any()
    assert result["measured"]["isobath"]["global_nearest_claim"] is False
    assert result["source_identity"]["observation_period"] is None
    original = (p.inputs.root / "synthetic-depth.tif").read_bytes()
    assert (generation / "input-0.bin").read_bytes() == original


@pytest.mark.parametrize(
    "change", ["sha", "header", "scale", "units", "unknown_date", "scope", "budget"]
)
def test_native_receipt_rejects_before_generation(producer_inputs, tmp_path, change):
    p = producer_inputs
    path, record = receipt_for(p)
    if change == "sha":
        record["source"]["raw_sha256"] = "0" * 64
    elif change == "header":
        record["measured_header"]["width"] += 1
    elif change == "scale":
        record["measured_header"]["scale"] = 2
    elif change == "units":
        record["interpretation"]["units"] = "ft"
    elif change == "unknown_date":
        record["source_identity"]["observation_period"] = "2009-01-01"
    elif change == "scope":
        record["scope"] = "regional_production"
    else:
        record["execution_budget"]["max_total_staging_bytes"] = 1
    path.write_bytes(canonical_bytes(record))
    workspace = tmp_path / "unwritten"
    with pytest.raises(StudyConfigError):
        run_native_source_probe(path, p.inputs.root, workspace)
    assert not workspace.exists()


def test_graph_missing_neighbor_and_compositional_depth_dependency():
    cells = ("a", "b", "c", "d", "e", "f")
    edges = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": cells[:-1],
            "TARGET_H3_INDEX": cells[1:],
            "EDGE_IS_WATER_PASSABLE": True,
        }
    )
    neighbors = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": ["a"] * 6,
            "TARGET_H3_INDEX": cells,
            "MINIMUM_HOP_COUNT": range(6),
        }
    )
    result = verify_graph_dependency_closure(
        edges, neighbors, ("a",), cells, 2, summary_hops=4, neighbor_fit_hops=1
    )
    assert result["required_depth_dependency_graph_hops"] == 5
    with pytest.raises(StudyConfigError, match="Incomplete"):
        verify_graph_dependency_closure(
            edges,
            neighbors.iloc[:-1],
            ("a",),
            cells,
            2,
            summary_hops=4,
            neighbor_fit_hops=1,
        )
    with pytest.raises(StudyConfigError, match="Incomplete"):
        verify_graph_dependency_closure(
            edges, neighbors, ("a",), cells[:-1], 2, summary_hops=4, neighbor_fit_hops=1
        )


def make_pilot(p):
    path, record = receipt_for(p)
    root = p.inputs.root
    record["scope"] = "real_source_pilot"
    configs = {
        r: SimpleNamespace(**(vars(p.config) | {"h3_resolution": r})) for r in (6, 8)
    }
    settings = {k: v for k, v in vars(p.config).items() if k != "h3_resolution"}
    bindings = _support_bindings(p.study, p.support, settings)
    mask = artifact(root / "mask.geojson", root, "water_mask", "GeoJSON")
    maskproof = root / "mask-qualification.json"
    maskproof.write_bytes(
        canonical_bytes(
            {
                "mask_raw_sha256": mask["raw_sha256"],
                "status": "source_relative_checked",
                "synthetic_test_only": True,
            }
        )
    )
    native = NativeReceipt.parse(
        canonical_bytes(record | {"scope": "native_source_probe"})
    )
    coverage, _ = inspect_native_source(
        (root / "synthetic-depth.tif").read_bytes(),
        native,
        NativeMonitor(native.budget),
    )
    covpath = root / "coverage.parquet"
    coverage.to_parquet(covpath, index=False)
    graphs = []
    for r in (6, 8):
        np = root / f"nodes-{r}.parquet"
        pd.DataFrame({"H3_INDEX": p.support.cells(r, role="compute")}).to_parquet(
            np, index=False
        )
        neighborhood = root / f"synthetic-graph-r{r}.parquet"
        frame = pd.read_parquet(neighborhood)
        edges = frame[frame.MINIMUM_HOP_COUNT == 1][
            ["SOURCE_H3_INDEX", "TARGET_H3_INDEX"]
        ]
        edges = edges[edges.SOURCE_H3_INDEX < edges.TARGET_H3_INDEX].copy()
        edges["EDGE_IS_WATER_PASSABLE"] = True
        ep = root / f"edges-{r}.parquet"
        edges.to_parquet(ep, index=False)
        e = artifact(ep, root, "graph_edges", "Parquet")
        n = artifact(np, root, "graph_nodes", "Parquet")
        pp = root / f"passability-{r}.json"
        pp.write_bytes(
            canonical_bytes(
                {
                    "status": "source_relative_checked",
                    "mask_raw_sha256": mask["raw_sha256"],
                    "edges_raw_sha256": e["raw_sha256"],
                    "nodes_raw_sha256": n["raw_sha256"],
                    "canonical_edge_and_connector_completeness": True,
                    "synthetic_test_only": True,
                }
            )
        )
        graphs.append(
            {
                "resolution": r,
                "nodes": n,
                "edges": e,
                "neighborhoods": artifact(
                    neighborhood, root, "graph_neighborhoods", "Parquet"
                ),
                "passability_evidence": artifact(pp, root, "graph_lineage", "JSON"),
                "maximum_hops": 1,
            }
        )
    q = {
        "bindings": bindings,
        "method_settings": settings,
        "method_version": "synthetic-test-v1",
        "mask": {
            "artifact": mask,
            "revision": p.support.mask_revision,
            "encoding": "RFC7946_WGS84_Polygon_or_MultiPolygon_exact_UTF8_bytes",
            "source_qualification_artifact": artifact(
                maskproof, root, "mask_lineage", "JSON"
            ),
        },
        "coverage": artifact(covpath, root, "native_coverage", "Parquet"),
        "graphs": graphs,
        "checks": {
            k: "source_relative_checked"
            for k in (
                "mask_source_relative",
                "canonical_graph_edges_and_connectors",
                "source_interpretation",
            )
        },
        "evidence": record["evidence"],
    }
    qp = root / "qualification.json"
    qp.write_bytes(canonical_bytes(q))
    record["qualification"] = {
        "artifact": artifact(qp, root, "qualification", "JSON"),
        "method": "synthetic-test",
        "version": "v1",
        "producer": "bathymetry",
        "checked_at": "2026-10-06T00:00:00Z",
        "status": "source_relative_checked",
        "bindings": bindings,
        "evidence": record["evidence"],
    }
    path.write_bytes(canonical_bytes(record))
    return path, record, configs, q


def test_real_source_pilot_api_with_synthetic_bound_evidence(producer_inputs, tmp_path):
    p = producer_inputs
    path, record, configs, q = make_pilot(p)
    result = run_real_source_pilot(
        p.study, p.support, path, tmp_path / "pilot", configs
    )
    assert result["status"] == "software_contract_acceptance"
    assert result["real_source_pilot_executed"] is False
    assert result["artifact_release_passed"] is False
    assert result["optional_terrain_selected"] is False
    assert result["global_nearest_claim"] is False
    assert result["products"]["6"]["reporting_rows"] == len(p.support.reporting_r6)
    generation = Path(result["generation"])
    frame = pd.read_parquet(generation / "products/bathymetry_r6.parquet").set_index(
        "H3_INDEX"
    )
    assert frame.loc[p.focal, "BATHYMETRY_LOCAL_ANOMALY"] == -90
    assert not (tmp_path / "pilot/.seascape/releases").exists()


@pytest.mark.parametrize(
    "change", ["binding", "coverage", "graph", "mask", "unknown_datum"]
)
def test_real_pilot_evidence_rejects_before_writes(producer_inputs, tmp_path, change):
    p = producer_inputs
    path, record, configs, q = make_pilot(p)
    if change == "binding":
        record["qualification"]["bindings"]["study_config_sha256"] = "0" * 64
    elif change == "unknown_datum":
        record["interpretation"]["vertical_reference"] = "unknown"
        record["interpretation"]["vertical_reference_status"] = "unknown"
    else:
        if change == "coverage":
            q["coverage"]["raw_sha256"] = "0" * 64
        elif change == "graph":
            q["graphs"][0]["passability_evidence"]["raw_sha256"] = "0" * 64
        else:
            q["mask"]["revision"] = "wrong"
        qp = p.inputs.root / "qualification.json"
        qp.write_bytes(canonical_bytes(q))
        record["qualification"]["artifact"] = artifact(
            qp, p.inputs.root, "qualification", "JSON"
        )
    path.write_bytes(canonical_bytes(record))
    workspace = tmp_path / "unwritten"
    with pytest.raises(StudyConfigError):
        run_real_source_pilot(p.study, p.support, path, workspace, configs)
    assert not workspace.exists()


def test_native_unknown_retrieval_and_annual_precision(producer_inputs):
    path, record = receipt_for(producer_inputs)
    record["source_identity"]["retrieved_at"] = None
    record["source_identity"]["date_precision"] = "year"
    record["source_identity"]["observation_period"] = "2026"
    assert (
        NativeReceipt.parse(canonical_bytes(record)).source_identity["retrieved_at"]
        is None
    )
    record["source_identity"]["observation_period"] = "2026-01-01"
    with pytest.raises(StudyConfigError, match="precision"):
        NativeReceipt.parse(canonical_bytes(record))


def test_graph_fractional_hops_cannot_be_truncated():
    edges = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": ["a"],
            "TARGET_H3_INDEX": ["b"],
            "EDGE_IS_WATER_PASSABLE": [True],
        }
    )
    frame = pd.DataFrame(
        {
            "SOURCE_H3_INDEX": ["a", "a"],
            "TARGET_H3_INDEX": ["a", "b"],
            "MINIMUM_HOP_COUNT": [0.0, 1.5],
        }
    )
    with pytest.raises(StudyConfigError, match="no truncation"):
        verify_graph_dependency_closure(edges, frame, ("a",), ("a", "b"), 1)


def test_real_pilot_measured_coverage_detects_semantic_tampering(
    producer_inputs, tmp_path
):
    p = producer_inputs
    path, record, configs, q = make_pilot(p)
    cov = p.inputs.root / "coverage.parquet"
    frame = pd.read_parquet(cov)
    frame.loc[0, "VALID_MARINE_PIXELS"] += 1
    frame.to_parquet(cov, index=False)
    q["coverage"] = artifact(cov, p.inputs.root, "native_coverage", "Parquet")
    qp = p.inputs.root / "qualification.json"
    qp.write_bytes(canonical_bytes(q))
    record["qualification"]["artifact"] = artifact(
        qp, p.inputs.root, "qualification", "JSON"
    )
    path.write_bytes(canonical_bytes(record))
    workspace = tmp_path / "unwritten"
    with pytest.raises(StudyConfigError, match="independently measured"):
        run_real_source_pilot(p.study, p.support, path, workspace, configs)
    assert not workspace.exists()


def test_native_rss_budget_stops_before_any_generation(producer_inputs, tmp_path):
    p = producer_inputs
    path, record = receipt_for(p)
    record["execution_budget"]["memory_stop_bytes"] = 1
    path.write_bytes(canonical_bytes(record))
    workspace = tmp_path / "unwritten"
    with pytest.raises(StudyConfigError, match="RSS/time"):
        run_native_source_probe(path, p.inputs.root, workspace)
    assert not workspace.exists()


def test_declared_artifact_size_caps_actual_read(tmp_path, monkeypatch):
    from seascape.study_native import NativeArtifact

    limits = []
    monkeypatch.setattr(
        "seascape.study_native._read_pinned",
        lambda base, root, path, digest, limit: limits.append(limit) or b"abc",
    )
    pin = NativeArtifact("evidence", "small.json", "0" * 64, 3, "JSON")
    assert pin.capture(tmp_path, tmp_path, 16 * 1024**2) == b"abc"
    assert limits == [3]
