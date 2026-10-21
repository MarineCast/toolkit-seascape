"""Product-column policy; native source validation and provenance remain intact."""

from __future__ import annotations

import copy
import json

import pyarrow as pa

SUBSTRATE_OMITTED_FIELDS = (
    "SOURCE_OBSERVATION_DATE_STATUS",
    "SEDIMENT_TEXTURE_STATUS",
    "SAND_POINT_SAMPLE_STATUS",
    "SAND_MASK_STATUS",
    "ROCK_POINT_SAMPLE_STATUS",
    "ROCK_MASK_STATUS",
    "POINT_SUPPORT_STATUS",
    "MUD_POINT_SAMPLE_STATUS",
    "MUD_MASK_STATUS",
    "H3_AREAL_SUBSTRATE_COVERAGE",
    "GRAVEL_POINT_SAMPLE_STATUS",
    "GRAVEL_MASK_STATUS",
    "UNSUPPORTED_PHYSICAL_METRICS_REASON",
    "SOURCE_OBSERVATION_PERIOD",
    "SOURCE_GRID_DEGREES",
)
SPATIAL_SUPPORT_OMITTED_FIELDS = (
    "GRAPH_QC_REASON",
    "GRAPH_CONNECTION_STATUS",
    "PARENT_H3_INDEX",
    "IS_HIERARCHY_ONLY_PARENT",
    "IS_AOI_BOUNDARY_CELL",
    "HAS_WATER_OVERLAP",
    "GRAPH_NODE_ELIGIBLE",
    "CONNECTOR_WATER_PATH_FRACTION",
    "CONNECTOR_TARGET_H3_INDEX",
    "CONNECTOR_DISTANCE_M",
)
_NATIVE_ALIASES = {"SUBSTRATE_SEDIMENT_TEXTURE_STATUS"}
_LINKS = {
    "qualifiers",
    "row_quality_and_coverage_columns",
    "source_observation_period_columns",
}


def project_delivery_table(area: str, table: pa.Table) -> pa.Table:
    """Omit reviewed public fields after validation, without changing arrays.

    Match exact native field names within their reviewed area. Native graph/support
    artifacts keep their full validated schema; only flat delivery is projected. The prefixed
    sediment-texture spelling is used by the current benthic producer; the other
    spelling is used by the retained SUBSTRATE_MODEL native source.
    """
    if area == "anthropogenic":
        from seascape.anthropogenic.presentation import anthropogenic_presentation

        return anthropogenic_presentation(table)
    if area not in {"substrate", "spatial-support"}:
        return table
    policy_fields = (
        {*SUBSTRATE_OMITTED_FIELDS, *_NATIVE_ALIASES}
        if area == "substrate"
        else set(SPATIAL_SUPPORT_OMITTED_FIELDS)
    )
    omitted = {
        name for name in table.column_names if name.rsplit("__", 1)[-1] in policy_fields
    }
    if not omitted:
        return table
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(b"seascape_domain", b"{}"))

    def trim_links(entry: dict) -> dict:
        entry = copy.deepcopy(entry)
        for key, value in entry.items():
            if key in _LINKS and isinstance(value, list):
                entry[key] = [name for name in value if name not in omitted]
            elif isinstance(value, dict) and key.isdigit():
                entry[key] = trim_links(value)
        return entry

    context["fields"] = {
        name: trim_links(entry)
        for name, entry in context.get("fields", {}).items()
        if name not in omitted
    }
    previous = context.get("delivery_projection", {}).get("omitted_columns", [])
    context["delivery_projection"] = {
        "policy": f"{area}-feature-projection-v1",
        "omitted_columns": sorted(set(previous) | omitted),
        "provenance": (
            "Source manifests, dictionaries and methods remain in source_context "
            "and retained native sources. Only prepared feature columns are omitted."
        ),
    }
    metadata[b"seascape_domain"] = json.dumps(context, sort_keys=True).encode()
    return table.select(
        [name for name in table.column_names if name not in omitted]
    ).replace_schema_metadata(metadata)
