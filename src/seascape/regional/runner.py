"""Installed regional candidate commands; explicit sources and no acquisitions."""

from pathlib import Path

from .contract import Job, RegionalError, input_bytes

OPERATORS = (
    "bathymetry",
    "watergraph",
    "distance",
    "native-terrain",
    "shoreline",
    "anthropogenic",
    "kelp",
    "coastal",
    "freshwater",
    "estuary",
    "bivalve",
    "seagrass",
    "substrate",
    "terrain-form",
    "consolidate",
)


def run_spec(path: str | Path, *, preflight: bool = False) -> dict:
    job = Job.load(Path(path))
    if job.operator not in OPERATORS:
        raise RegionalError(f"Unsupported operator: {job.operator}")
    if preflight:
        return {
            "status": "byte_pinned_inputs_verified_execution_not_started",
            "operator": job.operator,
            "resolution": job.resolution,
            "domain": job.domain,
            "limits": job.limits,
            "input_bytes": sum(input_bytes(item.path) for item in job.inputs.values()),
            "network_bytes": 0,
            "output": str(job.output),
        }
    job.guard()
    job.output.mkdir(parents=True, exist_ok=False)
    try:
        if job.operator == "terrain-form":
            from .terrain import run
        elif job.operator == "substrate":
            from .point_products import substrate as run
        elif job.operator in ("freshwater", "estuary"):
            from .point_products import proximity as run
        elif job.operator == "seagrass":
            from .seagrass_product import run
        elif job.operator == "consolidate":
            from .consolidate import run
        elif job.operator in ("coastal", "bivalve", "shoreline"):
            from . import polygon_products

            run = getattr(polygon_products, job.operator)
        elif job.operator in ("anthropogenic", "kelp"):
            from . import physical

            run = getattr(physical, job.operator)
        else:
            from . import native

            run = getattr(native, job.operator.replace("-", "_"))
        from .monitor import resource_monitor

        with resource_monitor(job):
            method, details = run(job)
            return job.finish(method, details)
    except Exception as exc:
        # Preserve failed evidence. No checksum manifest or completion claim.
        import json

        (job.output / "FAILED.json").write_text(
            json.dumps(
                {
                    "status": "failed_unusable_candidate",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
            )
            + "\n"
        )
        raise
