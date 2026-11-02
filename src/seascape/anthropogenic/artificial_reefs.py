"""Source-scoped artificial reef points and native-H3 mapped evidence."""

from __future__ import annotations

import hashlib
import json
import math
from importlib.resources import files
from pathlib import Path

import geopandas as gpd
import h3
import pyarrow as pa
from pyproj import Geod
from shapely.geometry import Point

from .sources import _record, normalize_anthropogenic_inventory

DEFINITION = (
    "True/1 means at least one qualified mapped artificial reef site is assigned "
    "to this native H3 cell. False/0 means no mapped positive evidence in the "
    "retained partial inventories, not confirmed absence. ARSBC 2016, WDFW 2025 "
    "and NOAA Puget Sound ESI 2006 are static location references; source dates "
    "do not establish current condition, activity or complete coverage."
)
ALIASES = {"THE TREES (BOEING CREEK)": "THE TREES", "WEST SEATTLE": "ALKI"}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def coordinate(parts, *, west=False):
    if len(parts) not in {2, 3} or any(not math.isfinite(v) for v in parts):
        raise ValueError("Expected finite degrees/minutes[/seconds]")
    if (
        parts[0] < 0
        or not 0 <= parts[1] < 60
        or (len(parts) == 3 and not 0 <= parts[2] < 60)
    ):
        raise ValueError("Invalid coordinate components")
    value = parts[0] + parts[1] / 60 + (parts[2] / 3600 if len(parts) == 3 else 0)
    if value > (180 if west else 90):
        raise ValueError("Coordinate outside geographic bounds")
    return -value if west else value


def published_sites():
    """Load small reviewed factual transcriptions, not entire source documents."""
    resource = files("seascape").joinpath("resources/artificial_reef_sites.json")
    payload = json.loads(resource.read_text())
    records = []
    for site in payload["sites"]:
        records.append(
            {
                **site,
                "record_id": f"{site['source']}:{site['site_id']}",
                "latitude": coordinate(site["latitude_components"]),
                "longitude": coordinate(site["longitude_components"], west=True),
                "source_context": payload["sources"][site["source"]],
            }
        )
    return records, payload["sources"]


def noaa_sites(archive):
    """Join exact reef type by HUNUM, validating the selected join cardinality."""
    path = "/vsizip/" + str(Path(archive).resolve())
    attributes = gpd.read_file(path, layer="soc_dat")
    attributes = attributes.loc[attributes.TYPE.str.strip().eq("ARTIFICIAL REEF")]
    if attributes.empty or attributes.HUNUM.duplicated().any():
        raise ValueError("NOAA reef attributes must have unique HUNUM")
    points = gpd.read_file(path, layer="socecon_point")
    if points.crs is None:
        raise ValueError("NOAA source CRS required")
    points = points.loc[points.HUNUM.isin(attributes.HUNUM)]
    if set(points.HUNUM) != set(attributes.HUNUM):
        raise ValueError("NOAA reef attribute has no point")
    source_crs = str(points.crs)
    points = points.to_crs(4326).merge(
        attributes.drop(columns=["TYPE"]), on="HUNUM", validate="one_to_one"
    )
    sources = gpd.read_file(path, layer="sources")
    if sources.SOURCE_ID.duplicated().any():
        raise ValueError("NOAA source IDs must be unique")
    lineage = sources.set_index("SOURCE_ID").to_dict("index")
    result = []
    for _, row in points.iterrows():
        if (
            row.geometry is None
            or row.geometry.is_empty
            or row.geometry.geom_type != "Point"
        ):
            raise ValueError("NOAA reef must have point geometry")
        source_ids = {int(row.G_SOURCE), int(row.A_SOURCE)}
        if not source_ids <= lineage.keys():
            raise ValueError("NOAA reef source lineage missing")
        result.append(
            {
                "source": "noaa",
                "record_id": f"noaa:{int(row.ID)}:{int(row.HUNUM)}",
                "site_id": str(int(row.HUNUM)),
                "name": row.NAME.strip(),
                "latitude": row.geometry.y,
                "longitude": row.geometry.x,
                "deployment_date": None,
                "source_context": {
                    "url": "https://www.fisheries.noaa.gov/inport/item/40620",
                    "vintage": "2006 atlas; reef source WDFW 2005",
                    "rights": "CC0-1.0",
                    "source_crs": source_crs,
                    "output_crs": "EPSG:4326",
                    "source_feature_id": int(row.ID),
                    "HUNUM": int(row.HUNUM),
                    "lineage": {str(k): lineage[k] for k in sorted(source_ids)},
                },
            }
        )
    return result


