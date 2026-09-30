"""Validate a release tag against the authoritative project version."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

SEMVER_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def project_version(project_file: Path) -> str:
    """Return the statically declared PEP 621 project version."""
    project = tomllib.loads(project_file.read_text())["project"]
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml must declare a static project.version")
    return version


def validate(tag: str, project_file: Path) -> str:
    """Return the version when *tag* is strict SemVer and exactly matches metadata."""
    match = SEMVER_TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"Release tag must have form vX.Y.Z: {tag!r}")
    tagged = tag.removeprefix("v")
    declared = project_version(project_file)
    if tagged != declared:
        raise ValueError(
            f"Release tag {tag!r} does not match project version {declared!r}"
        )
    return declared


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Git tag, for example v0.1.0")
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    print(validate(args.tag, args.project))
