"""Bounded retained-input replay and delivered layer maps; no network or publication."""

import argparse
import hashlib
import json
from pathlib import Path

import geopandas as gpd
import h3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely.geometry import Polygon

from seascape.biogenic_habitat.bivalve.extents import build_bivalve_extents
from seascape.biogenic_habitat.seagrass.native import native_cell_geometries
from seascape.reviewed_delivery import restore_native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    data = root / "Data/Seascape"
    toolkit = root / "Toolkits/toolkit-seascape"
    report = {
        "review_date": "2026-10-29",
        "scope": "Static projection verification; 40-cell R6 bivalve scientific replay; delivered maps, not full regional reconstruction",
        "products": {},
    }
    for path in sorted(data.glob("*-static.parquet")):
        public = pq.read_table(path)
        native = restore_native(public)
        df = public.to_pandas()
        key = "H3_INDEX" if "H3_INDEX" in df else "h3_index"
        assert not df[key].duplicated().any()
        report["products"][path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(df),
            "columns": list(df),
            "native_columns": native.num_columns,
            "audit_projection_verified": True,
            "nulls": df.isna().sum().to_dict(),
        }
    source = toolkit / ".seascape/work/biogenic-recovery-20261020"
    inventory = gpd.read_parquet(source / "source-inventory.parquet")
    context = json.loads((source / "source-context.json").read_text())
    original = restore_native(
        pq.read_table(data / "bivalve-r6-static.parquet")
    ).to_pandas()
    field = "BIVALVE_EXTENT_ALL_TIME_M2"
    chosen = pd.concat(
        [
            original.loc[original[field].gt(0)].sort_values("H3_INDEX").head(20),
            original.loc[original[field].isna()].sort_values("H3_INDEX").head(20),
        ]
    )
    keys = chosen.H3_INDEX.tolist()
    geometry, _ = native_cell_geometries(keys)
    cells = gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [6] * len(keys)},
        geometry=geometry,
        crs=4326,
    )
    result = build_bivalve_extents(inventory, cells, source_context=context)
    actual = result.tables.static.to_pandas().set_index("H3_INDEX").loc[keys]
    expected = chosen.set_index("H3_INDEX").loc[keys]
    assert np.array_equal(actual[field].isna(), expected[field].isna())
    np.testing.assert_allclose(
        actual[field], expected[field], rtol=1e-10, atol=1e-6, equal_nan=True
    )
    pq.write_table(result.tables.static, out / "bivalve-40-cell-replay.parquet")
    report["replay"] = {
        "cells": len(keys),
        "positive": int(expected[field].gt(0).sum()),
        "null": int(expected[field].isna().sum()),
        "max_absolute_error_m2": float((actual[field] - expected[field]).abs().max()),
        "source_inventory_sha256": hashlib.sha256(
            (source / "source-inventory.parquet").read_bytes()
        ).hexdigest(),
        "comparison": "H3 keys, native area and null masks; not byte identity or all provenance fields",
    }
    specs = [
        ("bathymetry", 8, "bathymetry__BATHYMETRY", "Mean depth", "m positive down"),
        ("terrain", 8, "seafloor_slope_mean_deg", "Seafloor slope", "degrees"),
        ("shoreline", 8, "mapped_shoreline_length_m", "Mapped shoreline", "m"),
        (
            "freshwater",
            8,
            "freshwater_sources__DISTANCE_TO_RIVER_MOUTH_M",
            "River-mouth distance",
            "m",
        ),
        (
            "estuary",
            8,
            "distance_to_mapped_estuary_point_m",
            "Mapped estuary distance",
            "m",
        ),
        ("bivalve", 6, field, "All-time mapped bivalve beds", "m²"),
        ("kelp", 6, "KELP_EXTENT_ALL_TIME_M2", "All-time mapped kelp beds", "m²"),
        (
            "mapped-substrate-classes",
            6,
            "mapped_hard_substrate_fraction",
            "Mapped hard substrate",
            "fraction",
        ),
    ]
    for area, res, column, title, unit in specs:
        path = data / f"{area}-r{res}-static.parquet"
        table = pq.read_table(path)
        if area in ("kelp", "bivalve"):
            table = restore_native(table)
        df = table.to_pandas()
        key = "H3_INDEX" if "H3_INDEX" in df else "h3_index"
        centers = df[key].map(h3.cell_to_latlng)
        mask = centers.map(lambda p: 47.8 <= p[0] <= 49 and -123.6 <= p[1] <= -122.3)
        df = df.loc[mask]
        polygons = [
            Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(k)])
            for k in df[key]
        ]
        geo = gpd.GeoDataFrame(df, geometry=polygons, crs=4326).to_crs(32610)
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.set_facecolor("#f6f5f0")
        geo.plot(ax=ax, color="#bdbdbd", linewidth=0)
        valid = geo.loc[geo[column].notna()]
        if len(valid):
            valid.plot(
                column=column,
                ax=ax,
                cmap="viridis",
                legend=True,
                legend_kwds={"label": unit, "shrink": 0.65},
                linewidth=0,
            )
        ax.set_title(f"{title} · native H3 R{res}", loc="left", fontsize=14, pad=12)
        ax.set_xlabel("UTM zone 10N easting (m)")
        ax.set_ylabel("Northing (m)")
        ax.ticklabel_format(style="plain", axis="both")
        ax.tick_params(labelsize=8)
        fig.text(
            0.08,
            0.035,
            "Gray: native no data / unknown. Unfilled background: outside displayed support.\nSource: retained MarineCast Seascape + bound native audits · reviewed 2026-10-29\nFull H3 display geometry; values retain original support. No interpolation.",
            fontsize=8,
        )
        fig.subplots_adjust(bottom=0.17)
        fig.savefig(out / f"{area}.png", dpi=140)
        plt.close(fig)
    report["sill_research_rows"] = pq.read_metadata(
        data / "research/sill-candidates.parquet"
    ).num_rows
    w = pq.read_table(data / "waterbody-morphometry-r8-static.parquet").to_pandas()
    report["waterbody_sill_distance_nonnull"] = int(
        w.distance_to_sill_candidate_m.notna().sum()
    )
    (out / "evidence.json").write_text(json.dumps(report, indent=2, default=int) + "\n")
    print(json.dumps(report["replay"]))


if __name__ == "__main__":
    main()
