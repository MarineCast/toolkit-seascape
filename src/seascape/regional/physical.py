"""Reviewed direct physical leaves and annual mapped kelp evidence."""

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

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
                weighted = sum(f * g.length for f, g in unions.items())
                unknown = [
                    int(i)
                    for i in ids
                    if class_values[i] == "shoreline_survey"
                    and not (denominator_values[i] and np.isfinite(fraction_values[i]))
                ]
                unknown_union = shapely.union_all([pieces[i] for i in unknown])
                known_union = shapely.union_all(values)
                availability_conflict = unknown_union.intersection(known_union).length
                row.update(
                    SYSTEMATIC_KNOWN_ARMORING_UNION_LENGTH_M=denominator,
                    SYSTEMATIC_UNKNOWN_ARMORING_UNION_LENGTH_M=unknown_union.length,
                    ARMORING_ESTIMATE_DISAGREEMENT_LENGTH_M=conflict,
                    ARMORING_AVAILABILITY_DISAGREEMENT_LENGTH_M=availability_conflict,
                    ARMORING_WEIGHTED_UNION_LENGTH_M=weighted
                    if conflict <= 1e-8
                    else None,
                    SHORELINE_ARMORING_FRAC=weighted / denominator
                    if denominator > 0 and conflict <= 1e-8
                    else None,
                    ARMORING_QC="conflicting_fraction_estimates_primary_null"
                    if conflict > 1e-8
                    else "no_known_systematic_length"
                    if denominator == 0
                    else "unique_length_fraction_estimates_source_relative",
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
    return "native_physical_anthropogenic_union_leaves_v3", {
        "rows": len(keys),
        "inventory_projection": inv_evidence,
        "water_projection_subdivision": water_evidence,
        "survey_absence_qualified": False,
        "network_metrics": "unqualified_null",
    }


def kelp(job):
    from seascape.biogenic_habitat.kelp.build import annual_spatial_processing

    keys = job.keys()
    layers = job.settings.get("annual_layers", [])
    if not layers or len({item["year"] for item in layers}) != len(layers):
        raise RegionalError("Explicit distinct annual source layers required")
    native_cells = cells(keys).to_crs(6933).geometry.to_numpy()
    water, evidence = projected(job, "water", crs=6933, subdivide=True)
    tree = shapely.STRtree(water)
    schema = pa.schema(
        [
            ("H3_INDEX", pa.string()),
            ("H3_RESOLUTION", pa.int64()),
            ("SOURCE_DATASET", pa.string()),
            ("OBSERVATION_YEAR", pa.int16()),
            ("MAPPED_BED_EXTENT_IN_FULL_H3_M2", pa.float64()),
            ("MAPPED_BED_EXTENT_IN_CURRENT_WATER_M2", pa.float64()),
            ("CURRENT_MAPPED_WATER_AREA_M2", pa.float64()),
            ("POSITIVE_MAPPED_BED_EXTENT_WATER_FRAC", pa.float64()),
            ("MAPPED_POSITIVE_BED_EVIDENCE", pa.bool_()),
            ("ANNUAL_SURVEY_ABSENCE", pa.bool_()),
            ("QC", pa.string()),
            ("SPATIAL_PROCESSING", pa.string()),
        ]
    )
    years = [[] for _ in keys]
    qualification = []
    with pq.ParquetWriter(
        job.output / "annual.parquet", schema, compression="zstd"
    ) as writer:
        for item in sorted(layers, key=lambda x: x["year"]):
            year = item["year"]
            if type(year) is not int or year == 1993 or not 1989 <= year <= 2024:
                raise RegionalError(
                    "Source year must match supported annual inventory; 1993 unsurveyed"
                )
            from .projection import qualify_projected_geometries

            native = inventory(
                job, item["input"], allow_invalid=True, layer=item.get("layer")
            )
            native_repairs = []
            factor = native.crs.axis_info[0].unit_conversion_factor
            for index in native.index[~native.geometry.is_valid]:
                original = native.geometry.loc[index]
                fixed = shapely.make_valid(original)
                delta = abs(fixed.area - original.area)
                if (
                    native.crs.is_geographic
                    or delta * factor * factor > 0.01
                    or delta / max(abs(original.area), 1) > 1e-10
                    or not fixed.is_valid
                ):
                    raise RegionalError(
                        "Annual native ring normalization exceeds reviewed precision guard"
                    )
                native_repairs.append(
                    {
                        "row": str(index),
                        "absolute_area_change_m2": delta * factor * factor,
                        "relative_area_change": delta / max(abs(original.area), 1),
                    }
                )
                native.loc[index, "geometry"] = fixed
            source = native.to_crs(6933)
            values, repairs = qualify_projected_geometries(
                native.geometry.to_numpy(), source.geometry.to_numpy()
            )
            source = source.set_geometry(values)
            proof = {
                "native_precision_normalization": native_repairs,
                "projected_precision_normalization": repairs,
            }
            year_column = item.get("year_column", "OBSERVATION_YEAR")
            if year_column != "OBSERVATION_YEAR" and year_column in source:
                source["OBSERVATION_YEAR"] = source[year_column]
            if (
                "OBSERVATION_YEAR" not in source
                or not source.OBSERVATION_YEAR.eq(year).all()
            ):
                raise RegionalError("Annual source observation year differs")
            source_parts = source.geometry.to_numpy()
            source_tree = shapely.STRtree(source_parts)
            qualification.append(
                {"year": year, "projection": proof, "source_rows": len(source)}
            )
            for first in range(0, len(keys), min(1024, job.limits["batch_rows"])):
                rows = []
                for i in range(
                    first, min(first + min(1024, job.limits["batch_rows"]), len(keys))
                ):
                    cell = native_cells[i]
                    hits = tree.query(cell, predicate="intersects")
                    wet = shapely.union_all(shapely.intersection(water[hits], cell))
                    if wet.area <= 0:
                        raise RegionalError(
                            "Mapped reporting water area must be positive"
                        )
                    ids = source_tree.query(cell, predicate="intersects")
                    # Centroid translation preserves EPSG6933 metre geometry while
                    # reducing cancellation in exact overlay, as in the reviewed caller.
                    origin = np.array([cell.centroid.x, cell.centroid.y])
                    local = lambda g: shapely.transform(g, lambda xy: xy - origin)
                    bed = shapely.union_all(
                        shapely.intersection(local(source_parts[ids]), local(cell))
                    )
                    area = bed.area
                    mapped = bed.intersection(local(wet)).area
                    reference = shapely.union_all(
                        [g.intersection(local(wet)) for g in local(source_parts[ids])]
                    ).area
                    if not np.isclose(mapped, reference, rtol=1e-9, atol=1e-5):
                        raise RegionalError("Kelp union/clip independent parity failed")
                    if area > 0:
                        years[i].append(year)
                    rows.append(
                        dict(
                            H3_INDEX=keys[i],
                            H3_RESOLUTION=job.resolution,
                            SOURCE_DATASET=item.get(
                                "source_dataset", f"WA_DNR_FLOATING_KELP_{year}"
                            ),
                            OBSERVATION_YEAR=year,
                            MAPPED_BED_EXTENT_IN_FULL_H3_M2=area,
                            MAPPED_BED_EXTENT_IN_CURRENT_WATER_M2=mapped,
                            CURRENT_MAPPED_WATER_AREA_M2=wet.area,
                            POSITIVE_MAPPED_BED_EXTENT_WATER_FRAC=mapped / wet.area
                            if mapped > 0
                            else None,
                            MAPPED_POSITIVE_BED_EVIDENCE=True if area > 0 else None,
                            ANNUAL_SURVEY_ABSENCE=None,
                            QC="positive_mapped_bed_extent_not_pure_canopy"
                            if area > 0
                            else "no_mapped_bed_record_unknown_survey_absence",
                            SPATIAL_PROCESSING=annual_spatial_processing(year),
                        )
                    )
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                job.guard()
    pq.write_table(
        pa.table(
            {
                "H3_INDEX": keys,
                "H3_RESOLUTION": [job.resolution] * len(keys),
                "YEARS_WITH_MAPPED_BED_INTERSECTION_JSON": [
                    json.dumps(v) for v in years
                ],
                "FIRST_MAPPED_POSITIVE_SURVEY_YEAR": pa.array(
                    [min(v) if v else None for v in years], type=pa.int16()
                ),
                "LAST_MAPPED_POSITIVE_SURVEY_YEAR": pa.array(
                    [max(v) if v else None for v in years], type=pa.int16()
                ),
                "STATIC_SUMMARY_SEMANTICS": [
                    "historical_positive_dates_no_forward_fill_or_persistence"
                ]
                * len(keys),
            }
        ),
        job.output / "static.parquet",
        compression="zstd",
    )
    return "annual_mapped_bed_extent_native_full_h3_current_water_v3", {
        "rows": len(keys) * len(layers),
        "annual_layers": qualification,
        "water_qualification": evidence,
        "generalized_persistence": "not_computed_source_blocked",
        "survey_absence_qualified": False,
        "pure_canopy_fraction_qualified": False,
    }
