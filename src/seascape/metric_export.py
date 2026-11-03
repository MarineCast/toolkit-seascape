"""Metric-only public projection, independent of historical audit outputs."""

from __future__ import annotations

import json
import re
from copy import deepcopy

import h3
import pyarrow as pa
import pyarrow.compute as pc

from seascape.reviewed_delivery import CORE_SCHEMAS

POLICY = b"seascape_metrics"
KEYS_FOR_PROJECTION = {"H3_INDEX", "H3_RESOLUTION", "date"}
# These are diagnostics, not measurements of the physical environment.
_DIAGNOSTIC = re.compile(
    r"(^|_)(COVERAGE|CENSORED|AUDIT|QC|STATUS|PROVENANCE|SOURCE|METHOD|CONFIDENCE|UNMAPPED|CONNECTOR|HIERARCHY|DISCONTINUITY|COUNT_VALID|VALID_COUNT|SAMPLE_COUNT|OBSERVATION_YEAR|OBSERVATION_DATE|PIXEL_COUNT|EVIDENCE_INCLUDED|GEOMETRY_INCLUDED|RECORD_COUNT|LATEST_SURVEY_YEAR|LATEST_ASSESSMENT_YEAR|YEARS_SURVEYED|YEARS_OBSERVED|FIRST_YEAR|LAST_YEAR|RECENCY_YEARS|VALID_NEIGHBOR|ASSESSED_SITE_COUNT)(_|$)",
    re.I,
)

# Existing public spellings outside the compact lower-case core families.
_NATIVE_LAYOUT = {"bathymetry", "freshwater", "seagrass", "kelp", "bivalve"}
_METRIC_ROLES = {"predictor", "state", "categorical"}
_ALIASES = {
    ("estuary", "DISTANCE_TO_QUALIFIED_NORMALIZED_MAPPED_ESTUARY_POINT_M"): {
        "DISTANCE_TO_ESTUARY_M",
        "MINIMUM_DISTANCE_M",
    },
}


def supports_resolution(area: str, resolution: int) -> bool:
    """Internal producer scales do not automatically become public variants."""
    return area not in CORE_SCHEMAS or any(
        resolution in metric["resolutions"] for metric in CORE_SCHEMAS[area]["metrics"]
    )


def native_keys(table: pa.Table) -> pa.Table:
    """Validate public/native identity without consulting any external audit."""
    if "h3_index" in table.column_names:
        if "H3_INDEX" in table.column_names:
            raise ValueError("Ambiguous H3 identity")
        metadata = table.schema.metadata
        table = table.rename_columns(
            ["H3_INDEX" if n == "h3_index" else n for n in table.column_names]
        ).replace_schema_metadata(metadata)
    if "H3_RESOLUTION" not in table.column_names:
        table = table.append_column(
            "H3_RESOLUTION",
            pa.array(
                [h3.get_resolution(v) for v in table["H3_INDEX"].to_pylist()],
                type=pa.int64(),
            ),
        )
    return table


