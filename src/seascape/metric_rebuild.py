"""Complete current-metric workflow with isolated, resource-bounded producers."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path
from threading import Event

from seascape.core.config.data import load_data_config
from seascape.workflow import DomainBuildContext, DomainBuildStage

BASE = "data/processed/domain/environmental_layer/seascape"
PRODUCERS = (
    "terrain",
    "shoreline-proximity",
    "coast-complexity",
    "nearshore",
    "coastal-bounds",
    "waterbody",
    "shoreline",
    "freshwater",
    "fluvial",
    "estuary",
    "anthropogenic",
    "substrate",
    "mapped-substrate",
    "kelp",
    "seagrass",
    "bivalve",
)
DIRECTORIES = (
    "seafloor_physiography/geomorphometry",
    "coastal_configuration/shoreline_proximity",
    "coastal_configuration/coast_complexity",
    "coastal_configuration/nearshore_transitions",
    "coastal_configuration/exposure_and_enclosure",
    "coastal_configuration/waterbody_morphometry",
    "coastal_configuration/shoreline_characterization",
    "hydrologic_connectivity/freshwater_sources",
    "hydrologic_connectivity/fluvial_connectivity",
    "hydrologic_connectivity/estuarine_connectivity",
    "anthropogenic",
    "benthic_substrate/classification",
    "benthic_substrate/mapped_classes",
    "biogenic_habitat/kelp",
    "biogenic_habitat/seagrass",
    "biogenic_habitat/bivalve",
)


def settings(config_path):
    section = load_data_config(config_path).get("metric_rebuild")
    if not isinstance(section, dict) or not section.get("sources"):
        raise ValueError(
            "The metrics profile requires metric_rebuild.sources and source qualifications"
        )
    return section


def monitor_command(command, *, directory, limits, env=None, stop=None):
    """Bound a process tree, retain its receipt and terminate its whole group on failure."""
    import shutil

    import psutil

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    maximum = float(limits.get("memory_gib", 3)) * 1024**3
    seconds = float(limits.get("seconds", 1800))
    reserve = float(limits.get("disk_reserve_gib", 20)) * 1024**3
    log_bytes = float(limits.get("log_mib", 8)) * 1024**2
    if min(maximum, seconds, log_bytes) <= 0 or reserve < 0:
        raise ValueError("Invalid metric-worker resource limits")
    if shutil.disk_usage(directory).free < reserve:
        raise RuntimeError("Metric worker cannot start below its free-disk reserve")
    started, peak, reason, last = time.monotonic(), 0, None, 0.0
    receipt = directory / "status.json"
    log = directory / "output.log"
    process = None
    try:
        with log.open("w") as output:
            process = subprocess.Popen(
                command,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            while process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    rss = parent.memory_info().rss
                    for child in parent.children(recursive=True):
                        try:
                            rss += child.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                    peak = max(peak, rss)
                except psutil.NoSuchProcess:
                    pass
                elapsed = time.monotonic() - started
                if stop is not None and stop.is_set():
                    reason = "cancelled producer group"
                elif peak > maximum:
                    reason = "process-tree memory limit"
                elif elapsed > seconds:
                    reason = "worker time limit"
                elif shutil.disk_usage(directory).free < reserve:
                    reason = "free-disk reserve"
                elif log.stat().st_size > log_bytes:
                    reason = "worker log limit"
                elif psutil.virtual_memory().available < 512 * 1024**2:
                    reason = "512 MiB available-memory reserve"
                if elapsed - last >= 5 or reason:
                    receipt.write_text(
                        json.dumps(
                            {
                                "active": True,
                                "pid": process.pid,
                                "seconds": elapsed,
                                "peak_rss_bytes": peak,
                                "stop_reason": reason,
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                    last = elapsed
                if reason:
                    break
                time.sleep(0.1)
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()
        result = {
            "active": False,
            "pid": process.pid if process is not None else None,
            "command": command,
            "seconds": time.monotonic() - started,
            "peak_rss_bytes": peak,
            "stop_reason": reason,
            "returncode": process.returncode if process is not None else None,
        }
        receipt.write_text(json.dumps(result, indent=2) + "\n")
    if reason or result["returncode"] != 0:
        raise RuntimeError(
            f"Metric worker failed ({reason or result['returncode']}); see {log}"
        )
    return result


def run_worker(name, ctx, *, stop=None):
    limits = settings(ctx.config_path).get("limits", {})
    command = [
        sys.executable,
        "-m",
        "seascape.metric_rebuild",
        "--worker",
        name,
        "--config",
        str(ctx.config_path),
        "--root",
        str(ctx.candidate_root),
        "--workspace",
        str(ctx.canonical_root),
    ]
    if ctx.output_dir:
        command.extend(["--output", str(ctx.output_dir)])
    env = dict(
        os.environ,
        SEASCAPE_WORKSPACE=str(ctx.canonical_root),
        SEASCAPE_CANDIDATE_ROOT=str(ctx.candidate_root),
        PYTHONUNBUFFERED="1",
    )
    common = ctx.candidate_root / ".seascape/config/common.yaml"
    if common.is_file():
        env["SEASCAPE_COMMON_CONFIG"] = str(common)
    env["MPLCONFIGDIR"] = str(ctx.candidate_root / ".seascape/mpl")
    temporary = ctx.candidate_root / ".seascape/tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(temporary)
    print(f"[metrics] {name} start", flush=True)
    result = monitor_command(
        command,
        directory=ctx.candidate_root / ".seascape/metric-workers" / name,
        limits=limits,
        env=env,
        stop=stop,
    )
    print(
        f"[metrics] {name} complete ({result['seconds']:.1f}s, {result['peak_rss_bytes'] / 1024**3:.2f} GiB peak)",
        flush=True,
    )
    return result


def run_producers(ctx):
    jobs = settings(ctx.config_path).get("limits", {}).get("jobs", 1)
    if type(jobs) is not int or not 1 <= jobs <= 4:
        raise ValueError("metric_rebuild.limits.jobs must be an integer from 1 to 4")
    results = {}
    stop = Event()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {
            pool.submit(run_worker, name, ctx, stop=stop): name for name in PRODUCERS
        }
        try:
            for future in as_completed(pending):
                results[pending[future]] = future.result()
        except BaseException:
            stop.set()
            for future in pending:
                future.cancel()
            raise
    path = ctx.candidate_root / ".seascape/metric-producers.json"
    path.write_text(json.dumps({"producers": results}, indent=2) + "\n")


def metric_stages():
    """Use the existing workflow's dependency, config, source and resume contracts."""
    return (
        DomainBuildStage(
            "metric-sources",
            "Acquire or verify pinned scientific inputs.",
            partial(run_worker, "sources"),
            declared_manifests=(".seascape/metric-sources.json",),
        ),
        DomainBuildStage(
            "metric-water-geometry",
            "Rebuild source-derived coastal masks and native membership.",
            partial(run_worker, "water-geometry"),
            dependencies=("metric-sources",),
            declared_outputs=(f"{BASE}/spatial_support/water_geometry",),
            declared_manifests=(
                f"{BASE}/spatial_support/water_geometry/water_geometry_manifest.json",
            ),
        ),
        DomainBuildStage(
            "metric-water-network",
            "Rebuild native H3 geometry, water graphs and operators.",
            partial(run_worker, "water-network"),
            dependencies=("metric-water-geometry",),
            declared_outputs=(
                f"{BASE}/spatial_support/h3_geometry",
                f"{BASE}/spatial_support/water_network",
            ),
            declared_manifests=(
                f"{BASE}/spatial_support/water_network/_dataset_manifest.json",
            ),
        ),
        DomainBuildStage(
            "metric-bathymetry",
            "Rebuild both native bathymetry variants from the raster.",
            partial(run_worker, "bathymetry"),
            dependencies=("metric-water-network",),
            declared_outputs=(f"{BASE}/seafloor_physiography/bathymetry",),
            declared_manifests=(
                f"{BASE}/seafloor_physiography/bathymetry/bathymetry_manifest.json",
            ),
        ),
        DomainBuildStage(
            "metric-producers",
            "Calculate every current metric family from scientific inputs.",
            run_producers,
            dependencies=("metric-bathymetry",),
            declared_outputs=tuple(f"{BASE}/{p}" for p in DIRECTORIES),
            declared_manifests=(".seascape/metric-producers.json",),
        ),
        DomainBuildStage(
            "seascape-parquets",
            "Export and verify all 29 metric tables without diagnostics.",
            partial(run_worker, "export"),
            dependencies=("metric-producers",),
            terminal_action=True,
        ),
    )


