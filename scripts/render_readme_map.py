"""Render the README's real, exploratory San Juan pilot map from local inputs.

Cartographic export only: existing production values and clipped geometries are
joined one-to-one. No downloads, interpolation, builders, or release promotion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--land", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace.resolve()
    product = next(root.rglob("BATHYMETRY.parquet"))
    geometry = next(root.rglob("H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_8.parquet"))
    manifest = json.loads(product.with_name("bathymetry_manifest.json").read_text())
    # Bind this illustration to the reviewed pilot, not any arbitrary family.
    if (
        checksum_path(product)
        != "a2b5cea25fea014e13113158b66452b552a69f36bec0585a63197814878560aa"
    ):
        raise ValueError("Expected the documented San Juan replicate-1 pilot product")
    for record in [
        *manifest["artifacts"],
        *manifest["upstream_artifacts"],
        *manifest["sources"],
    ]:
        if (
            record.get("path")
            and checksum_path(root / record["path"]) != record["checksum"]
        ):
            raise ValueError(f"Manifest checksum mismatch: {record['path']}")
    for path in (root / "data/processed").rglob("*manifest.json"):
        validate_manifest(load_manifest(path), project_root=root, verify_artifacts=True)
    table = pd.read_parquet(product)[["H3_INDEX", "BATHYMETRY"]]
    cells = gpd.read_parquet(geometry)
    if set(cells.H3_INDEX) != set(table.H3_INDEX):
        raise ValueError("Geometry and depth cell identities differ")
    mapped = cells.merge(table, on="H3_INDEX", validate="one_to_one").to_crs(32610)
    if len(mapped) != 4660 or not (mapped.BATHYMETRY.dropna() > 0).all():
        raise ValueError("Unexpected pilot depth support")
    # Read only the regional window from the cached, public-domain land layer.
    land = gpd.read_file(args.land, bbox=(-125.5, 46.7, -121, 50.5))
    land = gpd.clip(land, box(-125.5, 46.7, -121, 50.5)).dissolve().to_crs(32610)
    transform = Transformer.from_crs(4326, 32610, always_xy=True)
    ink, teal, ocean, ground = "#123E37", "#0F766E", "#E9F3F2", "#F1F3E9"
    cmap = LinearSegmentedColormap.from_list(
        "seascape", ["#ECFDF5", "#5EAAA0", "#0F766E", "#06465A"]
    )
    norm = Normalize(0, 400)
    if mapped.BATHYMETRY.max() > norm.vmax:
        raise ValueError("Depth scale would clip data")
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "text.color": ink, "font.size": 11}
    )
    fig = plt.figure(figsize=(12, 9), facecolor="#FFFFFF")
    fig.text(
        0.055,
        0.947,
        "SEASCAPE  /  REAL-DATA EXPLORER",
        color=teal,
        weight="bold",
        size=11,
    )
    fig.text(
        0.055, 0.898, "San Juan Islands & surrounding waters", weight="bold", size=23
    )
    fig.text(
        0.055,
        0.86,
        "Salish Sea · Washington / British Columbia     |     GEBCO 2026 → H3 resolution 8",
        size=12,
    )
    ax = fig.add_axes((0.055, 0.16, 0.62, 0.65), facecolor=ocean)
    land.plot(ax=ax, color=ground, edgecolor="#97ACA5", linewidth=0.5)
    mapped.plot(
        ax=ax,
        column="BATHYMETRY",
        cmap=cmap,
        norm=norm,
        edgecolor="none",
        missing_kwds={"color": "#A6AFB4"},
    )
    # Redraw the coastline over the cell layer without altering cell values.
    land.boundary.plot(ax=ax, color="#81978D", linewidth=0.4)
    west, south = transform.transform(-123.65, 48.30)
    east, north = transform.transform(-122.50, 49.06)
    ax.set(xlim=(west, east), ylim=(south, north), xticks=[], yticks=[])
    ax.set_aspect("equal")
    for spine in ax.spines.values():
        spine.set_color("#CFDDDA")

    def label(axis, lon, lat, name, size=10, water=False):
        x, y = transform.transform(lon, lat)
        axis.text(
            x,
            y,
            name,
            ha="center",
            va="center",
            fontsize=size,
            color=ink,
            style="italic" if water else "normal",
            weight="normal" if water else "bold",
            path_effects=[
                pe.withStroke(linewidth=3, foreground=ocean if water else ground)
            ],
        )

    for lon, lat, name in [
        (-123.07, 48.54, "San Juan\nIsland"),
        (-122.91, 48.68, "Orcas\nIsland"),
        (-122.88, 48.47, "Lopez\nIsland"),
        (-123.34, 48.83, "Pender\nIsland"),
        (-123.17, 48.80, "Saturna\nIsland"),
        (-122.74, 48.71, "Lummi\nIsland"),
    ]:
        label(ax, lon, lat, name)
    label(ax, -123.51, 48.62, "Vancouver\nIsland", 11)
    label(ax, -123.24, 48.63, "Haro Strait", 10, True)
    label(ax, -122.87, 48.94, "Strait of Georgia", 11, True)
    x, y = transform.transform(-123.017, 48.535)
    ax.plot(x, y, "o", color=ink, ms=3)
    ax.annotate(
        "Friday Harbor",
        (x, y),
        xytext=(-66, -32),
        textcoords="offset points",
        fontsize=9,
        arrowprops={"arrowstyle": "-", "color": ink},
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 2},
    )
    # A true-north arrow projected from a meridian; scale bar uses UTM metres.
    x, y = transform.transform(-122.70, 48.98)
    xn, yn = transform.transform(-122.70, 49.015)
    ax.annotate(
        "N",
        (xn, yn),
        (x, y),
        ha="center",
        weight="bold",
        arrowprops={"arrowstyle": "-|>", "color": ink},
    )
    x, y = west + 3500, south + 3500
    ax.plot([x, x + 10000], [y, y], color=ink, lw=3)
    ax.text(x + 5000, y + 1600, "10 km", ha="center", size=10)

    inset = fig.add_axes((0.715, 0.51, 0.23, 0.28), facecolor=ocean)
    land.plot(ax=inset, color=ground, edgecolor="#97ACA5", linewidth=0.4)
    region = gpd.GeoSeries([box(-123.35, 48.38, -122.70, 49.02)], crs=4326).to_crs(
        32610
    )
    region.boundary.plot(ax=inset, color=teal, linewidth=1.8)
    a, b = transform.transform(-125.0, 47.0)
    c, d = transform.transform(-121.4, 50.2)
    inset.set(xlim=(a, c), ylim=(b, d), xticks=[], yticks=[])
    inset.set_title(
        "IN THE PACIFIC NORTHWEST", loc="left", size=10, weight="bold", pad=12
    )
    for lon, lat, name in [
        (-123.10, 49.28, "Vancouver"),
        (-123.37, 48.43, "Victoria"),
        (-122.33, 47.61, "Seattle"),
    ]:
        x, y = transform.transform(lon, lat)
        inset.plot(x, y, "o", ms=2, color=ink)
        inset.annotate(
            name, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8
        )
    label(inset, -123.8, 49.8, "BRITISH COLUMBIA", 7)
    label(inset, -122.5, 47.18, "WASHINGTON", 7)
    for spine in inset.spines.values():
        spine.set_color("#CFDDDA")
    fig.text(0.715, 0.452, "Mean water depth", size=15, weight="bold")
    fig.text(0.715, 0.424, "Metres below sea level · positive down", size=9)
    cbax = fig.add_axes((0.715, 0.381, 0.23, 0.018))
    cb = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=cmap),
        cax=cbax,
        orientation="horizontal",
        ticks=[0, 100, 200, 300, 400],
    )
    cb.ax.tick_params(labelsize=9, color=ink)
    cb.outline.set_visible(False)
    fig.legend(
        handles=[
            Patch(facecolor="#A6AFB4", label="Unavailable cell depth"),
            Patch(facecolor=ocean, label="Outside pilot support"),
            Patch(facecolor=ground, edgecolor="#97ACA5", label="Land (generalized)"),
        ],
        loc="upper left",
        bbox_to_anchor=(0.708, 0.33),
        frameon=False,
        fontsize=10,
        labelspacing=0.9,
    )
    fig.text(0.715, 0.185, "EXPLORATORY PILOT", color=teal, weight="bold", size=10)
    fig.text(
        0.715,
        0.17,
        "Real source data; not a complete\nregional release or navigation chart.",
        size=9,
        linespacing=1.5,
        va="top",
    )
    fig.text(
        0.055,
        0.087,
        "Depth: GEBCO Compilation Group (2026) · 15 arc-second source grid. Land: Natural Earth v5.1.1 · 1:10 million.",
        size=9,
    )
    fig.text(
        0.055,
        0.059,
        "Existing production cell means; no smoothing. Coastlines are generalized. WGS 84 / UTM zone 10N.",
        size=9,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    evidence = {
        "product_checksum": checksum_path(product),
        "geometry_checksum": checksum_path(geometry),
        "land_checksum": checksum_path(args.land),
        "cells": len(mapped),
        "available": int(mapped.BATHYMETRY.notna().sum()),
        "unavailable": int(mapped.BATHYMETRY.isna().sum()),
        "depth_min_m": float(mapped.BATHYMETRY.min()),
        "depth_max_m": float(mapped.BATHYMETRY.max()),
        "projection": "EPSG:32610",
        "synthetic": False,
        "scope": "Exploratory San Juan pilot; not a complete regional release",
        "rendered_image_checksum": checksum_path(args.output),
    }
    args.output.with_suffix(".json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
