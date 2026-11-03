"""Render offline QA maps from replay_real_sources candidates."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyarrow.parquet as pq

from seascape.regional.geometry import cells


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    fig, axes = plt.subplots(2, 2, figsize=(11, 9), layout="constrained")
    items = [
        (
            "shoreline-r8",
            "SHORELINE_TOTAL_MAPPED_LENGTH_M",
            "Mapped shoreline length (m)",
            "NOAA 2018 • R8",
        ),
        (
            "anthropogenic-r8",
            "SHORELINE_ARMORING_FRAC",
            "Systematic armoring fraction",
            "WA DNR bounded extract • R8",
        ),
        (
            "estuary-r8",
            "MINIMUM_DISTANCE_M",
            "Distance to mapped estuary point (m)",
            "PMEP bounded inventory • R8",
        ),
        (
            "substrate-r6",
            "MODELED_SEDIMENT_SAND_FRACTION",
            "Modeled sand point fraction",
            "dbSEABED ver202512 • R6",
        ),
    ]
    for ax, (sub, c, title, source) in zip(axes.flat, items, strict=True):
        df = pq.read_table(a.input / sub / "candidate/metrics.parquet").to_pandas()
        geo = cells(df.H3_INDEX.tolist()).merge(df, on="H3_INDEX")
        geo.plot(
            column=c,
            ax=ax,
            legend=True,
            cmap="viridis",
            edgecolor="black",
            linewidth=0.25,
            missing_kwds={"color": "lightgray", "label": "Unknown"},
            vmin=0,
            vmax=1 if "FRAC" in c else None,
        )
        ax.set_title(title + "\n" + source, fontsize=10)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.tick_params(labelsize=8)
    fig.suptitle(
        "Real-source candidate QA • 29 October 2026\nSampled full H3 cells; gray = unknown. Blank space = unsampled. Not a promoted dataset.",
        fontsize=11,
    )
    fig.savefig(a.output, dpi=145)
    plt.close(fig)


if __name__ == "__main__":
    main()
