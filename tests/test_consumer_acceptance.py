"""Regression checks for packaging failures and the consumer process boundary."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_location_rejects_other_environment_and_source(tmp_path):
    check = load("check_installed_package").check_location
    prefix = tmp_path / "consumer"
    check(prefix / "lib/python3.14/site-packages/seascape/__init__.py", prefix)
    with pytest.raises(RuntimeError, match="this interpreter"):
        check(tmp_path / "inherited/site-packages/seascape/__init__.py", prefix)
    with pytest.raises(RuntimeError, match="installed wheel"):
        check(prefix / "src/seascape/__init__.py", prefix)


def test_missing_packaged_config_fails(tmp_path):
    module = load("check_installed_package")
    for name in module.REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    module.check_resources(tmp_path)
    (tmp_path / "resources/config/data/environment_seascape.yaml").unlink()
    with pytest.raises(FileNotFoundError, match="environment_seascape.yaml"):
        module.check_resources(tmp_path)


@pytest.mark.parametrize("case", ["network", "checkout", "child"])
def test_guard_rejects_activity_in_invoked_process(tmp_path, case):
    outside = tmp_path / "outside"
    outside.mkdir()
    forbidden = tmp_path / "checkout"
    forbidden.mkdir()
    shutil.copyfile(SCRIPTS / "consumer_guard.py", outside / "consumer_guard.py")
    operation = {
        "network": "import socket; socket.create_connection(('192.0.2.1', 443))",
        "checkout": f"from pathlib import Path; Path({str(forbidden / 'secret')!r}).read_bytes()",
        "child": "import subprocess; subprocess.run(['definitely-not-launched'])",
    }[case]
    probe = outside / "probe.py"
    probe.write_text(operation)
    completed = subprocess.run(
        [
            sys.executable,
            outside / "consumer_guard.py",
            "--forbid-root",
            forbidden,
            "--script",
            probe,
        ],
        cwd=outside,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 1
    assert {
        "network": "denies outbound activity",
        "checkout": "Checkout access forbidden",
        "child": "denies child processes",
    }[case] in completed.stderr


@pytest.mark.parametrize("failure", [None, "missing", "different"])
def test_sdist_wheel_resource_survival(tmp_path, monkeypatch, failure):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = load("check_distribution")
    sdist = tmp_path / "toolkit.tar.gz"
    wheel = tmp_path / "toolkit.whl"
    files = {name: b"fixture" for name in module.REQUIRED_FILES}
    files["resources/docs/products.md"] = b"packaged documentation"
    with tarfile.open(sdist, "w:gz") as archive:
        contents = {
            "pkg/pyproject.toml": b"fixture",
            **{f"pkg/src/seascape/{name}": value for name, value in files.items()},
        }
        for name, value in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, value in files.items():
            if name == "resources/docs/products.md" and failure:
                if failure == "missing":
                    continue
                value = b"altered"
            archive.writestr(f"seascape/{name}", value)
    if failure:
        with pytest.raises((KeyError, AssertionError)):
            module.inspect(sdist, wheel)
    else:
        assert module.inspect(sdist, wheel)["status"] == "PASS"


def test_consumer_refuses_existing_output_and_checkout_output(tmp_path):
    module = load("check_consumer_install")
    forbidden = tmp_path / "checkout"
    source = forbidden / "toolkit-seascape"
    wheel = tmp_path / "transferred.whl"
    wheel.write_bytes(b"never installed")
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "user-file"
    sentinel.write_text("preserve")
    with pytest.raises(FileExistsError):
        module.accept(wheel, source, output, forbidden)
    assert list(output.iterdir()) == [sentinel] and sentinel.read_text() == "preserve"
    with pytest.raises(ValueError, match="outside"):
        module.accept(wheel, source, forbidden / "output", forbidden)
    assert not (forbidden / "output").exists()


def test_guard_executes_console_script_with_arguments(tmp_path):
    guard = tmp_path / "consumer_guard.py"
    shutil.copyfile(SCRIPTS / "consumer_guard.py", guard)
    console = tmp_path / "console"
    console.write_text(
        "import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(sys.argv[2])\n"
    )
    artifact = tmp_path / "actual-output"
    completed = subprocess.run(
        [
            sys.executable,
            guard,
            "--forbid-root",
            tmp_path / "checkout",
            "--script",
            console,
            "--",
            artifact,
            "executed",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert artifact.read_text() == "executed"


def test_injected_demo_network_failure_leaves_fail_report(tmp_path):
    for name in ("consumer_guard.py", "check_consumer_failures.py"):
        shutil.copyfile(SCRIPTS / name, tmp_path / name)
    workspace = tmp_path / "injected"
    completed = subprocess.run(
        [
            sys.executable,
            tmp_path / "consumer_guard.py",
            "--forbid-root",
            tmp_path / "checkout",
            "--script",
            tmp_path / "check_consumer_failures.py",
            "--",
            "outbound-demo",
            "--workspace",
            workspace,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 1
    assert "Offline consumer denies outbound activity" in completed.stderr
    assert (
        json.loads((workspace / ".seascape/demo/report.json").read_text())["status"]
        == "FAIL"
    )
