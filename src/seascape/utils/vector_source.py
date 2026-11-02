"""Read and select vector sources without materializing an entire input first."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from itertools import islice
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import box, shape


def _arrow_frame(batch: pa.RecordBatch, geometry: str, crs: Any) -> gpd.GeoDataFrame:
    values = pa.Table.from_batches([batch])
    attributes = values.drop_columns(geometry).to_pandas(types_mapper=pd.ArrowDtype)
    return gpd.GeoDataFrame(
        attributes,
        geometry=gpd.GeoSeries.from_wkb(values[geometry].to_pylist(), crs=crs),
        crs=crs,
    )


def _batches(path: Path, batch_size: int) -> Iterator[gpd.GeoDataFrame]:
    if path.suffix.lower() in {".parquet", ".geoparquet"}:
        source = pq.ParquetFile(path)
        metadata = source.schema_arrow.metadata or {}
        if b"geo" not in metadata:
            raise ValueError(f"Vector Parquet requires GeoParquet metadata: {path}")
        geo = json.loads(metadata[b"geo"])
        name = geo["primary_column"]
        column = geo["columns"][name]
        if column.get("encoding") != "WKB":
            raise ValueError(f"Vector source requires WKB geometry: {path}")
        crs = column.get("crs", "OGC:CRS84")
        if crs is None:
            raise ValueError(f"Vector source has unknown CRS: {path}")
        for batch in source.iter_batches(batch_size=batch_size):
            yield _arrow_frame(batch, name, crs)
    elif path.suffix.lower() in {".geojson", ".json"}:
        import ijson

        # RFC 7946 uses WGS84 when the legacy CRS member is absent. Scan for
        # that small member without retaining the (potentially huge) features.
        with path.open("rb") as stream:
            declared = next(ijson.items(stream, "crs", use_float=True), None)
        crs = declared["properties"]["name"] if declared else "EPSG:4326"
        with path.open("rb") as stream:
            items = ijson.items(stream, "features.item", use_float=True)
            while features := list(islice(items, batch_size)):
                properties = [feature.get("properties") or {} for feature in features]
                names = dict.fromkeys(name for item in properties for name in item)
                attributes = pa.table(
                    {name: [item.get(name) for item in properties] for name in names}
                ).to_pandas(types_mapper=pd.ArrowDtype)
                yield gpd.GeoDataFrame(
                    attributes,
                    geometry=[
                        shape(feature["geometry"]) if feature.get("geometry") else None
                        for feature in features
                    ],
                    crs=crs,
                )
    else:
        import pyogrio

        with pyogrio.open_arrow(
            path, batch_size=batch_size, use_pyarrow=True
        ) as source:
            metadata, batches = source
            if not metadata["crs"]:
                raise ValueError(f"Vector source has unknown CRS: {path}")
            geometry = metadata["geometry_name"] or "wkb_geometry"
            for batch in batches:
                yield _arrow_frame(batch, geometry, metadata["crs"])


def read_vector_source(
    path: str | Path,
    *,
    bbox: Mapping[str, float] | None = None,
    clip: bool = False,
    batch_size: int = 1024,
    select: Callable[[gpd.GeoDataFrame], gpd.GeoDataFrame] | None = None,
) -> gpd.GeoDataFrame:
    """Select in EPSG:4326 per batch, preserving attributes and source order.

    Only selected features accumulate in memory. ``clip=True`` applies the
    same GeoPandas clipping/geometry-type policy as the river producer, before
    concatenation rather than after loading the full raw source.
    """
    path = Path(path)
    if batch_size < 1:
        raise ValueError("Vector source batch_size must be positive")
    if clip and bbox is None:
        raise ValueError("Vector clipping requires an explicit bounding box")
    frames = []
    empty = gpd.GeoDataFrame(geometry=[], crs=4326)
    for frame in iter_vector_source(path, bbox=bbox, clip=clip, batch_size=batch_size):
        empty = frame.iloc[:0]
        if select is not None:
            frame = select(frame)
        if not frame.empty:
            frames.append(frame)
    return (
        gpd.GeoDataFrame(
            pd.concat(frames, ignore_index=True), geometry="geometry", crs=4326
        )
        if frames
        else empty.reset_index(drop=True)
    )


def iter_vector_source(
    path: str | Path,
    *,
    bbox: Mapping[str, float] | None = None,
    clip: bool = False,
    batch_size: int = 1024,
) -> Iterator[gpd.GeoDataFrame]:
    """Yield normalized, optionally clipped batches in deterministic source order."""
    path = Path(path)
    if batch_size < 1:
        raise ValueError("Vector source batch_size must be positive")
    if clip and bbox is None:
        raise ValueError("Vector clipping requires an explicit bounding box")
    selector = (
        box(*(bbox[k] for k in ("min_lon", "min_lat", "max_lon", "max_lat")))
        if bbox is not None
        else None
    )
    for frame in _batches(path, batch_size):
        frame = frame.to_crs(4326)
        if selector is not None:
            frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty]
            frame = frame.loc[frame.intersects(selector)]
            if clip and not frame.empty:
                frame = gpd.clip(frame, selector, keep_geom_type=True, sort=True)
        yield frame
