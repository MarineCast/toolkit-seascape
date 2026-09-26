"""Run offline demo acceptance from an installed runtime-only wheel.

Copy this helper outside the checkout, then use the consumer Python to run it.
The process audit guard rejects socket connections/DNS and child processes;
this is Python-level denial, not an operating-system network firewall.
"""

from __future__ import annotations

import argparse
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys


class RuntimeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {
            "orcacast",
            "pytest",
            "IPython",
            "ipykernel",
            "jupyter",
            "jupyterlab",
            "nbformat",
            "nbclient",
            "nbconvert",
        }:
            raise ImportError(f"Development/application import forbidden: {fullname}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--forbid-root", type=Path)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    demo_root = args.workspace.resolve() / ".seascape/demo"
    for name in ("pytest", "nbconvert", "jupyterlab", "ipykernel"):
        if importlib.util.find_spec(name) is not None:
            raise AssertionError(f"Consumer must have no development package: {name}")
    sys.meta_path.insert(0, RuntimeImports())
    attempts = []
    blocked_children = []
    # shutil's safe cleanup uses descriptor-relative paths. Retain their bases
    # so those audit events are checked against the real directory, not cwd.
    descriptor_paths = {}
    original_open, original_close = os.open, os.close

    def opened(path, flags, mode=0o777, *, dir_fd=None):
        resolved = Path(os.fsdecode(path))
        if not resolved.is_absolute():
            resolved = descriptor_paths.get(dir_fd, Path.cwd()) / resolved
        descriptor = original_open(resolved, flags, mode)
        descriptor_paths[descriptor] = resolved.resolve()
        return descriptor

    def closed(descriptor):
        descriptor_paths.pop(descriptor, None)
        return original_close(descriptor)

    os.open, os.close = opened, closed

    def deny_network(event, arguments):
        if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(arguments[0])).resolve()
            if (
                "toolkit-seascape" in path.parts
                or "OrcaCast" in path.parts
                or (
                    args.forbid_root and path.is_relative_to(args.forbid_root.resolve())
                )
            ):
                raise AssertionError(f"Checkout access forbidden: {path}")
            flags = arguments[2]
            if flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            ):
                if not path.is_relative_to(demo_root):
                    raise AssertionError(f"Write outside demo: {path}")
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename"}:
            paths = arguments[:2] if event == "os.rename" else arguments[:1]
            for index, name in enumerate(paths):
                path = Path(os.fsdecode(name))
                fd_index = (
                    index + 2
                    if event == "os.rename"
                    else (2 if event == "os.mkdir" else 1)
                )
                descriptor = arguments[fd_index]
                if not path.is_absolute() and descriptor not in (None, -1):
                    if descriptor not in descriptor_paths:
                        raise AssertionError(
                            f"Unknown directory descriptor: {descriptor}"
                        )
                    path = descriptor_paths[descriptor] / path
                path = path.resolve()
                if not path.is_relative_to(demo_root) and not (
                    event == "os.mkdir" and path in demo_root.parents
                ):
                    raise AssertionError(
                        f"Filesystem mutation outside demo: {event} {path}"
                    )
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
            blocked_children.append(event)
            # Matplotlib can fall back to bundled fonts when local font discovery
            # is denied. No child is launched outside this process's guard.
            raise PermissionError(f"Offline acceptance denied: {event}")
        if event in {
            "socket.connect",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.sendto",
            "socket.sendmsg",
        }:
            attempts.append(event)
            raise RuntimeError(f"Offline acceptance denied: {event}")

    sys.addaudithook(deny_network)
    # Verify the guard actually rejects an attempted outbound connection.
    try:
        with socket.socket() as connection:
            connection.connect(("192.0.2.1", 443))
    except RuntimeError as exc:
        assert "Offline acceptance denied" in str(exc)
    else:
        raise AssertionError("Outbound guard did not reject connect")
    assert attempts == ["socket.connect"]
    attempts.clear()
    import seascape
    from seascape.cli import main as cli_main

    package = Path(seascape.__file__).resolve()
    assert package.is_relative_to(Path(sys.prefix).resolve())
    assert "site-packages" in package.parts
    assert cli_main(["--workspace", str(args.workspace), "demo"]) == 0
    assert not attempts, attempts
    report = args.workspace.resolve() / ".seascape/demo/report.json"
    payload = json.loads(report.read_text())
    assert payload["status"] == "PASS"
    assert payload["row_count"] > 0
    assert payload["checks"] and all(payload["checks"].values())
    print(
        json.dumps(
            {
                "status": "PASS",
                "package": str(package),
                "python": sys.version,
                "checks": len(payload["checks"]),
                "network_attempts": attempts,
                "blocked_child_processes": blocked_children,
                "report": str(report),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
