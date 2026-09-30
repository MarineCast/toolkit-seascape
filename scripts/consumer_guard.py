"""Run a copied acceptance script/module with Python offline and checkout guards.

Dependency installation is a separate, unguarded step. This denies Python socket
activity and child processes, not native-extension traffic at the OS level.
Notebook kernels use check_validation_notebook.py's separate loopback-aware guard.
"""

from __future__ import annotations

import argparse
import os
import runpy
import socket
import sys
from pathlib import Path


def install_guard(forbidden: Path) -> None:
    sys.dont_write_bytecode = True

    def audit(event, arguments):
        if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(arguments[0])).resolve()
            if path.is_relative_to(forbidden):
                raise AssertionError(f"Checkout access forbidden: {path}")
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
            raise PermissionError(f"Offline consumer denies child processes: {event}")
        if event in {
            "socket.connect",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.sendto",
            "socket.sendmsg",
        }:
            raise RuntimeError(f"Offline consumer denies outbound activity: {event}")

    sys.addaudithook(audit)
    try:
        with socket.socket() as connection:
            connection.connect(("192.0.2.1", 443))
    except RuntimeError as exc:
        assert "Offline consumer denies outbound activity" in str(exc)
    else:
        raise AssertionError("Outbound guard failed")
    try:
        (forbidden / "seascape-acceptance-read-probe").read_bytes()
    except AssertionError as exc:
        assert "Checkout access forbidden" in str(exc)
    else:
        raise AssertionError("Checkout guard failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forbid-root", required=True, type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--script", type=Path)
    target.add_argument("--module")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    install_guard(args.forbid_root.resolve())
    remainder = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    sys.argv = [str(args.script or args.module), *remainder]
    if args.script:
        runpy.run_path(str(args.script), run_name="__main__")
    else:
        runpy.run_module(args.module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
