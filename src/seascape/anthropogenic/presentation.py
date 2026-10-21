"""Public Anthropogenic picker policy; all source arrays remain available internally."""

import json

import pyarrow as pa
import pyarrow.compute as pc

RETIRED_PICKER_FIELDS = (
    "COMPREHENSIVE_SURVEY_COVERAGE_ESTABLISHED",
    "FULL_H3_WITHIN_SOURCE_RECTANGLE",
    "GENERALIZED_FALLBACK",
    "GLOBAL_INVENTORY_COMPLETE",
    "NATIVE_LAND_FOOTPRINT_UNKNOWN",
    "NETWORK_DISTANCE_QC_REASON",
    "OBSERVATION_PERIOD",
    "OVERWATER_QC",
    "POLICY_EDGE_REVIEW",
    "SOURCE_COVERAGE",
    "AQUACULTURE_MAPPED_AREA_M2",
    "AQUACULTURE_POSITIVE_MAPPED_WATER_FRAC",
    "ARMORING_AVAILABILITY_DISAGREEMENT_LENGTH_M",
    "ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE",
    "DISPOSAL_SITE_POSITIVE_MAPPED_WATER_FRAC",
    "MAPPED_WATER_AREA_M2",
    "MAPPED_WATER_SHARE_OF_FULL_CELL",
    "PROJECTED_PRECISION_NORMALIZATION_TILE_BOUNDS_INTERSECT_CELL",
)
PRESENCE_LABELS = {
    "AQUACULTURE_MAPPED_POSITIVE_EVIDENCE": "Aquaculture",
    "ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE": "Artificial Reef",
    "DISPOSAL_SITE_MAPPED_POSITIVE_EVIDENCE": "Disposal Site",
    "DREDGED_CHANNEL_MAPPED_POSITIVE_EVIDENCE": "Dredged Channel",
}
PRESENCE_DEFINITIONS = {
    "Aquaculture": "True means a qualified mapped aquaculture point intersects this native cell. This is mapped presence, not footprint area, activity or regulatory growing-area classification.",
    "Artificial Reef": "True means mapped artificial-reef inventory evidence intersects this native cell. It does not establish present activity or comprehensive reef coverage.",
    "Dredged Channel": "True means positive mapped dredged-channel polygon area in this native cell, qualified by positive_mapped_polygon_inventory QC. It does not establish current dredging activity.",
    "Disposal Site": "True means positive mapped disposal-site polygon area in this native cell, qualified by positive_mapped_polygon_inventory QC. It does not establish current disposal activity.",
}
UNKNOWN_DEFINITION = " False means no mapped positive evidence, including unknown values filled False by the requested public-display policy. False does not establish ecological or physical absence. Original nullable evidence and source coverage/QC are retained internally."


def anthropogenic_presentation(table: pa.Table) -> pa.Table:
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(b"seascape_domain", b"{}"))
    for source in list(table.column_names):
        native_source = source.rsplit("__", 1)[-1]
        if native_source in {
            "DISPOSAL_SITE_MAPPED_AREA_M2",
            "DREDGED_CHANNEL_MAPPED_AREA_M2",
        }:
            group = native_source.removesuffix("_MAPPED_AREA_M2")
            prefix = source[: -len(native_source)]
            target = prefix + group + "_MAPPED_POSITIVE_EVIDENCE"
            qc_column = prefix + group + "_AREA_QC"
            if target not in table.column_names:
                if qc_column not in table.column_names:
                    raise ValueError(
                        "Mapped polygon presence requires linked polygon QC"
                    )
                values = []
                for area, qc in zip(
                    table[source].to_pylist(), table[qc_column].to_pylist(), strict=True
                ):
                    if area is not None and area < 0:
                        raise ValueError("Mapped polygon area cannot be negative")
                    values.append(
                        True
                        if area is not None
                        and area > 0
                        and qc == "positive_mapped_polygon_inventory"
                        else None
                    )
                table = table.append_column(target, pa.array(values, type=pa.bool_()))
                context.setdefault("fields", {})[target] = {
                    "derived_from": [source, qc_column],
                    "role": "source_field",
                    "qualifiers": [source, qc_column],
                    "unit": "boolean",
                }
    for column in table.column_names:
        native = column.rsplit("__", 1)[-1]
        if native in PRESENCE_LABELS:
            if not pa.types.is_boolean(table[column].type):
                raise ValueError("Mapped presence must remain a nullable boolean")
            original_column = column + "_SOURCE_NULLABLE"
            if original_column not in table.column_names:
                table = table.append_column(original_column, table[column])
            table = table.set_column(
                table.schema.get_field_index(column),
                column,
                pc.fill_null(table[original_column], False),
            )
            context.setdefault("fields", {})[original_column] = {
                "picker_visible": False,
                "role": "source_quality_or_context",
                "definition": "Original nullable mapped evidence before public unknown-to-False policy.",
            }
            label = PRESENCE_LABELS[native]
            update = {
                "picker_visible": True,
                "common_name": label,
                "definition": PRESENCE_DEFINITIONS[label] + UNKNOWN_DEFINITION,
                "family": "Anthropogenic",
                "public_missing_value_policy": "unknown_filled_false_not_confirmed_absence",
                "nullable_source_column": original_column,
            }
        elif native in RETIRED_PICKER_FIELDS or any(
            group in native
            for group in (
                "AQUACULTURE",
                "ARTIFICIAL_REEF",
                "DISPOSAL_SITE",
                "DREDGED_CHANNEL",
            )
        ):
            update = {"picker_visible": False}
        else:
            continue
        entry = context.setdefault("fields", {}).setdefault(column, {})
        entry.update(update)
        for key, value in entry.items():
            if key.isdigit() and isinstance(value, dict):
                value.update(update)
    metadata[b"seascape_domain"] = json.dumps(context, sort_keys=True).encode()
    return table.replace_schema_metadata(metadata)
