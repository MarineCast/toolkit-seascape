"""Render the retained September 19 San Juan bathymetry snapshot without acquisition.

Static cartography only. Fixed source identities, exact-key joins and shared
linear depth encoding preserve the original R8/R6 products and missingness.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Patch

from seascape.core.artifacts.checksums import checksum_path
from seascape.utils.artifacts import load_manifest, validate_manifest

BASE = Path("data/processed/domain/environmental_layer/seascape")
IDENTITIES = {
    8: (
        "27caefaba8979f57a6b89798883bc5f1c4273e6a5b716aa9edaef6a9109de3f8",
        "1f774932eabe1d2f8900f75455e19d6cafab8a433d6d2b89e5166b578df8dec2",
    ),
    6: (
        "76aac92873007d2a0b6c16b4c6600524725df491d810fa7aa07a6391b65f88b4",
        "48dc80fd89ed49c4569d68f9d546d694b2f05187b6c87945f629e9fcb88355c5",
    ),
}
BOUNDS = (-123.31, 48.395, -122.72, 48.795)


def load_snapshot(root: Path):
    family = root / BASE / "seafloor_physiography/bathymetry/bathymetry_manifest.json"
    manifest = load_manifest(family)
    validate_manifest(manifest, project_root=root, verify_artifacts=True)
    for item in [*manifest["sources"], *manifest["upstream_artifacts"]]:
        if item.get("path") and checksum_path(root / item["path"]) != item["checksum"]:
            raise ValueError(f"Snapshot input changed: {item['path']}")
    frames, evidence = {}, {}
    for res, (product_hash, geometry_hash) in IDENTITIES.items():
        name = "BATHYMETRY.parquet" if res == 8 else "BATHYMETRY_RES_6.parquet"
        product = family.parent / name
        geometry = (
            root
            / BASE
            / f"spatial_support/h3_geometry/H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_{res}.parquet"
        )
        if (
            checksum_path(product) != product_hash
            or checksum_path(geometry) != geometry_hash
        ):
            raise ValueError(f"Expected the retained September 19 R{res} snapshot")
        table = pd.read_parquet(product)[["H3_INDEX", "BATHYMETRY"]]
        cells = gpd.read_parquet(geometry)
        if table.H3_INDEX.isna().any() or set(table.H3_INDEX) != set(cells.H3_INDEX):
            raise ValueError("Depth and geometry support differ")
        values = table.BATHYMETRY.dropna()
        if not np.isfinite(values).all() or not values.between(0, 400).all():
            raise ValueError("Depth values exceed the fixed display scale")
        merged = cells.merge(table, on="H3_INDEX", validate="one_to_one")
        visible = gpd.clip(merged.to_crs(4326), box(*BOUNDS)).to_crs(32610)
        frames[res] = visible
        evidence[str(res)] = {
            "product_checksum": product_hash,
            "geometry_checksum": geometry_hash,
            "full_support_cells": len(merged),
            "displayed_cells": len(visible),
            "displayed_available": int(visible.BATHYMETRY.notna().sum()),
            "displayed_unavailable": int(visible.BATHYMETRY.isna().sum()),
            "displayed_min_m": float(visible.BATHYMETRY.min()),
            "displayed_max_m": float(visible.BATHYMETRY.max()),
        }
    return frames, evidence, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--land", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frames, evidence, manifest = load_snapshot(args.workspace.resolve())
    land = gpd.read_file(args.land, bbox=BOUNDS)
    if land.crs is None:
        raise ValueError("Land source has no CRS")
    land = gpd.clip(land.to_crs(4326), box(*BOUNDS)).to_crs(32610)
    ink, muted, paper = "#173C43", "#597078", "#FCFCF9"
    ground, outside, missing = "#E8EBDD", "#F1F5F4", "#A6AFB4"
    cmap = LinearSegmentedColormap.from_list(
        "san_juan_depth", ["#E2F4EF", "#92CFCC", "#328D9E", "#176379", "#103B55"]
    )
    norm = Normalize(0, 400)
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "text.color": ink, "font.size": 11}
    )
    fig = plt.figure(figsize=(14, 10), facecolor=paper)
    fig.text(
        0.045,
        0.952,
        "MARINECAST  /  SEASCAPE ATLAS",
        size=11,
        weight="bold",
        color="#257D80",
    )
    fig.text(
        0.955,
        0.952,
        "SNAPSHOT 01     ·     19 SEP 2026",
        size=10,
        ha="right",
        color=muted,
    )
    fig.text(0.045, 0.891, "Beneath the San Juans", size=31, weight="bold")
    fig.text(
        0.045,
        0.851,
        "Mean water depth across the island passages  ·  GEBCO 2026 on two H3 grids",
        size=13,
        color=muted,
    )
    transform = Transformer.from_crs(4326, 32610, always_xy=True)
    bounds = gpd.GeoSeries([box(*BOUNDS)], crs=4326).to_crs(32610).total_bounds

    def draw_map(rect, res, line_width):
        ax = fig.add_axes(rect, facecolor=outside)
        land.plot(ax=ax, color=ground, edgecolor="#ABB9AD", linewidth=0.55, zorder=1)
        frames[res].plot(
            ax=ax,
            column="BATHYMETRY",
            cmap=cmap,
            norm=norm,
            edgecolor=(1, 1, 1, 0.42),
            linewidth=line_width,
            missing_kwds={"color": missing, "edgecolor": "#E1E5E5"},
            zorder=2,
        )
        land.boundary.plot(ax=ax, color="#788C80", linewidth=0.45, zorder=3)
        ax.set(
            xlim=(bounds[0], bounds[2]),
            ylim=(bounds[1], bounds[3]),
            xticks=[],
            yticks=[],
        )
        ax.set_aspect("equal")
        for spine in ax.spines.values():
            spine.set_color("#CDD8D4")
        return ax

    ax = draw_map((0.045, 0.175, 0.625, 0.62), 8, 0.18)
    ax.text(
        0.025,
        0.963,
        "H3 RESOLUTION 8",
        transform=ax.transAxes,
        size=10,
        weight="bold",
        va="top",
        bbox={"facecolor": paper, "edgecolor": "none", "pad": 6},
    )

    def label(lon, lat, text, water=False, size=10):
        x, y = transform.transform(lon, lat)
        ax.text(
            x,
            y,
            text,
            ha="center",
            va="center",
            fontsize=size,
            weight="normal" if water else "bold",
            style="italic" if water else "normal",
            color="#304F59" if water else ink,
            path_effects=[pe.withStroke(linewidth=3, foreground=paper, alpha=0.88)],
        )

    for lon, lat, name in [
        (-123.09, 48.54, "SAN JUAN\nISLAND"),
        (-122.92, 48.68, "ORCAS\nISLAND"),
        (-122.885, 48.46, "LOPEZ\nISLAND"),
        (-122.96, 48.59, "SHAW"),
    ]:
        label(lon, lat, name, size=10 if name != "SHAW" else 8)
    label(-123.235, 48.625, "Haro Strait", True, 11)
    label(-122.80, 48.585, "Rosario\nStrait", True, 10)
    x, y = transform.transform(-123.017, 48.535)
    ax.plot(x, y, "o", color=ink, ms=3, zorder=5)
    ax.annotate(
        "Friday Harbor",
        (x, y),
        xytext=(9, -15),
        textcoords="offset points",
        size=8,
        bbox={"facecolor": paper, "edgecolor": "none", "alpha": 0.92, "pad": 2},
        zorder=6,
    )
    x, y = bounds[0] + 2200, bounds[1] + 2300
    ax.plot([x, x + 5000], [y, y], color=ink, lw=2.5, zorder=5)
    ax.text(x + 2500, y + 850, "5 km", ha="center", size=9)
    x, y = transform.transform(-122.755, 48.738)
    xn, yn = transform.transform(-122.755, 48.768)
    ax.annotate(
        "N",
        (xn, yn),
        (x, y),
        ha="center",
        weight="bold",
        size=10,
        arrowprops={"arrowstyle": "-|>", "color": ink},
    )

    fig.text(
        0.725,
        0.777,
        "THE SAME WATERS, COARSER CELLS",
        size=9,
        weight="bold",
        color=muted,
    )
    inset = draw_map((0.725, 0.50, 0.23, 0.25), 6, 0.55)
    inset.text(
        0.04,
        0.94,
        "H3 R6",
        transform=inset.transAxes,
        size=8,
        weight="bold",
        va="top",
        bbox={"facecolor": paper, "edgecolor": "none", "pad": 3},
    )
    fig.text(0.725, 0.475, "Same extent. Same depth scale.", size=10, weight="bold")
    fig.text(
        0.725,
        0.448,
        "Native product means; no smoothing\nor interpolation between cells.",
        size=9,
        color=muted,
        linespacing=1.5,
        va="top",
    )
    fig.text(0.725, 0.377, "MEAN DEPTH", size=10, weight="bold")
    fig.text(0.725, 0.352, "Metres · positive down", size=10, color=muted)
    cbax = fig.add_axes((0.725, 0.317, 0.23, 0.017))
    cb = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=cmap),
        cax=cbax,
        orientation="horizontal",
        ticks=[0, 100, 200, 300, 400],
    )
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=9, length=3, color=muted)
    fig.legend(
        handles=[
            Patch(facecolor=ground, label="Generalized land"),
            Patch(facecolor=missing, label="Depth unavailable"),
            Patch(
                facecolor=outside, edgecolor="#CDD8D4", label="Outside snapshot support"
            ),
        ],
        loc="upper left",
        bbox_to_anchor=(0.719, 0.277),
        frameon=False,
        fontsize=9,
        labelspacing=0.8,
    )
    fig.text(0.045, 0.124, "A fixed view of real source data", weight="bold", size=12)
    fig.text(
        0.045,
        0.099,
        "Thin outlines reveal the grid. Gray cells retain missing depth; land is shown separately.",
        size=10,
        color=muted,
    )
    fig.text(
        0.045,
        0.065,
        "Depth: GEBCO Compilation Group (2026), GEBCO 2026 Grid · 15 arc seconds. Land: Natural Earth v5.1.1 · 1:10 million.",
        size=8.5,
        color=muted,
    )
    fig.text(
        0.045,
        0.041,
        "Exploratory notebook snapshot · generalized coastlines · WGS 84 / UTM 10N · not for navigation or a complete regional release.",
        size=8.5,
        color=muted,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=220, facecolor=paper)
    fig.savefig(args.output.with_suffix(".pdf"), facecolor=paper)
    plt.close(fig)
    result = {
        "snapshot_built_at_utc": manifest["built_at_utc"],
        "synthetic": False,
        "scope": "Retained September 19 exploratory notebook products; rendering only",
        "bbox_wgs84": BOUNDS,
        "projection": "EPSG:32610",
        "scale_m": [0, 400],
        "products": evidence,
        "family_manifest_checksum": checksum_path(
            args.workspace.resolve()
            / BASE
            / "seafloor_physiography/bathymetry/bathymetry_manifest.json"
        ),
        "land_files": {
            p.name: checksum_path(p)
            for p in sorted(args.land.parent.glob(args.land.stem + ".*"))
            if p.is_file()
        },
        "image_checksum": checksum_path(args.output),
        "pdf_checksum": checksum_path(args.output.with_suffix(".pdf")),
    }
    args.output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