def project_metrics(area: str, table: pa.Table) -> pa.Table:
    """Keep keys and declared measurements, preserving every metric null."""
    if b"seascape_review" in (table.schema.metadata or {}):
        raise ValueError(
            "Legacy compact input may have filled missing metrics; rebuild from scientific inputs, not historical audit output"
        )
    mapping = {}
    columns = {"date": table["date"]} if "date" in table.column_names else {}
    key = "H3_INDEX" if area in _NATIVE_LAYOUT else "h3_index"
    columns[key] = table["H3_INDEX"]
    resolutions = pc.unique(table["H3_RESOLUTION"]).to_pylist()
    if len(resolutions) != 1:
        raise ValueError("Metric projection requires one native resolution")
    original = json.loads((table.schema.metadata or {}).get(b"seascape_domain", b"{}"))
    if area in CORE_SCHEMAS and "date" not in table.column_names:
        for metric in CORE_SCHEMAS[area]["metrics"]:
            source, name = metric["source_column"], metric["proposed_column"]
            if resolutions[0] not in metric["resolutions"] or _DIAGNOSTIC.search(name):
                continue
            suffix = source.rsplit("__", 1)[-1]
            aliases = _ALIASES.get((area, suffix), set())
            matches = [
                n
                for n in table.column_names
                if n in {source, name} or n.rsplit("__", 1)[-1] in {suffix, *aliases}
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Metric requires unambiguous scientific input: {source}"
                )
            mapping[name] = matches[0]
            value = table[matches[0]]
            columns[name] = (
                pc.cast(value, pa.int64()) if pa.types.is_boolean(value.type) else value
            )
    else:
        for field in table.schema:
            if field.name in {
                "H3_INDEX",
                "H3_RESOLUTION",
                "date",
            } or _DIAGNOSTIC.search(field.name):
                continue
            entry = original.get("fields", {}).get(field.name, {})
            entry = {**entry, **entry.get(str(resolutions[0]), {})}
            role = entry.get("role")
            if role is not None and role not in _METRIC_ROLES:
                continue
            if not (
                pa.types.is_integer(field.type)
                or pa.types.is_floating(field.type)
                or pa.types.is_boolean(field.type)
            ):
                continue
            name = field.name if area in _NATIVE_LAYOUT else field.name.lower()
            if area in {"seagrass", "kelp", "bivalve"}:
                name = field.name.rsplit("__", 1)[-1]
            if name in columns:
                raise ValueError(f"Duplicate metric alias: {name}")
            mapping[name] = field.name
            columns[name] = table[field.name]
        extent = f"{area.upper()}_EXTENT_ALL_TIME_M2"
        if "date" not in columns and area in {"seagrass", "kelp", "bivalve"}:
            matches = [n for n in table.column_names if n.rsplit("__", 1)[-1] == extent]
            if len(matches) == 1:
                flag = f"{area.upper()}_EXTENT_BOOL"
                if flag not in columns:
                    columns[flag] = pc.cast(
                        pc.greater(table[matches[0]], 0), pa.int64()
                    )
                    mapping[flag] = matches[0]
    if len(columns) <= (2 if "date" in columns else 1):
        raise ValueError(f"No scientific metrics selected for {area}")
    if area in _NATIVE_LAYOUT and "date" in columns:
        columns["date"] = columns.pop("date")
    fields = {}
    for name, source in mapping.items():
        entry = original.get("fields", {}).get(source, {})
        entry = {**entry, **entry.get(str(resolutions[0]), {})}
        fields[name] = deepcopy(entry)
        if name.endswith("_EXTENT_BOOL"):
            fields[name].update(
                unit="1",
                arrow_type="int64",
                definition="1 when mapped extent is positive, 0 when zero, null when extent is unknown.",
            )
    context = deepcopy(original)
    context.update(fields=fields, resolution=resolutions[0])
    context["delivery_projection"] = {
        "policy": "keys-and-metrics-v1",
        "source_columns": mapping,
        "omitted_columns": [
            n
            for n in table.column_names
            if n not in {*mapping.values(), *KEYS_FOR_PROJECTION}
        ],
    }
    if area == "nearshore-transitions":
        for parameter in ("DEPTH_THRESHOLD_M", "NEARSHORE_BAND_WIDTH_M"):
            matches = [
                n for n in table.column_names if n.rsplit("__", 1)[-1] == parameter
            ]
            if matches:
                values = pc.unique(table[matches[0]]).to_pylist()
                if len(matches) != 1 or len(values) != 1 or values[0] is None:
                    raise ValueError(
                        f"Nearshore parameter must be uniform: {parameter}"
                    )
                context.setdefault("parameters", {})[parameter.lower()] = values[0]
    if "temporal_support" in original:
        temporal = dict(original["temporal_support"])
        start, end = temporal.get("start_column"), temporal.get("end_exclusive_column")
        if start in table.column_names and end in table.column_names:
            intervals = {}
            for label, stop in zip(
                table[start].to_pylist(), table[end].to_pylist(), strict=True
            ):
                if label is None or stop is None or stop <= label:
                    raise ValueError(
                        "Composite support requires valid temporal intervals"
                    )
                key, value = label.isoformat(), stop.isoformat()
                if key in intervals and intervals[key] != value:
                    raise ValueError(
                        "Composite date labels have conflicting temporal intervals"
                    )
                intervals[key] = value
            temporal["intervals"] = intervals
        context["temporal_support"] = temporal
    metadata = {
        k: v
        for k, v in (table.schema.metadata or {}).items()
        if k not in {b"pandas", b"geo"}
    }
    metadata.update(
        {
            POLICY: json.dumps(
                {"policy": "keys-and-metrics-v1", "area": area, "nulls": "preserved"}
            ).encode(),
            b"seascape_domain": json.dumps(context, default=str).encode(),
        }
    )
    return pa.table(columns).replace_schema_metadata(metadata)
