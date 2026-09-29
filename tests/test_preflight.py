from __future__ import annotations

import json
import os
import socket
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import rasterio
import yaml
from rasterio.transform import from_origin

from seascape.cli import initialize_workspace, main
from seascape.core.config.data import load_data_config
from seascape.preflight import preflight_build
from seascape.workflow import DOMAIN_LAYER_STAGES, run_domain_layer_build


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    initialize_workspace(root)
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(root))
    source = root / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(source.read_text())
    vector = root / "data/raw/fixture.geojson"
    vector.parent.mkdir(parents=True)
    vector.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": 1},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[-123, 48], [-122, 48], [-122, 49], [-123, 48]]
                            ],
                        },
                    }
                ],
            }
        )
    )
    for key in raw["water_geometry"]["download"]["sources"]:
        raw["water_geometry"]["download"]["sources"][key] = str(vector)
    source.write_text(yaml.safe_dump(raw))
    raster = root / "data/raw/bathymetry/GEBCO_2026_MODEL_AREA.tif"
    raster.parent.mkdir(parents=True)
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-123, 49, 0.1, 0.1),
    ) as dataset:
        dataset.write(np.full((4, 4), -5, dtype="float32"), 1)
    return root


def plan(root, **kwargs):
    return preflight_build(
        only=["seascape-geomorphometry"],
        candidate_root=root / ".seascape/candidate",
        **kwargs,
    )


def test_optional_selected_outlet_reports_unconfigured_ids(workspace):
    report = preflight_build(
        only=["seascape-selected-outlets"],
        candidate_root=workspace / ".seascape/candidate",
    )
    assert report["status"] == "failed"
    checks = [
        check for check in report["checks"]
        if check["stage"] == "seascape-selected-outlets"
    ]
    assert any(
        check["status"] == "invalid" and "selected_ids" in check["detail"]
        for check in checks
    )


def change(root, callback):
    file = root / "config/data/environment_seascape.yaml"
    raw = yaml.safe_load(file.read_text())
    callback(raw)
    file.write_text(yaml.safe_dump(raw))


def tree(root):
    return {
        str(p.relative_to(root)): (
            p.lstat().st_mode,
            p.read_bytes() if p.is_file() else None,
        )
        for p in root.rglob("*")
    }


def test_valid_selected_plan_and_exact_generated_intermediates(workspace):
    report = plan(workspace)
    assert report["status"] == "ready", report["checks"]
    assert [s["name"] for s in report["stages"]] == [
        "seascape-water-geometry",
        "h3-water-universe",
        "h3-marine-spatial-support",
        "seascape-bathymetry",
        "seascape-geomorphometry",
    ]
    inputs = [c for c in report["checks"] if c["path"] and c["stage"] != "plan"]
    assert sum(c["status"] == "ready" for c in inputs) == 8
    assert any(
        c["status"] == "generated_by_plan" and c["name"] == "bathymetry_path"
        for c in inputs
    )
    assert all(c["status"] != "missing_external" for c in inputs)
    assert not (workspace / ".seascape/candidate").exists()
    assert any("no pixel read" in p for c in inputs for p in c["performed"])


def test_missing_raster_is_external_not_a_generated_product(workspace):
    raster = workspace / "data/raw/bathymetry/GEBCO_2026_MODEL_AREA.tif"
    raster.unlink()
    report = plan(workspace)
    assert report["status"] == "failed"
    missing = [c for c in report["checks"] if c["status"] == "missing_external"]
    assert {c["stage"] for c in missing} == {
        "seascape-bathymetry",
        "seascape-geomorphometry",
    }
    assert all(c["path"] == str(raster) and c["corrective_action"] for c in missing)


def test_unrelated_family_inputs_do_not_block(workspace):
    change(workspace, lambda raw: raw.pop("kelp_habitat"))
    assert plan(workspace)["status"] == "ready"


