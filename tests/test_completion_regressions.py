"""Reproductions from the October completion review; all inputs are synthetic."""

import json

import pytest
from shapely.geometry import LineString, box

from seascape.coastal_configuration.passage_sections import measure_passage_section
from seascape.products import resolve_product
from seascape.publication import SeascapeReleasePublisher
from seascape.release import publish_candidate_release
from tests.test_products import _candidate_fixture


def test_audit_rejects_inputs_changed_during_validation(tmp_path, monkeypatch):
    import yaml

    from seascape import release

    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"products": {"p": {"metric_family": "seascape"}}})
    )
    monkeypatch.setattr(release, "_catalog_table_audit", lambda *args: [])
    monkeypatch.setattr(
        release,
        "_governance_audit",
        lambda *args: {"feature_eligibility_complete": True},
    )
    for name in ("_depth_band_audit", "_shoreline_audit", "_radius_operator_audit"):
        monkeypatch.setattr(release, name, lambda *args: [])

    def mutate(*args):
        catalog.write_text("changed during audit")
        return {}

    monkeypatch.setattr(release, "_manifest_audit", mutate)
    with pytest.raises(ValueError, match="changed during release audit"):
        release.build_release_audit(tmp_path, catalog)


def test_promotion_rechecks_after_taking_writer_lock(tmp_path, monkeypatch):
    candidate, workspace = tmp_path / "candidate", tmp_path / "workspace"
    source = _candidate_fixture(candidate, b"fixture")
    enter = SeascapeReleasePublisher.__enter__

    def mutate(self):
        publisher = enter(self)
        source.write_bytes(b"changed while waiting for writer lock")
        return publisher

    monkeypatch.setattr(SeascapeReleasePublisher, "__enter__", mutate)
    with pytest.raises(ValueError, match="changed before publication"):
        publish_candidate_release(
            canonical_project_root=workspace, candidate_project_root=candidate
        )
    assert not (workspace / "data").exists()


def section(water, depth_at, half_length=150):
    passage = box(-100, 0, 100, 500)
    return measure_passage_section(
        "p",
        passage,
        LineString([(0, 0), (0, 500)]),
        water,
        depth_at,
        along_axis_m=250,
        half_length_m=half_length,
        sample_step_m=100,
        depth_threshold_m=25,
        tangent_scale_m=50,
    )


@pytest.mark.parametrize(
    "depths,total,longest",
    [
        ((50, 0, 50), 100, 50),
        ((0, 50, 0), 100, 100),
        ((50, 25, 50), 200, 200),
        ((25, 25, 25), 200, 200),
        ((50, None, 50), None, None),
    ],
)
def test_threshold_runs_preserve_shallow_gaps(depths, total, longest):
    result = section(
        box(-100, 0, 100, 500), lambda x, y: depths[round((x + 100) / 100)]
    )
    assert result.width_at_depth_threshold_m == total
    assert result.max_contiguous_width_at_depth_threshold_m == longest


@pytest.mark.parametrize(
    "water", [box(-1000, -1000, 1000, 1000), box(-100, 0, 1000, 500)]
)
def test_passage_extent_is_not_an_observed_bank(water):
    result = section(water, lambda x, y: 50)
    assert result.bank_status == "bank_censored"
    assert result.cross_section_area_m2 is None
    assert result.valid_integral_area_m2 == 10_000


def test_section_endpoint_on_bank_remains_censored():
    result = section(box(-100, 0, 100, 500), lambda x, y: 50, half_length=100)
    assert result.bank_status == "bank_censored"
    assert result.cross_section_area_m2 is None


@pytest.mark.parametrize(
    "relative",
    [
        "data/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry/BATHYMETRY_RES_6.parquet",
        "data/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry/bathymetry_manifest.json",
        "config/feature_catalog.yaml",
        "config/data/environment_seascape.yaml",
        "docs/products.md",
        "data/processed/domain/environmental_layer/seascape/new-file.txt",
    ],
)
def test_promotion_rejects_stale_audit_without_changing_release(tmp_path, relative):
    workspace, candidate = tmp_path / "workspace", tmp_path / "candidate"
    _candidate_fixture(candidate, b"original")
    publish_candidate_release(
        canonical_project_root=workspace, candidate_project_root=candidate
    )
    first = resolve_product(workspace=workspace, product="bathymetry", resolution=6)
    before = {
        str(p.relative_to(workspace)): p.read_bytes()
        for p in workspace.rglob("*")
        if p.is_file()
    }
    (candidate / relative).write_text("changed after audit")
    with pytest.raises(ValueError, match="bound release audit"):
        publish_candidate_release(
            canonical_project_root=workspace, candidate_project_root=candidate
        )
    assert {
        str(p.relative_to(workspace)): p.read_bytes()
        for p in workspace.rglob("*")
        if p.is_file()
    } == before
    assert (
        resolve_product(workspace=workspace, product="bathymetry", resolution=6)
        == first
    )


@pytest.mark.parametrize("passed", ["true", 1, False, None])
def test_promotion_requires_boolean_pass(tmp_path, passed):
    candidate = tmp_path / "candidate"
    _candidate_fixture(candidate, b"fixture")
    audit = (
        candidate
        / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    )
    payload = json.loads(audit.read_text())
    payload["artifact_release_passed"] = passed
    audit.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="has not passed"):
        publish_candidate_release(
            canonical_project_root=tmp_path / "workspace",
            candidate_project_root=candidate,
        )
    assert not (tmp_path / "workspace").exists()


def test_promotion_rejects_unbound_legacy_audit(tmp_path):
    candidate = tmp_path / "candidate"
    _candidate_fixture(candidate, b"fixture")
    audit = (
        candidate
        / "outputs/domains/environmental_layer/seascape/seascape_release_audit.json"
    )
    audit.write_text(json.dumps({"artifact_release_passed": True}))
    with pytest.raises(ValueError, match="bound release audit"):
        publish_candidate_release(
            canonical_project_root=tmp_path / "workspace",
            candidate_project_root=candidate,
        )


def test_promotion_checks_actual_staged_bytes(tmp_path, monkeypatch):
    candidate, workspace = tmp_path / "candidate", tmp_path / "workspace"
    _candidate_fixture(candidate, b"fixture")
    original = SeascapeReleasePublisher.stage_candidate

    def tamper(self, relative, **kwargs):
        staged = original(self, relative, **kwargs)
        if str(relative).endswith(".parquet"):
            staged.write_bytes(b"concurrent change")
        return staged

    monkeypatch.setattr(SeascapeReleasePublisher, "stage_candidate", tamper)
    with pytest.raises(ValueError, match="changed during staging"):
        publish_candidate_release(
            canonical_project_root=workspace, candidate_project_root=candidate
        )
    assert not (workspace / "data").exists()
    assert not list((workspace / ".seascape/releases").glob("*"))
