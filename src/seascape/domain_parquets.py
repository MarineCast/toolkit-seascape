"""Flat, replace-in-place H3 tables. No retained data generations or sidecars."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import h3
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

from seascape.core.artifacts import TransactionalFamilyPublisher
from seascape.core.config.paths import project_root
from seascape.delivery_projection import project_delivery_table

DEFAULT_OUTPUT = Path("Data/Seascape")
METADATA_KEY = b"seascape_domain"
KEYS = ("H3_INDEX", "H3_RESOLUTION")

# Evidence and confidence belong beside the quantities they qualify.
PRODUCT_AREAS = {
    "h3_marine_support": "spatial-support",
    "bathymetry": "bathymetry",
    "gebco_tid": "bathymetry",
    "geomorphometry": "terrain",
    "geomorphic_units": "terrain",
    "shoreline_proximity": "shoreline",
    "shoreline_characterization": "shoreline",
    "nearshore_transitions": "nearshore-transitions",
    "coast_complexity": "coast-complexity",
    "exposure_and_enclosure": "coastal-bounds",
    "waterbody_morphometry": "waterbody-morphometry",
    "freshwater_sources": "freshwater",
    "fluvial_connectivity": "fluvial-connectivity",
    "fluvial_barriers": "fluvial-barriers",
    "fluvial_barriers_confidence": "fluvial-barriers",
    "estuarine_connectivity": "estuary",
    "anthropogenic": "anthropogenic",
    "anthropogenic_confidence": "anthropogenic",
    "benthic_substrate": "substrate",
    "benthic_substrate_confidence": "substrate",
    "bottom_hardness": "bottom-hardness",
    "bottom_hardness_confidence": "bottom-hardness",
    "seagrass": "seagrass",
    "kelp": "kelp",
    "kelp_annual": "kelp",
    "reef_habitat": "reef",
    "reef_habitat_confidence": "reef",
    "benthic_habitat_panel": "habitat-composite",
    "benthic_habitat_panel_confidence": "habitat-composite",
}


@dataclass(frozen=True)
class AreaTables:
    static: pa.Table | None = None
    dynamic: pa.Table | None = None


def output_root(workspace: str | Path | None = None) -> Path:
    root = Path(workspace).expanduser().resolve() if workspace else project_root()
    return root / DEFAULT_OUTPUT


def _area_name(area: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", area):
        raise ValueError(f"Invalid Seascape area: {area!r}")
    return area


def _io_root(root: Path) -> Path:
    # Recovery bookkeeping is temporary/internal and never appears in Data/Seascape.
    identity = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:16]
    return root.parent.parent / ".marinecast-work" / "seascape" / identity


def validate_table(table: pa.Table, *, dynamic: bool) -> pa.Table:
    """Validate native cell identity, time grain and missingness before any write."""
    keys = [*KEYS, *(["date"] if dynamic else [])]
    if len(set(table.column_names)) != table.num_columns:
        raise ValueError("Duplicate metric column names")
    if set(keys) - set(table.column_names) or not table.num_rows:
        raise ValueError(f"Nonempty table requires keys {keys}")
    if not dynamic and "date" in table.column_names:
        raise ValueError("Static tables cannot have a date column")
    if dynamic and not pa.types.is_date32(table.schema.field("date").type):
        raise ValueError("Dynamic date must be an Arrow date32 column")
    cells = table["H3_INDEX"].to_pylist()
    resolutions = table["H3_RESOLUTION"].to_pylist()
    for cell, resolution in zip(cells, resolutions, strict=True):
        if (
            not isinstance(cell, str)
            or not h3.is_valid_cell(cell)
            or isinstance(resolution, bool)
            or resolution != h3.get_resolution(cell)
        ):
            raise ValueError("Invalid H3 identity or resolution")
    key_values = list(zip(*(table[key].to_pylist() for key in keys), strict=True))
    if any(None in key for key in key_values) or len(set(key_values)) != len(
        key_values
    ):
        raise ValueError(f"Null or duplicate {keys} keys")
    for field in table.schema:
        if pa.types.is_floating(field.type):
            invalid = pc.invert(pc.is_finite(table[field.name]))
            if pc.any(pc.fill_null(invalid, False)).as_py():
                raise ValueError(
                    f"Nonfinite metric: {field.name}; use null for missing"
                )
    return table.take(
        pc.sort_indices(table, sort_keys=[(key, "ascending") for key in keys])
    )


def label_annual_dates(
    table: pa.Table, *, year_column: str = "OBSERVATION_YEAR"
) -> pa.Table:
    """Use January 1 as an annual index label, never as a survey-day claim."""
    years = table[year_column].to_pylist()
    if any(
        not isinstance(year, int) or isinstance(year, bool) or not 1 <= year <= 9999
        for year in years
    ):
        raise ValueError("Annual observations require explicit integer survey years")
    dates = pa.array([date(year, 1, 1) for year in years], type=pa.date32())
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(METADATA_KEY, b"{}"))
    context["temporal_support"] = {
        "precision": "year",
        "date_label": "January 1 labels the survey year; it is not an observed survey day. No daily expansion or forward fill.",
    }
    metadata[METADATA_KEY] = json.dumps(context).encode()
    return table.append_column("date", dates).replace_schema_metadata(metadata)


def _catalog(root: Path) -> dict[str, Any]:
    path = root / "catalog.json"
    if not path.exists():
        if root.exists() and any(path.name != ".DS_Store" for path in root.iterdir()):
            raise ValueError("Output contains files without a Seascape catalog")
        return {}
    catalog = json.loads(path.read_text())
    if not isinstance(catalog, dict):
        raise ValueError("Invalid Seascape catalog")
    expected = {"catalog.json"}
    if (root / "research").exists() or (root / "research").is_symlink():
        _research_tree(root)
        expected.add("research")
    for area, record in catalog.items():
        _area_name(area)
        if not isinstance(record, dict) or not isinstance(
            record.get("last_updated_utc"), str
        ):
            raise ValueError(f"Invalid catalog entry: {area}")
        for kind in ("static", "dynamic"):
            variants = record.get(kind, {})
            if not isinstance(variants, dict):
                raise ValueError(f"Invalid resolution mapping: {area}/{kind}")
            for resolution, name in variants.items():
                if (
                    not re.fullmatch(r"(?:[0-9]|1[0-5])", str(resolution))
                    or name != f"{area}-r{resolution}-{kind}.parquet"
                    or not (root / name).is_file()
                ):
                    raise ValueError(f"Invalid or missing catalog file: {name}")
                expected.add(name)
    if {path.name for path in root.iterdir() if path.name != ".DS_Store"} != expected:
        raise ValueError("Output contains unexpected files; migrate them explicitly")
    return catalog


def _research_tree(root: Path) -> Path | None:
    """Keep separately keyed research objects outside the flat H3 table catalog."""
    path = root / "research"
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Seascape research must be a local directory")
    if any(item.is_symlink() for item in path.rglob("*")):
        raise ValueError("Seascape research cannot contain symbolic links")
    return path


def _copy_research_tree(source: Path, destination: Path) -> None:
    path = _research_tree(source)
    if path is not None:
        shutil.copytree(path, destination / "research")


def _resolution_variant(table: pa.Table, resolution: int) -> pa.Table:
    """Select native rows and omit only explicitly unavailable padding columns."""
    table = table.filter(pc.equal(table["H3_RESOLUTION"], resolution))
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(METADATA_KEY, b"{}"))
    fields = context.get("fields", {})
    selected = []
    for name in table.column_names:
        info = fields.get(name, {})
        available = info.get("available_resolutions")
        if available is None and info.get("collection_paths"):
            available = list(info["collection_paths"])
        if available is None and any(
            re.fullmatch(r"(?:[0-9]|1[0-5])", key) for key in info
        ):
            available = [key for key in info if re.fullmatch(r"(?:[0-9]|1[0-5])", key)]
        if (
            name not in {*KEYS, "date"}
            and available is not None
            and resolution not in {int(value) for value in available}
        ):
            if table[name].null_count != table.num_rows:
                raise ValueError(
                    f"Non-null metric marked unavailable at R{resolution}: {name}"
                )
            continue
        selected.append(name)
    context["fields"] = {
        name: info for name, info in fields.items() if name in selected
    }
    context["resolution"] = resolution
    metadata[METADATA_KEY] = json.dumps(context, sort_keys=True, default=str).encode()
    return table.select(selected).replace_schema_metadata(metadata)


def write_areas(
    areas: Mapping[str, AreaTables],
    *,
    output: str | Path | None = None,
    _preserve_existing_variants: bool = False,
    retire_areas: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Replace selected areas and update one small catalog in a recoverable transaction.

    Omitted areas keep their files and timestamp. An omitted static/dynamic variant
    of an updated area is removed, so a stale dated table cannot survive a rebuild.
    Metadata, definitions and source context are embedded in the Parquet schema.
    """
    root = Path(output).expanduser().resolve() if output else output_root()
    if not areas:
        raise ValueError("Select at least one Seascape area")
    if set(retire_areas) & set(areas):
        raise ValueError("Cannot retire and replace the same area")
    for retired in retire_areas:
        _area_name(retired)
    validated: dict[str, AreaTables] = {}
    for area, pair in areas.items():
        _area_name(area)
        if pair.static is None and pair.dynamic is None:
            raise ValueError(f"Area has no tables: {area}")
        validated[area] = AreaTables(
            project_delivery_table(area, validate_table(pair.static, dynamic=False))
            if pair.static is not None
            else None,
            project_delivery_table(area, validate_table(pair.dynamic, dynamic=True))
            if pair.dynamic is not None
            else None,
        )
    with TransactionalFamilyPublisher(_io_root(root)) as writer:
        catalog = _catalog(root)
        unknown = set(retire_areas) - set(catalog)
        if unknown:
            raise ValueError(
                f"Unknown areas selected for retirement: {sorted(unknown)}"
            )
        catalog = {
            area: record for area, record in catalog.items() if area not in retire_areas
        }
        staged = writer.stage_path(root)
        staged.mkdir()
        _copy_research_tree(root, staged)
        for area, previous_record in catalog.items():
            if area not in validated:
                for kind in ("static", "dynamic"):
                    for name in previous_record.get(kind, {}).values():
                        shutil.copyfile(root / name, staged / name)
        now = datetime.now(timezone.utc).isoformat()
        for area, pair in validated.items():
            record: dict[str, Any] = {"last_updated_utc": now}
            for kind in ("static", "dynamic"):
                variants = {}
                if _preserve_existing_variants:
                    for resolution, name in catalog.get(area, {}).get(kind, {}).items():
                        shutil.copyfile(root / name, staged / name)
                        variants[resolution] = name
                table = getattr(pair, kind)
                if table is not None:
                    for resolution in sorted(
                        pc.unique(table["H3_RESOLUTION"]).to_pylist()
                    ):
                        name = f"{area}-r{resolution}-{kind}.parquet"
                        native = _resolution_variant(table, resolution)
                        metadata = dict(native.schema.metadata or {})
                        context = json.loads(metadata.get(METADATA_KEY, b"{}"))
                        context.update(
                            {"area": area, "kind": kind, "last_updated_utc": now}
                        )
                        presentation_family = {
                            "mapped-substrate-classes": "Substrate",
                            "shoreline": "Coastal Environment",
                            "coast-complexity": "Coastal Environment",
                            "nearshore-transitions": "Coastal Environment",
                        }.get(area)
                        if presentation_family:
                            for column in native.column_names:
                                if column not in {*KEYS, "date"}:
                                    info = context.setdefault("fields", {}).setdefault(
                                        column, {}
                                    )
                                    info["family"] = presentation_family
                                    for key, value in info.items():
                                        if key.isdigit() and isinstance(value, dict):
                                            value["family"] = presentation_family
                        metadata[METADATA_KEY] = json.dumps(
                            context, sort_keys=True, default=str
                        ).encode()
                        native = native.replace_schema_metadata(metadata)
                        pq.write_table(native, staged / name, compression="zstd")
                        if not pq.read_table(staged / name).equals(
                            native, check_metadata=True
                        ):
                            raise ValueError(f"Parquet readback mismatch: {name}")
                        variants[str(resolution)] = name
                if variants:
                    record[kind] = variants
            catalog[area] = record
        (staged / "catalog.json").write_text(
            json.dumps(catalog, indent=2, sort_keys=True) + "\n"
        )
        writer.publish()
    return catalog


