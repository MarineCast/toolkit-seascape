"""H3 r8 habitat processing and feature-aware aggregation to H3 r6."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from shapely import area, difference, length, union_all

from seascape.spatial_support.water_network.graph import (
    WaterGraph,
    target_graph_mapping,
)
from seascape.spatial_support.water_network.load import (
    multi_source_shortest_paths,
)
from seascape.spatial_support.water_network.radius_operator import (
    RadiusSumOperator,
)
from seascape.utils.habitat_aggregation import (
    validate_surface_tables,
)
from seascape.utils.habitat_inventory import normalize_inventory


def _spatial_pairs(
    cells: Any, inventory: Any, equal_area_crs: str
) -> tuple[Any, Any, pd.DataFrame]:
    import geopandas as gpd

    projected_cells = cells.to_crs(equal_area_crs).reset_index(drop=True)
    projected_inventory = inventory.to_crs(equal_area_crs).reset_index(drop=True)
    left = projected_cells[["H3_INDEX", "geometry"]].copy()
    right = projected_inventory[["geometry"]].copy()
    joined = gpd.sjoin(left, right, how="inner", predicate="intersects")
    pairs = joined[["H3_INDEX", "index_right"]].drop_duplicates().reset_index(drop=True)
    return projected_cells, projected_inventory, pairs


def _footprint_absence_geometry(footprint: Any, local_records: Any) -> Any:
    """Only an explicit complete event footprint can imply unmapped absence."""

    present = local_records.loc[
        local_records["GEOMETRY_ROLE"].eq("observation")
        & local_records["OBSERVATION_STATUS"].eq("present")
        & local_records["SURVEY_EVENT_ID"].eq(footprint.SURVEY_EVENT_ID)
        & local_records["OBSERVATION_YEAR"].eq(footprint.OBSERVATION_YEAR)
        & local_records.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    return (
        footprint.geometry.difference(union_all(present.geometry.to_numpy()))
        if not present.empty
        else footprint.geometry
    )


def _composition_metrics(
    cells: Any,
    inventory: Any,
    pairs: pd.DataFrame,
    support: pd.DataFrame,
    *,
    return_geometries: bool = False,
) -> Any:
    composition_mask = (
        inventory["COMPOSITION_ELIGIBLE"].astype(bool)
        & inventory["SUPPORTS_AREA"].astype(bool)
        & inventory["OBSERVATION_STATUS"].eq("present")
    )
    composition = inventory.loc[composition_mask].copy()
    output = pd.DataFrame(
        {
            "H3_INDEX": support["H3_INDEX"].astype("string"),
            "HABITAT_AREA_M2": np.zeros(len(support), dtype="float64"),
            "PATCH_COUNT": np.zeros(len(support), dtype="int32"),
            "LARGEST_PATCH_AREA_M2": np.zeros(len(support), dtype="float64"),
            "EDGE_LENGTH_M": np.zeros(len(support), dtype="float64"),
            "TOPOLOGY_QC_REASON": ["no_mapped_patch"] * len(support),
        }
    ).set_index("H3_INDEX")
    if composition.empty:
        return (output.reset_index(), {}) if return_geometries else output.reset_index()
    if not composition["COVERAGE_WEIGHT"].eq(1.0).all():
        raise ValueError(
            "Composition-eligible polygons must use exact coverage weight 1. "
            "Fractional survey estimates belong in persistence/confidence fields."
        )
    composition_indices = set(composition.index)
    selected_pairs = pairs.loc[pairs["index_right"].isin(composition_indices)]
    observed_absence = inventory.loc[
        inventory["GEOMETRY_ROLE"].eq("observation")
        & inventory["OBSERVED_VS_MODELED"].eq("observed")
        & inventory["OBSERVATION_STATUS"].eq("absent")
        & inventory.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    absence_pairs = pairs.loc[pairs["index_right"].isin(set(observed_absence.index))]
    absence_by_cell = {
        str(cell): rows["index_right"].astype(int).tolist()
        for cell, rows in absence_pairs.groupby("H3_INDEX", sort=False)
    }
    footprint_indices = set(
        inventory.index[
            inventory["GEOMETRY_ROLE"].eq("survey_footprint")
            & inventory["SURVEY_COMPLETENESS"].eq("complete")
        ]
    )
    footprint_pairs = pairs.loc[pairs["index_right"].isin(footprint_indices)]
    footprints_by_cell = {
        str(cell): rows["index_right"].astype(int).tolist()
        for cell, rows in footprint_pairs.groupby("H3_INDEX", sort=False)
    }
    all_by_cell = {
        str(cell): rows["index_right"].astype(int).tolist()
        for cell, rows in pairs.groupby("H3_INDEX", sort=False)
    }
    cell_positions = {
        str(cell): index for index, cell in enumerate(cells["H3_INDEX"].astype(str))
    }
    resolved_geometries: dict[str, Any] = {}
    for cell, cell_pairs in selected_pairs.groupby("H3_INDEX", sort=False):
        cell_position = cell_positions[str(cell)]
        cell_geometry = cells.geometry.iloc[cell_position]
        local_records = inventory.iloc[all_by_cell.get(str(cell), [])]
        blockers: list[tuple[int, int, Any]] = []
        for absent_index in absence_by_cell.get(str(cell), []):
            absent = inventory.iloc[absent_index]
            blockers.append(
                (
                    int(absent["OBSERVATION_YEAR"])
                    if pd.notna(absent["OBSERVATION_YEAR"])
                    else -32768,
                    int(absent["SOURCE_PRIORITY"]),
                    absent.geometry,
                )
            )
        for footprint_index in footprints_by_cell.get(str(cell), []):
            footprint = inventory.iloc[footprint_index]
            blockers.append(
                (
                    int(footprint["OBSERVATION_YEAR"]),
                    int(footprint["SOURCE_PRIORITY"]),
                    _footprint_absence_geometry(footprint, local_records),
                )
            )
        fragments = []
        for record_index in cell_pairs["index_right"]:
            record = inventory.iloc[int(record_index)]
            fragment = cell_geometry.intersection(record.geometry)
            current_year = (
                int(record["OBSERVATION_YEAR"])
                if pd.notna(record["OBSERVATION_YEAR"])
                else -32768
            )
            current_priority = int(record["SOURCE_PRIORITY"])
            for absent_year, absent_priority, absent_geometry in blockers:
                if (absent_year, absent_priority) >= (current_year, current_priority):
                    fragment = fragment.difference(absent_geometry)
            patch_area = float(fragment.area)
            if fragment.is_empty or patch_area <= 0:
                continue
            fragments.append(fragment)
        if not fragments:
            continue
        local_union = union_all(np.asarray(fragments, dtype=object))
        resolved_geometries[str(cell)] = local_union
        polygon_parts = []
        pending = [local_union]
        while pending:
            geometry = pending.pop()
            if geometry.geom_type == "Polygon":
                if geometry.area > 0:
                    polygon_parts.append(geometry)
            elif hasattr(geometry, "geoms"):
                pending.extend(geometry.geoms)
        if not polygon_parts:
            continue
        output.loc[str(cell), "HABITAT_AREA_M2"] = float(area(local_union))
        # The H3 clip is a reporting boundary, not evidence of habitat edge.
        measured_boundary = difference(local_union.boundary, cell_geometry.boundary)
        output.loc[str(cell), "EDGE_LENGTH_M"] = float(length(measured_boundary))
        if local_union.boundary.intersects(cell_geometry.boundary):
            output.loc[str(cell), "TOPOLOGY_QC_REASON"] = "reporting_boundary_truncated"
        else:
            output.loc[str(cell), "TOPOLOGY_QC_REASON"] = None
        output.loc[str(cell), "PATCH_COUNT"] = len(polygon_parts)
        output.loc[str(cell), "LARGEST_PATCH_AREA_M2"] = max(
            float(geometry.area) for geometry in polygon_parts
        )
    water_area = support.set_index("H3_INDEX")["WATER_AREA_M2"].astype("float64")
    output["HABITAT_AREA_M2"] = np.minimum(output["HABITAT_AREA_M2"], water_area)
    return (
        (output.reset_index(), resolved_geometries)
        if return_geometries
        else output.reset_index()
    )


def habitat_topology_for_support(
    cells: Any, inventory: Any, equal_area_crs: str
) -> pd.DataFrame:
    """Recompute bounded patch geometry for each reporting support independently."""

    projected_cells, projected_inventory, pairs = _spatial_pairs(
        cells, inventory, equal_area_crs
    )
    support = pd.DataFrame(
        {
            "H3_INDEX": projected_cells["H3_INDEX"].astype("string"),
            "WATER_AREA_M2": projected_cells.geometry.area.to_numpy(),
        }
    )
    return _composition_metrics(projected_cells, projected_inventory, pairs, support)


def _record_metrics(
    inventory: Any,
    pairs: pd.DataFrame,
    target_cells: list[str],
    reference_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame, set[str]]:
    pair_records = pairs.merge(
        inventory.drop(columns="geometry"),
        left_on="index_right",
        right_index=True,
        how="left",
        validate="many_to_one",
    )
    mapped = pair_records.loc[
        pair_records["OBSERVATION_STATUS"].eq("present")
        & pair_records["COMPOSITION_ELIGIBLE"].astype(bool)
    ].copy()
    observed = pair_records.loc[
        pair_records["OBSERVED_VS_MODELED"].eq("observed")
        & pair_records["OBSERVATION_STATUS"].isin(["present", "absent"])
    ].copy()
    complete_footprints = pair_records.loc[
        pair_records["GEOMETRY_ROLE"].eq("survey_footprint")
        & pair_records["SURVEY_COMPLETENESS"].eq("complete")
    ]
    feature_rows: list[dict[str, Any]] = []
    confidence_rows: list[dict[str, Any]] = []
    observed["H3_INDEX"] = observed["H3_INDEX"].astype(str)
    mapped["H3_INDEX"] = mapped["H3_INDEX"].astype(str)
    by_cell = {
        str(cell): rows for cell, rows in observed.groupby("H3_INDEX", sort=False)
    }
    mapped_by_cell = {
        str(cell): rows for cell, rows in mapped.groupby("H3_INDEX", sort=False)
    }
    footprints_by_cell = {
        str(cell): rows
        for cell, rows in complete_footprints.groupby("H3_INDEX", sort=False)
    }
    present_cells = set(
        mapped.loc[mapped["OBSERVATION_STATUS"].eq("present"), "H3_INDEX"].astype(str)
    )
    for cell in target_cells:
        rows = by_cell.get(cell)
        mapped_rows = mapped_by_cell.get(cell)
        if rows is None:
            rows = observed.iloc[0:0]
        if mapped_rows is None:
            mapped_rows = mapped.iloc[0:0]
        if rows.empty:
            feature_rows.append(
                {
                    "H3_INDEX": cell,
                    "FIRST_YEAR": pd.NA,
                    "LAST_YEAR": pd.NA,
                    "YEARS_OBSERVED": 0,
                    "YEARS_SURVEYED": 0,
                    "PERSISTENCE_RATIO": np.nan,
                    "PERSISTENCE_BASIS": None,
                    "RECENT_5YR_PRESENCE": False,
                    "RECENCY_YEARS": np.nan,
                    "OBSERVED_PRESENCE": False,
                    "OBSERVED_ABSENCE": False,
                    "UNSURVEYED": True,
                }
            )
        else:
            years = sorted({int(value) for value in rows["OBSERVATION_YEAR"].dropna()})
            observed_years = sorted(
                {
                    int(value)
                    for value in rows.loc[
                        rows["OBSERVATION_STATUS"].eq("present"), "OBSERVATION_YEAR"
                    ].dropna()
                }
            )
            latest_year = max(years) if years else None
            latest = (
                rows.loc[rows["OBSERVATION_YEAR"].eq(latest_year)] if years else rows
            )
            has_present = bool(latest["OBSERVATION_STATUS"].eq("present").any())
            has_absent = bool(
                not has_present and latest["OBSERVATION_STATUS"].eq("absent").any()
            )
            first_year = min(years) if years else pd.NA
            last_year = max(years) if years else pd.NA
            footprint_rows = footprints_by_cell.get(cell)
            years_surveyed = (
                footprint_rows["OBSERVATION_YEAR"].dropna().nunique()
                if footprint_rows is not None
                else 0
            )
            years_observed = len(observed_years)
            has_explicit_dated_absence = bool(
                (
                    rows["OBSERVATION_STATUS"].eq("absent")
                    & rows["OBSERVATION_YEAR"].notna()
                ).any()
            )
            source_persistence = rows["SOURCE_PERSISTENCE_RATIO"].dropna()
            if years_surveyed and has_explicit_dated_absence:
                persistence = years_observed / years_surveyed
                persistence_basis = "surveyed_years"
            elif not source_persistence.empty:
                persistence = float(source_persistence.max())
                persistence_basis = "mapped_binned_proportion_midpoint"
            else:
                persistence = np.nan
                persistence_basis = None
            recent = bool(
                any(
                    reference_year - 4 <= year <= reference_year
                    for year in observed_years
                )
            )
            recency = reference_year - max(observed_years) if observed_years else np.nan
            feature_rows.append(
                {
                    "H3_INDEX": cell,
                    "FIRST_YEAR": first_year,
                    "LAST_YEAR": last_year,
                    "YEARS_OBSERVED": years_observed,
                    "YEARS_SURVEYED": years_surveyed,
                    "PERSISTENCE_RATIO": persistence,
                    "PERSISTENCE_BASIS": persistence_basis,
                    "RECENT_5YR_PRESENCE": recent,
                    "RECENCY_YEARS": recency,
                    "OBSERVED_PRESENCE": has_present,
                    "OBSERVED_ABSENCE": has_absent,
                    "UNSURVEYED": not (has_present or has_absent),
                }
            )
        metadata_rows = mapped_rows if not mapped_rows.empty else rows
        metadata_years = sorted(
            {int(value) for value in metadata_rows["OBSERVATION_YEAR"].dropna()}
        )
        sources = sorted(set(metadata_rows["SOURCE_DATASET"].dropna().astype(str)))
        methods = sorted(set(metadata_rows["SURVEY_METHOD"].dropna().astype(str)))
        spatial = sorted(
            set(metadata_rows["SPATIAL_PRECISION_CLASS"].dropna().astype(str))
        )
        temporal = sorted(
            set(metadata_rows["TEMPORAL_PRECISION_CLASS"].dropna().astype(str))
        )
        evidence_modes = sorted(
            set(metadata_rows["OBSERVED_VS_MODELED"].dropna().astype(str))
        )
        confidence_rows.append(
            {
                "H3_INDEX": cell,
                "SOURCE_DATASETS": "|".join(sources) or None,
                "SOURCE_COUNT": len(sources),
                "LATEST_SURVEY_YEAR": max(metadata_years) if metadata_years else pd.NA,
                "SURVEY_METHOD": "|".join(methods) or None,
                "SPATIAL_PRECISION_CLASS": "|".join(spatial) or None,
                "TEMPORAL_PRECISION_CLASS": "|".join(temporal) or None,
                "OBSERVED_VS_MODELED": "|".join(evidence_modes) or None,
                "CONFIDENCE": (
                    int(metadata_rows["CONFIDENCE_CLASS"].max())
                    if not metadata_rows.empty
                    else 0
                ),
            }
        )
    features = pd.DataFrame(feature_rows)
    confidence = pd.DataFrame(confidence_rows)
    for column in ("FIRST_YEAR", "LAST_YEAR", "LATEST_SURVEY_YEAR"):
        target = features if column in features else confidence
        target[column] = pd.to_numeric(target[column], errors="coerce").astype("Int16")
    return features, confidence, present_cells


def _surveyed_fraction(
    cells: Any,
    inventory: Any,
    pairs: pd.DataFrame,
    support: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    survey = inventory.loc[
        inventory["GEOMETRY_ROLE"].eq("survey_footprint")
        & inventory["SURVEY_COMPLETENESS"].eq("complete")
        & inventory["OBSERVED_VS_MODELED"].eq("observed")
        & inventory.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    if survey.empty:
        return (
            np.full(len(cells), np.nan, dtype="float64"),
            np.full(len(cells), "unknown", dtype=object),
            np.full(len(cells), None, dtype=object),
        )
    surveyed_area = np.full(len(cells), np.nan, dtype="float64")
    survey_years = np.full(len(cells), None, dtype=object)
    selected_pairs = pairs.loc[pairs["index_right"].isin(set(survey.index))]
    cell_positions = {
        str(cell): index for index, cell in enumerate(cells["H3_INDEX"].astype(str))
    }
    for cell, cell_pairs in selected_pairs.groupby("H3_INDEX", sort=False):
        cell_position = cell_positions[str(cell)]
        cell_geometry = cells.geometry.iloc[cell_position]
        fragments = [
            cell_geometry.intersection(inventory.geometry.iloc[int(record_index)])
            for record_index in cell_pairs["index_right"]
        ]
        fragments = [fragment for fragment in fragments if not fragment.is_empty]
        if fragments:
            surveyed_area[cell_position] = float(
                area(union_all(np.asarray(fragments, dtype=object)))
            )
            survey_years[cell_position] = "|".join(
                str(value)
                for value in sorted(
                    set(
                        inventory.iloc[cell_pairs["index_right"].astype(int)][
                            "OBSERVATION_YEAR"
                        ]
                        .dropna()
                        .astype(int)
                    )
                )
            )
    denominator = support["WATER_AREA_M2"].to_numpy(dtype="float64")
    fraction = np.clip(
        np.divide(
            surveyed_area,
            denominator,
            out=np.full_like(surveyed_area, np.nan),
            where=(denominator > 0) & np.isfinite(surveyed_area),
        ),
        0.0,
        1.0,
    )
    status = np.asarray(
        [
            "unknown"
            if not np.isfinite(value)
            else "spatiotemporal_mosaic"
            if value >= 1.0 - 1e-9 and years and "|" in years
            else "partial_spatiotemporal_mosaic"
            if years and "|" in years
            else "complete"
            if value >= 1.0 - 1e-9
            else "partial"
            for value, years in zip(fraction, survey_years, strict=True)
        ],
        dtype=object,
    )
    return fraction, status, survey_years


def _observation_area_metrics(
    cells: Any,
    inventory: Any,
    pairs: pd.DataFrame,
    support: pd.DataFrame,
) -> pd.DataFrame:
    """Latest applicable observed polygon evidence per location, with unknown area."""

    indexed_pairs = {
        str(cell): rows["index_right"].astype(int).tolist()
        for cell, rows in pairs.groupby("H3_INDEX", sort=False)
    }
    geometry_by_cell = dict(
        zip(cells["H3_INDEX"].astype(str), cells.geometry, strict=True)
    )
    output: list[dict[str, Any]] = []
    for cell, water_area in zip(
        support["H3_INDEX"].astype(str),
        support["WATER_AREA_M2"].astype(float),
        strict=True,
    ):
        cell_geometry = geometry_by_cell[cell]
        records = inventory.iloc[indexed_pairs.get(cell, [])]
        records = records.loc[
            records["GEOMETRY_ROLE"].eq("observation")
            & records["OBSERVED_VS_MODELED"].eq("observed")
            & records["OBSERVATION_STATUS"].isin(["present", "absent"])
        ]
        point_or_line_presence = bool(
            (
                records["OBSERVATION_STATUS"].eq("present")
                & ~records.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            ).any()
        )
        polygons = records.loc[
            records.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        ].copy()
        footprints = inventory.iloc[indexed_pairs.get(cell, [])]
        footprints = footprints.loc[
            footprints["GEOMETRY_ROLE"].eq("survey_footprint")
            & footprints["SURVEY_COMPLETENESS"].eq("complete")
        ]
        inferred_absence: list[dict[str, Any]] = []
        for footprint in footprints.itertuples():
            surveyed = _footprint_absence_geometry(footprint, records)
            if surveyed.is_empty or surveyed.area <= 0:
                continue
            inferred_absence.append(
                {
                    "RECORD_ID": f"{footprint.RECORD_ID}:inferred_absence",
                    "OBSERVATION_YEAR": footprint.OBSERVATION_YEAR,
                    "SOURCE_PRIORITY": footprint.SOURCE_PRIORITY,
                    "OBSERVATION_STATUS": "absent",
                    "geometry": surveyed,
                }
            )
        if inferred_absence:
            polygons = pd.concat(
                [polygons, pd.DataFrame(inferred_absence)], ignore_index=True
            )
        polygons["_YEAR"] = polygons["OBSERVATION_YEAR"].fillna(-32768).astype(int)
        # Equal-year/equal-priority contradictory records resolve conservatively
        # to absence, matching the composition blocker ordering.
        polygons["_STATUS_PRIORITY"] = (
            polygons["OBSERVATION_STATUS"].eq("absent").astype(int)
        )
        polygons = polygons.sort_values(
            ["_YEAR", "SOURCE_PRIORITY", "_STATUS_PRIORITY", "RECORD_ID"],
            ascending=[False, False, False, True],
        )
        remaining = cell_geometry
        present_area = 0.0
        absent_area = 0.0
        for record in polygons.itertuples():
            part = remaining.intersection(record.geometry)
            if part.is_empty or part.area <= 0:
                continue
            if record.OBSERVATION_STATUS == "present":
                present_area += float(part.area)
            else:
                absent_area += float(part.area)
            remaining = remaining.difference(record.geometry)
        denominator = water_area if water_area > 0 else float(cell_geometry.area)
        present = min(1.0, present_area / denominator) if denominator > 0 else np.nan
        absent = (
            min(1.0 - present, absent_area / denominator) if denominator > 0 else np.nan
        )
        unknown = max(0.0, 1.0 - present - absent) if denominator > 0 else np.nan
        if present > 0 and absent > 0:
            state = "mixed_partial"
        elif present > 0:
            state = "present" if unknown <= 1e-9 else "partial_present"
        elif absent > 0:
            state = "absent" if unknown <= 1e-9 else "partial_absent"
        elif point_or_line_presence:
            state = "point_or_line_presence"
        else:
            state = "unknown"
        output.append(
            {
                "H3_INDEX": cell,
                "PRESENT_AREA_FRAC": present,
                "ABSENT_AREA_FRAC": absent,
                "UNKNOWN_AREA_FRAC": unknown,
                "OBSERVATION_STATE": state,
                "OBSERVED_PRESENCE": bool(present > 0 or point_or_line_presence),
                "OBSERVED_ABSENCE": state == "absent",
                "UNSURVEYED": state == "unknown",
            }
        )
    return pd.DataFrame(output).set_index("H3_INDEX")


def habitat_network_metrics(
    graph: WaterGraph,
    target_cells: list[str],
    present_cells: set[str],
    area_by_cell: pd.Series,
    radius_operator: RadiusSumOperator | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Shared producer calculation of mapped habitat reachability and radius area.

    This is a toolkit-internal habitat operation, not a downstream consumer API.
    """
    if not present_cells:
        return (
            np.full(len(target_cells), np.nan, dtype="float64"),
            np.zeros(len(target_cells), dtype="float64"),
            np.full(len(target_cells), "no_mapped_habitat_source", dtype=object),
        )
    ordered_sources = sorted(present_cells)
    source_positions, source_connectors, source_reasons = target_graph_mapping(
        graph, ordered_sources
    )
    dijkstra_sources: list[tuple[str, float, int]] = []
    for owner, (position, connector) in enumerate(
        zip(source_positions, source_connectors, strict=True)
    ):
        if position >= 0 and np.isfinite(connector):
            dijkstra_sources.append(
                (str(graph.cells[int(position)]), float(connector), owner)
            )
    target_positions, target_connectors, target_reasons = target_graph_mapping(
        graph, target_cells
    )
    distance = np.full(len(target_cells), np.nan, dtype="float64")
    qc = np.empty(len(target_cells), dtype=object)
    if dijkstra_sources:
        graph_distances, _owners = multi_source_shortest_paths(graph, dijkstra_sources)
        for index, (position, connector, reason) in enumerate(
            zip(target_positions, target_connectors, target_reasons, strict=True)
        ):
            if position < 0 or not np.isfinite(connector):
                qc[index] = (
                    str(reason)
                    if reason is not None and not pd.isna(reason) and str(reason)
                    else "target_has_no_graph_mapping"
                )
                continue
            graph_value = float(graph_distances[int(position)])
            if not np.isfinite(graph_value):
                qc[index] = "no_mapped_habitat_in_water_component"
                continue
            distance[index] = graph_value + float(connector)
            qc[index] = reason
    else:
        source_reason = next(
            (
                str(value)
                for value in source_reasons
                if value is not None and not pd.isna(value) and str(value)
            ),
            "no_graph_attached_source",
        )
        for index, reason in enumerate(target_reasons):
            qc[index] = (
                str(reason)
                if reason is not None and not pd.isna(reason) and str(reason)
                else source_reason
            )
    source_lookup = {cell: index for index, cell in enumerate(target_cells)}
    for cell in present_cells:
        position = source_lookup.get(cell)
        if position is not None:
            distance[position] = 0.0
    if radius_operator is None:
        radius_sum = np.zeros(len(target_cells), dtype="float64")
    else:
        if radius_operator.cells.astype(str).tolist() != target_cells:
            raise ValueError(
                "Radius operator and habitat target support order disagree."
            )
        area_values = area_by_cell.reindex(target_cells).to_numpy(dtype="float64")
        eligible = np.isfinite(area_values) & (area_values > 0)
        radius_sum = radius_operator.apply(area_values, eligible_sources=eligible)
    return distance, radius_sum, qc


