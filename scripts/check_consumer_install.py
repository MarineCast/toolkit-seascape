"""Accept a wheel in a fresh consumer, runtime first, then declared test/notebook extras.

Invoke with an explicit source checkout only to copy acceptance files. Every
consumer command runs outside it. No environment inherits host site packages.
Output must be a new directory outside the forbidden checkout/workspace root.
Dependency installation may use the network; guarded computation may not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path


def accept(wheel: Path, source: Path, output: Path, forbidden: Path) -> int:
    if not wheel.is_file():
        raise FileNotFoundError(wheel)
    if not source.is_relative_to(forbidden):
        raise ValueError("--forbid-root must contain the explicit source checkout")
    if output.is_relative_to(forbidden) or wheel.is_relative_to(forbidden):
        raise ValueError(
            "Place output and transferred wheel outside the forbidden root"
        )
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "logs"
    controls = output / "outside"
    logs.mkdir()
    controls.mkdir()
    report = {
        "status": "RUNNING",
        "commands": [],
        "wheel": str(wheel),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "network_boundary": "Python guards during execution; installation permits network; not an OS firewall",
    }
    environment = dict(os.environ)
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "SEASCAPE_WORKSPACE",
        "SEASCAPE_CANDIDATE_ROOT",
        "SEASCAPE_COMMON_CONFIG",
        "SEASCAPE_DEMO_WORKSPACE",
        "MPLCONFIGDIR",
    ):
        environment.pop(key, None)
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    environment["IPYTHONDIR"] = str(output / "ipython")
    environment["JUPYTER_CONFIG_DIR"] = str(output / "jupyter-config")

    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(name, command, *, expected=0, marker=None):
        entry = {
            "name": name,
            "argv": list(map(str, command)),
            "cwd": str(controls),
            "expected_exit": expected,
            "status": "RUNNING",
        }
        report["commands"].append(entry)
        save()
        started = time.monotonic()
        log = logs / f"{name}.log"
        with log.open("w") as stream:
            completed = subprocess.run(
                entry["argv"],
                cwd=controls,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        entry.update(
            exit_code=completed.returncode,
            seconds=round(time.monotonic() - started, 2),
            log=str(log),
        )
        passed = completed.returncode == expected and (
            marker is None or marker in log.read_text()
        )
        entry["status"] = "PASS" if passed else "FAIL"
        save()
        print(
            f"{name}: {entry['status']} (exit {completed.returncode}); {log}",
            flush=True,
        )
        if not passed:
            raise RuntimeError(f"Consumer step failed: {name}; see {log}")

    try:
        save()
        consumer = output / "consumer"
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(consumer)
        python = consumer / "bin/python"
        assert (
            "include-system-site-packages = false"
            in (consumer / "pyvenv.cfg").read_text()
        )
        environment["PATH"] = (
            str(python.parent) + os.pathsep + environment.get("PATH", "")
        )
        for name in (
            "consumer_guard.py",
            "check_installed_package.py",
            "check_demo.py",
            "check_consumer_failures.py",
            "check_validation_notebook.py",
        ):
            shutil.copyfile(source / "scripts" / name, controls / name)
        guard = [python, controls / "consumer_guard.py", "--forbid-root", forbidden]

        def script(name, filename, *arguments, **options):
            run(
                name,
                [*guard, "--script", controls / filename, "--", *arguments],
                **options,
            )

        def cli(name, *arguments, **options):
            run(
                name,
                [*guard, "--script", consumer / "bin/seascape", "--", *arguments],
                **options,
            )

        run("install-runtime", [python, "-m", "pip", "install", wheel])
        run("runtime-pip-check", [*guard, "--module", "pip", "--", "check"])
        script(
            "runtime-imports",
            "check_installed_package.py",
            "--snapshot",
            output / "runtime-environment.json",
        )
        runtime = json.loads((output / "runtime-environment.json").read_text())
        assert not {
            "pytest",
            "ipykernel",
            "nbconvert",
            "jupyterlab",
            "ruff",
            "mypy",
        } & {name.lower() for name in runtime["distributions"]}
        cli("runtime-help", "--help", marker="usage: seascape")
        workspace = output / "init-workspace"
        cli("runtime-init", "--workspace", workspace, "init")
        for name in (
            "project.yaml",
            "environment_seascape.yaml",
            "presentation_settings.yaml",
        ):
            assert (workspace / "config/data" / name).is_file(), name
        cli(
            "runtime-dry-run",
            "--workspace",
            workspace,
            "build",
            "--dry-run",
            marker="seascape-release",
        )
        assert not (controls / "01_TOOLKIT_VALIDATION.ipynb").exists()
        run(
            "runtime-demo",
            [
                python,
                controls / "check_demo.py",
                "--workspace",
                output / "runtime-demo",
                "--forbid-root",
                forbidden,
            ],
        )

        script(
            "missing-dependency",
            "check_consumer_failures.py",
            "missing-dependency",
            expected=1,
            marker="SS-03 missing runtime dependency: rasterio",
        )
        script(
            "source-import",
            "check_consumer_failures.py",
            "source-import",
            "--source",
            source,
            expected=1,
            marker="Checkout access forbidden",
        )
        # Remove only this throwaway installation's known config, restore even on failure.
        config = (
            Path(runtime["package"]).parent
            / "resources/config/data/environment_seascape.yaml"
        )
        assert config.is_relative_to(consumer.resolve())
        hidden = config.with_suffix(".ss03-missing")
        assert config.is_file() and not hidden.exists()
        config.rename(hidden)
        try:
            script(
                "missing-resource",
                "check_installed_package.py",
                expected=1,
                marker="Missing packaged resources",
            )
        finally:
            hidden.rename(config)
        injected = output / "outbound-demo"
        script(
            "outbound-demo",
            "check_consumer_failures.py",
            "outbound-demo",
            "--workspace",
            injected,
            expected=1,
            marker="Offline consumer denies outbound activity",
        )
        assert (
            json.loads((injected / ".seascape/demo/report.json").read_text())["status"]
            == "FAIL"
        )
        report["runtime_status"] = "PASS"
        save()

        run(
            "install-extras",
            [
                python,
                "-m",
                "pip",
                "install",
                f"toolkit-seascape[test,notebook] @ {wheel.as_uri()}",
            ],
        )
        run("extras-pip-check", [*guard, "--module", "pip", "--", "check"])
        script(
            "extras-imports",
            "check_installed_package.py",
            "--snapshot",
            output / "extras-environment.json",
        )
        external_tests = controls / "tests"
        external_tests.mkdir()
        for name in (
            "__init__.py",
            "test_products.py",
            "test_review_regressions.py",
            "test_demo.py",
            "test_metric_matrix.py",
        ):
            shutil.copyfile(source / "tests" / name, external_tests / name)
        run(
            "external-tests",
            [
                *guard,
                "--module",
                "pytest",
                "--",
                "-q",
                "--noconftest",
                "--basetemp",
                output / "pytest-temp",
                "tests/test_products.py",
                "tests/test_review_regressions.py",
                "tests/test_demo.py",
                "tests/test_metric_matrix.py",
            ],
        )
        notebook_dir = output / "notebook-only"
        notebook_dir.mkdir()
        shutil.copyfile(
            source / "notebooks/validation/01_TOOLKIT_VALIDATION.ipynb",
            notebook_dir / "01_TOOLKIT_VALIDATION.ipynb",
        )
        run(
            "copied-notebook",
            [
                python,
                controls / "check_validation_notebook.py",
                "--notebook",
                notebook_dir / "01_TOOLKIT_VALIDATION.ipynb",
                "--output",
                output / "executed-notebook.ipynb",
                "--forbid-root",
                forbidden,
                "--workspace",
                output / "notebook-demo",
            ],
        )
        report["status"] = "PASS"
        return 0
    except Exception as exc:
        report.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
        print(report["error"], file=sys.stderr)
        return 1
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--forbid-root", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(
        accept(
            args.wheel.resolve(),
            args.source.resolve(),
            args.output.resolve(),
            args.forbid_root.resolve(),
        )
    )
