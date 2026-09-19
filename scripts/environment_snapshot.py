"""Record the runtime/test dependency closure and native scientific library versions."""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import platform
from pathlib import Path
import sys
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def snapshot(project: Path) -> tuple[list[str], dict]:
    config = tomllib.loads(project.read_text())["project"]
    pending = [
        Requirement(item)
        for item in config["dependencies"] + config["optional-dependencies"]["test"]
    ]
    versions = {}
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = canonicalize_name(requirement.name)
        if name in versions:
            continue
        dist = metadata.distribution(requirement.name)
        versions[name] = dist.version
        pending.extend(Requirement(item) for item in dist.requires or [])
    import pyproj
    import rasterio
    import shapely

    evidence = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gdal": rasterio.__gdal_version__,
        "proj": pyproj.proj_version_str,
        "geos": shapely.geos_version_string,
        "dependencies": dict(sorted(versions.items())),
    }
    return [
        f"{name}=={version}" for name, version in sorted(versions.items())
    ], evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument(
        "--output", type=Path, required=True, help="Output filename stem"
    )
    args = parser.parse_args()
    requirements, evidence = snapshot(args.project)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".txt").write_text(
        "# Observed runtime/test dependency closure; platform details are in the matching JSON.\n"
        + "\n".join(requirements)
        + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
