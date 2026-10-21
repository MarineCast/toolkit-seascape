"""Replay an audited mapped-bed inventory to an explicit flat candidate directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pyarrow as pa

from seascape.biogenic_habitat.bivalve.extents import build_bivalve_extents
from seascape.domain_parquets import METADATA_KEY, AreaTables, write_areas


def build_bivalve_habitat(*, inventory, full_cells, source_context, output):
    """Build independent native grids; no acquisition, buffers or inferred dates."""
    if not full_cells:
        raise ValueError("Explicit full native cell geometry is required")
    results = {
        res: build_bivalve_extents(inventory, cells, source_context=source_context)
        for res, cells in sorted(full_cells.items())
    }
    for res, result in results.items():
        if result.report["native_resolution"] != res:
            raise ValueError("Requested and actual native resolution differ")
    contexts = {
        str(res): json.loads(result.tables.static.schema.metadata[METADATA_KEY])
        for res, result in results.items()
    }
    context = dict(next(iter(contexts.values())))
    context.pop("report", None)
    context["resolution_contexts"] = contexts
    table = pa.concat_tables(
        [r.tables.static for r in results.values()]
    ).replace_schema_metadata(
        {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
    )
    return write_areas(
        {"bivalve": AreaTables(static=table, dynamic=None)}, output=Path(output)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--source-context", type=Path, required=True)
    parser.add_argument(
        "--full-cells", action="append", required=True, metavar="RES=PARQUET"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cells = {
        int(s.split("=", 1)[0]): gpd.read_parquet(s.split("=", 1)[1])
        for s in args.full_cells
    }
    build_bivalve_habitat(
        inventory=gpd.read_parquet(args.inventory),
        full_cells=cells,
        source_context=json.loads(args.source_context.read_text()),
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
