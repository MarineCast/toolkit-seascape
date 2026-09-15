"""Normalize and aggregate cross-border mapped river-system segments."""

from __future__ import annotations

from typing import Any

import pandas as pd

from seascape.utils.values import clean_optional_text

from .source_classification import bc_stream_mask, nhd_flowline_mask, source_classification
from .source_geometry import line_parts


def system_frame(
    frame: Any,
    *,
    dataset: str,
    id_column: str,
    name_column: str | None,
):
    import geopandas as gpd

    lines = line_parts(frame)
    records = []
    for position, row in enumerate(lines.to_dict("records")):
        identifier = clean_optional_text(row.get(id_column)) or str(position)
        classification = {
            key.replace("MOUTH_", "", 1): value
            for key, value in source_classification(dataset, row).items()
        }
        records.append(
            {
                "RIVER_SEGMENT_ID": f"{dataset}_{identifier}_{position}",
                "SOURCE_DATASET": dataset,
                "RIVER_NAME": clean_optional_text(row.get(name_column)) if name_column else None,
                **classification,
                "geometry": row["geometry"],
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=lines.crs)


def build_river_systems(frames: dict[str, Any]):
    """Build the normalized B.C., U.S., and HydroRIVERS segment inventory."""

    import geopandas as gpd

    bc = frames["bc_stream_network"]
    bc = bc.loc[bc_stream_mask(bc)].copy()
    us = frames["us_network_flowlines"]
    us = us.loc[nhd_flowline_mask(us)].copy()
    systems = gpd.GeoDataFrame(
        pd.concat(
            [
                system_frame(
                    bc,
                    dataset="BC_FWA_STREAM_NETWORK",
                    id_column="LINEAR_FEATURE_ID",
                    name_column="GNIS_NAME",
                ),
                system_frame(
                    us,
                    dataset="US_NHD_SMALL_SCALE",
                    id_column="COMID",
                    name_column="GNIS_NAME",
                ),
                system_frame(
                    frames["hydrorivers"],
                    dataset="HYDRORIVERS_V10",
                    id_column="HYRIV_ID",
                    name_column=None,
                ),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )
    return systems.sort_values(["SOURCE_DATASET", "RIVER_SEGMENT_ID"]).reset_index(drop=True)


__all__ = ["build_river_systems", "system_frame"]
