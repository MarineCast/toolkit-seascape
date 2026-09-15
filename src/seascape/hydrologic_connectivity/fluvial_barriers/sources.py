"""Source normalization and evidence contracts for fluvial barriers."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import Point, box

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.acquisition import (
    load_download_config as load_habitat_download_config,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.values import (
    clean_optional_text,
    iter_frame_records,
)

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

LOGGER = logging.getLogger(__name__)
_clean = clean_optional_text

PREFIX = "FLUVIAL_BARRIERS"

BARRIER_TYPES = {"DAM", "CULVERT", "WATERFALL", "TIDE_GATE", "NATURAL_BARRIER"}

PASSAGE_STATUSES = {
    "BLOCKED",
    "PARTIAL",
    "PASSABLE",
    "POTENTIAL_BARRIER",
    "UNKNOWN",
    "NOT_ASSESSED",
}

COUNT_COLUMNS = [
    "MAPPED_UPSTREAM_BARRIER_COUNT",
    "MAPPED_UPSTREAM_DAM_COUNT",
    "MAPPED_UPSTREAM_CULVERT_COUNT",
    "MAPPED_UPSTREAM_WATERFALL_COUNT",
    "MAPPED_UPSTREAM_TIDE_GATE_COUNT",
    "MAPPED_ASSESSED_SITE_COUNT",
    "MAPPED_BLOCKED_COUNT",
    "MAPPED_PARTIAL_COUNT",
    "MAPPED_PASSABLE_COUNT",
    "MAPPED_POTENTIAL_BARRIER_COUNT",
    "MAPPED_UNKNOWN_STATUS_COUNT",
]


def validate_feature_table(frame: pd.DataFrame, resolution: int) -> None:
    """Validate the public fluvial-barrier model-feature contract."""

    required = {
        "H3_INDEX",
        "H3_RESOLUTION",
        "BARRIER_INVENTORY_STATE",
        "MAPPED_UPSTREAM_BARRIER_PRESENT",
        "MAPPED_UPSTREAM_BARRIER_COUNT",
        "PASSAGE_STATUS_COVERAGE_FRAC",
        "NEAREST_MAPPED_BARRIER_FROM_MOUTH_KM",
        "WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Fluvial-barrier feature table is missing columns: {missing}")
    if frame.empty or frame["H3_INDEX"].isna().any() or not frame["H3_INDEX"].is_unique:
        raise ValueError("Fluvial-barrier features require one non-null row per H3 cell.")
    if not frame["H3_RESOLUTION"].eq(resolution).all():
        raise ValueError(f"Fluvial-barrier table contains non-r{resolution} rows.")
    for column in [
        *COUNT_COLUMNS,
        "NEAREST_MAPPED_BARRIER_FROM_MOUTH_KM",
        "WATER_NETWORK_DISTANCE_TO_BARRIER_AFFECTED_MOUTH_M",
    ]:
        if (pd.to_numeric(frame[column], errors="coerce").dropna() < 0).any():
            raise ValueError(f"Fluvial-barrier non-negative metric is negative: {column}")
    if (
        not pd.to_numeric(frame["PASSAGE_STATUS_COVERAGE_FRAC"], errors="coerce")
        .dropna()
        .between(0, 1)
        .all()
    ):
        raise ValueError("Passage-status coverage must be null or in [0, 1].")
    no_records = frame["BARRIER_INVENTORY_STATE"].eq("NO_MAPPED_BARRIER_RECORDS")
    if frame.loc[no_records, "MAPPED_UPSTREAM_BARRIER_COUNT"].notna().any():
        raise ValueError("No-record basins must not be encoded as zero barrier counts.")


INVENTORY_COLUMNS = [
    "SOURCE_RECORD_ID",
    "SOURCE_DATASET",
    "SOURCE_FEATURE_ID",
    "JURISDICTION",
    "BARRIER_TYPE",
    "BARRIER_SUBTYPE",
    "ORIGIN",
    "PASSAGE_STATUS",
    "PASSABLE_FRACTION",
    "PHYSICAL_STATUS",
    "REMEDIATION_STATUS",
    "ASSESSMENT_DATE",
    "STATUS_DATE",
    "SPECIES_SCOPE",
    "FISHWAY_PRESENT",
    "EVIDENCE_CLASS",
    "CONFIDENCE_CLASS",
    "SOURCE_PRIORITY",
    "SOURCE_RAW_TYPE",
    "SOURCE_RAW_STATUS",
    "SOURCE_PROPERTIES_JSON",
    "IS_CANONICAL",
    "CANONICAL_BARRIER_ID",
    "DUPLICATE_DISTANCE_M",
    "geometry",
]

NETWORK_COLUMNS = [
    "NETWORK_SNAP_STATUS",
    "NETWORK_SOURCE",
    "NETWORK_SNAP_DISTANCE_M",
    "FLUVIAL_SEGMENT_ID",
    "RIVER_BASIN_ID",
    "OUTLET_SUBBASIN_ID",
    "FLUVIAL_MOUTH_ID",
    "ALONG_RIVER_DISTANCE_TO_MOUTH_KM",
    "NETWORK_QC_REASON",
]


def _processing(config_path: str | Path) -> tuple[dict[str, Any], Path]:
    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get(SECTION_NAME), SECTION_NAME)
    processing = _mapping(section.get("processing"), f"{SECTION_NAME}.processing")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    for key in (
        "deduplication_tolerance_m",
        "river_network_snap_max_m",
        "source_water_max_distance_m",
        "graph_connector_max_distance_m",
        "graph_connector_candidate_limit",
    ):
        if float(processing[key]) <= 0:
            raise ValueError(f"{SECTION_NAME}.processing.{key} must be positive.")
    return processing, base_dir


def _value(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row.index:
            value = row[name]
            return None if value is None or pd.isna(value) else value
    normalized = {re.sub(r"[^a-z0-9]", "", str(column).casefold()): column for column in row.index}
    for name in names:
        column = normalized.get(re.sub(r"[^a-z0-9]", "", name.casefold()))
        if column is not None:
            value = row[column]
            return None if value is None or pd.isna(value) else value
    return None


def _properties(row: pd.Series, geometry_name: str) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in row.drop(labels=[geometry_name], errors="ignore").items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        clean[str(key)] = value.item() if isinstance(value, np.generic) else value
    return clean


def _json_properties(values: Mapping[str, Any]) -> str:
    return json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))


def _date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return _clean(value)
    return parsed.date().isoformat()


def _representative_point(geometry: Any) -> Point:
    if geometry.geom_type == "Point":
        return geometry
    if geometry.geom_type in {"LineString", "LinearRing"}:
        return geometry.interpolate(0.5, normalized=True)
    if geometry.geom_type == "MultiLineString":
        longest = max(geometry.geoms, key=lambda item: item.length)
        return longest.interpolate(0.5, normalized=True)
    return geometry.representative_point()


def _record(
    *,
    source_name: str,
    source_id: Any,
    jurisdiction: str,
    barrier_type: str,
    subtype: Any,
    origin: str,
    passage_status: str,
    passable_fraction: float | None,
    physical_status: Any,
    remediation_status: Any,
    assessment_date: Any,
    status_date: Any,
    species_scope: Any,
    fishway_present: bool | None,
    evidence_class: str,
    confidence: int,
    priority: int,
    raw_type: Any,
    raw_status: Any,
    properties: Mapping[str, Any],
    geometry: Any,
) -> dict[str, Any]:
    source_id = str(source_id)
    return {
        "SOURCE_RECORD_ID": f"{source_name}:{source_id}",
        "SOURCE_DATASET": source_name,
        "SOURCE_FEATURE_ID": source_id,
        "JURISDICTION": jurisdiction,
        "BARRIER_TYPE": barrier_type,
        "BARRIER_SUBTYPE": _clean(subtype),
        "ORIGIN": origin,
        "PASSAGE_STATUS": passage_status,
        "PASSABLE_FRACTION": passable_fraction,
        "PHYSICAL_STATUS": _clean(physical_status),
        "REMEDIATION_STATUS": _clean(remediation_status),
        "ASSESSMENT_DATE": _date(assessment_date),
        "STATUS_DATE": _date(status_date),
        "SPECIES_SCOPE": _clean(species_scope),
        "FISHWAY_PRESENT": fishway_present,
        "EVIDENCE_CLASS": evidence_class,
        "CONFIDENCE_CLASS": int(confidence),
        "SOURCE_PRIORITY": int(priority),
        "SOURCE_RAW_TYPE": _clean(raw_type),
        "SOURCE_RAW_STATUS": _clean(raw_status),
        "SOURCE_PROPERTIES_JSON": _json_properties(properties),
        "IS_CANONICAL": True,
        "CANONICAL_BARRIER_ID": None,
        "DUPLICATE_DISTANCE_M": np.nan,
        "geometry": _representative_point(geometry),
    }


def normalize_pscis_status(value: Any) -> tuple[str, float | None]:
    """Normalize a PSCIS barrier description without inventing passage."""

    text = (_clean(value) or "").casefold()
    if "passable" in text and "no barrier" in text:
        return "PASSABLE", 1.0
    if "potential" in text:
        return "POTENTIAL_BARRIER", None
    if "partial" in text:
        return "PARTIAL", None
    if text == "barrier" or ("barrier" in text and "no barrier" not in text):
        return "BLOCKED", 0.0
    return "UNKNOWN", None


def normalize_wdfw_status(status: Any, percent: Any) -> tuple[str, float | None]:
    """Normalize WDFW coded assessment fields to an explicit status enum."""

    status_text = (_clean(status) or "").casefold()
    percent_text = (_clean(percent) or "").casefold()
    try:
        status_text = str(int(float(status_text)))
    except ValueError:
        pass
    try:
        percent_text = str(int(float(percent_text)))
    except ValueError:
        pass
    percent_map = {
        "10": 0.0,
        "20": 0.33,
        "30": 0.67,
        "40": 1.0,
        "0%": 0.0,
        "33%": 0.33,
        "67%": 0.67,
        "100%": 1.0,
    }
    fraction = percent_map.get(percent_text)
    if fraction == 1.0 or status_text in {"20", "no", "not a barrier", "no barrier"}:
        return "PASSABLE", 1.0
    if fraction in {0.33, 0.67}:
        return "PARTIAL", fraction
    if fraction == 0.0 or status_text in {"10", "yes", "barrier"}:
        return "BLOCKED", 0.0 if fraction is None else fraction
    return "UNKNOWN", None


def _barrier_type(text: Any, *, default: str = "OTHER_CROSSING") -> str:
    value = (_clean(text) or "").casefold()
    if "culvert" in value or value.strip() == "cv":
        return "CULVERT"
    if "tide gate" in value or "tidal gate" in value or "floodbox" in value:
        return "TIDE_GATE"
    if "waterfall" in value or re.search(r"\bfalls?\b", value) or "cascade" in value:
        return "WATERFALL"
    if "beaver dam" in value:
        return "NATURAL_BARRIER"
    if "dam" in value:
        return "DAM"
    if "natural barrier" in value or "natural obstacle" in value:
        return "NATURAL_BARRIER"
    return default


def _read_geo(path: Path):
    import geopandas as gpd

    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"Barrier source lacks CRS metadata: {path}")
    return frame.to_crs("EPSG:4326")


def _normalize_pscis(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        if item.geometry is None or item.geometry.is_empty:
            continue
        properties = _properties(item, frame.geometry.name)
        source_id = _value(item, "STREAM_CROSSING_ID", "ASSESSMENT_ID", "OBJECTID") or position
        raw_type = " ".join(
            filter(
                None,
                map(
                    _clean,
                    (
                        _value(
                            item,
                            "CURRENT_CROSSING_TYPE_DESC",
                            "CURRENT_CROSSING_TYPE_DESCRIPTION",
                            "CROSSING_TYPE_DESC",
                            "CROSSING_TYPE_DESCRIPTION",
                            "CROSSING_TYPE",
                        ),
                        _value(
                            item,
                            "CURRENT_CROSSING_SUBTYPE_DESC",
                            "CURRENT_CROSSING_SUBTYPE_DESCRIPTION",
                            "CROSSING_SUBTYPE_DESC",
                            "CROSSING_SUBTYPE_DESCRIPTION",
                            "CROSSING_SUBTYPE",
                        ),
                    ),
                ),
            )
        )
        raw_status = _value(item, "CURRENT_BARRIER_DESCRIPTION", "BARRIER_DESCRIPTION")
        passage, fraction = normalize_pscis_status(raw_status)
        remediation = _value(item, "CURRENT_PSCIS_STATUS", "PSCIS_STATUS")
        rows.append(
            _record(
                source_name=name,
                source_id=source_id,
                jurisdiction="BC",
                barrier_type=_barrier_type(raw_type),
                subtype=raw_type,
                origin=(
                    "ANTHROPOGENIC" if _barrier_type(raw_type) != "NATURAL_BARRIER" else "NATURAL"
                ),
                passage_status=passage,
                passable_fraction=fraction,
                physical_status=None,
                remediation_status=remediation,
                assessment_date=_value(item, "ASSESSMENT_DATE"),
                status_date=_value(item, "CURRENT_STATUS_DATE", "LAST_UPDATE_DATE"),
                species_scope=_value(item, "FISH_SPECIES", "SPECIES"),
                fishway_present=None,
                evidence_class=str(source["evidence_class"]),
                confidence=3,
                priority=100,
                raw_type=raw_type,
                raw_status=raw_status,
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_obstacles(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        if item.geometry is None or item.geometry.is_empty:
            continue
        properties = _properties(item, frame.geometry.name)
        raw_type = " ".join(
            filter(
                None,
                map(
                    _clean,
                    (
                        _value(item, "OBSTACLE_CODE"),
                        _value(item, "OBSTACLE_NAME"),
                        _value(item, "FEATURE_CODE"),
                    ),
                ),
            )
        )
        rows.append(
            _record(
                source_name=name,
                source_id=_value(item, "FISH_OBSTACLE_POINT_ID", "OBJECTID") or position,
                jurisdiction="BC",
                barrier_type=_barrier_type(raw_type, default="NATURAL_BARRIER"),
                subtype=raw_type,
                origin=(
                    "NATURAL"
                    if _barrier_type(raw_type, default="NATURAL_BARRIER")
                    in {"WATERFALL", "NATURAL_BARRIER"}
                    else "ANTHROPOGENIC"
                ),
                passage_status="NOT_ASSESSED",
                passable_fraction=None,
                physical_status=_value(item, "OBSTACLE_STATUS"),
                remediation_status=None,
                assessment_date=_value(item, "SURVEY_DATE"),
                status_date=None,
                species_scope=_value(item, "SPECIES_CODE"),
                fishway_present=None,
                evidence_class=str(source["evidence_class"]),
                confidence=2,
                priority=70,
                raw_type=raw_type,
                raw_status=None,
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_dams(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        if item.geometry is None or item.geometry.is_empty:
            continue
        properties = _properties(item, frame.geometry.name)
        raw_type = _value(item, "DAM_TYPE", "STRUCTURE_TYPE", "DAM_NAME") or "dam"
        rows.append(
            _record(
                source_name=name,
                source_id=_value(item, "WRIS_DP_SYSID", "DAM_ID", "DAM_NUMBER", "OBJECTID")
                or position,
                jurisdiction="BC",
                barrier_type="DAM",
                subtype=raw_type,
                origin="ANTHROPOGENIC",
                passage_status="NOT_ASSESSED",
                passable_fraction=None,
                physical_status=_value(item, "DAM_STATUS", "STATUS"),
                remediation_status=None,
                assessment_date=None,
                status_date=_value(item, "LAST_UPDATE_DATE", "UPDATE_DATE"),
                species_scope=None,
                fishway_present=None,
                evidence_class=str(source["evidence_class"]),
                confidence=3,
                priority=80,
                raw_type=raw_type,
                raw_status=_value(item, "DAM_STATUS", "STATUS"),
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_tide_gates(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        if item.geometry is None or item.geometry.is_empty:
            continue
        works_type = (_clean(_value(item, "WORKS_TYPE_APPURT")) or "").upper()
        flood_gate = _clean(_value(item, "FLOOD_BOX_GATE_TYPE"))
        outlet_gate = _clean(_value(item, "OUTLET_POINT_GATE_TYPE"))
        if works_type != "FLOODBOX" and not (works_type == "OUTLET POINT" and outlet_gate):
            continue
        properties = _properties(item, frame.geometry.name)
        subtype = flood_gate or outlet_gate or "gate type unmapped"
        rows.append(
            _record(
                source_name=name,
                source_id=_value(item, "FPW_AS_SYSID", "OBJECTID") or position,
                jurisdiction="BC",
                barrier_type="TIDE_GATE",
                subtype=subtype,
                origin="ANTHROPOGENIC",
                passage_status="NOT_ASSESSED",
                passable_fraction=None,
                physical_status=_value(item, "PHYSICAL_STATUS", "STATUS"),
                remediation_status=None,
                assessment_date=_value(item, "SURVEY_DATE"),
                status_date=_value(item, "FEATURE_EFFECTIVE_DATE"),
                species_scope=None,
                fishway_present=None,
                evidence_class=str(source["evidence_class"]),
                confidence=3,
                priority=90,
                raw_type=f"{works_type} {subtype}",
                raw_status=None,
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_wdfw(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        if item.geometry is None or item.geometry.is_empty:
            continue
        properties = _properties(item, frame.geometry.name)
        raw_type = _value(item, "FeatureType")
        data_source = _value(item, "DataSource")
        type_text = f"{_clean(raw_type) or ''} {_clean(data_source) or ''}"
        barrier_type = _barrier_type(type_text)
        if barrier_type == "OTHER_CROSSING" and "natural" in type_text.casefold():
            barrier_type = "NATURAL_BARRIER"
        raw_status = _value(item, "FishPassageBarrierStatusCode")
        passage, fraction = normalize_wdfw_status(
            raw_status,
            _value(item, "PercentFishPassableCode"),
        )
        feature_lower = (_clean(raw_type) or "").casefold()
        rows.append(
            _record(
                source_name=name,
                source_id=_value(item, "SiteRecordID", "SiteId", "OBJECTID") or position,
                jurisdiction="WA",
                barrier_type=barrier_type,
                subtype=raw_type,
                origin=(
                    "NATURAL"
                    if barrier_type in {"WATERFALL", "NATURAL_BARRIER"}
                    else "ANTHROPOGENIC"
                ),
                passage_status=passage,
                passable_fraction=fraction,
                physical_status=None,
                remediation_status=_value(item, "BarrierCorrectionYearsText"),
                assessment_date=_value(item, "SurveyDate"),
                status_date=None,
                species_scope=_value(item, "PotentialSpecies"),
                fishway_present=True if "fishway" in feature_lower else None,
                evidence_class=str(source["evidence_class"]),
                confidence=3,
                priority=100,
                raw_type=raw_type,
                raw_status=raw_status,
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _truthy(value: Any) -> bool:
    return (_clean(value) or "").casefold() in {"true", "yes", "y", "1", "present"}


def _normalize_wa_tidal(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        gate = _value(item, "WCF_Tide_Flood_Gates_Present", "Tide_Flood_Gates_Present")
        if item.geometry is None or item.geometry.is_empty or not _truthy(gate):
            continue
        properties = _properties(item, frame.geometry.name)
        impact = _value(item, "Tidal_Connectivity_Impacts")
        impact_text = (_clean(impact) or "").casefold()
        passage = (
            "BLOCKED" if any(word in impact_text for word in ("complete", "blocked")) else "UNKNOWN"
        )
        rows.append(
            _record(
                source_name=name,
                source_id=_value(item, "OBJECTID", "GlobalID") or position,
                jurisdiction="WA",
                barrier_type="TIDE_GATE",
                subtype="tidal flood gate",
                origin="ANTHROPOGENIC",
                passage_status=passage,
                passable_fraction=0.0 if passage == "BLOCKED" else None,
                physical_status=_value(item, "Physical_Status"),
                remediation_status=None,
                assessment_date=_value(item, "Field_Verification_Date", "SurveyDate"),
                status_date=None,
                species_scope=None,
                fishway_present=None,
                evidence_class=str(source["evidence_class"]),
                confidence=3,
                priority=90,
                raw_type="tidal flood gate",
                raw_status=impact,
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_usgs(path: Path, name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = _read_geo(path)
    rows = []
    for position, item in iter_frame_records(frame):
        if item.geometry is None or item.geometry.is_empty:
            continue
        properties = _properties(item, frame.geometry.name)
        raw_type = " ".join(
            str(value) for key, value in properties.items() if "type" in str(key).casefold()
        )
        combined = f"{raw_type} {' '.join(map(str, properties.values()))}".casefold()
        if "rapid" in combined and not any(word in combined for word in ("waterfall", "falls")):
            continue
        rows.append(
            _record(
                source_name=name,
                source_id=_value(
                    item, "feature id", "OBJECTID", "Permanent_Identifier", "GNIS_ID", "ID"
                )
                or position,
                jurisdiction="WA",
                barrier_type="WATERFALL",
                subtype=raw_type or "waterfall",
                origin="NATURAL",
                passage_status="NOT_ASSESSED",
                passable_fraction=None,
                physical_status=None,
                remediation_status=None,
                assessment_date=None,
                status_date=None,
                species_scope=None,
                fishway_present=None,
                evidence_class=str(source["evidence_class"]),
                confidence=2,
                priority=60,
                raw_type=raw_type or "waterfall",
                raw_status=None,
                properties=properties,
                geometry=item.geometry,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def validate_inventory(frame: Any) -> None:
    missing = sorted(set(INVENTORY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Fluvial-barrier inventory is missing columns: {missing}")
    if frame.empty or frame["SOURCE_RECORD_ID"].isna().any():
        raise ValueError("Fluvial-barrier inventory must contain identified records.")
    if frame["SOURCE_RECORD_ID"].duplicated().any():
        raise ValueError("Fluvial-barrier source record IDs must be unique.")
    if not set(frame["PASSAGE_STATUS"].dropna()).issubset(PASSAGE_STATUSES):
        raise ValueError("Fluvial-barrier passage status is outside the stable enum.")
    fractions = pd.to_numeric(frame["PASSABLE_FRACTION"], errors="coerce").dropna()
    if not fractions.between(0.0, 1.0).all():
        raise ValueError("Passable fractions must be null or in [0, 1].")
    if frame.crs is None:
        raise ValueError("Fluvial-barrier inventory must retain CRS metadata.")


NORMALIZERS = {
    "bc_pscis_assessments": _normalize_pscis,
    "bc_provincial_obstacles": _normalize_obstacles,
    "bc_dams": _normalize_dams,
    "bc_flood_appurtenances": _normalize_tide_gates,
    "wa_wdfw_fish_passage_sites": _normalize_wdfw,
    "wa_wdfw_tidal_restrictions": _normalize_wa_tidal,
    "usgs_waterfalls": _normalize_usgs,
}


def load_source_inventory(config_path: str | Path = DEFAULT_CONFIG_PATH):
    """Normalize every configured authoritative snapshot into one schema."""

    import geopandas as gpd

    download = load_habitat_download_config(SECTION_NAME, config_path)
    bounds = box(
        download.bbox["min_lon"],
        download.bbox["min_lat"],
        download.bbox["max_lon"],
        download.bbox["max_lat"],
    )
    frames = []
    for name, source in download.sources.items():
        if not bool(source.get("enabled", True)):
            continue
        path = download.raw_dir / str(source["raw_filename"])
        if not path.exists():
            raise FileNotFoundError(f"Fluvial-barrier source not found: {path}. Run download.py.")
        normalizer = NORMALIZERS.get(name)
        if normalizer is None:
            raise ValueError(f"No fluvial-barrier normalizer is registered for {name}.")
        frame = normalizer(path, name, source)
        if not frame.empty:
            frame = frame.loc[frame.geometry.intersects(bounds)].copy()
            frames.append(frame)
    if not frames:
        raise ValueError("No configured source produced a fluvial-barrier record.")
    inventory = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    inventory = inventory.loc[:, INVENTORY_COLUMNS].copy()
    inventory["SOURCE_RECORD_ID"] = inventory["SOURCE_RECORD_ID"].astype("string")
    duplicated = inventory["SOURCE_RECORD_ID"].duplicated(keep=False)
    if duplicated.any():
        inventory.loc[duplicated, "SOURCE_RECORD_ID"] = [
            f"{value}:{index}"
            for index, value in enumerate(inventory.loc[duplicated, "SOURCE_RECORD_ID"])
        ]
    validate_inventory(inventory)
    return inventory.sort_values("SOURCE_RECORD_ID").reset_index(drop=True)


def deduplicate_inventory(frame: Any, tolerance_m: float):
    """Select a canonical record while retaining every overlap in lineage."""

    import geopandas as gpd

    validate_inventory(frame)
    result = frame.copy().reset_index(drop=True)
    projected = result.to_crs("EPSG:6933")
    result["IS_CANONICAL"] = True
    result["CANONICAL_BARRIER_ID"] = pd.NA
    result["DUPLICATE_DISTANCE_M"] = np.nan
    lineage_rows: list[dict[str, Any]] = []
    for (jurisdiction, barrier_type), group in projected.groupby(
        ["JURISDICTION", "BARRIER_TYPE"], sort=True
    ):
        group = group.copy()
        spatial_index = group.sindex
        ordered = group.sort_values(
            ["SOURCE_PRIORITY", "CONFIDENCE_CLASS", "SOURCE_RECORD_ID"],
            ascending=[False, False, True],
        )
        canonical_indices: set[int] = set()
        for index, row in iter_frame_records(ordered):
            candidates = spatial_index.query(
                row.geometry.buffer(float(tolerance_m)), predicate="intersects"
            )
            candidate_indices = [int(group.index[int(position)]) for position in candidates]
            matches = [
                candidate for candidate in candidate_indices if candidate in canonical_indices
            ]
            if matches:
                distances = [
                    (float(projected.loc[candidate].geometry.distance(row.geometry)), candidate)
                    for candidate in matches
                ]
                distance, canonical_index = min(
                    distances,
                    key=lambda item: (item[0], str(result.loc[item[1], "SOURCE_RECORD_ID"])),
                )
                canonical_id = str(result.loc[canonical_index, "CANONICAL_BARRIER_ID"])
                result.loc[index, "IS_CANONICAL"] = False
                result.loc[index, "CANONICAL_BARRIER_ID"] = canonical_id
                result.loc[index, "DUPLICATE_DISTANCE_M"] = distance
                relationship = "OVERLAPPING_SOURCE_RECORD"
            else:
                canonical_indices.add(int(index))
                digest = hashlib.sha1(str(row["SOURCE_RECORD_ID"]).encode("utf-8")).hexdigest()[:16]
                canonical_id = f"FLUVIAL_BARRIER_{digest}"
                result.loc[index, "CANONICAL_BARRIER_ID"] = canonical_id
                distance = 0.0
                relationship = "CANONICAL_SOURCE_RECORD"
            lineage_rows.append(
                {
                    "CANONICAL_BARRIER_ID": canonical_id,
                    "SOURCE_RECORD_ID": str(row["SOURCE_RECORD_ID"]),
                    "SOURCE_DATASET": str(row["SOURCE_DATASET"]),
                    "RELATIONSHIP": relationship,
                    "MATCH_DISTANCE_M": distance,
                    "JURISDICTION": jurisdiction,
                    "BARRIER_TYPE": barrier_type,
                }
            )
    lineage = (
        pd.DataFrame(lineage_rows)
        .sort_values(["CANONICAL_BARRIER_ID", "SOURCE_RECORD_ID"])
        .reset_index(drop=True)
    )
    result = gpd.GeoDataFrame(result, geometry="geometry", crs=frame.crs)
    validate_inventory(result)
    return result.sort_values("SOURCE_RECORD_ID").reset_index(drop=True), lineage
