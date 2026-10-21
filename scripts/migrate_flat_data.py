"""Convert a retained consolidated Seascape directory to flat current area tables.

Reads existing values only. Never removes the source; filesystem cleanup follows
successful independent readback. No downloads, regional recomputation or release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from seascape.domain_parquets import (
    METADATA_KEY,
    AreaTables,
    label_annual_dates,
    validate_table,
    write_areas,
)

NAMESPACES = {
    "BATHYMETRY": "bathymetry",
    "WATERGRAPH_ANOMALY": "bathymetry",
    "ISOBATH": "bathymetry",
    "TERRAIN": "terrain",
    "TERRAIN_FORM": "terrain",
    "SHORELINE": "shoreline",
    "SHORE_DISTANCE": "shoreline",
    "COASTAL_BOUNDS": "coastal-bounds",
    "FRESHWATER": "freshwater",
    "ESTUARY": "estuary",
    "SUBSTRATE_MODEL": "substrate",
    "SEAGRASS_MODEL": "seagrass",
    "BIVALVE": "bivalve",
    "KELP_DATES": "kelp",
    "ANTHROPOGENIC": "anthropogenic",
}


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def embedded(table, context):
    return table.replace_schema_metadata(
        {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
    )


def pivot_bearings(table):
    """Retain every native directional value as a metric column; never average."""
    bearings = sorted(pc.unique(table["BEARING_INDEX"]).to_pylist())
    slices = {}
    expected = None
    for bearing in bearings:
        part = validate_table(
            table.filter(pc.equal(table["BEARING_INDEX"], bearing)).drop(
                ["BEARING_INDEX"]
            ),
            dynamic=False,
        )
        keys = part.select(["H3_INDEX", "H3_RESOLUTION"])
        if expected is not None and not keys.equals(expected):
            raise ValueError("Directional cell support mismatch")
        expected = keys
        slices[bearing] = part
    columns = {name: expected[name] for name in expected.column_names}
    fields = {}
    first = slices[bearings[0]]
    for name in first.column_names:
        if name in columns:
            continue
        if all(first[name].equals(part[name]) for part in slices.values()):
            column = f"COASTAL_RAY__{name}"
            columns[column] = first[name]
            fields[column] = {
                "source_column": name,
                "bearing": "invariant across all native bearings",
            }
        else:
            for bearing, part in slices.items():
                column = f"COASTAL_RAY__{name}__bearing_{bearing:02d}"
                columns[column] = part[name]
                fields[column] = {"source_column": name, "bearing_index": bearing}
    return pa.table(columns), fields


def migrate(source, output):
    source, output = source.resolve(), output.resolve()
    if source == output or output.is_relative_to(source):
        raise ValueError("Use a separate output while validating migration")
    manifest = json.loads((source / "manifest.json").read_text())
    for record in manifest["files"]:
        path = (source / record["path"]).resolve()
        if not path.is_relative_to(source) or digest(path) != record["sha256"]:
            raise ValueError(f"Source checksum mismatch: {record['path']}")
    dictionary = json.loads((source / "FIELD_DICTIONARY.json").read_text())
    scope = json.loads((source / "SCOPE_AND_JOIN_CONTRACT_SCHEMA3.json").read_text())
    parts, contexts = {}, {}
    for resolution in (6, 8):
        original = pq.read_table(
            source / f"metrics/SEASCAPE_STATIC_NATIVE_R{resolution}.parquet"
        )
        table = validate_table(original, dynamic=False)
        entries = {
            item["output_column"]: item
            for item in dictionary
            if item["resolution"] == resolution
        }
        by_area = {}
        for name in table.column_names:
            if name in {"H3_INDEX", "H3_RESOLUTION"}:
                continue
            entry = entries[name]
            if entry.get("alias_of"):
                if not table[name].equals(table[entry["alias_of"]]):
                    raise ValueError(f"Alias is not exact: {name}")
                continue
            if entry.get("role") == "immutable_release_identifier":
                continue
            namespace = name.split("__")[0]
            if namespace not in NAMESPACES:
                raise ValueError(f"Unassigned Seascape area: {name}")
            area = NAMESPACES[namespace]
            by_area.setdefault(area, []).append(name)
            context = contexts.setdefault(
                area, {"fields": {}, "source_context": {}, "limits": scope}
            )
            # Keep the complete dictionary and source interpretation in the Parquet.
            context["fields"].setdefault(name, {})[str(resolution)] = entry
            identity = entry.get("source_release")
            if identity and identity not in context["source_context"]:
                originals = source.parent / identity
                context["source_context"][identity] = {
                    path.name: json.loads(path.read_text())
                    for path in originals.glob("*.json")
                    if path.name.lower()
                    in {
                        "manifest.json",
                        "field_dictionary.json",
                        "method_scope.json",
                        "metric_definitions.json",
                        "qualified_partial_scope_metric_definitions_schema3.json",
                    }
                }
        for area, columns in by_area.items():
            part = table.select(["H3_INDEX", "H3_RESOLUTION", *columns])
            parts.setdefault(area, []).append(part)

    pairs = {
        area: AreaTables(
            static=embedded(
                pa.concat_tables(tables, promote_options="permissive"), contexts[area]
            )
        )
        for area, tables in parts.items()
    }
    for binding in json.loads((source / "SIDECAR_BINDINGS.json").read_text()):
        path = Path(binding["absolute_path"])
        if digest(path) != binding["sha256"]:
            raise ValueError(f"Source checksum mismatch: {path.name}")
        table = pq.read_table(path)
        if "OBSERVATION_YEAR" in binding["grain"]:
            dynamic = label_annual_dates(table)
            context = json.loads(dynamic.schema.metadata[METADATA_KEY])
            context.update(
                {"source_context": contexts["kelp"]["source_context"], "limits": scope}
            )
            pairs["kelp"] = AreaTables(
                static=pairs["kelp"].static, dynamic=embedded(dynamic, context)
            )
        elif "BEARING_INDEX" in binding["grain"]:
            rays, fields = pivot_bearings(table)
            current = pairs["coastal-bounds"].static
            native = validate_table(
                current.filter(pc.equal(current["H3_RESOLUTION"], 8)), dynamic=False
            )
            if not native.select(["H3_INDEX", "H3_RESOLUTION"]).equals(
                rays.select(["H3_INDEX", "H3_RESOLUTION"]).cast(
                    native.select(["H3_INDEX", "H3_RESOLUTION"]).schema
                )
            ):
                raise ValueError("Coastal bounds and directional support mismatch")
            for name in rays.column_names[2:]:
                native = native.append_column(name, rays[name])
            other = current.filter(pc.not_equal(current["H3_RESOLUTION"], 8))
            combined = (
                pa.concat_tables([other, native], promote_options="permissive")
                if other.num_rows
                else native
            )
            contexts["coastal-bounds"]["fields"].update(fields)
            contexts["coastal-bounds"]["directional_support"] = (
                "16 native bearings pivoted exactly into columns. No physical fetch qualification added."
            )
            pairs["coastal-bounds"] = AreaTables(
                static=embedded(combined, contexts["coastal-bounds"])
            )
        else:
            raise ValueError(f"Unassigned companion grain: {binding['grain']}")
    catalog = write_areas(pairs, output=output)
    # Independently compare every retained static array after serialization/type promotion.
    for resolution in (6, 8):
        original = validate_table(
            pq.read_table(
                source / f"metrics/SEASCAPE_STATIC_NATIVE_R{resolution}.parquet"
            ),
            dynamic=False,
        )
        for area, record in catalog.items():
            name = record.get("static", {}).get(str(resolution))
            if name is None:
                continue
            candidate = pq.read_table(output / name)
            if not candidate.num_rows:
                continue
            if not original.select(["H3_INDEX", "H3_RESOLUTION"]).equals(
                candidate.select(["H3_INDEX", "H3_RESOLUTION"]), check_metadata=False
            ):
                raise ValueError(f"Migration support differs: {area}")
            for name in candidate.column_names[2:]:
                if name in original.column_names and not original[name].cast(
                    candidate[name].type
                ).equals(candidate[name]):
                    raise ValueError(f"Migration values differ: {name}")
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.output), indent=2))