def list_areas(*, output: str | Path | None = None) -> tuple[str, ...]:
    root = Path(output).expanduser().resolve() if output else output_root()
    with TransactionalFamilyPublisher._exclusive_parent(_io_root(root)):
        TransactionalFamilyPublisher._recover_owned(_io_root(root))
        return tuple(sorted(_catalog(root)))


def read_area(
    area: str,
    *,
    resolution: int | None = None,
    dynamic: bool = False,
    output: str | Path | None = None,
) -> pa.Table:
    """Read the current table under the writer lock; no release ID or frozen path."""
    _area_name(area)
    root = Path(output).expanduser().resolve() if output else output_root()
    kind = "dynamic" if dynamic else "static"
    with TransactionalFamilyPublisher._exclusive_parent(_io_root(root)):
        TransactionalFamilyPublisher._recover_owned(_io_root(root))
        record = _catalog(root).get(area, {})
        variants = record.get(kind, {})
        if not variants:
            raise KeyError(f"Seascape {area} has no {kind} table")
        if resolution is None:
            if len(variants) != 1:
                raise ValueError(
                    f"Select an exact resolution for {area}/{kind}: {sorted(variants)}"
                )
            resolution = int(next(iter(variants)))
        name = variants.get(str(resolution))
        if name is None:
            raise KeyError(f"Seascape {area} has no R{resolution} {kind} table")
        table = pq.read_table(root / name)
        if pc.unique(table["H3_RESOLUTION"]).to_pylist() != [resolution]:
            raise ValueError("Filename and native H3 resolution disagree")
        return table


