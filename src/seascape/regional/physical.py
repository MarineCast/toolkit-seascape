"""Reviewed direct physical leaves and annual mapped kelp evidence."""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from seascape.anthropogenic.armoring import dataset_estimates, maximum_estimate

from .contract import RegionalError
from .geometry import cells, inventory, projected


def anthropogenic(job):
    from seascape.anthropogenic.build import DISTANCE_FEATURES

    keys = job.keys()
    source = inventory(job)
    required = (
        "FEATURE_CLASS",
        "IS_CANONICAL",
        "SUPPORTS_AREA",
        "SUPPORTS_SHORELINE_DENOMINATOR",
        "ARMORING_FRACTION_ESTIMATE",
        "SOURCE_DATASET",
    )
    if any(name not in source for name in required):
        raise RegionalError("Normalized physical inventory required")
    projected_inventory, inv_evidence = projected(job, crs=6933)
    all_geoms = projected_inventory.geometry.to_numpy()
    tree = shapely.STRtree(all_geoms)
    water_geoms, water_evidence = projected(job, "water", crs=6933, subdivide=True)
    water_tree = shapely.STRtree(water_geoms)
    class_values = source.FEATURE_CLASS.to_numpy()
    canonical_values = source.IS_CANONICAL.to_numpy()
    area_values = source.SUPPORTS_AREA.to_numpy()
    denominator_values = source.SUPPORTS_SHORELINE_DENOMINATOR.to_numpy()
    fraction_values = source.ARMORING_FRACTION_ESTIMATE.to_numpy(
        dtype=float, na_value=np.nan
    )
    datasets = source.SOURCE_DATASET.to_numpy()
    resolution = job.resolution
    writer = None
    try:
        for first in range(0, len(keys), min(1024, job.limits["batch_rows"])):
            selected = keys[first : first + min(1024, job.limits["batch_rows"])]
            geometries = cells(selected).to_crs(6933).geometry
            rows = []
            for cell, geometry in zip(selected, geometries, strict=True):
                ids = tree.query(geometry, predicate="intersects")
                pieces = {
                    int(i): shapely.intersection(geometry, all_geoms[i]) for i in ids
                }
                wids = water_tree.query(geometry, predicate="intersects")
                wet = shapely.union_all(
                    shapely.intersection(water_geoms[wids], geometry)
                )
                wet_area = wet.area
                row = {
                    "H3_INDEX": cell,
                    "H3_RESOLUTION": resolution,
                    "MAPPED_WATER_AREA_M2": wet_area,
                    "MAPPED_WATER_SHARE_OF_FULL_CELL": wet_area / geometry.area,
                    "SOURCE_COVERAGE": "partial_no_complete_survey_footprint",
                    "OBSERVATION_PERIOD": None,
                    "COMPREHENSIVE_SURVEY_COVERAGE_ESTABLISHED": False,
                    "MAPPED_INVENTORY_RECORD_INTERSECTION_COUNT": len(ids),
                    "MAPPED_SOURCE_DATASETS_JSON": json.dumps(
                        sorted(set(datasets[ids]))
                    ),
                    "NETWORK_DISTANCE_QC_REASON": "not_computed_source_attachment_and_seed_closure_unqualified",
                    "GLOBAL_INVENTORY_COMPLETE": False,
                }
                for column in DISTANCE_FEATURES:
                    row[column] = None
                row["OVERWATER_STRUCTURE_DENSITY_PER_KM2"] = None
                row["OVERWATER_STRUCTURE_COUNT_WITHIN_5KM"] = None
                row["OVERWATER_QC"] = (
                    "not_computed_reachable_radius_and_source_multiplicity_unqualified"
                )
                for cls in ["dredged_channel", "disposal_site", "aquaculture"]:
                    eligible = [
                        int(i)
                        for i in ids
                        if canonical_values[i]
                        and class_values[i] == cls
                        and area_values[i]
                    ]
                    covered = shapely.intersection(
                        shapely.union_all([pieces[i] for i in eligible]), wet
                    ).area
                    row[f"{cls.upper()}_MAPPED_AREA_M2"] = covered
                    row[f"{cls.upper()}_MAPPED_POSITIVE_EVIDENCE"] = (
                        True if covered > 0 else None
                    )
                    row[f"{cls.upper()}_POSITIVE_MAPPED_WATER_FRAC"] = (
                        covered / wet_area if covered > 0 and wet_area > 0 else None
                    )
                    row[f"{cls.upper()}_AREA_QC"] = (
                        "positive_mapped_polygon_inventory"
                        if covered > 0
                        else "no_positive_mapped_polygon_unknown_absence"
                    )
                # Canonical points/lines establish mapped evidence only, never area.
                for cls in ("aquaculture", "artificial_reef"):
                    positive = any(
                        canonical_values[i] and class_values[i] == cls for i in ids
                    )
                    row[f"{cls.upper()}_MAPPED_POSITIVE_EVIDENCE"] = (
                        True if positive else None
                    )
                    row[f"{cls.upper()}_PRESENCE_QC"] = (
                        "positive_inventory_intersection"
                        if positive
                        else "no_inventory_intersection_unknown_absence"
                    )
                known = [
                    int(i)
                    for i in ids
                    if denominator_values[i] and np.isfinite(fraction_values[i])
                ]
                groups = {}
                for i in known:
                    groups.setdefault(float(fraction_values[i]), []).append(pieces[i])
                unions = {f: shapely.union_all(gs) for f, gs in groups.items()}
                values = list(unions.values())
                denominator = shapely.union_all(values).length
                conflict = shapely.union_all(
                    [
                        a.intersection(b)
                        for pos, a in enumerate(values)
                        for b in values[pos + 1 :]
                    ]
                ).length
                unknown = [
                    int(i)
                    for i in ids
                    if class_values[i] == "shoreline_survey"
                    and not (denominator_values[i] and np.isfinite(fraction_values[i]))
                ]
                unknown_union = shapely.union_all([pieces[i] for i in unknown])
                known_union = shapely.union_all(values)
                availability_conflict = unknown_union.intersection(known_union).length
                estimates = dataset_estimates(
                    (pieces[i], fraction_values[i], datasets[i]) for i in known
                )
                selected_weighted, selected_surveyed, maximum_fraction = (
                    maximum_estimate(estimates)
                )
                row.update(
                    SYSTEMATIC_KNOWN_ARMORING_UNION_LENGTH_M=denominator,
                    SYSTEMATIC_UNKNOWN_ARMORING_UNION_LENGTH_M=unknown_union.length,
                    ARMORING_ESTIMATE_DISAGREEMENT_LENGTH_M=conflict,
                    ARMORING_AVAILABILITY_DISAGREEMENT_LENGTH_M=availability_conflict,
                    ARMORING_WEIGHTED_UNION_LENGTH_M=selected_weighted
                    if selected_surveyed > 0
                    else None,
                    SHORELINE_ARMORING_FRAC=maximum_fraction
                    if selected_surveyed > 0
                    else None,
                    ARMORING_QC="maximum_available_dataset_cell_fraction"
                    if estimates
                    else "no_known_systematic_length",
                )
                rows.append(row)
            table = pa.Table.from_pylist(rows)
            types = {column: pa.float64() for column in DISTANCE_FEATURES}
            types.update(
                {
                    column: pa.float64()
                    for column in table.column_names
                    if column.endswith(("_FRAC", "_LENGTH_M"))
                    or column.startswith("OVERWATER_STRUCTURE_")
                }
            )
            types.update(
                {
                    "OBSERVATION_PERIOD": pa.string(),
                    "AQUACULTURE_MAPPED_POSITIVE_EVIDENCE": pa.bool_(),
                    "ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE": pa.bool_(),
                    "DREDGED_CHANNEL_MAPPED_POSITIVE_EVIDENCE": pa.bool_(),
                    "DISPOSAL_SITE_MAPPED_POSITIVE_EVIDENCE": pa.bool_(),
                }
            )
            for column, typ in types.items():
                table = table.set_column(
                    table.schema.get_field_index(column),
                    column,
                    table[column].cast(typ),
                )
            if writer is None:
                writer = pq.ParquetWriter(
                    job.output / "metrics.parquet", table.schema, compression="zstd"
                )
            writer.write_table(table)
            job.guard()
    finally:
        if writer:
            writer.close()
    return "native_physical_anthropogenic_maximum_dataset_v4", {
        "rows": len(keys),
        "inventory_projection": inv_evidence,
        "water_projection_subdivision": water_evidence,
        "survey_absence_qualified": False,
        "network_metrics": "unqualified_null",
        "armoring_method": "maximum_available_dataset_cell_fraction_v1",
    }
