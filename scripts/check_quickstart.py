"""Execute the documented source-install quickstart outside the checkout.

Dependency installation permits network. Runtime CLI calls use consumer_guard's
Python socket/child/read guard, not an OS firewall. No scientific acquisition.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def fenced_example(text: str, name: str, language: str = "sh") -> str:
    start, end = f"<!-- BEGIN {name} -->", f"<!-- END {name} -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"Expected one example marker pair: {name}")
    block = text.split(start, 1)[1].split(end, 1)[0].strip()
    match = re.fullmatch(rf"```{language}\n(.*?)\n```", block, re.S)
    if not match or not match[1].strip():
        raise ValueError(f"Missing/nonempty fenced {language} example: {name}")
    return match[1] + "\n"


def examples(readme: str, workflows: str) -> dict[str, str]:
    blocks = {
        name: fenced_example(readme, f"QUICKSTART {name}")
        for name in ("install", "demo")
    }
    blocks["plan"] = fenced_example(workflows, "QUICKSTART plan")
    # These reviewed operations are safe in a disposable workspace. New commands
    # require deliberate review; never execute acquisition/promotion from prose.
    expected = {
        "install": [
            'SEASCAPE_ENV="$PWD/.venv"',
            'python3 -m venv "$SEASCAPE_ENV"',
            '. "$SEASCAPE_ENV/bin/activate"',
            "python -m pip install 'pip>=26.2'",
            "python -m pip install .",
            "python -m pip check",
        ],
        "demo": [
            'cd "$(mktemp -d "${TMPDIR:-/tmp}/seascape-first-result.XXXXXX")"',
            'export SEASCAPE_WORKSPACE="$PWD/seascape-workspace"',
            'seascape --workspace "$SEASCAPE_WORKSPACE" demo',
        ],
        "plan": [
            'seascape --workspace "$SEASCAPE_WORKSPACE" init',
            'seascape --workspace "$SEASCAPE_WORKSPACE" stages',
            'seascape --workspace "$SEASCAPE_WORKSPACE" build --dry-run',
        ],
    }
    for name, block in blocks.items():
        if block.splitlines() != expected[name]:
            raise ValueError(
                f"Quickstart operations changed; review safety before execution: {name}"
            )
    return blocks


def extract_source(sdist: Path, destination: Path) -> Path:
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        for member in members:
            path = Path(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError(f"Unsafe source archive member: {member.name}")
        for member in members:
            path = destination / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target)
    roots = list(destination.iterdir())
    if len(roots) != 1 or not (roots[0] / "pyproject.toml").is_file():
        raise ValueError("Expected one source package root with pyproject.toml")
    return roots[0]


def run(sdist: Path, source: Path, forbidden: Path, output: Path) -> dict:
    output = output.resolve()
    if output.is_relative_to(forbidden.resolve()) or output.exists():
        raise ValueError(
            "Quickstart output must be fresh and outside the checkout/group"
        )
    if not source.resolve().is_relative_to(
        forbidden.resolve()
    ) or sdist.resolve().is_relative_to(forbidden.resolve()):
        raise ValueError(
            "Forbid the explicit source checkout and transfer the sdist outside it"
        )
    blocks = examples(
        (source / "README.md").read_text(), (source / "docs/WORKFLOWS.md").read_text()
    )
    output.mkdir(parents=True)
    report = {
        "status": "FAIL",
        "blocks": blocks,
        "source_archive": str(sdist.resolve()),
        "forbid_root": str(forbidden.resolve()),
    }
    try:
        copied_source = extract_source(sdist, output / "source")
        helpers = output / "helpers"
        helpers.mkdir()
        shutil.copyfile(
            Path(__file__).with_name("consumer_guard.py"), helpers / "consumer_guard.py"
        )
        # This runner is transferred before runtime; neither source tree can
        # supply imports. Only the normal installation under .venv is permitted.
        (helpers / "cli.py").write_text(
            "import importlib.util, os, runpy, sys\nfrom pathlib import Path\n"
            "from consumer_guard import install_guard\n"
            f"source = Path({str(copied_source)!r})\n"
            "prefix = Path(sys.prefix).resolve()\n"
            "assert prefix == source / '.venv' and sys.prefix != sys.base_prefix\n"
            "assert all(importlib.util.find_spec(x) is None for x in ('pytest', 'jupyter', 'nbconvert', 'orcacast'))\n"
            "import seascape\n"
            "location = Path(seascape.__file__).resolve()\n"
            "assert location.is_relative_to(prefix) and 'site-packages' in location.parts\n"
            "def audit(event, args):\n"
            "    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):\n"
            "        path = Path(os.fsdecode(args[0])).resolve()\n"
            "        if path.is_relative_to(source) and not path.is_relative_to(prefix):\n"
            "            raise AssertionError('Source archive access forbidden: ' + str(path))\n"
            "sys.addaudithook(audit)\n"
            "try:\n    (source / 'README.md').read_bytes()\n"
            "except AssertionError:\n    pass\nelse:\n    raise AssertionError('Archive read guard failed')\n"
            f"install_guard(Path({str(forbidden.resolve())!r}))\n"
            "sys.argv[0] = str(prefix / 'bin/seascape')\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n"
        )
        env = os.environ.copy()
        for key in (
            "PYTHONPATH",
            "PYTHONHOME",
            "SEASCAPE_WORKSPACE",
            "SEASCAPE_COMMON_CONFIG",
            "SEASCAPE_CANDIDATE_ROOT",
            "MPLCONFIGDIR",
            "VIRTUAL_ENV",
            "BASH_ENV",
            "ENV",
        ):
            env.pop(key, None)
        temporary = output / "tmp"
        temporary.mkdir()
        env.update(
            TMPDIR=str(temporary),
            PIP_CACHE_DIR=str(output / "pip-cache"),
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        # Pin python3 to the selected CI/local interpreter; all documented lines
        # run verbatim in one shell, preserving activation and workspace state.
        script = (
            "set -eu\npython3() { "
            + shlex.quote(sys.executable)
            + ' "$@"; }\n'
            + blocks["install"]
        )
        script += (
            "seascape() { python " + shlex.quote(str(helpers / "cli.py")) + ' "$@"; }\n'
        )
        script += "export TMPDIR=" + shlex.quote(str(temporary)) + "\n"
        script += blocks["demo"] + blocks["plan"]
        script += (
            'printf "%s" "$SEASCAPE_WORKSPACE" > '
            + shlex.quote(str(output / "workspace.txt"))
            + "\n"
        )
        (output / "commands.sh").write_text(script)
        with (output / "commands.log").open("w") as log:
            completed = subprocess.run(
                ["bash", "-x", str(output / "commands.sh")],
                cwd=copied_source,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1200,
            )
        report["exit_code"] = completed.returncode
        if completed.returncode:
            raise RuntimeError(
                f"Quickstart failed: exit {completed.returncode}; see {output / 'commands.log'}"
            )
        workspace = Path((output / "workspace.txt").read_text()).resolve()
        assert workspace.is_relative_to(temporary)
        demo = json.loads((workspace / ".seascape/demo/report.json").read_text())
        assert (
            demo["status"] == "PASS" and demo["checks"] and all(demo["checks"].values())
        )
        report.update(
            status="PASS",
            workspace=str(workspace),
            demo_checks=len(demo["checks"]),
            interpreter=sys.version,
            log=str(output / "commands.log"),
        )
        return report
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--forbid-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.sdist, args.source, args.forbid_root, args.output), indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
