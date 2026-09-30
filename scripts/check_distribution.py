"""Inspect an sdist and its built wheel without extracting or executing either."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

from check_installed_package import REQUIRED_FILES


def inspect(sdist: Path, wheel: Path) -> dict:
    with tarfile.open(sdist) as archive, zipfile.ZipFile(wheel) as built:
        names = archive.getnames()
        root = names[0].split("/")[0]
        assert f"{root}/pyproject.toml" in names
        project_file = archive.extractfile(f"{root}/pyproject.toml")
        assert project_file is not None
        requires_python = tomllib.loads(project_file.read().decode())["project"][
            "requires-python"
        ]
        assert requires_python == ">=3.14,<3.15", requires_python
        for metadata in (
            archive.extractfile(f"{root}/PKG-INFO"),
            built.open(
                next(
                    name
                    for name in built.namelist()
                    if name.endswith(".dist-info/METADATA")
                )
            ),
        ):
            assert metadata is not None
            with metadata:
                declared = BytesParser().parsebytes(metadata.read())["Requires-Python"]
            assert declared is not None
            assert {clause.strip() for clause in declared.split(",")} == {
                clause.strip() for clause in requires_python.split(",")
            }, declared
        for relative in REQUIRED_FILES:
            member = archive.extractfile(f"{root}/src/seascape/{relative}")
            assert member is not None, relative
            assert member.read() == built.read(f"seascape/{relative}"), relative
        resources = [
            name
            for name in archive.getmembers()
            if name.isfile() and name.name.startswith(f"{root}/src/seascape/resources/")
        ]
        assert resources
        for resource in resources:
            relative = resource.name.removeprefix(f"{root}/src/")
            assert archive.extractfile(resource).read() == built.read(relative), (
                relative
            )
        assert built.testzip() is None
        assert not any(name.startswith("notebooks/") for name in built.namelist())
    return {
        "status": "PASS",
        "required_files": len(REQUIRED_FILES),
        "packaged_resources": len(resources),
        "requires_python": requires_python,
        "sdist": str(sdist),
        "sdist_sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
        "wheel": str(wheel),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.sdist.resolve(), args.wheel.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
