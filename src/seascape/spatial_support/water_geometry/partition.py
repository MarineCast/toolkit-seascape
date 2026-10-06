"""Adopt explicit source-mapped land/water tile partitions without redefining water.

The rectangular partition and the engineering coastal reporting selector are separate.
No source acquisition, union/dissolve, simplification or coastline fabrication occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd

from seascape.core.geo.h3 import polygon_to_cells_overlap


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourcePartition:
    """Pinned polygon partition, retaining tile pieces, islands and holes."""

    handoff: dict[str, Any]
    geometry_path: Path
    geometry_sha256: str

    def pieces(self, layer: str = "water_area") -> gpd.GeoDataFrame:
        if layer not in {"land_area", "water_area", "reporting_water"}:
            raise ValueError(
                "Select an explicit land, water or separate reporting layer."
            )
        if raw_sha256(self.geometry_path) != self.geometry_sha256:
            raise ValueError("Pinned partition bytes changed.")
        frame = gpd.read_file(self.geometry_path, layer=layer)
        if frame.crs is None or frame.crs.to_epsg() != 4326 or frame.empty:
            raise ValueError("Partition layer must be nonempty native WGS84.")
        if (
            frame.geometry.isna().any()
            or frame.geometry.is_empty.any()
            or not frame.geometry.is_valid.all()
            or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        ):
            raise ValueError("Partition contains invalid or non-area source geometry.")
        # Do not dissolve: nonoverlapping source tiles have union semantics.
        return frame

    def native_reporting_cells(
        self,
        resolution: int = 8,
        *,
        check: Callable[[], None] | None = None,
        progress: Callable[[dict[str, int]], None] | None = None,
    ) -> list[str]:
        """Direct polygon-overlap native companions from the separate reporting layer.

        This is mapped selector support, not final 12-nm eligibility or water-network proof.
        H3's overlap-aware implementation is mandatory; center-only fallback is refused.
        """
        import h3

        if resolution != 8 or not hasattr(h3, "polygon_to_cells_experimental"):
            raise ValueError("Native companions require overlap-aware H3 resolution 8.")
        cells: set[str] = set()
        pieces = self.pieces("reporting_water")
        for index, geometry in enumerate(pieces.geometry):
            if check is not None:
                check()
            cells.update(polygon_to_cells_overlap(geometry, resolution))
            if progress is not None:
                progress(
                    {
                        "pieces_completed": index + 1,
                        "pieces_total": len(pieces),
                        "native_cells": len(cells),
                    }
                )
        if check is not None:
            check()
        return sorted(cells)


def load_source_partition(handoff_path: str | Path) -> SourcePartition:
    """Require explicit complete outer source coverage and retained topology evidence."""
    path = Path(handoff_path).resolve()
    record = json.loads(path.read_bytes())
    if (
        record.get("water_equation")
        != "study_rectangle minus land_area; valid nonoverlapping tile pieces with union semantics"
    ):
        raise ValueError(
            "Partition must explicitly define water as study rectangle minus land."
        )
    checks = record.get("topology_checks", {})
    if (
        checks.get("valid_land_water") is not True
        or checks.get("positive_area_overlap") is not False
        or checks.get("partition_gaps") is not False
    ):
        raise ValueError("Source partition lacks valid gap-free, nonoverlap evidence.")
    if not record.get("coverage") or "global" not in record["coverage"].casefold():
        raise ValueError(
            "Missing complete outer source coverage; absent local geometry is not water."
        )
    geometry = (path.parent / record["geometry_file"]).resolve()
    if geometry.parent != path.parent:
        raise ValueError("Partition geometry must be beside the explicit handoff.")
    expected = record.get("geometry_sha256")
    if not isinstance(expected, str) or raw_sha256(geometry) != expected:
        raise ValueError("Partition geometry checksum mismatch.")
    return SourcePartition(record, geometry, expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument("--native-r8-output", type=Path)
    args = parser.parse_args()
    partition = load_source_partition(args.handoff)
    result: dict[str, Any] = {
        "status": "source_partition_adopted",
        "geometry_sha256": partition.geometry_sha256,
        "water_definition": partition.handoff["water_equation"],
        "final_12nm_eligibility": False,
    }
    if args.native_r8_output:
        cells = partition.native_reporting_cells()
        with args.native_r8_output.open("x") as output:
            output.write("".join(cell + "\n" for cell in cells))
        result["native_r8_cells"] = len(cells)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
