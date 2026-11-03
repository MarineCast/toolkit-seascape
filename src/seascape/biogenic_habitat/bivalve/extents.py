"""One Bivalve feature: all-history spatial union with source dates as provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import shapely

from seascape.domain_parquets import METADATA_KEY, AreaTables, validate_table

ALL_TIME = "BIVALVE_EXTENT_ALL_TIME_M2"
EXTENT_COLUMNS = (ALL_TIME,)
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class BivalveExtentResult:
    tables: AreaTables
    report: dict[str, Any]


def eligible_extent_inventory(inventory: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Only documented positive mapped polygons; source map dates are not surveys."""
    required = {
        "RECORD_ID",
        "SOURCE_DATASET",
        "OBSERVATION_STATUS",
        "OBSERVATION_YEAR",
        "HABITAT_TYPE",
        "OBSERVED_VS_MODELED",
        "SURVEY_METHOD",
        "SPECIES",
        "SOURCE_PERIOD",
        "SOURCE_MAP_DATE",
    }
    if required - set(inventory) or inventory.crs is None:
        raise ValueError(
            "Bivalve source identity, methodology, species, temporal support and CRS are required"
        )
    if (
        inventory.RECORD_ID.isna().any()
        or inventory.RECORD_ID.astype(str).duplicated().any()
    ):
        raise ValueError("Bivalve record identities must be unique and non-null")
    # Admission depends on a documented mapped-bed source and polygon support.
    # General observation footprints and harvest/lease boundaries are not beds.
    positive = (
        inventory.HABITAT_TYPE.eq("mapped_bivalve_bed")
        & inventory.OBSERVATION_STATUS.eq("present")
        & inventory.OBSERVED_VS_MODELED.eq("observed")
        & inventory.geom_type.isin(["Polygon", "MultiPolygon"])
    )
    selected = inventory.loc[
        positive
        & inventory.SOURCE_DATASET.isin(
            [
                "WA_WDFW_MAPPED_OYSTER_BEDS",
                "BC_CRIMS_CLAM_BEDS",
                "WA_WDFW_PHS_MAPPED_BIVALVE_BEDS",
            ]
        )
    ].copy()
    if selected.OBSERVATION_YEAR.notna().any():
        raise ValueError(
            "Current legacy bed sources have no verified observation year; map/source dates are provenance only"
        )
    if (
        selected.empty
        or selected.geometry.isna().any()
        or selected.geometry.is_empty.any()
        or not selected.geometry.is_valid.all()
    ):
        raise ValueError(
            "Bivalve extent requires valid audited positive polygon evidence"
        )
    return selected.reset_index(drop=True)


