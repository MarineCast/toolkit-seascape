"""Native annual mapped-positive polygon amounts without inferred survey absence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd
import h3
import pandas as pd
import pyarrow as pa
import shapely

from seascape.domain_parquets import METADATA_KEY, validate_table

_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class AnnualFootprintResult:
    table: pa.Table
    report: dict[str, Any]


def build_native_annual_footprints(
    inventory: gpd.GeoDataFrame,
    full_cells: gpd.GeoDataFrame,
    water_cells: gpd.GeoDataFrame,
    *,
    start_year: int,
    end_year: int,
    source_context: Mapping[str, Any],
    max_cells: int = 100000,
    max_records: int = 200000,
    max_cell_years: int = 3000000,
    max_pairs_per_year: int = 2000000,
) -> AnnualFootprintResult:
    """Measure explicit annual positive evidence on independently supplied native cells."""
    inventory = inventory.reset_index(drop=True)
    required = {"RECORD_ID", "SOURCE_DATASET", "OBSERVATION_YEAR", "OBSERVATION_STATUS"}
    if required - set(inventory) or not source_context.get("rights"):
        raise ValueError(
            "Annual source identity, observation year and rights are required"
        )
    if (
        not 1800 <= start_year <= end_year <= 9998
        or min(max_cells, max_records, max_cell_years, max_pairs_per_year) < 1
    ):
        raise ValueError("Annual year/resource bounds are invalid")
    if (
        inventory.RECORD_ID.isna().any()
        or inventory.RECORD_ID.duplicated().any()
        or len(inventory) > max_records
    ):
        raise ValueError("Annual records exceed their bound or have invalid identity")
    for frame in (inventory, full_cells, water_cells):
        if (
            frame.crs is None
            or frame.geometry.isna().any()
            or frame.geometry.is_empty.any()
            or not frame.geometry.is_valid.all()
            or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        ):
            raise ValueError(
                "Annual inputs require valid nonempty polygon geometry and CRS"
            )
    full = full_cells.to_crs(6933).sort_values("H3_INDEX").reset_index(drop=True)
    wet = water_cells.to_crs(6933).sort_values("H3_INDEX").reset_index(drop=True)
    keys = full.H3_INDEX.astype(str).tolist()
    if (
        not keys
        or len(keys) > max_cells
        or len(set(keys)) != len(keys)
        or keys != wet.H3_INDEX.astype(str).tolist()
    ):
        raise ValueError("Annual full/water native support identities disagree")
    resolutions = {h3.get_resolution(key) for key in keys if h3.is_valid_cell(key)}
    if len(resolutions) != 1 or any(not h3.is_valid_cell(key) for key in keys):
        raise ValueError("Annual support requires one valid native H3 resolution")
    resolution = resolutions.pop()
    if (
        not full.H3_RESOLUTION.eq(resolution).all()
        or not wet.H3_RESOLUTION.eq(resolution).all()
    ):
        raise ValueError("Annual native resolution fields disagree")
    if (
        not full.geometry.is_valid.all()
        or not wet.geometry.is_valid.all()
        or wet.geometry.area.le(0).any()
    ):
        raise ValueError("Projected annual support is invalid or empty")
    if any(
        clip.difference(cell).area > 1e-4
        for cell, clip in zip(full.geometry, wet.geometry, strict=True)
    ):
        raise ValueError("Annual water geometry extends outside its full native cell")
    years = pd.to_numeric(inventory.OBSERVATION_YEAR, errors="raise")
    if years.isna().any() or (years % 1).ne(0).any():
        raise ValueError("Explicit integer observation years are required")
    selected = inventory.loc[years.between(start_year, end_year)].to_crs(6933).copy()
    selected["OBSERVATION_YEAR"] = years.loc[selected.index].astype(int)
    actual = sorted(selected.OBSERVATION_YEAR.unique().tolist())
    if not actual or len(keys) * len(actual) > max_cell_years:
        raise ValueError("No annual positive source or cell-year budget exceeded")
    if (
        "OBSERVATION_STATUS" in selected
        and not selected.OBSERVATION_STATUS.eq("present").all()
    ):
        raise ValueError(
            "Annual footprint input must contain only explicit positive records"
        )
    rows = []
    full_geometry = full.geometry.to_numpy()
    wet_geometry = wet.geometry.to_numpy()
    water_areas = wet.geometry.area.to_numpy()
    for year, records in selected.groupby("OBSERVATION_YEAR", sort=True):
        records = records.reset_index(drop=True)
        dataset_names = "|".join(sorted(records.SOURCE_DATASET.astype(str).unique()))
        pairs = full.sindex.query(records.geometry, predicate="intersects")
        if pairs.shape[1] > max_pairs_per_year:
            raise ValueError("Annual source-overlap pair budget exceeded")
        by_cell: dict[int, list[int]] = {}
        for record_index, cell_index in zip(*pairs, strict=True):
            by_cell.setdefault(int(cell_index), []).append(int(record_index))
        for index, key in enumerate(keys):
            mapped_full = mapped_wet = None
            ids = by_cell.get(index, [])
            if ids:
                polygon = shapely.union_all(records.geometry.iloc[ids].to_numpy())
                full_area = float(polygon.intersection(full_geometry[index]).area)
                if full_area > 0:
                    mapped_full = full_area
                    mapped_wet = float(polygon.intersection(wet_geometry[index]).area)
            rows.append(
                {
                    "H3_INDEX": key,
                    "H3_RESOLUTION": resolution,
                    "date": date(int(year), 1, 1),
                    "OBSERVATION_YEAR": int(year),
                    "MAPPED_BED_EXTENT_IN_FULL_H3_M2": mapped_full,
                    "MAPPED_BED_EXTENT_IN_STATIC_WATER_M2": mapped_wet,
                    "STATIC_WATER_AREA_M2": float(water_areas[index]),
                    "POSITIVE_MAPPED_BED_EVIDENCE": True
                    if mapped_full is not None
                    else None,
                    "ANNUAL_SURVEY_ABSENCE": None,
                    "QC": "positive_mapped_evidence"
                    if mapped_full is not None
                    else "no_positive_mapped_evidence",
                    "SOURCE_DATASETS": dataset_names,
                }
            )
    source_hash = hashlib.sha256()
    for row in selected.sort_values("RECORD_ID").itertuples(index=False):
        source_hash.update(
            json.dumps(
                [
                    str(row.RECORD_ID),
                    str(row.SOURCE_DATASET),
                    int(row.OBSERVATION_YEAR),
                ],
                separators=(",", ":"),
            ).encode()
        )
        source_hash.update(row.geometry.wkb)
    report = {
        "method": "native_annual_positive_polygon_union_v1",
        "actual_years": actual,
        "missing_requested_years": sorted(
            set(range(start_year, end_year + 1)) - set(actual)
        ),
        "native_resolution": resolution,
        "native_cells": len(keys),
        "source_records": len(selected),
        "source_geometry_sha256": source_hash.hexdigest(),
        "code_sha256": _CODE_SHA256,
        "survey_absence_qualified": False,
        "physical_full_catalog_qualified": False,
    }
    metadata = {
        "temporal_support": {
            "kind": "annual_survey",
            "precision": "year",
            "date_label": "January 1 labels the survey year, not the observation day",
            "availability": "unknown unless explicitly qualified in source context",
        },
        "area_method": "EPSG:6933 polygon intersection, independent native H3 support",
        "water_mask_temporal_support": "static cartographic reference; no historical water-level reconstruction",
        "source_context": dict(source_context),
        "report": report,
        "availability_known": False,
        "fields": {
            "MAPPED_BED_EXTENT_IN_FULL_H3_M2": {"unit": "m2"},
            "MAPPED_BED_EXTENT_IN_STATIC_WATER_M2": {"unit": "m2"},
            "STATIC_WATER_AREA_M2": {"unit": "m2"},
        },
    }
    table = pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                ("H3_INDEX", pa.string()),
                ("H3_RESOLUTION", pa.int8()),
                ("date", pa.date32()),
                ("OBSERVATION_YEAR", pa.int16()),
                ("MAPPED_BED_EXTENT_IN_FULL_H3_M2", pa.float64()),
                ("MAPPED_BED_EXTENT_IN_STATIC_WATER_M2", pa.float64()),
                ("STATIC_WATER_AREA_M2", pa.float64()),
                ("POSITIVE_MAPPED_BED_EVIDENCE", pa.bool_()),
                ("ANNUAL_SURVEY_ABSENCE", pa.bool_()),
                ("QC", pa.string()),
                ("SOURCE_DATASETS", pa.string()),
            ]
        ),
    )
    table = validate_table(table, dynamic=True).replace_schema_metadata(
        {METADATA_KEY: json.dumps(metadata, sort_keys=True).encode()}
    )
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _CODE_SHA256:
        raise ValueError(
            "Annual footprint code changed during processing; reload before recomputing"
        )
    return AnnualFootprintResult(table, report)
