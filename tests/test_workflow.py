from __future__ import annotations

import json
from pathlib import Path

import pytest

from seascape.utils.artifacts import build_manifest
from seascape.workflow import (
    DomainBuildContext,
    DomainBuildStage,
    _environment_domain_config,
    _seed_canonical_stage,
    run_domain_layer_build,
    selected_stages,
)


def _write_runner(relative: str, calls: list[str], *, fail: bool = False):
    def run(context) -> None:
        calls.append(relative)
        if fail:
            raise RuntimeError(f"failed {relative}")
        path = context.candidate_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    return run


def test_environment_domain_config_resolves_candidate_include(tmp_path: Path) -> None:
    include = tmp_path / "candidate/.seascape/config/environment_seascape.yaml"
    include.parent.mkdir(parents=True)
    include.write_text("schema_version: 2\n", encoding="utf-8")
    project = tmp_path / "candidate/.seascape/config/project.yaml"
    project.write_text(
        f"SEASCAPE_LAYER: {include}\n",
        encoding="utf-8",
    )
    context = DomainBuildContext(
        config_path=project,
        source_config_path=tmp_path / "config/data/project.yaml",
        candidate_root=tmp_path / "candidate",
        canonical_root=tmp_path,
    )

    assert _environment_domain_config(context, "SEASCAPE_LAYER") == include


def test_dependency_closure_is_topological_and_rejects_invalid_graphs() -> None:
    def noop(_context):
        return None

    stages = (
        DomainBuildStage("root", "root", noop),
        DomainBuildStage("middle", "middle", noop, dependencies=("root",)),
        DomainBuildStage("leaf", "leaf", noop, dependencies=("middle",)),
    )
    assert [stage.name for stage in selected_stages(only=("leaf",), stages=stages)] == [
        "root",
        "middle",
        "leaf",
    ]
    with pytest.raises(ValueError, match="unknown dependencies"):
        selected_stages(stages=(DomainBuildStage("bad", "bad", noop, dependencies=("missing",)),))
    with pytest.raises(ValueError, match="dependency cycle"):
        selected_stages(
            stages=(
                DomainBuildStage("left", "left", noop, dependencies=("right",)),
                DomainBuildStage("right", "right", noop, dependencies=("left",)),
            )
        )