def reconcile(primary, noaa, *, tolerance_m=250):
    """Keep all records; choose WDFW coordinates for reviewed same-site aliases."""
    if not math.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("Positive finite comparison tolerance required")
    records = [dict(record) for record in [*primary, *noaa]]
    ids = [record["record_id"] for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate reef record identity")
    for record in records:
        if not (
            math.isfinite(record["latitude"])
            and -90 <= record["latitude"] <= 90
            and math.isfinite(record["longitude"])
            and -180 <= record["longitude"] <= 180
        ):
            raise ValueError("Invalid reef coordinate")
        record["canonical_record_id"] = record["record_id"]
        record["cross_check"] = (
            "outside_noaa_atlas" if record["source"] == "arsbc" else "unmatched"
        )
    preferred = {}
    for record in records:
        if record["source"] == "wdfw":
            name = record["name"].strip().upper()
            if name in preferred:
                raise ValueError("Ambiguous WDFW site name")
            preferred[name] = record
    checks = []
    matched = set()
    geod = Geod(ellps="WGS84")
    for record in records:
        if record["source"] != "noaa":
            continue
        name = record["name"].strip().upper()
        other = preferred.get(ALIASES.get(name, name))
        if other is None:
            continue
        if other["record_id"] in matched:
            raise ValueError("Multiple NOAA records matched one WDFW site")
        matched.add(other["record_id"])
        distance = geod.inv(
            other["longitude"],
            other["latitude"],
            record["longitude"],
            record["latitude"],
        )[2]
        status = (
            "location_agrees"
            if distance <= tolerance_m
            else "coordinate_conflict_wdfw_preferred"
        )
        record.update(canonical_record_id=other["record_id"], cross_check=status)
        other["cross_check"] = status
        checks.append(
            {
                "wdfw": other["record_id"],
                "noaa": record["record_id"],
                "distance_m": distance,
                "status": status,
                "independent_confirmation": False,
            }
        )
    return records, checks


def inventory(records):
    """Return the existing normalized Anthropogenic inventory contract."""
    rows = []
    for record in records:
        row = _record(
            record_id=record["record_id"],
            source_dataset=record["source"],
            source_feature_id=record["site_id"],
            jurisdiction="BC" if record["source"] == "arsbc" else "WA",
            feature_class="artificial_reef",
            feature_subtype="published_reef_location",
            evidence_class="published_location_inventory",
            source_priority=50,
            confidence_class=2,
            geometry_precision_class="published_coordinate_datum_qualified",
            geometry=Point(record["longitude"], record["latitude"]),
            properties=record,
        )
        row["IS_CANONICAL"] = record["canonical_record_id"] == record["record_id"]
        row["DUPLICATE_OF_RECORD_ID"] = (
            None if row["IS_CANONICAL"] else record["canonical_record_id"]
        )
        rows.append(row)
    return normalize_anthropogenic_inventory(gpd.GeoDataFrame(rows, crs=4326))


def cell_memberships(records, keys, resolution):
    """Assign canonical locations directly at each native resolution, no buffer."""
    if len(set(keys)) != len(keys) or any(
        not h3.is_valid_cell(k) or h3.get_resolution(k) != resolution for k in keys
    ):
        raise ValueError("Unique native H3 keys required")
    members = {key: [] for key in keys}
    outside = []
    canonical = {
        r["record_id"]: r for r in records if r["canonical_record_id"] == r["record_id"]
    }
    for record in records:
        if record["canonical_record_id"] not in canonical:
            raise ValueError("Missing canonical reef record")
    for identity, record in sorted(canonical.items()):
        key = h3.latlng_to_cell(record["latitude"], record["longitude"], resolution)
        if key in members:
            members[key].append(identity)
        else:
            outside.append({"record_id": identity, "native_cell": key})
    return members, outside


def enrich_native(table, records, *, evidence):
    """Replace only reef evidence/QC and attach exact source membership."""
    resolution = set(table["H3_RESOLUTION"].to_pylist())
    if len(resolution) != 1:
        raise ValueError("One native resolution required")
    resolution = resolution.pop()
    keys = table["H3_INDEX"].to_pylist()
    members, outside = cell_memberships(records, keys, resolution)
    columns = [
        n
        for n in table.column_names
        if n.rsplit("__", 1)[-1] == "ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE"
    ]
    if len(columns) != 1:
        raise ValueError("Unambiguous native reef evidence required")
    column = columns[0]
    values = [
        bool(members[key]) or old is True
        for key, old in zip(keys, table[column].to_pylist(), strict=True)
    ]
    table = table.set_column(
        table.schema.get_field_index(column), column, pa.array(values)
    )
    nullable = column + "_SOURCE_NULLABLE"
    if nullable in table.column_names:
        native = [
            True if members[key] else old
            for key, old in zip(keys, table[nullable].to_pylist(), strict=True)
        ]
        table = table.set_column(
            table.schema.get_field_index(nullable),
            nullable,
            pa.array(native, type=pa.bool_()),
        )
    qc = column.removesuffix("MAPPED_POSITIVE_EVIDENCE") + "PRESENCE_QC"
    if qc in table.column_names:
        table = table.set_column(
            table.schema.get_field_index(qc),
            qc,
            pa.array(
                [
                    "positive_reconciled_reef_inventory_location"
                    if members[key]
                    else old
                    for key, old in zip(keys, table[qc].to_pylist(), strict=True)
                ]
            ),
        )
    record_column = column.removesuffix("MAPPED_POSITIVE_EVIDENCE") + "RECORDS_JSON"
    record_values = pa.array([json.dumps(members[key]) for key in keys])
    if record_column in table.column_names:
        table = table.set_column(
            table.schema.get_field_index(record_column), record_column, record_values
        )
    else:
        table = table.append_column(record_column, record_values)
    metadata = dict(table.schema.metadata or {})
    context = json.loads(metadata.get(b"seascape_domain", b"{}"))
    info = context.setdefault("fields", {}).setdefault(column, {})
    info.update(
        definition=DEFINITION,
        common_name="Has mapped artificial reef",
        unit="1",
        family="Anthropogenic",
        source_release="artificial-reef-inventories-20261101",
        source_path=evidence["inventory_path"],
        source_sha256=evidence["inventory_sha256"],
        use_status="mapped_positive_evidence",
        non_null_rows=sum(values),
        null_rows=len(values) - sum(values),
    )
    for stale in ("scientific_definition_reference", "source_manifest_sha256"):
        info.pop(stale, None)
    info["qualifiers"] = list(
        dict.fromkeys([*info.get("qualifiers", []), record_column])
    )
    context["fields"][record_column] = {
        "picker_visible": False,
        "role": "source_quality_or_context",
    }
    context["artificial_reef_inventory"] = {
        **evidence,
        "cell_memberships": {k: v for k, v in members.items() if v},
        "outside_native_support": outside,
        "source_records": records,
    }
    metadata[b"seascape_domain"] = json.dumps(context, sort_keys=True).encode()
    return table.replace_schema_metadata(metadata), {
        "resolution": resolution,
        "rows": len(keys),
        "positive_cells": sum(values),
        "mapped_sites": sum(map(len, members.values())),
        "outside_native_support": outside,
    }
