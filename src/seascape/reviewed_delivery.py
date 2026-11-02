"""Reviewed public schemas backed by required, immutable native audit tables."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

KEY = b"seascape_review"
CONTEXT = b"seascape_domain"
POLICY = "reviewed-static-v1"
CORE_POLICY = "reviewed-core-static-v2"
CORE_SCHEMAS = json.loads(
    files("seascape").joinpath("resources/reviewed_core.json").read_text()
)
HABITATS = {"seagrass", "bivalve", "kelp"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _project_v1(area: str, table: pa.Table) -> pa.Table:
    """Apply only approved static policies; never infer new H3 cells or dates."""
    if "date" in table.column_names:
        return table
    field = f"{area.upper()}_EXTENT_ALL_TIME_M2"
    if area not in {"bathymetry", "freshwater"} and not (
        area in HABITATS and field in table.column_names
    ):
        return table
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(CONTEXT, b"{}"))
    fields = copy.deepcopy(context.get("fields", {}))
    if area in HABITATS:
        values = table[field]
        if not pa.types.is_floating(values.type):
            raise ValueError("Mapped habitat extent must be a floating area in m2")
        if pc.any(pc.fill_null(pc.less(values, 0), False)).as_py():
            raise ValueError("Mapped habitat extent cannot be negative")
        values = pc.fill_null(values, 0)
        flag = f"{area.upper()}_EXTENT_BOOL"
        table = pa.table(
            {
                "H3_INDEX": table["H3_INDEX"],
                field: values,
                flag: pc.cast(pc.greater(values, 0), pa.int64()),
            }
        )
        entry = fields.get(field, {})
        entry["definition"] = (
            entry.get("definition", "Mapped all-time positive footprint union, m2.")
            + " Public delivery fills source nulls with zero: zero means no mapped "
            "positive evidence, including unknown coverage; it does not establish "
            "surveyed absence. Original nulls, methods and QC remain in the required audit."
        )
        entry.update(family="Biogenic Habitats", unit="m2", picker_visible=True)
        fields[field] = entry
        fields[flag] = {
            "common_name": f"{area.title()} Mapped Presence (All Time)",
            "definition": "1 if the all-time mapped area is greater than zero; "
            "0 otherwise, including source nulls. Not confirmed habitat absence or current presence.",
            "family": "Biogenic Habitats",
            "unit": "1",
            "role": "predictor",
            "picker_visible": True,
            "modeling_eligibility": "mapped_evidence_only",
        }
    else:
        table = table.drop(["H3_RESOLUTION"])
    kept = set(table.column_names)

    def trim(entry: Any) -> Any:
        if not isinstance(entry, dict):
            return entry
        return {
            k: [v for v in value if v in kept]
            if k
            in {
                "qualifiers",
                "row_quality_and_coverage_columns",
                "source_observation_period_columns",
            }
            and isinstance(value, list)
            else trim(value)
            if isinstance(value, dict)
            else value
            for k, value in entry.items()
        }

    context["fields"] = {k: trim(v) for k, v in fields.items() if k in kept}
    metadata[CONTEXT] = json.dumps(context, sort_keys=True).encode()
    return table.replace_schema_metadata(metadata)


def _resolve_column(table: pa.Table, name: str) -> str:
    if name in table.column_names:
        return name
    suffix = name.rsplit("__", 1)[-1]
    matches = [n for n in table.column_names if n.rsplit("__", 1)[-1] == suffix]
    if len(matches) != 1:
        raise ValueError(
            f"Approved compact schema requires unambiguous source field: {name}"
        )
    return matches[0]


def _project_core(area: str, table: pa.Table) -> pa.Table:
    specification = CORE_SCHEMAS[area]
    resolutions = pc.unique(table["H3_RESOLUTION"]).to_pylist()
    if len(resolutions) != 1:
        raise ValueError("Compact core requires one native resolution per file")
    resolution = resolutions[0]
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(CONTEXT, b"{}"))
    source_fields = context.get("fields", {})
    columns = {"h3_index": table["H3_INDEX"]}
    fields = {}
    mapping = {"h3_index": "H3_INDEX"}
    for metric in specification["metrics"]:
        if resolution not in metric["resolutions"]:
            continue
        source = _resolve_column(table, metric["source_column"])
        name = metric["proposed_column"]
        value = table[source]
        if metric["units"] == "0/1":
            if not pa.types.is_boolean(value.type):
                raise ValueError(f"Expected nullable native boolean: {source}")
            value = pc.cast(value, pa.int64())
        columns[name] = value
        mapping[name] = source
        raw = source_fields.get(source, {})
        entry = copy.deepcopy(raw.get(str(resolution), raw))
        definition = (
            entry.get("definition")
            or entry.get("scientific_definition")
            or entry.get("units_and_support")
            or metric["description"]
        )
        entry.update(
            {
                "common_name": name.replace("_", " ").capitalize(),
                "definition": str(definition) + " " + specification["limitations"],
                "unit": "1" if metric["units"] == "0/1" else metric["units"],
                "picker_visible": True,
                "source_column": source,
                "public_column": name,
                "output_column": name,
                "arrow_type": str(value.type),
                "qualifiers": [],
                "row_quality_and_coverage_columns": [],
                "source_observation_period_columns": [],
            }
        )
        fields[name] = entry
    if len(columns) == 1:
        raise ValueError(f"No approved core metrics available for {area}/R{resolution}")
    context["fields"] = fields
    parameters = {}
    if area == "nearshore-transitions":
        for parameter in ("DEPTH_THRESHOLD_M", "NEARSHORE_BAND_WIDTH_M"):
            matches = [
                n for n in table.column_names if n.rsplit("__", 1)[-1] == parameter
            ]
            if matches:
                values = pc.unique(table[matches[0]]).to_pylist()
                if len(matches) != 1 or len(values) != 1:
                    raise ValueError(
                        f"Compact nearshore parameter must be uniform: {parameter}"
                    )
                parameters[parameter.lower()] = values[0]
    context["core_schema"] = {
        "policy": CORE_POLICY,
        "source_columns": mapping,
        "limitations": specification["limitations"],
        "parameters": parameters,
    }
    metadata[CONTEXT] = json.dumps(context, sort_keys=True).encode()
    return pa.table(columns).replace_schema_metadata(metadata)


def project(area: str, table: pa.Table, *, policy: str | None = None) -> pa.Table:
    """Preserve v1 restoration and apply approved v2 cores only to their areas."""
    if "date" in table.column_names:
        return table
    if policy == CORE_POLICY or (policy is None and area in CORE_SCHEMAS):
        if area not in CORE_SCHEMAS:
            raise ValueError("Unapproved compact core area")
        return _project_core(area, table)
    if policy not in {None, POLICY}:
        raise ValueError("Unsupported reviewed Seascape policy")
    return _project_v1(area, table)


def stage_compact(
    area: str, table: pa.Table, *, audit_root: Path, writer: Any
) -> pa.Table:
    """Stage native audit first; its binding becomes visible with the public table."""
    if KEY in (table.schema.metadata or {}):
        raise ValueError("Restore reviewed input before writing it again")
    public = project(area, table)
    if public is table:
        return table
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as stream:
        stream.write_table(table)
    identity = hashlib.sha256(sink.getvalue()).hexdigest()
    audit = audit_root.resolve() / f"{area}-{identity}.parquet"
    if audit.exists():
        if not pq.read_table(audit).equals(table, check_metadata=True):
            raise ValueError("Existing immutable audit differs from native input")
        checksum = digest(audit)
    else:
        staged = writer.stage_path(audit)
        pq.write_table(table, staged, compression="zstd")
        if not pq.read_table(staged).equals(table, check_metadata=True):
            raise ValueError("Native audit readback mismatch")
        checksum = digest(staged)
    metadata = dict(public.schema.metadata or {})
    metadata[KEY] = json.dumps(
        {
            "policy": CORE_POLICY if area in CORE_SCHEMAS else POLICY,
            "area": area,
            "audit_path": str(audit),
            "audit_sha256": checksum,
            "native_rows": table.num_rows,
            "native_columns": table.num_columns,
        },
        sort_keys=True,
    ).encode()
    return public.replace_schema_metadata(metadata)


def restore_native(table: pa.Table) -> pa.Table:
    """Verify the public projection and recover every original field/type/null."""
    metadata = dict(table.schema.metadata or {})
    raw = metadata.pop(KEY, None)
    if raw is None:
        return table
    binding = json.loads(raw)
    if binding.get("policy") not in {POLICY, CORE_POLICY}:
        raise ValueError("Unsupported reviewed Seascape policy")
    path = Path(binding["audit_path"])
    if not path.is_absolute() or digest(path) != binding["audit_sha256"]:
        raise ValueError("Seascape audit checksum mismatch")
    native = pq.read_table(path)
    if (
        native.num_rows != binding["native_rows"]
        or native.num_columns != binding["native_columns"]
    ):
        raise ValueError("Seascape audit shape mismatch")
    expected = project(binding["area"], native, policy=binding["policy"])
    if not expected.equals(
        table.replace_schema_metadata(metadata), check_metadata=True
    ):
        raise ValueError("Reviewed Seascape table differs from its audited projection")
    return native


def compact_existing(
    output: str | Path, *, audit_root: str | Path | None = None
) -> dict[str, Any]:
    """Migrate reviewed static files atomically, without rebuilding measurements.

    Untouched products, research objects, notes and source-update dates survive.
    Calling twice verifies existing bindings and performs no second write.
    """
    from seascape.core.artifacts import TransactionalFamilyPublisher
    from seascape.domain_parquets import _audit_root, _catalog, _io_root, validate_table

    root = Path(output).expanduser().resolve()
    audit_dir = Path(audit_root).resolve() if audit_root else _audit_root(root)
    if audit_dir.is_relative_to(root):
        raise ValueError("Required audit storage must be outside public delivery")
    changes = []
    with TransactionalFamilyPublisher(_io_root(root)) as writer:
        catalog = _catalog(root)
        source_hashes = {
            str(path.relative_to(root)): digest(path)
            for path in root.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        selected = {}
        for area in sorted(
            HABITATS | {"bathymetry", "freshwater"} | CORE_SCHEMAS.keys()
        ):
            for name in catalog.get(area, {}).get("static", {}).values():
                native = pq.read_table(root / name)
                if KEY in (native.schema.metadata or {}):
                    validate_table(restore_native(native), dynamic=False)
                    continue
                if project(area, native) is not native:
                    validate_table(native, dynamic=False)
                    resolution = int(name.rsplit("-r", 1)[1].split("-", 1)[0])
                    if pc.unique(native["H3_RESOLUTION"]).to_pylist() != [resolution]:
                        raise ValueError("Filename and native H3 resolution disagree")
                    selected[name] = (area, native)
        if not selected:
            return {"policy": CORE_POLICY, "changed": []}
        staged = writer.stage_path(root, terminal=True)
        shutil.copytree(root, staged)
        for name, (area, native) in selected.items():
            public = stage_compact(area, native, audit_root=audit_dir, writer=writer)
            pq.write_table(public, staged / name, compression="zstd")
            if not pq.read_table(staged / name).equals(public, check_metadata=True):
                raise ValueError("Public compact table readback mismatch")
            binding = json.loads(public.schema.metadata[KEY])
            changes.append(
                {
                    "file": name,
                    "before_sha256": digest(root / name),
                    "after_sha256": digest(staged / name),
                    "rows": native.num_rows,
                    "before_columns": native.column_names,
                    "after_columns": public.column_names,
                    "audit": binding,
                }
            )
            catalog[area]["delivery_schema"] = binding["policy"]
        (staged / "catalog.json").write_text(
            json.dumps(catalog, indent=2, sort_keys=True) + "\n"
        )
        current_hashes = {
            str(path.relative_to(root)): digest(path)
            for path in root.rglob("*")
            if path.is_file() and path.name != ".DS_Store"
        }
        if current_hashes != source_hashes:
            raise ValueError("Concurrent source change during Seascape compaction")
        writer.publish()
    for change in changes:
        restore_native(pq.read_table(root / change["file"]))
    return {"policy": CORE_POLICY, "changed": changes}