def build_bivalve_extents(
    inventory: gpd.GeoDataFrame,
    full_cells: gpd.GeoDataFrame,
    *,
    source_context: Mapping[str, Any],
    max_cells: int = 200000,
    max_records: int = 200000,
    max_pairs: int = 4000000,
) -> BivalveExtentResult:
    """Union admitted mapped bed polygons independently on each native H3 grid.

    Source dates remain provenance; no annual output or absence inference.
    """
    if not source_context.get("rights"):
        raise ValueError("Bivalve source rights/provenance are required")
    if min(max_cells, max_records, max_pairs) < 1:
        raise ValueError("Bivalve resource bounds must be positive")
    records = eligible_extent_inventory(inventory)
    if len(records) > max_records:
        raise ValueError("Bivalve record budget exceeded")
    if full_cells.crs is None or not {"H3_INDEX", "H3_RESOLUTION"} <= set(full_cells):
        raise ValueError("Explicit native full H3 geometry and CRS are required")
    full = full_cells.to_crs(4326).sort_values("H3_INDEX").reset_index(drop=True)
    full.geometry = full.geometry.segmentize(0.001)
    full = full.to_crs(6933)
    keys = full.H3_INDEX.astype(str).tolist()
    resolutions = {h3.get_resolution(key) for key in keys if h3.is_valid_cell(key)}
    if (
        not keys
        or len(keys) > max_cells
        or len(set(keys)) != len(keys)
        or len(resolutions) != 1
        or any(not h3.is_valid_cell(key) for key in keys)
    ):
        raise ValueError(
            "Bivalve support requires unique valid cells at one native resolution within budget"
        )
    resolution = resolutions.pop()
    if (
        not full.H3_RESOLUTION.eq(resolution).all()
        or full.geometry.isna().any()
        or full.geometry.is_empty.any()
        or not full.geometry.is_valid.all()
        or not full.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    ):
        raise ValueError("Bivalve full H3 geometry/resolution is invalid")
    records = records.to_crs(6933)
    if not records.geometry.is_valid.all():
        raise ValueError(
            "Projected bivalve geometry requires a separate recorded audit"
        )
    source_hash = hashlib.sha256()
    for row in records.sort_values("RECORD_ID").itertuples():
        source_hash.update(str(row.RECORD_ID).encode())
        source_hash.update(row.geometry.wkb)
    report: dict[str, Any] = {
        "method": "bivalve_mapped_bed_union_v1",
        "code_sha256": _CODE_SHA256,
        "native_resolution": resolution,
        "native_cells": len(keys),
        "source_records": len(records),
        "source_geometry_sha256": source_hash.hexdigest(),
        "all_time_dated_years": sorted(
            records.OBSERVATION_YEAR.dropna().astype(int).unique().tolist()
        ),
        "nonannual_records_included": int(records.OBSERVATION_YEAR.isna().sum()),
        "survey_absence_qualified": False,
        "water_mask_used_for_extent": False,
        "source_periods": sorted(
            records.SOURCE_PERIOD.dropna().astype(str).unique().tolist()
        ),
        "species": sorted(records.SPECIES.dropna().astype(str).unique().tolist()),
        "observation_classes": sorted(records.OBSERVED_VS_MODELED.unique().tolist()),
        "source_datasets": records.SOURCE_DATASET.value_counts().sort_index().to_dict(),
        "excluded_input_records": len(inventory) - len(records),
    }
    definition = (
        "Geometric union of eligible official mapped bivalve-bed polygons over all retained history, intersected with full native H3 cells in EPSG:6933 square metres. "
        "Overlaps count once. Legacy generalized bed mapping is not exact organism canopy, structural reef confirmation or current presence. "
        "Missing positive evidence is null/unknown, never surveyed absence. Harvest/growing/closure areas, aquaculture leases, potential habitat, "
        "ShoreZone observation-unit polygons, points, lines and sample estimates are excluded. Undated evidence remains undated."
    )

    def reduce(selected: gpd.GeoDataFrame) -> pa.Table:
        column = ALL_TIME
        pairs = full.sindex.query(selected.geometry, predicate="intersects")
        if pairs.shape[1] > max_pairs:
            raise ValueError("Bivalve polygon-overlap budget exceeded")
        by_cell: dict[int, list[int]] = {}
        for record_index, cell_index in zip(*pairs, strict=True):
            by_cell.setdefault(int(cell_index), []).append(int(record_index))
        amounts: list[float | None] = [None] * len(keys)
        statuses = ["no_positive_evidence_unknown_absence"] * len(keys)
        sources, observed = ["[]"] * len(keys), ["[]"] * len(keys)
        provenance = {
            name: ["[]"] * len(keys)
            for name in (
                "SOURCE_METHODS_JSON",
                "SPECIES_JSON",
                "SOURCE_PERIODS_JSON",
                "SOURCE_MAP_DATES_JSON",
                "OBSERVED_VS_MODELED_JSON",
            )
        }
        undated, repaired, counts = (
            [False] * len(keys),
            [False] * len(keys),
            [0] * len(keys),
        )
        for index, positions in by_cell.items():
            rows = selected.iloc[positions]
            # Remove boundary-only touches before attributing source support.
            areas = shapely.area(
                shapely.intersection(
                    rows.geometry.to_numpy(), full.geometry.iloc[index]
                )
            )
            rows = rows.loc[np.asarray(areas) > 0]
            if rows.empty:
                continue
            amount = float(
                shapely.union_all(rows.geometry.to_numpy())
                .intersection(full.geometry.iloc[index])
                .area
            )
            amounts[index] = amount if amount > 0 else None
            statuses[index] = (
                "mapped_positive_extent"
                if amount
                else "no_positive_evidence_unknown_absence"
            )
            sources[index] = json.dumps(
                sorted(rows.SOURCE_DATASET.astype(str).unique()), separators=(",", ":")
            )
            observed[index] = json.dumps(
                sorted(rows.OBSERVATION_YEAR.dropna().astype(int).unique().tolist()),
                separators=(",", ":"),
            )
            for field, source_column in (
                ("SOURCE_METHODS_JSON", "SURVEY_METHOD"),
                ("SPECIES_JSON", "SPECIES"),
                ("SOURCE_PERIODS_JSON", "SOURCE_PERIOD"),
                ("SOURCE_MAP_DATES_JSON", "SOURCE_MAP_DATE"),
                ("OBSERVED_VS_MODELED_JSON", "OBSERVED_VS_MODELED"),
            ):
                provenance[field][index] = json.dumps(
                    sorted(rows[source_column].dropna().astype(str).unique().tolist()),
                    separators=(",", ":"),
                )
            undated[index] = bool(rows.OBSERVATION_YEAR.isna().any())
            repaired[index] = bool(
                rows.get("GEOMETRY_PROCESSING", pd.Series(dtype=str))
                .eq("made_valid_not_source_certified")
                .any()
            )
            counts[index] = len(rows)
        data: dict[str, Any] = {
            "H3_INDEX": pa.array(keys),
            "H3_RESOLUTION": pa.array([resolution] * len(keys), type=pa.int8()),
            column: pa.array(amounts, type=pa.float64()),
            "QC": pa.array(statuses),
            **{name: pa.array(values) for name, values in provenance.items()},
            "SOURCE_DATASETS_JSON": pa.array(sources),
            "OBSERVATION_YEARS_JSON": pa.array(observed),
            "NONANNUAL_EVIDENCE_INCLUDED": pa.array(undated),
            "REPAIRED_GEOMETRY_INCLUDED": pa.array(repaired),
            "INTERSECTING_SOURCE_RECORD_COUNT": pa.array(counts, type=pa.int32()),
        }
        scientific_name = "Bivalve Extent (All-Time)"
        qualifiers = [
            name
            for name in data
            if name not in {"H3_INDEX", "H3_RESOLUTION", "date", column}
        ]
        fields = {
            name: {"role": "support_or_qc", "picker_visible": False}
            for name in qualifiers
        }
        fields[column] = {
            "common_name": scientific_name,
            "family": "Biogenic Habitats",
            "unit": "m2",
            "role": "predictor",
            "picker_visible": True,
            "definition": definition
            + " All eligible retained mapped-bed history contributes; legacy map/source dates remain provenance, not observation years.",
            "qualifiers": qualifiers,
            "modeling_eligibility": "source_qualified_extent_not_current_presence",
        }
        context = {
            "dataset": "bivalve",
            "schema_version": 1,
            "fields": fields,
            "report": report,
            "source_context": dict(source_context),
            "availability_known": False,
            "model_eligible": False,
            "temporal_support": {
                "kind": "static_reference",
                "definition": "All-history mapped-bed union; observation dates unknown; map/source dates retained separately",
                "dated_years": report["all_time_dated_years"],
                "nonannual_records_included": report["nonannual_records_included"],
            },
        }
        return validate_table(pa.table(data), dynamic=False).replace_schema_metadata(
            {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
        )

    static = reduce(records)
    report["all_time_positive_cells"] = static.num_rows - static[ALL_TIME].null_count
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _CODE_SHA256:
        raise ValueError(
            "Bivalve extent code changed during processing; reload before recomputing"
        )
    return BivalveExtentResult(AreaTables(static=static, dynamic=None), report)