def test_resume_reuses_only_valid_stage_state_and_force_rebuilds(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("base_directory: .\n", encoding="utf-8")
    candidate = tmp_path / "candidate"
    calls: list[str] = []
    stages = (
        DomainBuildStage(
            "root",
            "root",
            _write_runner("root.txt", calls),
            declared_outputs=("root.txt",),
        ),
        DomainBuildStage(
            "leaf",
            "leaf",
            _write_runner("leaf.txt", calls),
            dependencies=("root",),
            declared_outputs=("leaf.txt",),
        ),
    )
    first = run_domain_layer_build(
        config_path=config,
        only=("leaf",),
        candidate_root=candidate,
        publish=False,
        stage_definitions=stages,
    )
    assert [result.status for result in first] == ["complete", "complete"]
    resumed = run_domain_layer_build(
        config_path=config,
        only=("leaf",),
        candidate_root=candidate,
        publish=False,
        resume=True,
        stage_definitions=stages,
    )
    assert [result.status for result in resumed] == ["reused", "reused"]
    forced = run_domain_layer_build(
        config_path=config,
        only=("leaf",),
        candidate_root=candidate,
        publish=False,
        resume=True,
        overwrite=True,
        stage_definitions=stages,
    )
    assert [result.status for result in forced] == ["complete", "complete"]
    assert calls == ["root.txt", "leaf.txt", "root.txt", "leaf.txt"]


def test_resume_invalidates_when_included_domain_config_changes(tmp_path: Path) -> None:
    include = tmp_path / "seascape.yaml"
    include.write_text("schema_version: 1\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"SEASCAPE_LAYER: {include}\n", encoding="utf-8")
    calls: list[str] = []
    stage = DomainBuildStage(
        "fixture",
        "fixture",
        _write_runner("artifact.txt", calls),
        declared_outputs=("artifact.txt",),
    )
    candidate = tmp_path / "candidate"
    run_domain_layer_build(
        config_path=config,
        candidate_root=candidate,
        publish=False,
        stage_definitions=(stage,),
    )
    include.write_text("schema_version: 2\n", encoding="utf-8")
    result = run_domain_layer_build(
        config_path=config,
        candidate_root=candidate,
        publish=False,
        resume=True,
        stage_definitions=(stage,),
    )

    assert result[0].status == "complete"
    assert calls == ["artifact.txt", "artifact.txt"]


def test_resume_grants_overwrite_only_to_invalidated_candidate_stage(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("base_directory: .\n", encoding="utf-8")
    observed_overwrite: list[bool] = []

    def runner(context) -> None:
        observed_overwrite.append(context.overwrite)
        path = context.candidate_root / "artifact.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("valid", encoding="utf-8")

    stage = DomainBuildStage(
        "fixture",
        "fixture",
        runner,
        declared_outputs=("artifact.txt",),
    )
    candidate = tmp_path / "candidate"
    run_domain_layer_build(
        config_path=config,
        candidate_root=candidate,
        publish=False,
        stage_definitions=(stage,),
    )
    (candidate / "artifact.txt").write_text("stale", encoding="utf-8")
    run_domain_layer_build(
        config_path=config,
        candidate_root=candidate,
        publish=False,
        resume=True,
        stage_definitions=(stage,),
    )

    assert observed_overwrite == [False, True]


def test_continue_on_error_blocks_descendants_but_runs_independent_branch(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("base_directory: .\n", encoding="utf-8")
    calls: list[str] = []
    stages = (
        DomainBuildStage("failed", "failed", _write_runner("failed", calls, fail=True)),
        DomainBuildStage(
            "blocked",
            "blocked",
            _write_runner("blocked.txt", calls),
            dependencies=("failed",),
            declared_outputs=("blocked.txt",),
        ),
        DomainBuildStage(
            "independent",
            "independent",
            _write_runner("independent.txt", calls),
            declared_outputs=("independent.txt",),
        ),
    )
    results = run_domain_layer_build(
        config_path=config,
        candidate_root=tmp_path / "candidate",
        publish=False,
        continue_on_error=True,
        stage_definitions=stages,
    )
    assert {result.name: result.status for result in results} == {
        "failed": "failed",
        "blocked": "blocked_dependency",
        "independent": "complete",
    }
    assert calls == ["failed", "independent.txt"]


def test_skipped_stage_can_seed_only_checksum_valid_canonical_v3_artifacts(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    candidate = tmp_path / "candidate"
    relative_artifact = Path(
        "data/processed/domain/environmental_layer/seascape/fixture/artifact.txt"
    )
    relative_manifest = relative_artifact.with_name("fixture_manifest.json")
    artifact = canonical / relative_artifact
    artifact.parent.mkdir(parents=True)
    artifact.write_text("canonical", encoding="utf-8")
    payload = build_manifest(
        dataset_family="environment.seascape.fixture",
        run_id="fixture",
        resolved_config={},
        artifacts=[artifact],
        project_root=canonical,
        sources=[
            {
                "name": "fixture",
                "license": "fixture",
                "observation_period": "fixture",
                "redistribution_restrictions": "none",
                "source_warning": "fixture",
            }
        ],
        upstream_artifacts=[],
        attribution=[{"text": "fixture", "license": "fixture"}],
        source_completeness="complete",
    )
    (canonical / relative_manifest).write_text(json.dumps(payload), encoding="utf-8")
    stage = DomainBuildStage(
        "fixture",
        "fixture",
        lambda _context: None,
        declared_outputs=(str(relative_artifact),),
        declared_manifests=(str(relative_manifest),),
    )

    assert _seed_canonical_stage(
        stage,
        canonical_root=canonical,
        candidate_root=candidate,
    )
    assert (candidate / relative_artifact).read_text(encoding="utf-8") == "canonical"
    artifact.write_text("tampered", encoding="utf-8")
    second_candidate = tmp_path / "second-candidate"
    assert not _seed_canonical_stage(
        stage,
        canonical_root=canonical,
        candidate_root=second_candidate,
    )
    assert not second_candidate.exists()
