"""H3 r8 habitat processing and feature-aware aggregation to H3 r6."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from shapely import area, length, union_all

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


def _composition_metrics(
    cells: Any,
    inventory: Any,
    pairs: pd.DataFrame,
    support: pd.DataFrame,
) -> pd.DataFrame:
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
        }
    ).set_index("H3_INDEX")
    if composition.empty:
        return output.reset_index()
    if not composition["COVERAGE_WEIGHT"].eq(1.0).all():
        raise ValueError(
            "Composition-eligible polygons must use exact coverage weight 1. "
            "Fractional survey estimates belong in persistence/confidence fields."
        )
    composition_indices = set(composition.index)
    selected_pairs = pairs.loc[pairs["index_right"].isin(composition_indices)]
    cell_positions = {str(cell): index for index, cell in enumerate(cells["H3_INDEX"].astype(str))}
    for cell, cell_pairs in selected_pairs.groupby("H3_INDEX", sort=False):
        cell_position = cell_positions[str(cell)]
        cell_geometry = cells.geometry.iloc[cell_position]
        fragments = []
        for record_index in cell_pairs["index_right"]:
            fragment = cell_geometry.intersection(inventory.geometry.iloc[int(record_index)])
            patch_area = float(fragment.area)
            if fragment.is_empty or patch_area <= 0:
                continue
            fragments.append(fragment)
        if not fragments:
            continue
        local_union = union_all(np.asarray(fragments, dtype=object))
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
        output.loc[str(cell), "EDGE_LENGTH_M"] = float(length(local_union.boundary))
        output.loc[str(cell), "PATCH_COUNT"] = len(polygon_parts)
        output.loc[str(cell), "LARGEST_PATCH_AREA_M2"] = max(
            float(geometry.area) for geometry in polygon_parts
        )
    water_area = support.set_index("H3_INDEX")["WATER_AREA_M2"].astype("float64")
    output["HABITAT_AREA_M2"] = np.minimum(output["HABITAT_AREA_M2"], water_area)
    return output.reset_index()


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
    feature_rows: list[dict[str, Any]] = []
    confidence_rows: list[dict[str, Any]] = []
    observed["H3_INDEX"] = observed["H3_INDEX"].astype(str)
    mapped["H3_INDEX"] = mapped["H3_INDEX"].astype(str)
    by_cell = {str(cell): rows for cell, rows in observed.groupby("H3_INDEX", sort=False)}
    mapped_by_cell = {str(cell): rows for cell, rows in mapped.groupby("H3_INDEX", sort=False)}
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
            latest = rows.loc[rows["OBSERVATION_YEAR"].eq(latest_year)] if years else rows
            has_present = bool(latest["OBSERVATION_STATUS"].eq("present").any())
            has_absent = bool(not has_present and latest["OBSERVATION_STATUS"].eq("absent").any())
            first_year = min(years) if years else pd.NA
            last_year = max(years) if years else pd.NA
            years_surveyed = len(years)
            years_observed = len(observed_years)
            has_explicit_dated_absence = bool(
                (rows["OBSERVATION_STATUS"].eq("absent") & rows["OBSERVATION_YEAR"].notna()).any()
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
                any(reference_year - 4 <= year <= reference_year for year in observed_years)
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
        spatial = sorted(set(metadata_rows["SPATIAL_PRECISION_CLASS"].dropna().astype(str)))
        temporal = sorted(set(metadata_rows["TEMPORAL_PRECISION_CLASS"].dropna().astype(str)))
        evidence_modes = sorted(set(metadata_rows["OBSERVED_VS_MODELED"].dropna().astype(str)))
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
                    int(metadata_rows["CONFIDENCE_CLASS"].max()) if not metadata_rows.empty else 0
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
) -> np.ndarray:
    survey = inventory.loc[
        inventory["EVIDENCE_CLASS"].eq("direct_observation")
        & inventory["OBSERVED_VS_MODELED"].eq("observed")
        & inventory["OBSERVATION_STATUS"].isin(["present", "absent"])
        & inventory.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ]
    if survey.empty:
        return np.zeros(len(cells), dtype="float64")
    surveyed_area = np.zeros(len(cells), dtype="float64")
    selected_pairs = pairs.loc[pairs["index_right"].isin(set(survey.index))]
    cell_positions = {str(cell): index for index, cell in enumerate(cells["H3_INDEX"].astype(str))}
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
    denominator = support["WATER_AREA_M2"].to_numpy(dtype="float64")
    return np.clip(
        np.divide(
            surveyed_area,
            denominator,
            out=np.zeros_like(surveyed_area),
            where=denominator > 0,
        ),
        0.0,
        1.0,
    )


def _network_metrics(
    graph: WaterGraph,
    target_cells: list[str],
    present_cells: set[str],
    area_by_cell: pd.Series,
    radius_operator: RadiusSumOperator | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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
            dijkstra_sources.append((str(graph.cells[int(position)]), float(connector), owner))
    target_positions, target_connectors, target_reasons = target_graph_mapping(graph, target_cells)
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
            raise ValueError("Radius operator and habitat target support order disagree.")
        area_values = area_by_cell.reindex(target_cells).to_numpy(dtype="float64")
        eligible = np.isfinite(area_values) & (area_values > 0)
        radius_sum = radius_operator.apply(area_values, eligible_sources=eligible)
    return distance, radius_sum, qc


def _prefixed(frame: pd.DataFrame, prefix: str, keep: set[str]) -> pd.DataFrame:
    return frame.rename(
        columns={column: f"{prefix}_{column}" for column in frame.columns if column not in keep}
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
    target_cells = support["H3_INDEX"].astype(str).tolist()
    cells_projected, inventory_projected, pairs = _spatial_pairs(cells, inventory, equal_area_crs)
    composition = _composition_metrics(
        cells_projected, inventory_projected, pairs, support
    ).set_index("H3_INDEX")
    records, confidence, present_cells = _record_metrics(
        inventory_projected, pairs, target_cells, reference_year
    )
    records = records.set_index("H3_INDEX")
    confidence = confidence.set_index("H3_INDEX")
    surveyed_fraction = _surveyed_fraction(cells_projected, inventory_projected, pairs, support)
    confidence["SURVEYED_AREA_FRAC"] = surveyed_fraction
    confidence["UNMAPPED_AREA"] = surveyed_fraction < 1.0 - 1e-9

    area = composition["HABITAT_AREA_M2"].astype("float64")
    distance, within_radius, distance_qc = _network_metrics(
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
        out=np.zeros_like(habitat_area),
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