def _prefixed(frame: pd.DataFrame, prefix: str, keep: set[str]) -> pd.DataFrame:
    return frame.rename(
        columns={
            column: f"{prefix}_{column}"
            for column in frame.columns
            if column not in keep
        }
    )


def build_r8_tables(
    inventory: Any,
    support: pd.DataFrame,
    cells: Any,
    graph: WaterGraph,
    radius_operator: RadiusSumOperator,
    *,
    prefix: str,
    equal_area_crs: str,
    reference_year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the native H3 r8 feature and confidence tables."""

    inventory = normalize_inventory(inventory)
    inventory = inventory.loc[
        (
            inventory["OBSERVATION_END_YEAR"].isna()
            | inventory["OBSERVATION_END_YEAR"].le(reference_year)
        )
        & (
            inventory["AVAILABLE_YEAR"].isna()
            | inventory["AVAILABLE_YEAR"].le(reference_year)
        )
    ].reset_index(drop=True)
    target_cells = support["H3_INDEX"].astype(str).tolist()
    cells_projected, inventory_projected, pairs = _spatial_pairs(
        cells, inventory, equal_area_crs
    )
    composition = _composition_metrics(
        cells_projected, inventory_projected, pairs, support
    ).set_index("H3_INDEX")
    records, confidence, present_cells = _record_metrics(
        inventory_projected, pairs, target_cells, reference_year
    )
    records = records.set_index("H3_INDEX")
    confidence = confidence.set_index("H3_INDEX")
    area_evidence = _observation_area_metrics(
        cells_projected, inventory_projected, pairs, support
    )
    for column in area_evidence:
        records[column] = area_evidence.loc[target_cells, column].to_numpy()
    surveyed_fraction, survey_status, survey_years = _surveyed_fraction(
        cells_projected, inventory_projected, pairs, support
    )
    confidence["SURVEYED_AREA_FRAC"] = surveyed_fraction
    confidence["SURVEY_COMPLETENESS_STATUS"] = survey_status
    confidence["SURVEY_OBSERVATION_YEARS"] = survey_years
    confidence["UNMAPPED_AREA"] = np.isnan(surveyed_fraction) | (
        surveyed_fraction < 1.0 - 1e-9
    )

    area = composition["HABITAT_AREA_M2"].astype("float64")
    distance, within_radius, distance_qc = habitat_network_metrics(
        graph, target_cells, present_cells, area, radius_operator
    )
    water_area = support.set_index("H3_INDEX")["WATER_AREA_M2"].astype("float64")
    fraction = np.divide(
        area.to_numpy(),
        water_area.to_numpy(),
        out=np.zeros(len(area), dtype="float64"),
        where=water_area.to_numpy() > 0,
    )
    edge_density = np.divide(
        composition["EDGE_LENGTH_M"].to_numpy(),
        water_area.to_numpy() / 1_000_000.0,
        out=np.zeros(len(area), dtype="float64"),
        where=water_area.to_numpy() > 0,
    )
    patch_count = composition["PATCH_COUNT"].to_numpy(dtype="int32")
    habitat_area = area.to_numpy(dtype="float64")
    mean_patch_area = np.divide(
        habitat_area,
        patch_count,
        out=np.zeros_like(habitat_area),
        where=patch_count > 0,
    )
    fragmentation = np.divide(
        composition["LARGEST_PATCH_AREA_M2"].to_numpy(dtype="float64"),
        habitat_area,
        out=np.full_like(habitat_area, np.nan),
        where=habitat_area > 0,
    )
    fragmentation = np.clip(1.0 - fragmentation, 0.0, 1.0)
    lineage = support.set_index("H3_INDEX").loc[target_cells]
    features = pd.DataFrame(
        {
            "H3_INDEX": target_cells,
            "H3_RESOLUTION": 8,
            "AREA_M2": area.to_numpy(),
            "FRAC": fraction,
            "MAX_LOCAL_FRAC": fraction,
            "DISTANCE_M": distance,
            "AREA_WITHIN_5KM_M2": within_radius,
            "OCCUPIED_CHILD_COUNT": (habitat_area > 0).astype("int8"),
            "PATCH_COUNT": patch_count,
            "LARGEST_PATCH_AREA_M2": composition["LARGEST_PATCH_AREA_M2"].to_numpy(),
            "MEAN_PATCH_AREA_M2": mean_patch_area,
            "EDGE_LENGTH_M": composition["EDGE_LENGTH_M"].to_numpy(),
            "EDGE_DENSITY_M_PER_KM2": edge_density,
            "FRAGMENTATION_INDEX": fragmentation,
            "FRAGMENTATION_QC_REASON": np.where(
                habitat_area > 0, None, "no_mapped_patch"
            ),
            "TOPOLOGY_QC_REASON": composition["TOPOLOGY_QC_REASON"].to_numpy(),
            **{column: records[column].to_numpy() for column in records.columns},
            "WATER_COMPONENT_ID": lineage["WATER_COMPONENT_ID"].to_numpy(),
            "NETWORK_CONNECTOR_METHOD": lineage["CONNECTOR_METHOD"].to_numpy(),
            "NETWORK_CONNECTOR_DISTANCE_M": lineage["CONNECTOR_DISTANCE_M"].to_numpy(),
            "NETWORK_DISTANCE_QC_REASON": distance_qc,
        }
    )
    confidence = confidence.reset_index()
    confidence.insert(1, "H3_RESOLUTION", 8)
    features = _prefixed(
        features,
        prefix,
        {
            "H3_INDEX",
            "H3_RESOLUTION",
            "WATER_COMPONENT_ID",
            "NETWORK_CONNECTOR_METHOD",
            "NETWORK_CONNECTOR_DISTANCE_M",
            "NETWORK_DISTANCE_QC_REASON",
        },
    )
    confidence = _prefixed(confidence, prefix, {"H3_INDEX", "H3_RESOLUTION"})
    validate_surface_tables(features, confidence, prefix, 8)
    return features, confidence


__all__ = ["build_r8_tables"]
