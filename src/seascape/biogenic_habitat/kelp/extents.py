"""One Kelp dataset: annual observed bed extent and its all-history spatial union."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import shapely

from seascape.domain_parquets import METADATA_KEY, AreaTables, validate_table

ANNUAL = "ANNUAL_KELP_EXTENT_M2"
ALL_TIME = "KELP_EXTENT_ALL_TIME_M2"
EXTENT_COLUMNS = (ANNUAL, ALL_TIME)
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class KelpExtentResult:
    tables: AreaTables
    report: dict[str, Any]


def eligible_extent_inventory(inventory: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Select observed polygon evidence; never turn shoreline lengths into area."""
    required = {
        "RECORD_ID",
        "SOURCE_DATASET",
        "OBSERVATION_STATUS",
        "OBSERVATION_YEAR",
        "HABITAT_TYPE",
        "OBSERVED_VS_MODELED",
    }
    if required - set(inventory) or inventory.crs is None:
        raise ValueError(
            "Kelp source identity, habitat, observation state/year and CRS are required"
        )
    if (
        inventory.RECORD_ID.isna().any()
        or inventory.RECORD_ID.astype(str).duplicated().any()
    ):
        raise ValueError("Kelp source record identities must be unique and non-null")
    source = inventory.SOURCE_DATASET.astype(str)
    annual = source.str.fullmatch(r"WA_DNR_FLOATING_KELP_\d{4}")
    crims = source.eq("BC_CRIMS_KELP_BEDS")
    persistence = source.eq("WA_DNR_FLOATING_KELP_PERSISTENCE_CLASS")
    if persistence.any():
        ratio = pd.to_numeric(
            inventory.get("SOURCE_PERSISTENCE_RATIO"), errors="coerce"
        )
        persistence &= ratio.gt(0) & ratio.le(1)
    selected = inventory.loc[
        inventory.HABITAT_TYPE.isin(["floating_kelp", "kelp"])
        & inventory.OBSERVED_VS_MODELED.eq("observed")
        & inventory.OBSERVATION_STATUS.eq("present")
        & inventory.geom_type.isin(["Polygon", "MultiPolygon"])
        & (annual | crims | persistence)
    ].copy()
    selected["ANNUAL_ELIGIBLE"] = annual.loc[selected.index].to_numpy()
    if (
        selected.empty
        or selected.geometry.isna().any()
        or selected.geometry.is_empty.any()
        or not selected.geometry.is_valid.all()
    ):
        raise ValueError(
            "Kelp extent requires nonempty valid audited positive polygon evidence"
        )
    return selected.reset_index(drop=True)


