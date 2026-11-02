"""Four explicit source-bound producers; candidates never overwrite delivery."""

from pathlib import Path

from .contract import Job, RegionalError, input_bytes

OPERATORS = ("shoreline", "anthropogenic", "substrate", "estuary")


def run_spec(path: str | Path, *, preflight: bool = False) -> dict:
    job = Job.load(Path(path))
    if job.operator not in OPERATORS:
        raise RegionalError(f"Unsupported operator: {job.operator}")
    if preflight:
        return dict(
            status="byte_pinned_inputs_verified_execution_not_started",
            operator=job.operator,
            resolution=job.resolution,
            domain=job.domain,
            limits=job.limits,
            input_bytes=sum(input_bytes(v.path) for v in job.inputs.values()),
            network_bytes=0,
            output=str(job.output),
        )
    job.guard()
    job.output.mkdir(parents=True, exist_ok=False)
    try:
        if job.operator == "shoreline":
            from .shoreline import shoreline as run
        elif job.operator == "anthropogenic":
            from .physical import anthropogenic as run
        elif job.operator == "substrate":
            from .point_products import substrate as run
        else:
            from .point_products import proximity as run
        from .monitor import resource_monitor

        with resource_monitor(job):
            method, details = run(job)
            return job.finish(method, details)
    except Exception as exc:
        import json

        (job.output / "FAILED.json").write_text(
            json.dumps(
                dict(
                    status="failed_unusable_candidate",
                    error_type=type(exc).__name__,
                    error=str(exc),
                ),
                indent=2,
            )
            + "\n"
        )
        raise