def preflight_metrics(**kwargs):
    """Read-only profile planning; dataset hashes are checked during acquisition."""
    from seascape.workflow import plan_domain_layer_build

    check_inputs = kwargs.pop("check_inputs")
    for key in ("publish", "resume", "overwrite"):
        kwargs.pop(key, None)
    plan = plan_domain_layer_build(**kwargs, stage_definitions=metric_stages())
    checks = []
    if check_inputs:
        for item in settings(plan.source_config)["sources"]:
            path = (plan.canonical_root / Path(item["path"]).expanduser()).resolve()
            present = path.exists()
            checks.append(
                {
                    "stage": "metric-sources",
                    "name": item.get("name", path.name),
                    "status": "ready" if present else "missing_external",
                    "path": str(path),
                    "required": True,
                    "detail": "Path inspection only; pinned SHA256 checked by acquisition before producers",
                    "corrective_action": "Supply the pinned source or configure its acquisition URL",
                }
            )
    return {
        "schema_version": 1,
        "status": "failed"
        if any(c["status"] != "ready" for c in checks)
        else "ready"
        if check_inputs
        else "not_run",
        "config": str(plan.source_config),
        "candidate_root": str(plan.candidate_root),
        "checks": checks,
        "stages": [
            {"name": s.name, "dependencies": s.dependencies} for s in plan.stages
        ],
        "scope": "metrics profile; path-level inspection, not source or regional validation",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worker",
        choices=(
            "sources",
            "water-geometry",
            "water-network",
            "bathymetry",
            "export",
            *PRODUCERS,
        ),
        required=True,
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["SEASCAPE_WORKSPACE"] = str(args.workspace)
    os.environ["SEASCAPE_CANDIDATE_ROOT"] = str(args.root)
    import logging

    from seascape.metric_rebuild_stages import execute

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    ctx = DomainBuildContext(
        args.config,
        args.config,
        args.root,
        args.workspace,
        overwrite=True,
        output_dir=args.output,
    )
    execute(args.worker, ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