def build_kelp_extents(
    inventory: gpd.GeoDataFrame,
    full_cells: gpd.GeoDataFrame,
    *,
    source_context: Mapping[str, Any],
    start_year: int | None = None,
    end_year: int | None = None,
    include_undated: bool | None = None,
    max_cells: int = 100000,
    max_records: int = 200000,
    max_cell_years: int = 4000000,
    max_pairs: int = 4000000,
) -> KelpExtentResult:
    """Union compatible positive polygons in each full native H3 cell, in m².

    Default includes every available dated observation plus explicitly flagged
    undated legacy mapping. Explicit year bounds exclude undated records unless
    the caller deliberately opts in; no unknown date is assigned a survey year.
    The independent full-cell denominator preserves evidence outside revised
    water masks. No fraction, canopy, current presence or surveyed absence follows.
    """
    if not source_context.get("rights"):
        raise ValueError("Kelp source rights/provenance are required")
    if min(max_cells, max_records, max_cell_years, max_pairs) < 1:
        raise ValueError("Kelp resource bounds must be positive")
    if any(
        v is not None
        and (isinstance(v, bool) or not isinstance(v, int) or not 1800 <= v <= 9998)
        for v in (start_year, end_year)
    ):
        raise ValueError("Kelp year bounds must be integer years")
    if start_year is not None and end_year is not None and start_year > end_year:
        raise ValueError("Kelp year bounds are reversed")
    records = eligible_extent_inventory(inventory)
    if len(records) > max_records:
        raise ValueError("Kelp record budget exceeded")
    years = pd.to_numeric(records.OBSERVATION_YEAR, errors="raise")
    if ((years.dropna() % 1) != 0).any() or (
        records.ANNUAL_ELIGIBLE & years.isna()
    ).any():
        raise ValueError("Annual kelp requires integer observation years")
    include_undated = (
        (start_year is None and end_year is None)
        if include_undated is None
        else include_undated
    )
    keep = years.notna()
    if start_year is not None:
        keep &= years.ge(start_year).fillna(False)
    if end_year is not None:
        keep &= years.le(end_year).fillna(False)
    if include_undated:
        keep |= years.isna()
    records = records.loc[keep].copy().reset_index(drop=True)
    if records.empty:
        raise ValueError("No eligible kelp evidence in the requested range")
    if full_cells.crs is None or not {"H3_INDEX", "H3_RESOLUTION"} <= set(full_cells):
        raise ValueError("Explicit native full H3 geometry and CRS are required")
    full = full_cells.to_crs(6933).sort_values("H3_INDEX").reset_index(drop=True)
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
            "Kelp support requires unique valid cells at one native resolution within budget"
        )
    resolution = resolutions.pop()
    if (
        not full.H3_RESOLUTION.eq(resolution).all()
        or full.geometry.isna().any()
        or full.geometry.is_empty.any()
        or not full.geometry.is_valid.all()
        or not full.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    ):
        raise ValueError("Kelp full H3 geometry/resolution is invalid")
    records = records.to_crs(6933)
    if not records.geometry.is_valid.all():
        raise ValueError("Projected kelp geometry requires a separate recorded audit")
    actual_years = sorted(
        records.loc[records.ANNUAL_ELIGIBLE, "OBSERVATION_YEAR"]
        .astype(int)
        .unique()
        .tolist()
    )
    if len(keys) * max(1, len(actual_years)) > max_cell_years:
        raise ValueError("Kelp cell-year budget exceeded")
    source_hash = hashlib.sha256()
    for row in records.sort_values("RECORD_ID").itertuples():
        source_hash.update(str(row.RECORD_ID).encode())
        source_hash.update(row.geometry.wkb)
    report: dict[str, Any] = {
        "method": "kelp_positive_extent_union_v2",
        "code_sha256": _CODE_SHA256,
        "native_resolution": resolution,
        "native_cells": len(keys),
        "source_records": len(records),
        "source_geometry_sha256": source_hash.hexdigest(),
        "actual_annual_years": actual_years,
        "all_time_dated_years": sorted(
            records.OBSERVATION_YEAR.dropna().astype(int).unique().tolist()
        ),
        "undated_records_included": int(records.OBSERVATION_YEAR.isna().sum()),
        "requested_start_year": start_year,
        "requested_end_year": end_year,
        "include_undated": include_undated,
        "survey_absence_qualified": False,
        "water_mask_used_for_extent": False,
        "source_datasets": records.SOURCE_DATASET.value_counts().sort_index().to_dict(),
        "excluded_input_records": len(inventory) - len(records),
    }
    definition = (
        "Geometric union of eligible mapped positive kelp-bed polygons intersecting the full native H3 cell, EPSG:6933 m². "
        "Overlaps are counted once. Missing positive evidence is unknown, never inferred absence. "
        "Mapped bed extent is not pure canopy, current presence or a historical water-mask measurement."
    )

    def reduce(selected: gpd.GeoDataFrame, column: str, year: int | None) -> pa.Table:
        pairs = full.sindex.query(selected.geometry, predicate="intersects")
        if pairs.shape[1] > max_pairs:
            raise ValueError("Kelp polygon-overlap budget exceeded")
        by_cell: dict[int, list[int]] = {}
        for record_index, cell_index in zip(*pairs, strict=True):
            by_cell.setdefault(int(cell_index), []).append(int(record_index))
        amounts: list[float | None] = [None] * len(keys)
        statuses = ["no_positive_evidence_unknown_absence"] * len(keys)
        sources, observed = ["[]"] * len(keys), ["[]"] * len(keys)
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
            "SOURCE_DATASETS_JSON": pa.array(sources),
            "OBSERVATION_YEARS_JSON": pa.array(observed),
            "UNDATED_EVIDENCE_INCLUDED": pa.array(undated),
            "REPAIRED_GEOMETRY_INCLUDED": pa.array(repaired),
            "INTERSECTING_SOURCE_RECORD_COUNT": pa.array(counts, type=pa.int32()),
        }
        if year is not None:
            data["date"] = pa.array([date(year, 1, 1)] * len(keys), type=pa.date32())
        scientific_name = (
            "Annual Kelp Extent" if year is not None else "Kelp Extent (All Time)"
        )
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
            + (
                " Only the selected survey year contributes."
                if year
                else " All eligible available years contribute; explicitly flagged legacy evidence may have unknown observation dates."
            ),
            "qualifiers": qualifiers,
            "modeling_eligibility": "source_qualified_extent_not_current_presence",
        }
        context = {
            "dataset": "kelp",
            "schema_version": 2,
            "fields": fields,
            "report": report,
            "source_context": dict(source_context),
            "availability_known": False,
            "model_eligible": False,
            "temporal_support": {
                "kind": "annual_survey",
                "precision": "year",
                "date_label": "January 1 labels the survey year, not the observation day",
            }
            if year is not None
            else {
                "kind": "static_reference",
                "definition": "All-history spatial union; observed years and unknown-date legacy contributions are retained separately",
                "dated_years": report["all_time_dated_years"],
                "undated_records_included": report["undated_records_included"],
            },
        }
        return validate_table(
            pa.table(data), dynamic=year is not None
        ).replace_schema_metadata(
            {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
        )

    static = reduce(records, ALL_TIME, None)
    annual = []
    for year in actual_years:
        selected = records.loc[
            records.ANNUAL_ELIGIBLE & records.OBSERVATION_YEAR.eq(year)
        ].reset_index(drop=True)
        annual.append(reduce(selected, ANNUAL, year))
    dynamic = pa.concat_tables(annual) if annual else None
    report["all_time_positive_cells"] = static.num_rows - static[ALL_TIME].null_count
    report["annual_positive_cell_years"] = (
        dynamic.num_rows - dynamic[ANNUAL].null_count if dynamic is not None else 0
    )
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _CODE_SHA256:
        raise ValueError(
            "Kelp extent code changed during processing; reload before recomputing"
        )
    return KelpExtentResult(AreaTables(static=static, dynamic=dynamic), report)
