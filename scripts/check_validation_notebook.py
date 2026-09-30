"""Execute a copied notebook with the installed wheel's notebook extra.

Use a directory containing only the copied notebook. This creates a temporary
kernel specification for the calling interpreter, never registers a user kernel,
and writes an executed copy separately. Guards apply inside the kernel; they
permit Jupyter loopback traffic and reject outbound Python socket activity,
checkout reads and provider acquisition. This is not an OS-level firewall.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
from nbclient import NotebookClient

_GUARD = """import json, os, socket, sys
from pathlib import Path

_forbidden_root = Path(os.environ["SEASCAPE_NOTEBOOK_FORBIDDEN_ROOT"]).resolve()
_expected_python = Path(os.environ["SEASCAPE_NOTEBOOK_EXPECTED_PYTHON"]).resolve()
_network_attempts = []
_acquisition_attempts = []

def _offline_guard(event, arguments):
    if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(arguments[0])).resolve()
        if path.is_relative_to(_forbidden_root):
            raise AssertionError(f"Checkout access forbidden: {path}")
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
        raise PermissionError(f"Notebook acceptance denies child processes: {event}")
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto", "socket.sendmsg"}:
        address = arguments[1] if event in {"socket.connect", "socket.sendto", "socket.sendmsg"} else arguments[0]
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"localhost", "127.0.0.1", "::1"}:
            _network_attempts.append(event)
            raise RuntimeError(f"Outbound notebook activity denied: {event}")

sys.addaudithook(_offline_guard)
try:
    with socket.socket() as connection:
        connection.connect(("192.0.2.1", 443))
except RuntimeError as exc:
    assert "Outbound notebook activity denied" in str(exc)
else:
    raise AssertionError("Outbound guard failed")
assert _network_attempts == ["socket.connect"]
_network_attempts.clear()

import seascape
from seascape.seafloor_physiography.bathymetry import pipeline as _pipeline
assert Path(seascape.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert "site-packages" in Path(seascape.__file__).resolve().parts
assert Path(sys.executable).resolve() == _expected_python

def _deny_acquisition(*args, **kwargs):
    _acquisition_attempts.append("download_gebco_geotiff")
    raise AssertionError("Source acquisition forbidden in portable notebook")

_pipeline.download_gebco_geotiff = _deny_acquisition
_environment_before_notebook = {
    name: os.environ.get(name) for name in
    ("SEASCAPE_WORKSPACE", "SEASCAPE_CANDIDATE_ROOT", "SEASCAPE_COMMON_CONFIG", "MPLCONFIGDIR")
}
"""

_VERIFY = """assert not _network_attempts, _network_attempts
assert not _acquisition_attempts, _acquisition_attempts
assert _environment_before_notebook == {
    name: os.environ.get(name) for name in _environment_before_notebook
}
assert result.workspace == WORKSPACE / ".seascape/demo"
assert report["status"] == "PASS" and result.checks and all(result.checks.values())
assert report["checks"] == result.checks
assert manifest["metadata"]["synthetic"] is True
assert all(source["name"].startswith("SYNTHETIC ") for source in manifest["sources"])
assert len(result.figure_paths) == 2 and all(path.is_file() for path in result.figure_paths)
print("SEASCAPE NOTEBOOK ACCEPTANCE: " + json.dumps({
    "status": report["status"], "interpreter": sys.executable,
    "package": str(PACKAGE_PATH), "workspace": str(WORKSPACE),
    "production_checks": len(result.checks), "notebook_checks": len(CHECKS),
    "network_attempts": _network_attempts, "acquisition_attempts": _acquisition_attempts,
    "environment_restored": ENVIRONMENT_RESTORED, "report": str(result.report_path),
}))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--forbid-root", type=Path, required=True)
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Omit to exercise the notebook's retained temporary default",
    )
    args = parser.parse_args()
    source = args.notebook.resolve()
    output = args.output.resolve()
    if output.exists() or output == source or output.parent == source.parent:
        raise ValueError("Use a new output outside the notebook-only directory")
    if sorted(source.parent.iterdir()) != [source]:
        raise ValueError("Input directory must contain only the copied notebook")
    before = source.read_bytes()
    notebook = nbformat.reads(before.decode(), as_version=4)
    nbformat.validate(notebook)
    assert all(
        cell.get("execution_count") is None and not cell.get("outputs")
        for cell in notebook.cells
    )
    notebook.cells.insert(0, nbformat.v4.new_code_cell(_GUARD))
    notebook.cells.append(nbformat.v4.new_code_cell(_VERIFY))
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["SEASCAPE_NOTEBOOK_FORBIDDEN_ROOT"] = str(args.forbid_root.resolve())
    environment["SEASCAPE_NOTEBOOK_EXPECTED_PYTHON"] = sys.executable
    if args.workspace:
        environment["SEASCAPE_DEMO_WORKSPACE"] = str(args.workspace.resolve())
    else:
        environment.pop("SEASCAPE_DEMO_WORKSPACE", None)
    with tempfile.TemporaryDirectory(prefix="seascape-notebook-kernel-") as temporary:
        kernel_root = Path(temporary)
        kernel_name = "seascape-acceptance"
        spec_dir = kernel_root / kernel_name
        spec_dir.mkdir()
        (spec_dir / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [
                        sys.executable,
                        "-m",
                        "ipykernel_launcher",
                        "-f",
                        "{connection_file}",
                    ],
                    "display_name": "Seascape acceptance",
                    "language": "python",
                }
            )
        )
        manager = KernelManager(
            kernel_name=kernel_name,
            kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(kernel_root)]),
        )
        client = NotebookClient(
            notebook,
            km=manager,
            timeout=120,
            ipython_hist_file=":memory:",
            resources={"metadata": {"path": str(source.parent)}},
        )
        try:
            client.execute(cleanup_kc=True, env=environment)
        finally:
            output.parent.mkdir(parents=True, exist_ok=True)
            nbformat.write(notebook, output)
    assert source.read_bytes() == before, "Execution changed the copied source notebook"
    assert sorted(source.parent.iterdir()) == [source], (
        "Execution wrote into notebook-only cwd"
    )
    assert not any(
        item.get("output_type") == "error"
        for cell in notebook.cells
        for item in cell.get("outputs", [])
    )
    streams = "".join(
        item.get("text", "")
        for cell in notebook.cells
        for item in cell.get("outputs", [])
    )
    marker = "SEASCAPE NOTEBOOK ACCEPTANCE: "
    summary = json.loads(
        next(
            line[len(marker) :]
            for line in streams.splitlines()
            if line.startswith(marker)
        )
    )
    assert Path(summary["report"]).is_file(), (
        "Artifacts disappeared when the kernel exited"
    )
    retained = json.loads(Path(summary["report"]).read_text())
    assert retained["status"] == "PASS" and retained["metadata"]["synthetic"] is True
    embedded_figures = sum(
        "image/png" in item.get("data", {})
        for cell in notebook.cells
        for item in cell.get("outputs", [])
    )
    assert embedded_figures == 2, "Notebook did not display both generated figures"
    summary.update(
        {
            "executed_notebook": str(output),
            "source_sha256": hashlib.sha256(before).hexdigest(),
            "embedded_figures": embedded_figures,
            "retained_after_kernel_exit": True,
        }
    )
    output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