@pytest.mark.parametrize(
    "content", ["[one, two]", "bad: [", "SEASCAPE_LAYER: absent.yaml\n"]
)
def test_bad_config_reports_failure_as_json(workspace, capsys, content):
    (workspace / "config/data/project.yaml").write_text(content)
    assert (
        main(
            [
                "--workspace",
                str(workspace),
                "build",
                "--dry-run",
                "--check-inputs",
                "--json",
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["checks"][0]["corrective_action"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw["geomorphometry"]["processing"].update(
            projected_crs="EPSG:2263"
        ),
        lambda raw: raw["bathymetry"]["processing"].update(
            bathymetry_sign="negative_elevation"
        ),
        lambda raw: raw["bathymetry"]["processing"].update(bathymetry_sign="invalid"),
        lambda raw: raw["geomorphometry"]["processing"].update(
            slope_upper_quantile=0.8
        ),
        lambda raw: raw["water_network"].update(spatial_support_version=""),
    ],
)
def test_scientific_declarations_use_existing_validators(workspace, mutation):
    change(workspace, mutation)
    report = plan(workspace)
    assert report["status"] == "failed"
    assert any(c["status"] == "invalid" and c["required"] for c in report["checks"])


def test_workspace_flag_precedence_and_environment_restoration(
    workspace, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path / "other"))
    monkeypatch.setenv("SEASCAPE_COMMON_CONFIG", "external-common.yaml")
    before = dict(os.environ)
    assert (
        main(
            [
                "--workspace",
                str(workspace),
                "build",
                "--only",
                "seascape-geomorphometry",
                "--dry-run",
                "--check-inputs",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["workspace"] == str(workspace)
    assert dict(os.environ) == before
    assert (
        main(
            [
                "--workspace",
                str(workspace),
                "build",
                "--only",
                "unknown",
                "--dry-run",
                "--check-inputs",
                "--json",
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert dict(os.environ) == before


def test_workspace_environment_and_cwd_defaults(workspace, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert plan(workspace)["workspace"] == str(workspace)
    monkeypatch.delenv("SEASCAPE_WORKSPACE")
    monkeypatch.chdir(workspace)
    assert plan(workspace)["status"] == "ready"


def test_unreadable_source_fails(workspace, monkeypatch):
    original = Path.open

    def denied(self, *args, **kwargs):
        if self.name == "GEBCO_2026_MODEL_AREA.tif":
            raise PermissionError("fixture access denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    report = plan(workspace)
    assert report["status"] == "failed"
    assert any(
        c["status"] == "invalid" and c["name"] == "source raster"
        for c in report["checks"]
    )


def test_no_network_build_hash_or_filesystem_mutation(workspace, monkeypatch):
    before = tree(workspace)

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight attempted execution, hash, network or write")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr("seascape.workflow._prepare_candidate_config", forbidden)
    monkeypatch.setattr("seascape.workflow.checksum_path", forbidden)
    monkeypatch.setattr(
        "seascape.seafloor_physiography.bathymetry.pipeline.run_pipeline", forbidden
    )
    monkeypatch.setattr(
        "seascape.seafloor_physiography.geomorphometry.build.build_geomorphometry",
        forbidden,
    )
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    assert plan(workspace)["status"] == "ready"
    assert tree(workspace) == before


def test_source_header_failure_is_not_ready(workspace):
    (workspace / "data/raw/bathymetry/GEBCO_2026_MODEL_AREA.tif").write_bytes(
        b"not a raster"
    )
    assert plan(workspace)["status"] == "failed"


def test_native_header_contract_preserved(workspace):
    raster = workspace / "data/raw/bathymetry/GEBCO_2026_MODEL_AREA.tif"
    with rasterio.open(raster, "r+") as dataset:
        dataset.crs = "EPSG:3857"
    report = plan(workspace)
    assert any(
        c["status"] == "invalid" and c["name"] == "native_raster_path"
        for c in report["checks"]
    )


def test_not_every_file_under_upstream_directory_is_generated(workspace):
    change(
        workspace,
        lambda raw: raw["geomorphometry"]["processing"].update(
            bathymetry_path="data/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry/WRONG.parquet"
        ),
    )
    report = plan(workspace)
    assert any(
        c["status"] == "missing_external" and c["name"] == "bathymetry_path"
        for c in report["checks"]
    )


def test_skip_is_unverified_and_cannot_claim_generation(workspace):
    report = plan(workspace, skip=["seascape-bathymetry"])
    assert report["status"] == "failed"
    assert any(c["required"] and c["status"] == "unverified" for c in report["checks"])
    assert not any(
        c["name"] == "bathymetry_path" and c["status"] == "generated_by_plan"
        for c in report["checks"]
    )


def test_output_escape_is_rejected_read_only(workspace):
    change(
        workspace,
        lambda raw: raw["bathymetry"]["processing"].update(
            processed_path=str(workspace / "canonical.parquet")
        ),
    )
    before = tree(workspace)
    assert plan(workspace)["status"] == "failed"
    assert tree(workspace) == before


def test_json_plan_and_plain_dry_run_keep_existing_semantics(workspace, capsys):
    args = [
        "--workspace",
        str(workspace),
        "build",
        "--only",
        "seascape-geomorphometry",
        "--dry-run",
    ]
    assert main([*args, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and report["checks"] == []
    assert main(args) == 0
    assert "dependency-expanded stage order" in capsys.readouterr().out
    assert not (workspace / ".seascape/candidates").exists()


@pytest.mark.parametrize("option", ["--check-inputs", "--json"])
def test_preflight_flags_require_dry_run(workspace, option):
    with pytest.raises(SystemExit) as exc:
        main(["--workspace", str(workspace), "build", option])
    assert exc.value.code == 2
    assert not (workspace / ".seascape/candidates").exists()


def test_credentials_never_emitted(workspace, capsys):
    change(
        workspace,
        lambda raw: raw["bathymetry"]["source"].update(
            raw_dir="https://user:supersecret@example.invalid/data?token=secret"
        ),
    )
    assert (
        main(
            [
                "--workspace",
                str(workspace),
                "build",
                "--dry-run",
                "--check-inputs",
                "--json",
                "--only",
                "seascape-bathymetry",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "supersecret" not in output and "token=secret" not in output
    assert json.loads(output)["status"] == "failed"


def test_execution_and_preflight_share_paths_and_dependencies(workspace, monkeypatch):
    before = plan(workspace)
    captured = []

    def runner(context):
        from seascape.preflight import _contract

        raw = load_data_config(context.config_path)
        contract = _contract(
            next(s for s in DOMAIN_LAYER_STAGES if s.name == names[len(captured)]),
            context.config_path,
            raw,
        )
        captured.append(
            {
                "outputs": [str(p) for p in contract.outputs],
                "inputs": [str(i.path) for i in contract.inputs],
            }
        )

    names = [s["name"] for s in before["stages"]]
    stages = [
        replace(s, runner=runner, declared_outputs=(), declared_manifests=())
        for s in DOMAIN_LAYER_STAGES
        if s.name in names
    ]
    result = run_domain_layer_build(
        config_path="config/data/project.yaml",
        only=["seascape-geomorphometry"],
        candidate_root=workspace / ".seascape/candidate",
        publish=False,
        stage_definitions=stages,
    )
    assert [r.name for r in result] == names
    assert all(r.status == "complete" for r in result)
    for entry, execution in zip(before["stages"], captured, strict=True):
        assert set(execution["outputs"]).issubset(entry["configured_outputs"])
        assert set(execution["inputs"]) == {
            c["path"]
            for c in before["checks"]
            if c["stage"] == entry["name"] and c["path"]
        }


def test_all_packaged_stages_report_missing_inputs_without_execution(workspace):
    report = preflight_build()
    assert len(report["stages"]) == 26
    assert report["status"] == "failed"
    assert any(
        c["status"] == "missing_external" and "HydroRIVERS" in c["name"]
        for c in report["checks"]
    )
    assert any(c["status"] == "unverified" and c["required"] for c in report["checks"])


def test_preview_does_not_leak_rendered_configuration(workspace):
    original = load_data_config("config/data/project.yaml")
    assert plan(workspace)["status"] == "ready"
    assert load_data_config("config/data/project.yaml") == original
    assert original["base_directory"] == "."


def test_configured_h3_output_is_not_the_old_declared_default(workspace):
    change(
        workspace,
        lambda raw: raw["h3_geometry"].update(
            output_grid_filename_template="CUSTOM_GRID_{res}.parquet"
        ),
    )
    report = plan(workspace)
    stage = next(s for s in report["stages"] if s["name"] == "h3-water-universe")
    assert any("CUSTOM_GRID_8.parquet" in p for p in stage["configured_outputs"])
    assert not any("H3_GRIDS_8.parquet" in p for p in stage["configured_outputs"])


def test_candidate_file_is_invalid_and_preserved(workspace):
    candidate = workspace / "candidate-file"
    candidate.write_bytes(b"preserve this")
    report = preflight_build(only=["seascape-water-geometry"], candidate_root=candidate)
    assert report["status"] == "failed"
    assert candidate.read_bytes() == b"preserve this"


def test_config_directory_symlink_escape_is_rejected(workspace, tmp_path):
    candidate = workspace / "candidate"
    (candidate / ".seascape").mkdir(parents=True)
    (candidate / ".seascape/config").symlink_to(tmp_path, target_is_directory=True)
    before = tree(workspace)
    report = preflight_build(only=["seascape-water-geometry"], candidate_root=candidate)
    assert report["status"] == "failed"
    assert tree(workspace) == before


def test_disguised_vrt_rejected_before_native_open(workspace, monkeypatch):
    raster = workspace / "data/raw/bathymetry/GEBCO_2026_MODEL_AREA.tif"
    raster.write_text(
        "<VRTDataset><SourceFilename>/vsicurl/https://example.invalid/secret</SourceFilename></VRTDataset>"
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("disguised TIFF reached native open")

    monkeypatch.setattr(rasterio, "open", forbidden)
    assert plan(workspace)["status"] == "failed"


def test_headers_do_not_read_raster_pixels(workspace, monkeypatch):
    original = rasterio.open

    class HeaderOnly:
        def __init__(self, dataset):
            self.dataset = dataset

        def __getattr__(self, name):
            if name == "read":
                raise AssertionError("pixel read during preflight")
            return getattr(self.dataset, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.dataset.close()

    monkeypatch.setattr(
        rasterio, "open", lambda *a, **kw: HeaderOnly(original(*a, **kw))
    )
    assert plan(workspace)["status"] == "ready"


def test_human_report_lists_checks_actions_destinations_limits(workspace, capsys):
    assert (
        main(
            [
                "--workspace",
                str(workspace),
                "build",
                "--only",
                "seascape-bathymetry",
                "--dry-run",
                "--check-inputs",
                "--publish",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Preflight: READY" in output and "checked:" in output and "output:" in output
    assert "Limit:" in output and "publication_requested: True" in output
    assert "requires a successful executed release audit" in output


def test_barrier_plan_identifies_configured_fluvial_prerequisites(workspace):
    change(
        workspace,
        lambda raw: raw["fluvial_barriers"]["processing"].update(
            fluvial_segments_path="data/raw/EXTERNAL_SEGMENTS.parquet"
        ),
    )
    report = preflight_build(only=["seascape-fluvial-barriers"])
    barrier = [c for c in report["checks"] if c["stage"] == "seascape-fluvial-barriers"]
    assert any(
        c["name"] == "fluvial_segments_path" and c["status"] == "missing_external"
        for c in barrier
    )
    assert any(
        c["name"] == "watershed_crosswalk_path" and c["status"] == "generated_by_plan"
        for c in barrier
    )


@pytest.mark.parametrize("mode", ["text", "json", "debug-json"])
@pytest.mark.parametrize("failure", ["yaml", "include", "reference", "q90"])
def test_loader_failures_have_safe_detail_and_original_debug_context(
    workspace, monkeypatch, capsys, mode, failure
):
    project = workspace / "config/data/project.yaml"
    domain = workspace / "config/data/environment_seascape.yaml"
    if failure == "yaml":
        domain.write_text("password: [PRIVATE_YAML_VALUE\n")
        expected, stage, location = "Invalid configuration YAML", "plan", domain
    elif failure == "include":
        domain.write_text("extends: missing-parent.yaml\n")
        expected, stage, location = (
            "Configuration is missing",
            "plan",
            domain.parent / "missing-parent.yaml",
        )
    elif failure == "reference":
        domain.write_text("value: ${missing.setting}\n")
        expected, stage, location = "missing.setting", "plan", domain
    else:
        change(
            workspace,
            lambda raw: raw["geomorphometry"]["processing"].update(
                slope_upper_quantile=0.8, password="PRIVATE_UNUSED_VALUE"
            ),
        )
        expected, stage, location = (
            "slope_upper_quantile must be 0.90 for the stable Q90 column contract",
            "seascape-geomorphometry",
            project,
        )
    before, environment = tree(workspace), dict(os.environ)

    def forbidden(*args, **kwargs):
        pytest.fail("Preflight attempted acquisition or a producer")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr("seascape.workflow.run_domain_layer_build", forbidden)
    monkeypatch.setattr(
        "seascape.seafloor_physiography.bathymetry.run_pipeline", forbidden
    )
    args = ["--workspace", str(workspace)]
    if mode == "debug-json":
        args.append("--debug")
    args += [
        "build",
        "--only",
        "seascape-geomorphometry",
        "--dry-run",
        "--check-inputs",
    ]
    if mode != "text":
        args.append("--json")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert expected in captured.out and expected in captured.err
    assert str(location) in captured.out and str(location) in captured.err
    assert "Action:" in captured.err and "Guide:" in captured.err
    assert "PRIVATE_" not in captured.out
    assert "Traceback" not in captured.out
    if mode != "debug-json":
        assert "PRIVATE_" not in captured.err and "Traceback" not in captured.err
    else:
        assert "Traceback (most recent call last)" in captured.err
        assert "original failure" in captured.err and "preflight_build" in captured.err
    if failure == "yaml":
        assert "line 2, column 1" in captured.out
    if mode != "text":
        report = json.loads(captured.out)
        assert report["status"] == "failed" and report["schema_version"] == 1
        check = next(c for c in report["checks"] if expected in c.get("detail", ""))
        assert check["stage"] == stage and check["status"] == "invalid"
        assert check["error_type"]
        # Existing readers still consume their required schema-1 fields.
        legacy = [
            (
                c["stage"],
                c["name"],
                c["status"],
                c["required"],
                c["path"],
                c["performed"],
                c["corrective_action"],
            )
            for c in report["checks"]
        ]
        assert any(row[0] == stage and row[2] == "invalid" for row in legacy)
    assert tree(workspace) == before
    assert dict(os.environ) == environment


@pytest.mark.parametrize("mode", ["text", "json"])
@pytest.mark.parametrize(
    "value",
    [
        "password=PRIVATE_VALUE",
        "token: PRIVATE_VALUE",
        "api_key=PRIVATE_VALUE",
        "https://user:PRIVATE_VALUE@example.invalid/config?token=PRIVATE_VALUE",
        "PRIVATE_VALUE",
    ],
)
def test_preflight_config_values_are_not_echoed(workspace, capsys, mode, value):
    change(workspace, lambda raw: raw["bathymetry"].update(area=value))
    args = [
        "--workspace",
        str(workspace),
        "build",
        "--only",
        "seascape-geomorphometry",
        "--dry-run",
        "--check-inputs",
    ]
    if mode == "json":
        args.append("--json")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert "PRIVATE_VALUE" not in captured.out + captured.err
    assert "Unknown common area" in captured.out + captured.err
    assert "seascape-bathymetry" in captured.err
    if mode == "json":
        assert json.loads(captured.out)["status"] == "failed"


@pytest.mark.parametrize("site", ["plan", "family"])
@pytest.mark.parametrize(
    "error",
    [
        ValueError("programming defect"),
        TypeError("programming defect"),
        RuntimeError("programming defect"),
    ],
)
def test_preflight_does_not_swallow_unrelated_errors(
    workspace, monkeypatch, site, error
):
    from seascape import preflight

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        preflight, "plan_domain_layer_build" if site == "plan" else "_contract", broken
    )
    before, environment = tree(workspace), dict(os.environ)
    with pytest.raises(type(error)) as caught:
        plan(workspace)
    assert caught.value is error
    assert tree(workspace) == before and dict(os.environ) == environment


def test_bc_only_water_preflight_excludes_unneeded_us_inputs(workspace):
    def bc_only(raw):
        raw["water_geometry"]["build"]["jurisdictions"] = ["bc"]
        for key in (
            "wsdot_shorelines_path",
            "ws_marine_shoreline_type_path",
            "us_coastline_path",
            "us_waters_path",
        ):
            raw["water_geometry"]["download"]["sources"][key] = "missing-us-source.shp"

    change(workspace, bc_only)
    report = preflight_build(
        only=["seascape-water-geometry"],
        candidate_root=workspace / ".seascape/candidate",
    )
    source_names = {item["name"] for item in report["checks"]}
    assert report["status"] == "ready", report["checks"]
    assert "ca_regions_path" in source_names and "tz_file_path" in source_names
    assert "us_coastline_path" not in source_names
    assert "wsdot_shorelines_path" not in source_names


def test_configured_tid_is_required_by_bathymetry_preflight(workspace):
    change(
        workspace,
        lambda raw: raw["bathymetry"]["source"].update(
            tid_raw_filename="GEBCO_2026_TID_MODEL_AREA.tif", tid_release="2026"
        ),
    )
    report = plan(workspace)
    tid = [
        item
        for item in report["checks"]
        if item["name"] == "GEBCO categorical TID raster"
    ]
    assert len(tid) == 1
    assert tid[0]["status"] == "missing_external"
    assert tid[0]["required"]


def test_bc_only_habitat_loader_disables_wa_source_even_if_cached(workspace):
    from seascape.biogenic_habitat.kelp.build import (
        _annual_kelp_inventory,
        _source_path,
    )
    from seascape.utils.habitat_acquisition import load_habitat_download_config

    change(
        workspace,
        lambda raw: raw["kelp_habitat"]["download"].update(active_jurisdictions=["bc"]),
    )
    config = load_habitat_download_config(
        "kelp_habitat", workspace / "config/data/project.yaml"
    )
    stale = config.raw_dir / str(
        config.sources["wa_dnr_annual_floating_kelp"].get(
            "extract_directory", "WA_floating_kelp"
        )
    )
    stale.mkdir(parents=True)
    assert not config.sources["wa_dnr_annual_floating_kelp"]["enabled"]
    assert config.sources["bc_crims_kelp"]["enabled"]
    assert _source_path(config, "wa_dnr_kelp_persistence") is None
    assert _annual_kelp_inventory(config) == []
