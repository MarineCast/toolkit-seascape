"""Normalize and aggregate cross-border mapped river-system segments."""

from __future__ import annotations

from typing import Any

import pandas as pd

from seascape.utils.values import clean_optional_text

from .source_classification import (
    bc_stream_mask,
    nhd_flowline_mask,
    source_classification,
)
from .source_geometry import line_parts


def system_frame(
    frame: Any,
    *,
    dataset: str,
    id_column: str,
    name_column: str | None,
    position_offset: int = 0,
):
    import geopandas as gpd

    lines = line_parts(frame)
    records = []
    for position, row in enumerate(lines.to_dict("records"), start=position_offset):
        identifier = clean_optional_text(row.get(id_column)) or str(position)
        classification = {
            key.replace("MOUTH_", "", 1): value
            for key, value in source_classification(dataset, row).items()
        }
        records.append(
            {
                "RIVER_SEGMENT_ID": f"{dataset}_{identifier}_{position}",
                "SOURCE_DATASET": dataset,
                "RIVER_NAME": clean_optional_text(row.get(name_column))
                if name_column
                else None,
                **classification,
                "geometry": row["geometry"],
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=lines.crs)


def build_river_systems(frames: dict[str, Any], *, us_dataset="US_NHD_SMALL_SCALE"):
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
                    dataset=us_dataset,
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
    return systems.sort_values(["SOURCE_DATASET", "RIVER_SEGMENT_ID"]).reset_index(
        drop=True
    )


class StreamedRiverSystems:
    """A publisher-compatible Parquet writer with bounded source/derived batches."""

    def __init__(self, sources, bbox, *, batch_size=1024):
        self.sources = sources
        self.bbox = bbox
        self.batch_size = batch_size
        self.row_count = 0

    def __len__(self):
        return self.row_count

    def to_parquet(self, path, *, index=False, compression="zstd"):
        import io
        import json

        import numpy as np
        import pyarrow.parquet as pq

        from seascape.utils.vector_source import iter_vector_source

        writer = None
        extent = np.array([np.inf, np.inf, -np.inf, -np.inf])
        geo = None
        self.row_count = 0
        try:
            for source_path, dataset, id_column, name_column in self.sources:
                position = 0
                for frame in iter_vector_source(
                    source_path, bbox=self.bbox, clip=True, batch_size=self.batch_size
                ):
                    frame.columns = [
                        c if c == frame.geometry.name else str(c).upper() for c in frame
                    ]
                    if dataset == "BC_FWA_STREAM_NETWORK":
                        frame = frame.loc[bc_stream_mask(frame)]
                    elif dataset != "HYDRORIVERS_V10":
                        frame = frame.loc[nhd_flowline_mask(frame)]
                    if frame.empty:
                        continue
                    normalized = system_frame(
                        frame,
                        dataset=dataset,
                        id_column=id_column,
                        name_column=name_column,
                        position_offset=position,
                    )
                    if normalized.empty:
                        continue
                    position += len(normalized)
                    self.row_count += len(normalized)
                    for column in normalized.columns:
                        if column != normalized.geometry.name:
                            normalized[column] = normalized[column].astype("string")
                    bounds = normalized.total_bounds
                    extent[:2] = np.minimum(extent[:2], bounds[:2])
                    extent[2:] = np.maximum(extent[2:], bounds[2:])
                    buffer = io.BytesIO()
                    normalized.to_parquet(buffer, index=False, compression=compression)
                    buffer.seek(0)
                    table = pq.read_table(buffer)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            path, table.schema, compression=compression
                        )
                        geo = json.loads(table.schema.metadata[b"geo"])
                    writer.write_table(table)
            if writer is None:
                raise ValueError("No river-system source segments were selected")
            geo["columns"][geo["primary_column"]]["bbox"] = extent.tolist()
            writer.add_key_value_metadata({"geo": json.dumps(geo)})
        finally:
            if writer is not None:
                writer.close()


__all__ = ["build_river_systems", "system_frame", "StreamedRiverSystems"]
