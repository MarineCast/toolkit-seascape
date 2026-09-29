"""Categorical GEBCO type-identifier summaries on direct bathymetry pixel support."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from .build import _latlngs_to_h3, _pixel_centers

# GEBCO_2026 Grid documentation; identifiers describe source type, not accuracy.
DIRECT_CODES = (10, 11, 12, 13, 14, 15, 16, 17)
INDIRECT_CODES = (40, 41, 42, 43, 44, 45, 46, 47, 48)
UNKNOWN_CODES = (70, 71, 72)
MARINE_CODES = DIRECT_CODES + INDIRECT_CODES + UNKNOWN_CODES


def aggregate_tid(
    *,
    depth_path: Path,
    tid_path: Path,
    cells: list[str],
    resolution: int,
    depth_release: str,
    tid_release: str,
) -> pd.DataFrame:
    """Count exact categorical codes at valid marine depth pixel centers.

    Both rasters must share one pixel grid. No category interpolation or
    resampling is performed. Missing TID remains separate from unknown codes.
    """

    if depth_release != tid_release:
        raise ValueError("GEBCO depth and TID declared releases must match")
    if len(cells) != len(set(cells)):
        raise ValueError("Duplicate canonical H3 cells")
    with rasterio.open(depth_path) as depth, rasterio.open(tid_path) as tid:
        if depth.count != 1 or tid.count != 1:
            raise ValueError("GEBCO depth and TID rasters must have one band each")
        if (
            depth.crs != tid.crs
            or depth.crs is None
            or depth.crs.to_epsg() != 4326
            or depth.transform != tid.transform
            or depth.shape != tid.shape
        ):
            raise ValueError("GEBCO depth and TID pixel grids must align in EPSG:4326")
        if not np.issubdtype(np.dtype(tid.dtypes[0]), np.integer):
            raise ValueError("GEBCO TID raster must contain categorical integers")
        elevations = depth.read(1, masked=True)
        types = tid.read(1, masked=True)
        marine = ~np.ma.getmaskarray(elevations) & (elevations.data < 0)
        latitudes, longitudes = _pixel_centers(depth.transform, depth.shape)
    pixel_cells = _latlngs_to_h3(latitudes[marine], longitudes[marine], resolution)
    cell_set = set(cells)
    selected = np.asarray([cell in cell_set for cell in pixel_cells], dtype=bool)
    source_codes = np.asarray(types.data[marine])[selected]
    source_missing = np.ma.getmaskarray(types)[marine][selected]
    invalid = set(np.unique(source_codes[~source_missing]).tolist()) - set(MARINE_CODES)
    if invalid:
        raise ValueError(
            f"GEBCO TID contains unsupported marine codes: {sorted(invalid)}"
        )
    samples = pd.DataFrame(
        {
            "H3_INDEX": np.asarray(pixel_cells, dtype=object)[selected],
            "TID_CODE": pd.Series(source_codes).mask(source_missing).to_numpy(),
        }
    )
    grouped = samples.groupby("H3_INDEX", sort=False)
    counts = grouped.size().rename("GEBCO_TID_DEPTH_PIXEL_COUNT")
    known = grouped["TID_CODE"].count().rename("GEBCO_TID_KNOWN_PIXEL_COUNT")
    result = pd.DataFrame({"H3_INDEX": cells}).merge(
        pd.concat([counts, known], axis=1).reset_index(),
        on="H3_INDEX",
        how="left",
        validate="one_to_one",
    )
    for code in MARINE_CODES:
        code_counts = (
            samples.loc[samples["TID_CODE"].eq(code)].groupby("H3_INDEX").size()
        )
        result[f"GEBCO_TID_COUNT_{code}"] = result["H3_INDEX"].map(code_counts)
        has_depth = result["GEBCO_TID_DEPTH_PIXEL_COUNT"].notna()
        result.loc[has_depth, f"GEBCO_TID_COUNT_{code}"] = result.loc[
            has_depth, f"GEBCO_TID_COUNT_{code}"
        ].fillna(0)
    known_count = result["GEBCO_TID_KNOWN_PIXEL_COUNT"].replace(0, np.nan)
    for label, codes in (
        ("DIRECT", DIRECT_CODES),
        ("INDIRECT", INDIRECT_CODES),
        ("UNKNOWN_SOURCE", UNKNOWN_CODES),
    ):
        numerator = result[[f"GEBCO_TID_COUNT_{code}" for code in codes]].sum(
            axis=1, min_count=1
        )
        result[f"GEBCO_TID_{label}_FRAC_OF_KNOWN"] = numerator / known_count
    result["GEBCO_TID_STATUS"] = np.select(
        [
            result["GEBCO_TID_DEPTH_PIXEL_COUNT"].isna(),
            result["GEBCO_TID_KNOWN_PIXEL_COUNT"].eq(0),
            result["GEBCO_TID_KNOWN_PIXEL_COUNT"].lt(
                result["GEBCO_TID_DEPTH_PIXEL_COUNT"]
            ),
        ],
        ["no_depth_pixels", "tid_unavailable", "partial_tid"],
        default="complete",
    )
    return result


def build_tid_parquet(
    *,
    depth_path: Path,
    tid_path: Path,
    output_path: Path,
    cells: list[str],
    resolution: int,
    depth_release: str,
    tid_release: str,
) -> Path:
    table = aggregate_tid(
        depth_path=depth_path,
        tid_path=tid_path,
        cells=cells,
        resolution=resolution,
        depth_release=depth_release,
        tid_release=tid_release,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(output_path, index=False)
    return output_path
