"""Deliberate negative probes; success means these processes fail as expected."""

from __future__ import annotations

import argparse
import importlib.abc
from pathlib import Path
import socket
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "case", choices=("missing-dependency", "source-import", "outbound-demo")
    )
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.case == "missing-dependency":

        class MissingRasterio(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "rasterio" or fullname.startswith("rasterio."):
                    raise ModuleNotFoundError(
                        "SS-03 missing runtime dependency: rasterio"
                    )
                return None

        sys.meta_path.insert(0, MissingRasterio())
    elif args.case == "source-import":
        if args.source is None:
            parser.error("--source is required")
        sys.path.insert(0, str(args.source / "src"))
    from seascape.demo import run_demo

    if args.case == "outbound-demo":
        from seascape import demo

        def attempted_acquisition(*unused_args, **unused_kwargs):
            socket.create_connection(("192.0.2.1", 443))

        demo.run_pipeline = attempted_acquisition
        run_demo(args.workspace)
    raise AssertionError(f"Negative probe unexpectedly succeeded: {args.case}")


if __name__ == "__main__":
    main()
