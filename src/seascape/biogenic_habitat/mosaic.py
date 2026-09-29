"""Generic normalized vector adapter and as-of mapped habitat mosaic.

No provider schema is assumed. A provider contract must be reviewed and passed
explicitly; regional rights, coverage and observations are not bundled here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from seascape.products import resolve_product
from seascape.utils.habitat_inventory import normalize_inventory
from seascape.utils.habitat_surface import _composition_metrics, _spatial_pairs

HABITAT_SUPPORT = {
    "eelgrass": "marine",
    "floating_kelp": "marine",
    "understory_kelp": "marine",
    "other_macroalgae": "marine",
    "tidal_marsh": "intertidal",
    "mudflat_sandflat": "intertidal",
    "rocky_intertidal": "intertidal",
}


@dataclass(frozen=True)
class VectorProviderContract:
    source_id: str
    source_version: str
    rights: str
    mapping_method: str
    class_crosswalk: dict[str, str]
    source_class_field: str = "SOURCE_CLASS"
    feature_id_field: str = "SOURCE_FEATURE_ID"
    source_priority: int = 0

    def validate(self) -> None:
        if not all(
            (self.source_id, self.source_version, self.rights, self.mapping_method)
        ):
            raise ValueError("Source identity, rights and mapping method are required")
        if not self.class_crosswalk or set(self.class_crosswalk.values()) - set(
            HABITAT_SUPPORT
        ):
            raise ValueError("Habitat class crosswalk is missing or unsupported")


def normalize_vector_provider(
    raw: gpd.GeoDataFrame, contract: VectorProviderContract
) -> gpd.GeoDataFrame:
    """Normalize reviewed primary fields without inventing area or absence."""

    contract.validate()
    required = {
        contract.source_class_field,
        contract.feature_id_field,
        "OBSERVATION_YEAR",
        "OBSERVATION_STATUS",
        "EVIDENCE_CLASS",
    }
    if required - set(raw) or raw.crs is None:
        raise ValueError(
            f"Provider layer needs CRS and fields {sorted(required - set(raw))}"
        )
    unknown = set(raw[contract.source_class_field].dropna().astype(str)) - set(
        contract.class_crosswalk
    )
    if unknown:
        raise ValueError(f"Unmapped source classes: {sorted(unknown)}")
    if (
        raw[contract.feature_id_field].isna().any()
        or raw[contract.feature_id_field].duplicated().any()
    ):
        raise ValueError("Source feature IDs must be unique and non-null")
    records = []
    for row in raw.itertuples(index=False):
        source_class = str(getattr(row, contract.source_class_field))
        habitat = contract.class_crosswalk[source_class]
        evidence = str(getattr(row, "EVIDENCE_CLASS"))
        status = str(getattr(row, "OBSERVATION_STATUS"))
        geometry = row.geometry
        polygon = geometry.geom_type in {"Polygon", "MultiPolygon"}
        raw_role = getattr(row, "GEOMETRY_ROLE", None)
        role = "observation" if pd.isna(raw_role) else str(raw_role)
        raw_completeness = getattr(row, "SURVEY_COMPLETENESS", None)
        completeness = "unknown" if pd.isna(raw_completeness) else raw_completeness
        if role == "survey_footprint" and (status != "surveyed" or not polygon):
            raise ValueError(
                "Survey footprint must be a dated polygon with surveyed status"
            )
        record = {
            "RECORD_ID": f"{contract.source_id}:{contract.source_version}:{getattr(row, contract.feature_id_field)}",
            "HABITAT_TYPE": habitat,
            "SOURCE_DATASET": contract.source_id,
            "SOURCE_FEATURE_ID": str(getattr(row, contract.feature_id_field)),
            "EVIDENCE_CLASS": evidence,
            "OBSERVED_VS_MODELED": "observed"
            if evidence == "direct_observation"
            else "modeled",
            "OBSERVATION_STATUS": status,
            "OBSERVATION_YEAR": getattr(row, "OBSERVATION_YEAR"),
            "COMPOSITION_ELIGIBLE": polygon and status == "present",
            "SUPPORTS_AREA": polygon,
            "COVERAGE_WEIGHT": 1.0,
            "SOURCE_PERSISTENCE_RATIO": np.nan,
            "CONFIDENCE_CLASS": 2 if evidence == "direct_observation" else 1,
            "SURVEY_METHOD": contract.mapping_method,
            "SPATIAL_PRECISION_CLASS": "polygon" if polygon else "point_or_line",
            "TEMPORAL_PRECISION_CLASS": "year",
            "GEOMETRY_ROLE": role,
            "SURVEY_EVENT_ID": getattr(row, "SURVEY_EVENT_ID", None),
            "SURVEY_COMPLETENESS": completeness,
            "AVAILABLE_YEAR": getattr(row, "AVAILABLE_YEAR", None),
            "SOURCE_PRIORITY": contract.source_priority,
            "geometry": geometry,
        }
        records.append(record)
    if records:
        frame = gpd.GeoDataFrame(records, geometry="geometry", crs=raw.crs)
    else:
        # An explicitly empty map is valid input evidence; absence still needs
        # a separate complete survey footprint and cannot be inferred here.
        from seascape.utils.habitat_inventory import (
            EVIDENCE_EXTENSION_COLUMNS,
            NORMALIZED_INVENTORY_COLUMNS,
        )

        frame = gpd.GeoDataFrame(
            {
                column: pd.Series(dtype="object")
                for column in (
                    *NORMALIZED_INVENTORY_COLUMNS,
                    *EVIDENCE_EXTENSION_COLUMNS,
                )
            },
            geometry="geometry",
            crs=raw.crs,
        )
    normalized = normalize_inventory(frame)
    raw_class_by_id = {
        f"{contract.source_id}:{contract.source_version}:{feature_id}": source_class
        for feature_id, source_class in zip(
            raw[contract.feature_id_field],
            raw[contract.source_class_field],
            strict=True,
        )
    }
    normalized["RAW_CLASS"] = normalized.RECORD_ID.map(raw_class_by_id)
    normalized["SOURCE_VERSION"] = contract.source_version
    normalized["SOURCE_RIGHTS"] = contract.rights
    normalized["SUPPORT_TYPE"] = normalized.HABITAT_TYPE.map(HABITAT_SUPPORT)
    return normalized


def build_mapped_mosaic(
    support: gpd.GeoDataFrame,
    inventory: gpd.GeoDataFrame,
    *,
    as_of_year: int,
    equal_area_crs: str = "EPSG:6933",
) -> pd.DataFrame:
    """Resolve each class on its eligible marine/intertidal support.

    Combined area uses geometric union of the same resolved class footprints.
    Unknown survey opportunity remains null; a presence-only map is not zero
    outside occupied polygons. The caller supplies separately mapped tidal-frame
    intertidal support, never a negative-elevation marine mask surrogate.
    """

    required_support = {"H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "geometry"}
    if required_support - set(support) or support.crs is None:
        raise ValueError("Mapped support requires H3 identity, support type and CRS")
    if support.duplicated(["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE"]).any():
        raise ValueError("Duplicate habitat support identity")
    if not set(support.SUPPORT_TYPE) <= {"marine", "intertidal"}:
        raise ValueError("Unknown habitat support type")
    if "SUPPORT_TYPE" not in inventory:
        raise ValueError("Inventory must declare marine or intertidal support")
    extra = inventory.set_index("RECORD_ID")["SUPPORT_TYPE"]
    normalized = normalize_inventory(inventory)
    normalized["SUPPORT_TYPE"] = normalized.RECORD_ID.map(extra)
    if any(
        normalized.apply(
            lambda row: HABITAT_SUPPORT.get(row.HABITAT_TYPE) != row.SUPPORT_TYPE,
            axis=1,
        )
    ):
        raise ValueError("Habitat type and support type disagree")
    normalized = normalized.loc[
        (
            normalized.OBSERVATION_END_YEAR.isna()
            | normalized.OBSERVATION_END_YEAR.le(as_of_year)
        )
        & (normalized.AVAILABLE_YEAR.isna() | normalized.AVAILABLE_YEAR.le(as_of_year))
    ].copy()
    rows = []
    for support_type, cells in support.groupby("SUPPORT_TYPE", sort=True):
        cells = cells.to_crs(equal_area_crs).copy()
        if not cells.geometry.is_valid.all() or (cells.geometry.area <= 0).any():
            raise ValueError("Habitat support geometry must be valid and positive area")
        mapped = normalized.loc[normalized.SUPPORT_TYPE.eq(support_type)].copy()
        geometry_by_type: dict[str, dict[str, Any]] = {}
        survey_by_type: dict[str, dict[str, float]] = {}
        years_by_type: dict[str, set[int]] = {}
        evidence_by_type: dict[str, dict[str, tuple[str, ...]]] = {}
        for habitat_type in sorted(set(mapped.HABITAT_TYPE.dropna())):
            selected = mapped.loc[mapped.HABITAT_TYPE.eq(habitat_type)].copy()
            projected_cells, projected_inventory, pairs = _spatial_pairs(
                cells, selected, equal_area_crs
            )
            area_support = pd.DataFrame(
                {
                    "H3_INDEX": projected_cells.H3_INDEX.astype(str),
                    "WATER_AREA_M2": projected_cells.geometry.area.to_numpy(),
                }
            )
            metrics, geometries = _composition_metrics(
                projected_cells,
                projected_inventory,
                pairs,
                area_support,
                return_geometries=True,
            )
            geometry_by_type[habitat_type] = geometries
            evidence_by_type[habitat_type] = {
                str(cell_id): tuple(
                    sorted(
                        projected_inventory.iloc[
                            group.index_right.astype(int).to_numpy()
                        ]
                        .RECORD_ID.astype(str)
                        .unique()
                    )
                )
                for cell_id, group in pairs.groupby("H3_INDEX", sort=False)
            }
            years_by_type[habitat_type] = set(
                selected.OBSERVATION_YEAR.dropna().astype(int)
            )
            footprints = projected_inventory.loc[
                projected_inventory.GEOMETRY_ROLE.eq("survey_footprint")
                & projected_inventory.SURVEY_COMPLETENESS.eq("complete")
            ]
            survey_by_type[habitat_type] = {}
            for cell in projected_cells.itertuples(index=False):
                overlapping = [
                    feature.geometry.intersection(cell.geometry)
                    for feature in footprints.itertuples(index=False)
                    if feature.geometry.intersects(cell.geometry)
                ]
                if overlapping:
                    survey_by_type[habitat_type][str(cell.H3_INDEX)] = unary_union(
                        overlapping
                    ).area
            for cell, metric in zip(
                projected_cells.itertuples(index=False),
                metrics.itertuples(index=False),
                strict=True,
            ):
                area = float(metric.HABITAT_AREA_M2)
                eligible = float(cell.geometry.area)
                surveyed = survey_by_type[habitat_type].get(str(cell.H3_INDEX))
                rows.append(
                    {
                        "H3_INDEX": str(cell.H3_INDEX),
                        "H3_RESOLUTION": int(cell.H3_RESOLUTION),
                        "SUPPORT_TYPE": support_type,
                        "HABITAT_TYPE": habitat_type,
                        "MAPPED_AREA_M2": area,
                        "MAPPED_FRACTION_OF_ELIGIBLE": area / eligible,
                        "ELIGIBLE_AREA_M2": eligible,
                        "SURVEYED_AREA_M2": surveyed,
                        "SURVEYED_FRACTION_OF_ELIGIBLE": surveyed / eligible
                        if surveyed is not None
                        else None,
                        "PATCH_COUNT_WITHIN_SUPPORT": int(metric.PATCH_COUNT),
                        "TOPOLOGY_QC_REASON": metric.TOPOLOGY_QC_REASON,
                        "MOSAIC_STATUS": "multi_year_mosaic"
                        if len(years_by_type[habitat_type]) > 1
                        else "single_year_or_unknown",
                        "OBSERVATION_STATE": "mapped_presence"
                        if area > 0
                        else "mapped_absence"
                        if surveyed is not None and surveyed >= eligible - 1e-6
                        else "unknown",
                        "OPERATIONAL_HISTORY_STATUS": "unknown_availability"
                        if selected.AVAILABLE_YEAR.isna().any()
                        else "available_by_as_of_year",
                        "OBSERVATION_YEARS": "|".join(
                            map(str, sorted(years_by_type[habitat_type]))
                        ),
                        # These are intersecting evidence, including absence and
                        # superseded observations, not only surviving presence.
                        "INTERSECTING_EVIDENCE_RECORD_IDS": "|".join(
                            evidence_by_type[habitat_type].get(str(cell.H3_INDEX), ())
                        ),
                    }
                )
        for cell in cells.itertuples(index=False):
            fragments = [
                geometry_by_type[habitat_type][str(cell.H3_INDEX)]
                for habitat_type in geometry_by_type
                if str(cell.H3_INDEX) in geometry_by_type[habitat_type]
            ]
            combined = unary_union(fragments) if fragments else None
            all_years = set().union(*years_by_type.values()) if years_by_type else set()
            temporally_compatible = len(all_years) <= 1
            area = (
                combined.area
                if combined is not None and temporally_compatible
                else None
            )
            rows.append(
                {
                    "H3_INDEX": str(cell.H3_INDEX),
                    "H3_RESOLUTION": int(cell.H3_RESOLUTION),
                    "SUPPORT_TYPE": support_type,
                    "HABITAT_TYPE": "compatible_union",
                    "MAPPED_AREA_M2": area,
                    "MAPPED_FRACTION_OF_ELIGIBLE": area / cell.geometry.area
                    if area is not None
                    else None,
                    "ELIGIBLE_AREA_M2": cell.geometry.area,
                    "SURVEYED_AREA_M2": None,
                    "SURVEYED_FRACTION_OF_ELIGIBLE": None,
                    "PATCH_COUNT_WITHIN_SUPPORT": None,
                    "TOPOLOGY_QC_REASON": "combined_topology_not_asserted",
                    "MOSAIC_STATUS": "temporal_support_conflict"
                    if not temporally_compatible
                    else "single_year_or_unknown",
                    "OBSERVATION_STATE": "combined_mapped_presence"
                    if area is not None and area > 0
                    else "unknown",
                    "OPERATIONAL_HISTORY_STATUS": "unknown_availability"
                    if mapped.AVAILABLE_YEAR.isna().any()
                    else "available_by_as_of_year",
                    "OBSERVATION_YEARS": "|".join(map(str, sorted(all_years))),
                    "INTERSECTING_EVIDENCE_RECORD_IDS": "|".join(
                        sorted(
                            {
                                record_id
                                for by_cell in evidence_by_type.values()
                                for record_id in by_cell.get(str(cell.H3_INDEX), ())
                            }
                        )
                    ),
                }
            )
    output = pd.DataFrame(rows)
    if output.duplicated(
        ["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "HABITAT_TYPE"]
    ).any():
        raise ValueError("Duplicate habitat mosaic identity")
    return output.sort_values(
        ["H3_RESOLUTION", "H3_INDEX", "SUPPORT_TYPE", "HABITAT_TYPE"]
    ).reset_index(drop=True)


def read_released_mosaic(
    habitat_types: Iterable[str],
    *,
    workspace: str | Path | None = None,
    release_id: str | None = None,
    resolution: int = 8,
) -> pd.DataFrame:
    selected = tuple(dict.fromkeys(str(value) for value in habitat_types))
    if not selected:
        raise ValueError("Select exact habitat types")
    artifact = resolve_product(
        product="mapped_habitat_mosaic",
        resolution=resolution,
        workspace=workspace,
        release_id=release_id,
    )
    frame = pd.read_parquet(artifact.path)
    key = ["H3_INDEX", "H3_RESOLUTION", "SUPPORT_TYPE", "HABITAT_TYPE"]
    if frame[key].isna().any().any() or frame.duplicated(key).any():
        raise ValueError("Released mosaic key is ambiguous")
    if set(selected) - set(frame.HABITAT_TYPE.astype(str)):
        raise KeyError("Selected habitat type absent from release")
    return frame.loc[frame.HABITAT_TYPE.isin(selected)].copy()


def pivot_selected_habitats(
    frame: pd.DataFrame,
    habitat_types: Iterable[str],
    *,
    support_type: str,
) -> pd.DataFrame:
    selected = tuple(dict.fromkeys(str(value) for value in habitat_types))
    if not selected or set(selected) - set(frame.HABITAT_TYPE.astype(str)):
        raise ValueError("Select available habitat types explicitly")
    if support_type not in {"marine", "intertidal"}:
        raise ValueError("Select one explicit support type")
    rows = frame.loc[
        frame.SUPPORT_TYPE.eq(support_type) & frame.HABITAT_TYPE.isin(selected)
    ]
    if rows.duplicated(["H3_INDEX", "H3_RESOLUTION", "HABITAT_TYPE"]).any():
        raise ValueError("Mosaic pivot has one-to-many cell/type relationships")
    wide = rows.pivot(
        index=["H3_INDEX", "H3_RESOLUTION"],
        columns="HABITAT_TYPE",
        values="MAPPED_AREA_M2",
    )
    wide.columns = [
        f"MAPPED_AREA_M2__{len(str(value))}_{value}" for value in wide.columns
    ]
    return wide.reset_index()
