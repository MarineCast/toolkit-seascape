"""Record an installed dependency closure and native scientific library versions."""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import platform
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


def dependency_versions(
    project: Path, extras: Iterable[str] = ("test",)
) -> dict[str, str]:
    """Traverse activated extras, including extras requested by transitive dependencies.

    Raises ValueError for undeclared extras or invalid installed versions, and
    PackageNotFoundError for absent distributions. URLs and distribution paths
    are intentionally never included in the evidence.
    """
    config = tomllib.loads(project.read_text())["project"]
    selected = set(extras)
    optional = config.get("optional-dependencies", {})
    if selected - optional.keys():
        raise ValueError("Unknown project extra")
    pending = [(Requirement(item), "") for item in config["dependencies"]]
    pending += [
        (Requirement(item), extra)
        for extra in sorted(selected)
        for item in optional[extra]
    ]
    versions: dict[str, str] = {}
    visited: set[tuple[str, str]] = set()
    while pending:
        requirement, context = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": context}):
            continue
        name = canonicalize_name(requirement.name)
        dist = metadata.distribution(requirement.name)
        try:
            versions[name] = str(Version(dist.version))
        except InvalidVersion:
            raise ValueError("Invalid installed distribution version") from None
        for extra in {"", *requirement.extras}:
            if (name, extra) in visited:
                continue
            visited.add((name, extra))
            pending.extend((Requirement(item), extra) for item in dist.requires or [])
    return dict(sorted(versions.items()))


def snapshot(
    project: Path, extras: Iterable[str] = ("test",)
) -> tuple[list[str], dict[str, Any]]:
    selected = tuple(sorted(set(extras)))
    versions = dependency_versions(project, selected)
    import pyproj
    import rasterio
    import shapely

    evidence = {
        # Version/implementation only: no executable, install roots or direct URLs.
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gdal": rasterio.__gdal_version__,
        "proj": pyproj.proj_version_str,
        "geos": shapely.geos_version_string,
        "extras": list(selected),
        "dependencies": versions,
    }
    return [
        f"{name}=={version}" for name, version in sorted(versions.items())
    ], evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument(
        "--extra",
        action="append",
        help="Project extra to include (repeatable; default: test)",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output filename stem"
    )
    args = parser.parse_args()
    requirements, evidence = snapshot(
        args.project, args.extra if args.extra is not None else ("test",)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".txt").write_text(
        "# Observed installed closure; selected extras/platform are in the matching JSON.\n"
        + "\n".join(requirements)
        + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
