"""Hash-bound disk-indexed mapped substrate producer; no historical audit input."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from pyproj import CRS, Transformer

from seascape.domain_parquets import AreaTables, write_areas
from seascape.regional.contract import digest
from seascape.utils.geometry_quality import audit_polygon_inventory

from .areal import build_areal_class_fractions

HISTORICAL_PIPELINE = "+proj=pipeline +step +inv +proj=aea +lat_0=45 +lon_0=-126 +lat_1=50 +lat_2=58.5 +x_0=1000000 +y_0=0 +ellps=GRS80 +step +proj=cea +lat_ts=30 +lon_0=0 +x_0=0 +y_0=0 +ellps=WGS84"


def require_identity(path, expected):
    if digest(path) != expected:
        raise ValueError(f"Scientific source checksum mismatch: {path}")


def build_index(
    source,
    expected_sha256,
    work,
    *,
    operation="current",
    geometry_policy="reject",
    batch_size=1024,
):
    source, work = Path(source), Path(work)
    require_identity(source, expected_sha256)
    if operation not in {"current", "historical-no-grid"} or batch_size < 1:
        raise ValueError("Invalid coordinate operation or batch size")
    parquet = pq.ParquetFile(source)
    geo = json.loads(parquet.schema_arrow.metadata[b"geo"])
    geometry_column = geo["primary_column"]
    crs = CRS.from_user_input(geo["columns"][geometry_column].get("crs") or "OGC:CRS84")
    if operation == "historical-no-grid" and crs != CRS.from_epsg(3005):
        raise ValueError("Historical operation requires original EPSG:3005 source")
    transformer = (
        Transformer.from_pipeline(HISTORICAL_PIPELINE)
        if operation == "historical-no-grid"
        else None
    )
    work.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(work / "source.sqlite")
    db.execute(
        "CREATE TABLE source (id INTEGER PRIMARY KEY, record_id TEXT UNIQUE NOT NULL, class_code TEXT NOT NULL, geom BLOB NOT NULL)"
    )
    db.execute("CREATE VIRTUAL TABLE bounds USING rtree(id,minx,maxx,miny,maxy)")
    count = 0
    try:
        for batch in parquet.iter_batches(batch_size=batch_size):
            frame = batch.to_pandas()
            frame = gpd.GeoDataFrame(
                frame.drop(columns=geometry_column),
                geometry=gpd.GeoSeries.from_wkb(frame[geometry_column], crs=crs),
                crs=crs,
            )
            if transformer is None:
                frame = frame.to_crs(6933)
            else:
                frame = frame.set_geometry(
                    shapely.transform(
                        frame.geometry.to_numpy(),
                        transformer.transform,
                        interleaved=False,
                    )
                ).set_crs(6933, allow_override=True)
            if "GEOMETRY_PROCESSING" in frame:
                frame = frame.rename(
                    columns={"GEOMETRY_PROCESSING": "SOURCE_GEOMETRY_PROCESSING"}
                )
            frame = audit_polygon_inventory(frame, policy=geometry_policy).frame
            if frame.RECORD_ID.isna().any() or frame.CLASS_CODE.isna().any():
                raise ValueError("Null source identity or class")
            if set(frame.CLASS_CODE.astype(str)) - {"1", "2", "3"}:
                raise ValueError("Unknown mapped substrate class")
            for row in frame.itertuples():
                count += 1
                x0, y0, x1, y1 = row.geometry.bounds
                db.execute(
                    "INSERT INTO source VALUES (?,?,?,?)",
                    (
                        count,
                        str(row.RECORD_ID),
                        str(row.CLASS_CODE),
                        shapely.to_wkb(row.geometry),
                    ),
                )
                db.execute(
                    "INSERT INTO bounds VALUES (?,?,?,?,?)", (count, x0, x1, y0, y1)
                )
            db.commit()
    finally:
        db.close()
    if count == 0:
        raise ValueError("Source inventory is empty")
    require_identity(source, expected_sha256)
    receipt = dict(
        input=str(source.resolve()),
        input_sha256=expected_sha256,
        source_crs=crs.to_json_dict(),
        coordinate_operation=operation,
        explicit_pipeline=HISTORICAL_PIPELINE if transformer else None,
        geometry_policy=geometry_policy,
        records=count,
        index_sha256=digest(work / "source.sqlite"),
    )
    (work / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def produce(
    index, support, support_sha256, keys, *, rights, batch_size=128, max_records=800000
):
    index, support = Path(index), Path(support)
    receipt = json.loads((index / "manifest.json").read_text())
    require_identity(index / "source.sqlite", receipt["index_sha256"])
    require_identity(support, support_sha256)
    if not keys or len(set(keys)) != len(keys) or batch_size < 1 or not rights:
        raise ValueError(
            "Unique nonempty target keys, positive batch and source rights required"
        )
    db = sqlite3.connect(f"file:{index / 'source.sqlite'}?mode=ro", uri=True)
    tables = []
    try:
        for first in range(0, len(keys), batch_size):
            wet = gpd.read_parquet(
                support, filters=[("H3_INDEX", "in", keys[first : first + batch_size])]
            ).to_crs(6933)
            if wet.empty:
                continue
            x0, y0, x1, y1 = wet.total_bounds
            query = " FROM source s JOIN bounds b ON s.id=b.id WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?"
            args = (x1, x0, y1, y0)
            count = db.execute("SELECT COUNT(*)" + query, args).fetchone()[0]
            if count > max_records:
                raise ValueError(
                    "Spatial batch exceeds source-record limit; reduce batch size"
                )
            rows = db.execute(
                "SELECT s.record_id,s.class_code,s.geom" + query + " ORDER BY s.id",
                args,
            ).fetchall()
            # Empty intersections remain an empty inventory: never substitute a record.
            frame = pd.DataFrame(rows, columns=["RECORD_ID", "CLASS_CODE", "wkb"])
            inventory = gpd.GeoDataFrame(
                frame.drop(columns="wkb"),
                geometry=gpd.GeoSeries.from_wkb(frame.wkb, crs=6933),
                crs=6933,
            )
            tables.append(
                build_areal_class_fractions(
                    inventory,
                    wet,
                    classes={"1": "HARD", "2": "MIXED", "3": "SOFT"},
                    source_context={
                        **receipt,
                        "rights": rights,
                        "support_sha256": support_sha256,
                    },
                    max_records=max_records,
                )
            )
    finally:
        db.close()
    if not tables:
        raise ValueError("No requested keys have scientific support")
    return pa.concat_tables(tables)


def add_arguments(parser):
    for name in ("source", "support", "keys", "work", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-sha256", "support-sha256", "rights"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--coordinate-operation",
        choices=["current", "historical-no-grid"],
        default="current",
    )
    parser.add_argument(
        "--geometry-policy", choices=["reject", "make_valid"], default="reject"
    )
    parser.add_argument("--batch-size", type=int, default=128)


def run(args):
    keys = args.keys.read_text().splitlines()
    build_index(
        args.source,
        args.source_sha256,
        args.work,
        operation=args.coordinate_operation,
        geometry_policy=args.geometry_policy,
    )
    table = produce(
        args.work,
        args.support,
        args.support_sha256,
        keys,
        rights=args.rights,
        batch_size=args.batch_size,
    )
    pq.write_table(table, args.work / "native-diagnostics.parquet", compression="zstd")
    missing = sorted(set(keys) - set(table["H3_INDEX"].to_pylist()))
    (args.work / "support-diagnostics.json").write_text(
        json.dumps({"unsupported_keys": missing}, indent=2) + "\n"
    )
    write_areas(
        {"mapped-substrate-classes": AreaTables(static=table)}, output=args.output
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
