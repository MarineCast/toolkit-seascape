"""Explicit, traceable topology handling for source polygon inventories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from shapely import make_valid, union_all
from shapely.validation import explain_validity

GeometryPolicy = Literal["reject", "quarantine", "make_valid"]


@dataclass(frozen=True)
class PolygonAudit:
    frame: Any
    report: dict[str, Any]


def _polygon_parts(geometry: Any) -> tuple[list[Any], list[str]]:
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return [geometry], []
    if geometry.geom_type == "GeometryCollection":
        polygons, discarded = [], []
        for part in geometry.geoms:
            found, omitted = _polygon_parts(part)
            polygons.extend(found)
            discarded.extend(omitted)
        return polygons, discarded
    return [], [geometry.geom_type]


def audit_polygon_inventory(
    frame: Any,
    *,
    id_column: str = "RECORD_ID",
    policy: GeometryPolicy = "reject",
) -> PolygonAudit:
    """Return a copy plus QC; repairs never establish survey/source completeness."""
    import geopandas as gpd

    if policy not in {"reject", "quarantine", "make_valid"}:
        raise ValueError("Geometry policy must be reject, quarantine or make_valid")
    if not isinstance(frame, gpd.GeoDataFrame) or frame.crs is None:
        raise ValueError("Polygon evidence requires a GeoDataFrame with explicit CRS")
    if (
        id_column not in frame
        or frame[id_column].isna().any()
        or frame[id_column].astype(str).str.strip().eq("").any()
        or frame[id_column].astype(str).duplicated().any()
    ):
        raise ValueError("Polygon evidence requires unique, nonempty record IDs")
    if "GEOMETRY_PROCESSING" in frame:
        raise ValueError("GEOMETRY_PROCESSING already exists; retain the prior audit")
    result = frame.copy()
    keep, states, geometries, records = [], [], [], []
    for position, (identity, original) in enumerate(
        zip(frame[id_column].astype(str), frame.geometry, strict=True)
    ):
        usable = (
            original is not None
            and not original.is_empty
            and original.is_valid
            and original.geom_type in {"Polygon", "MultiPolygon"}
        )
        if usable:
            keep.append(position)
            geometries.append(original)
            states.append("source_geometry_valid")
            continue
        reason = (
            "missing_geometry"
            if original is None
            else "empty_geometry"
            if original.is_empty
            else explain_validity(original)
            if not original.is_valid
            else "non_polygon_geometry"
        )
        if policy == "reject":
            raise ValueError(f"Invalid polygon evidence {identity}: {reason}")
        record: dict[str, Any] = {
            "record_id": identity,
            "reason": reason,
            "original_geometry_sha256": hashlib.sha256(original.wkb).hexdigest()
            if original is not None
            else None,
            "state": "quarantined",
            "result_geometry_sha256": None,
            "discarded_component_types": [],
        }
        if policy == "make_valid" and original is not None and not original.is_empty:
            parts, discarded = _polygon_parts(make_valid(original))
            repaired = union_all(parts)
            record["discarded_component_types"] = discarded
            if (
                not repaired.is_empty
                and repaired.is_valid
                and repaired.geom_type in {"Polygon", "MultiPolygon"}
            ):
                keep.append(position)
                geometries.append(repaired)
                states.append("made_valid_not_source_certified")
                record["state"] = "made_valid_not_source_certified"
                record["result_geometry_sha256"] = hashlib.sha256(
                    repaired.wkb
                ).hexdigest()
        records.append(record)
    result = result.iloc[keep].copy()
    result.geometry = gpd.GeoSeries(geometries, index=result.index, crs=frame.crs)
    result["GEOMETRY_PROCESSING"] = states
    report = {
        "policy": policy,
        "input_records": len(frame),
        "retained_records": len(result),
        "unchanged_valid_records": len(frame) - len(records),
        "repaired_records": sum(
            r["state"] == "made_valid_not_source_certified" for r in records
        ),
        "quarantined_records": sum(r["state"] == "quarantined" for r in records),
        "source_completeness_established": False,
        "absence_established": False,
        "records": records,
    }
    return PolygonAudit(result, report)


def prepare_mixed_habitat_inventory(
    frame: Any, *, policy: GeometryPolicy = "reject"
) -> PolygonAudit:
    """Audit area evidence while retaining valid, explicitly non-areal observations."""
    import geopandas as gpd
    import pandas as pd

    if not isinstance(frame, gpd.GeoDataFrame) or frame.crs is None:
        raise ValueError("Habitat evidence requires a GeoDataFrame with explicit CRS")
    if (
        "RECORD_ID" not in frame
        or frame.RECORD_ID.isna().any()
        or frame.RECORD_ID.astype(str).str.strip().eq("").any()
        or frame.RECORD_ID.astype(str).duplicated().any()
    ):
        raise ValueError("Habitat evidence requires unique, nonempty record IDs")
    if "GEOMETRY_PROCESSING" in frame:
        raise ValueError("GEOMETRY_PROCESSING already exists; retain the prior audit")
    polygons = frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if "SUPPORTS_AREA" in frame:
        polygons = polygons | frame.SUPPORTS_AREA.fillna(False).astype(bool)
    non_areal = frame.loc[~polygons].copy()
    if (
        non_areal.geometry.isna().any()
        or non_areal.geometry.is_empty.any()
        or not non_areal.geometry.is_valid.all()
    ):
        raise ValueError("Invalid non-polygon evidence requires source-specific review")
    audited = audit_polygon_inventory(frame.loc[polygons], policy=policy)
    non_areal["GEOMETRY_PROCESSING"] = "valid_non_areal_source_geometry"
    combined = gpd.GeoDataFrame(
        pd.concat([audited.frame, non_areal]), geometry="geometry", crs=frame.crs
    ).sort_index()
    report = {
        **audited.report,
        "normalized_inventory_records": len(frame),
        "retained_non_areal_records": len(non_areal),
    }
    return PolygonAudit(combined, report)
