"""Conditional mapped areal classes with common coverage and explicit conflicts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd
import h3
import pyarrow as pa
import shapely

from seascape.domain_parquets import METADATA_KEY, validate_table

_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build_areal_class_fractions(
    inventory: gpd.GeoDataFrame,
    support: gpd.GeoDataFrame,
    *,
    classes: Mapping[str, str],
    source_context: Mapping[str, Any],
    max_cells: int = 100000,
    max_records: int = 500000,
    max_pairs: int = 3000000,
) -> pa.Table:
    """Union class polygons per cell; infer neither whole-cell classes nor hardness."""
    if (
        not classes
        or len(set(classes.values())) != len(classes)
        or any(
            not re.fullmatch(r"[A-Z][A-Z0-9_]*", label) for label in classes.values()
        )
        or not source_context.get("rights")
    ):
        raise ValueError(
            "Distinct class labels and explicit source rights are required"
        )
    if (
        min(max_cells, max_records, max_pairs) < 1
        or not 0 < len(support) <= max_cells
        or not 0 < len(inventory) <= max_records
    ):
        raise ValueError("Areal class resource bounds exceeded or inputs empty")
    if {"RECORD_ID", "CLASS_CODE"} - set(inventory) or {
        "H3_INDEX",
        "H3_RESOLUTION",
    } - set(support):
        raise ValueError("Areal classes require source and native support identities")
    if (
        inventory.RECORD_ID.isna().any()
        or inventory.RECORD_ID.duplicated().any()
        or support.H3_INDEX.isna().any()
        or support.H3_INDEX.duplicated().any()
    ):
        raise ValueError("Areal class source/support identities must be unique")
    if inventory.CLASS_CODE.isna().any() or set(inventory.CLASS_CODE.astype(str)) - set(
        classes
    ):
        raise ValueError(
            "Every source class, including unclassified, needs an explicit mapping"
        )
    for frame in (inventory, support):
        if (
            frame.crs is None
            or frame.geometry.isna().any()
            or frame.geometry.is_empty.any()
            or not frame.geometry.is_valid.all()
            or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all()
        ):
            raise ValueError(
                "Areal class inputs require valid nonempty polygons and CRS"
            )
    cells = support.to_crs(6933).sort_values("H3_INDEX").reset_index(drop=True)
    records = inventory.to_crs(6933).reset_index(drop=True)
    if (
        not records.geometry.is_valid.all()
        or not cells.geometry.is_valid.all()
        or cells.geometry.area.le(0).any()
    ):
        raise ValueError("Projected areal class geometry is invalid")
    keys = cells.H3_INDEX.astype(str).tolist()
    if (
        any(not h3.is_valid_cell(key) for key in keys)
        or any(
            h3.get_resolution(key) != resolution
            for key, resolution in zip(keys, cells.H3_RESOLUTION, strict=True)
        )
        or cells.H3_RESOLUTION.nunique() != 1
    ):
        raise ValueError("Areal classes require one valid native H3 resolution")
    pairs = cells.sindex.query(records.geometry, predicate="intersects")
    if pairs.shape[1] > max_pairs:
        raise ValueError("Areal class overlap-pair budget exceeded")
    by_cell: dict[int, list[int]] = {}
    for record_index, cell_index in zip(*pairs, strict=True):
        by_cell.setdefault(int(cell_index), []).append(int(record_index))
    labels = sorted(classes.values())
    rows = []
    for index, cell in enumerate(cells.itertuples(index=False)):
        fragments: dict[str, list[Any]] = {label: [] for label in labels}
        count = 0
        for position in by_cell.get(index, []):
            record = records.iloc[position]
            fragment = cell.geometry.intersection(record.geometry)
            if fragment.area > 0:
                fragments[classes[str(record.CLASS_CODE)]].append(fragment)
                count += 1
        unions = {label: shapely.union_all(parts) for label, parts in fragments.items()}
        covered = shapely.union_all(list(unions.values()))
        mapped_area = float(covered.area)
        amounts = {label: float(geometry.area) for label, geometry in unions.items()}
        excess = max(0.0, sum(amounts.values()) - mapped_area)
        conflict = excess > max(1.0, mapped_area * 1e-8)
        row = {
            "H3_INDEX": str(cell.H3_INDEX),
            "H3_RESOLUTION": int(cell.H3_RESOLUTION),
            "REPORTING_WATER_AREA_M2": float(cell.geometry.area),
            "MAPPED_SUBSTRATE_AREA_M2": mapped_area if mapped_area > 0 else None,
            "MAPPED_SOURCE_COVERAGE_FRAC": min(1.0, mapped_area / cell.geometry.area)
            if mapped_area > 0
            else None,
            "SOURCE_RECORD_COUNT": count,
            "CLASS_OVERLAP_EXCESS_AREA_M2": excess if mapped_area > 0 else None,
            "AREAL_CLASS_QC": "source_class_conflict"
            if conflict
            else "mapped_source_classes"
            if mapped_area > 0
            else "no_mapped_source_coverage",
        }
        for label in labels:
            row[f"{label}_CLASS_AREA_M2"] = amounts[label] if mapped_area > 0 else None
            row[f"{label}_CLASS_FRAC_OF_MAPPED_AREA"] = (
                amounts[label] / mapped_area
                if mapped_area > 0 and not conflict
                else None
            )
        rows.append(row)
    fields = [
        ("H3_INDEX", pa.string()),
        ("H3_RESOLUTION", pa.int8()),
        ("REPORTING_WATER_AREA_M2", pa.float64()),
        ("MAPPED_SUBSTRATE_AREA_M2", pa.float64()),
        ("MAPPED_SOURCE_COVERAGE_FRAC", pa.float64()),
        ("SOURCE_RECORD_COUNT", pa.int32()),
        ("CLASS_OVERLAP_EXCESS_AREA_M2", pa.float64()),
        ("AREAL_CLASS_QC", pa.string()),
    ]
    fields.extend(
        (name, pa.float64())
        for label in labels
        for name in (f"{label}_CLASS_AREA_M2", f"{label}_CLASS_FRAC_OF_MAPPED_AREA")
    )
    metadata = {
        "method": "native_conditional_areal_class_union_v1",
        "classes": dict(classes),
        "source_context": dict(source_context),
        "code_sha256": _CODE_SHA256,
        "denominator": "union of mapped source polygons in reporting water; not full-cell observational coverage",
        "class_conflict_tolerance": "max(1 m2, mapped area * 1e-8); fractions withheld above tolerance",
        "physical_hardness_index_qualified": False,
        "availability_known": False,
        "temporal_support": {
            "kind": "static_reference",
            "observation_date": "unknown; no annual reconstruction",
        },
        "fields": {
            name: {"unit": "m2" if name.endswith("M2") else "fraction"}
            for name, kind in fields
            if pa.types.is_floating(kind)
        },
    }
    table = validate_table(
        pa.Table.from_pylist(rows, schema=pa.schema(fields)), dynamic=False
    )
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _CODE_SHA256:
        raise ValueError("Areal class code changed during processing")
    return table.replace_schema_metadata(
        {METADATA_KEY: json.dumps(metadata, sort_keys=True).encode()}
    )
