"""One Seagrass feature: all-history spatial union with source dates as provenance."""

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

ALL_TIME = "SEAGRASS_EXTENT_ALL_TIME_M2"
EXTENT_COLUMNS = (ALL_TIME,)
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class SeagrassExtentResult:
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
            "Seagrass source identity, methodology, species, temporal support and CRS are required"
        )
    if (
        inventory.RECORD_ID.isna().any()
        or inventory.RECORD_ID.astype(str).duplicated().any()
    ):
        raise ValueError("Seagrass record identities must be unique and non-null")
    source = inventory.SOURCE_DATASET.astype(str)
    dated_survey = source.isin(
        ["WA_DNR_INTERTIDAL_EELGRASS_1995", "WA_DNR_INTERTIDAL_EELGRASS_1996"]
    )
    legacy = source.eq("BC_CRIMS_EELGRASS")
    composite = source.isin(
        ["GLOBAL_SENTINEL2_SEAGRASS_2019_2020", "GLOBAL_SENTINEL2_SEAGRASS_2023_2024"]
    )
    positive = (
        inventory.HABITAT_TYPE.isin(["eelgrass", "seagrass"])
        & inventory.OBSERVATION_STATUS.eq("present")
        & inventory.geom_type.isin(["Polygon", "MultiPolygon"])
    )
    selected = inventory.loc[
        positive
        & (
            ((dated_survey | legacy) & inventory.OBSERVED_VS_MODELED.eq("observed"))
            | (composite & inventory.OBSERVED_VS_MODELED.eq("modeled"))
        )
    ].copy()
    selected["DATED_SURVEY_EVIDENCE"] = dated_survey.loc[selected.index].to_numpy()
    for year in (1995, 1996):
        if (
            not selected.loc[
                selected.SOURCE_DATASET.eq(f"WA_DNR_INTERTIDAL_EELGRASS_{year}"),
                "OBSERVATION_YEAR",
            ]
            .eq(year)
            .all()
        ):
            raise ValueError(
                "Dated WA eelgrass evidence requires the documented inventory survey year"
            )
    # Multi-year modeled classifications and legacy map dates cannot become annual observations.
    if selected.loc[~selected.DATED_SURVEY_EVIDENCE, "OBSERVATION_YEAR"].notna().any():
        raise ValueError(
            "Composite or legacy map dates must not masquerade as observation years"
        )
    if (
        selected.empty
        or selected.geometry.isna().any()
        or selected.geometry.is_empty.any()
        or not selected.geometry.is_valid.all()
    ):
        raise ValueError(
            "Seagrass extent requires valid audited positive polygon evidence"
        )
    return selected.reset_index(drop=True)


def build_seagrass_extents(
    inventory: gpd.GeoDataFrame,
    full_cells: gpd.GeoDataFrame,
    *,
    source_context: Mapping[str, Any],
    max_cells: int = 200000,
    max_records: int = 200000,
    max_pairs: int = 4000000,
) -> SeagrassExtentResult:
    """Union compatible positive polygons in each full native H3 cell, in m².

    Every eligible available historical polygon contributes, including dated WA
    inventories, undated legacy mapping and explicitly qualified satellite
    composites. Dates remain provenance, with no annual delivery variant. Full
    native cells preserve evidence outside revised water masks. No fraction,
    current presence or surveyed absence follows.
    """
    if not source_context.get("rights"):
        raise ValueError("Seagrass source rights/provenance are required")
    if min(max_cells, max_records, max_pairs) < 1:
        raise ValueError("Seagrass resource bounds must be positive")
    records = eligible_extent_inventory(inventory)
    if len(records) > max_records:
        raise ValueError("Seagrass record budget exceeded")
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
            "Seagrass support requires unique valid cells at one native resolution within budget"
        )
    resolution = resolutions.pop()
    if (
        not full.H3_RESOLUTION.eq(resolution).all()
        or full.geometry.isna().any()
        or full.geometry.is_empty.any()
        or not full.geometry.is_valid.all()
        or not full.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    ):
        raise ValueError("Seagrass full H3 geometry/resolution is invalid")
    records = records.to_crs(6933)
    if not records.geometry.is_valid.all():
        raise ValueError(
            "Projected seagrass geometry requires a separate recorded audit"
        )
    source_hash = hashlib.sha256()
    for row in records.sort_values("RECORD_ID").itertuples():
        source_hash.update(str(row.RECORD_ID).encode())
        source_hash.update(row.geometry.wkb)
    report: dict[str, Any] = {
        "method": "seagrass_positive_extent_union_v2",
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
        "Geometric union of eligible mapped positive seagrass/eelgrass polygons and classified positive raster footprints intersecting the full native H3 cell, EPSG:6933 m². "
        "Overlaps are counted once. Missing positive evidence is unknown, never inferred absence. "
        "Mapped/classified extent mixes explicitly qualified source methods and species resolution; it is not current presence, pure canopy, field-confirmed satellite occurrence or a historical water-mask measurement."
    )

    def reduce(selected: gpd.GeoDataFrame) -> pa.Table:
        column = ALL_TIME
        pairs = full.sindex.query(selected.geometry, predicate="intersects")
        if pairs.shape[1] > max_pairs:
            raise ValueError("Seagrass polygon-overlap budget exceeded")
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
        scientific_name = "Seagrass Extent (All Time)"
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
            + " All eligible available history contributes; source observation years, composite periods and legacy map dates remain provenance.",
            "qualifiers": qualifiers,
            "modeling_eligibility": "source_qualified_extent_not_current_presence",
        }
        context = {
            "dataset": "seagrass",
            "schema_version": 3,
            "fields": fields,
            "report": report,
            "source_context": dict(source_context),
            "availability_known": False,
            "model_eligible": False,
            "temporal_support": {
                "kind": "static_reference",
                "definition": "All-history spatial union; WA observed years, unknown-date legacy mapping and modeled two-year composites remain distinct in provenance",
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
            "Seagrass extent code changed during processing; reload before recomputing"
        )
    return SeagrassExtentResult(AreaTables(static=static, dynamic=None), report)