def export_domain_parquets(
    *,
    workspace: str | Path,
    output: str | Path | None = None,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    """Join generated producer tables by native keys and export each area once."""
    from seascape.metric_matrix import _validated_table

    root = Path(workspace).expanduser().resolve()
    destination = Path(output).expanduser().resolve() if output else output_root(root)
    path = Path(catalog_path) if catalog_path else root / "config/feature_catalog.yaml"
    catalog = yaml.safe_load(path.read_text())
    products = catalog["products"]
    support = products["h3_marine_support"]["collection"]["paths"]
    matrices: dict[str, list[pa.Table]] = {}
    dynamic_matrices: dict[str, list[pa.Table]] = {}
    fields: dict[str, dict[str, Any]] = {}
    source_context: dict[str, dict[str, Any]] = {}
    for resolution, support_relative in sorted(support.items()):
        resolution = int(resolution)
        support_path = (root / support_relative).resolve()
        if not support_path.is_relative_to(root):
            raise ValueError("Support path escapes workspace")
        canonical, keys = _validated_table(
            support_path, resolution=resolution, expected_keys=None, selected=[]
        )
        columns: dict[str, dict[str, Any]] = {}
        dated: dict[str, pa.Table] = {}
        for product_id, product in sorted(products.items()):
            relative = product["collection"]["paths"].get(resolution)
            if relative is None:
                continue
            source = (root / relative).resolve()
            if not source.is_relative_to(root) or source.is_relative_to(destination):
                raise ValueError("Source path escapes workspace or overlaps output")
            selected = sorted(
                name
                for name, feature in product["features"].items()
                if resolution in feature["collection_paths"]
            )
            area = PRODUCT_AREAS.get(product_id, product_id.replace("_", "-"))
            source_context.setdefault(area, {})[f"{product_id}.r{resolution}"] = {
                "table_metadata": {
                    key.decode(): value.decode(errors="replace")
                    for key, value in (pq.read_schema(source).metadata or {}).items()
                },
                "family_context": {
                    path.name: json.loads(path.read_text())
                    for path in source.parent.glob("*manifest*.json")
                },
            }
            temporal_column = product.get("temporal_column")
            if temporal_column is not None:
                if temporal_column not in {"date", "OBSERVATION_YEAR"}:
                    raise ValueError(
                        "Declare a date or annual observation year without inferring daily coverage"
                    )
                names = list(dict.fromkeys([*KEYS, temporal_column, *selected]))
                temporal = pq.read_table(source, columns=names)
                if temporal_column == "OBSERVATION_YEAR":
                    temporal = label_annual_dates(temporal)
                temporal = validate_table(temporal, dynamic=True)
                if set(temporal["H3_INDEX"].to_pylist()) - set(keys):
                    raise ValueError(f"Dynamic H3 support mismatch: {product_id}")
                renamed = temporal.rename_columns(
                    [
                        name if name in {*KEYS, "date"} else f"{product_id}__{name}"
                        for name in temporal.column_names
                    ]
                ).replace_schema_metadata(temporal.schema.metadata)
                previous = dated.get(area)
                if previous is not None:
                    previous_support = json.loads(
                        (previous.schema.metadata or {}).get(METADATA_KEY, b"{}")
                    )
                    current_support = json.loads(
                        (renamed.schema.metadata or {}).get(METADATA_KEY, b"{}")
                    )
                    if previous_support.get("temporal_support") != current_support.get(
                        "temporal_support"
                    ):
                        raise ValueError(f"Dynamic temporal precision mismatch: {area}")
                    if not previous.select([*KEYS, "date"]).equals(
                        renamed.select([*KEYS, "date"])
                    ):
                        raise ValueError(f"Dynamic temporal support mismatch: {area}")
                    for name in renamed.column_names:
                        if name not in {*KEYS, "date"}:
                            previous = previous.append_column(name, renamed[name])
                    renamed = previous
                dated[area] = renamed
                fields.setdefault(area, {}).update(
                    {
                        f"{product_id}__{name}": feature
                        for name, feature in product["features"].items()
                        if name not in {*KEYS, "date"}
                    }
                )
                continue
            table, _ = _validated_table(
                source, resolution=resolution, expected_keys=keys, selected=selected
            )
            values = columns.setdefault(
                area,
                {
                    "H3_INDEX": canonical["H3_INDEX"],
                    "H3_RESOLUTION": pa.array([resolution] * len(keys), type=pa.int8()),
                },
            )
            for name in selected:
                column = f"{product_id}__{name}"
                if column in values:
                    raise ValueError(f"Duplicate column: {column}")
                value = table[name]
                if pa.types.is_dictionary(value.type):
                    value = value.cast(pa.large_string())
                values[column] = value
                fields.setdefault(area, {})[column] = product["features"][name]
        for area, values in columns.items():
            matrices.setdefault(area, []).append(pa.table(values))
        for area, table in dated.items():
            dynamic_matrices.setdefault(area, []).append(table)
    pairs = {}
    for area in sorted(set(matrices) | set(dynamic_matrices)):
        metadata = {
            "fields": fields.get(area, {}),
            "source_context": source_context.get(area, {}),
            "missingness": "Native values, nulls, evidence, coverage and QC are retained; unavailable resolutions are null. No resampling.",
            "source_validation": "producer_contracts_and_h3_support_checked",
        }
        variants = {}
        for kind, source_tables in (
            ("static", matrices.get(area)),
            ("dynamic", dynamic_matrices.get(area)),
        ):
            if source_tables:
                table = pa.concat_tables(source_tables, promote_options="permissive")
                context = dict(metadata)
                if kind == "dynamic":
                    original_context = json.loads(
                        (source_tables[0].schema.metadata or {}).get(
                            METADATA_KEY, b"{}"
                        )
                    )
                    context.update(original_context)
                variants[kind] = table.replace_schema_metadata(
                    {METADATA_KEY: json.dumps(context, default=str).encode()}
                )
        pairs[area] = AreaTables(**variants)
    # An undated producer snapshot is not a replacement for an existing annual
    # series. Replace only generated variants; retain a dated variant until its
    # own source is supplied, with its embedded update/source context unchanged.
    return write_areas(pairs, output=destination, _preserve_existing_variants=True)
