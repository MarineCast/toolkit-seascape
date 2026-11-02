"""Render a bounded offline example from metric-only scientific producer outputs."""

import argparse
from pathlib import Path

import geopandas as gpd
import h3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyarrow.parquet as pq
from matplotlib.patches import Patch
from shapely.geometry import Polygon


def panel(path, field, ax, title, units, limits):
    frame = pq.read_table(path, columns=["h3_index", field]).to_pandas()
    centers = frame.h3_index.map(h3.cell_to_latlng)
    keep = centers.map(lambda xy: 48 <= xy[0] <= 49.5 and -124.5 <= xy[1] <= -122.2)
    frame = frame.loc[keep].copy()
    if frame.empty:
        raise ValueError("No cells in the documented example extent")
    geometry = [
        Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(cell)])
        for cell in frame.h3_index
    ]
    geo = gpd.GeoDataFrame(frame, geometry=geometry, crs=4326)
    geo.plot(
        column=field,
        ax=ax,
        cmap="viridis",
        vmin=limits[0],
        vmax=limits[1],
        legend=True,
        legend_kwds={"label": units, "shrink": 0.75},
        missing_kwds={"color": "lightgray", "hatch": "///"},
        linewidth=0,
    )
    ax.set_title(title, fontsize=10)
    ax.set_xlim(-124.5, -122.2)
    ax.set_ylim(48, 49.5)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend(
        handles=[Patch(facecolor="lightgray", hatch="///", label="Missing metric")],
        loc="upper left",
        fontsize=7,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terrain", type=Path, required=True)
    parser.add_argument("--substrate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fig, axes = plt.subplots(2, 2, figsize=(11, 9), layout="constrained")
    for ax, path, field, title, units, limits in [
        (
            axes[0, 0],
            args.terrain,
            "seafloor_slope_mean_deg",
            "Native raster slope · R8",
            "Degrees",
            (0, None),
        ),
        (
            axes[0, 1],
            args.terrain,
            "seafloor_northness",
            "Terrain northness · R8",
            "Cosine of aspect",
            (-1, 1),
        ),
        (
            axes[1, 0],
            args.substrate,
            "mapped_hard_substrate_fraction",
            "Mapped hard substrate · R6",
            "Fraction of mapped area",
            (0, 1),
        ),
        (
            axes[1, 1],
            args.substrate,
            "mapped_soft_substrate_fraction",
            "Mapped soft substrate · R6",
            "Fraction of mapped area",
            (0, 1),
        ),
    ]:
        panel(path, field, ax, title, units, limits)
    fig.suptitle(
        "Installed scientific producer candidates · 1 November 2026\nGEBCO 2026 terrain; retained DFO substrate inventory, explicit historical CRS operation\nGray hatching = missing metric; colored zero = numeric zero. Blank = no selected cell. Not promoted.",
        fontsize=10,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=145)
    plt.close(fig)


if __name__ == "__main__":
    main()
