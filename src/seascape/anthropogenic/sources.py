"""Source normalization and schema contracts for anthropogenic seascape data."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely import make_valid, union_all
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import resolve_config_path
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)
from seascape.utils.acquisition import (
    load_download_config as load_habitat_download_config,
)
from seascape.utils.config import require_mapping as _mapping
from seascape.utils.values import iter_frame_records

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

LOGGER = logging.getLogger(__name__)

PREFIX = "ANTHROPOGENIC"

INVENTORY_COLUMNS = [
    "RECORD_ID",
    "SOURCE_DATASET",
    "SOURCE_FEATURE_ID",
    "JURISDICTION",
    "FEATURE_CLASS",
    "FEATURE_SUBTYPE",
    "EVIDENCE_CLASS",
    "OBSERVATION_YEAR",
    "SOURCE_PRIORITY",
    "CONFIDENCE_CLASS",
    "GEOMETRY_PRECISION_CLASS",
    "SUPPORTS_AREA",
    "SUPPORTS_SHORELINE_DENOMINATOR",
    "ARMORING_FRACTION_ESTIMATE",
    "STRUCTURE_COUNT",
    "IS_CANONICAL",
    "DUPLICATE_OF_RECORD_ID",
    "SOURCE_PROPERTIES_JSON",
    "geometry",
]

DISTANCE_FEATURES = {
    "DISTANCE_TO_SEAWALL_M": "seawall",
    "DISTANCE_TO_BREAKWATER_M": "breakwater",
    "DISTANCE_TO_JETTY_M": "jetty",
    "DISTANCE_TO_CAUSEWAY_M": "causeway",
    "DISTANCE_TO_PIER_M": "pier",
    "DISTANCE_TO_FERRY_TERMINAL_M": "ferry_terminal",
    "DISTANCE_TO_MARINA_M": "marina",
    "DISTANCE_TO_PORT_M": "port",
    "DISTANCE_TO_DREDGED_CHANNEL_M": "dredged_channel",
    "DISTANCE_TO_DISPOSAL_SITE_M": "disposal_site",
    "DISTANCE_TO_ARTIFICIAL_REEF_M": "artificial_reef",
    "DISTANCE_TO_AQUACULTURE_M": "aquaculture",
}

OVERWATER_CLASSES = {"pier", "ferry_terminal", "marina", "port"}

CONFIDENCE_FAMILIES = {
    "ARMORING": {"shoreline_survey", "seawall"},
    "OVERWATER": OVERWATER_CLASSES,
    "DREDGING": {"dredged_channel"},
    "DISPOSAL": {"disposal_site"},
    "AQUACULTURE": {"aquaculture"},
    "ARTIFICIAL_REEF": {"artificial_reef"},
}

FRACTION_COLUMNS = {
    "SHORELINE_ARMORING_FRAC",
    "DREDGED_AREA_FRAC",
    "DISPOSAL_SITE_AREA_FRAC",
    "AQUACULTURE_FOOTPRINT_FRAC",
}

PRESENCE_COLUMNS = {"ARTIFICIAL_REEF_PRESENCE", "AQUACULTURE_PRESENCE"}

REQUIRED_FEATURE_COLUMNS = {
    "H3_INDEX",
    "H3_RESOLUTION",
    *DISTANCE_FEATURES,
    *FRACTION_COLUMNS,
    *PRESENCE_COLUMNS,
    "OVERWATER_STRUCTURE_DENSITY_PER_KM2",
    "OVERWATER_STRUCTURE_COUNT_WITHIN_5KM",
    "NETWORK_DISTANCE_QC_REASON",
}


def _processing(config_path: str | Path) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    raw = load_data_config(path, domains="SEASCAPE_LAYER")
    section = _mapping(raw.get(SECTION_NAME), SECTION_NAME)
    processing = _mapping(section.get("processing"), f"{SECTION_NAME}.processing")
    for key in (
        "deduplication_tolerance_m",
        "source_water_max_distance_m",
        "graph_connector_max_distance_m",
        "graph_connector_candidate_limit",
    ):
        if float(processing[key]) <= 0:
            raise ValueError(f"{SECTION_NAME}.processing.{key} must be positive.")
    return processing


def validate_feature_table(frame: pd.DataFrame, resolution: int) -> None:
    """Fail closed on the model-output schema and metric domains."""

    missing = sorted(REQUIRED_FEATURE_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(f"Anthropogenic feature table is missing columns: {missing}")
    if frame.empty or frame["H3_INDEX"].isna().any() or not frame["H3_INDEX"].is_unique:
        raise ValueError("Anthropogenic features require one non-null row per H3 cell.")
    if not frame["H3_RESOLUTION"].eq(int(resolution)).all():
        raise ValueError(f"Anthropogenic features contain non-r{resolution} rows.")
    for column in FRACTION_COLUMNS:
        if not frame[column].dropna().astype(float).between(0.0, 1.0).all():
            raise ValueError(f"Anthropogenic fraction is outside [0, 1]: {column}")
    for column in PRESENCE_COLUMNS:
        values = set(frame[column].dropna().astype(float).unique())
        if not values.issubset({0.0, 1.0}):
            raise ValueError(f"Anthropogenic presence is not three-state encoded: {column}")
    for column in [
        *DISTANCE_FEATURES,
        "OVERWATER_STRUCTURE_DENSITY_PER_KM2",
        "OVERWATER_STRUCTURE_COUNT_WITHIN_5KM",
    ]:
        if (frame[column].dropna().astype(float) < 0).any():
            raise ValueError(f"Anthropogenic non-negative metric is negative: {column}")


def validate_confidence_table(
    frame: pd.DataFrame,
    resolution: int,
    feature_cells: pd.Series,
) -> None:
    """Validate confidence/provenance fields stay parallel to model features."""

    required = {"H3_INDEX", "H3_RESOLUTION"}
    for family in [*CONFIDENCE_FAMILIES, "ANTHROPOGENIC"]:
        required.update(
            {
                f"{family}_SOURCE_DATASETS",
                f"{family}_SOURCE_COUNT",
                f"{family}_CONFIDENCE",
                f"{family}_UNMAPPED_AREA",
            }
        )
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Anthropogenic confidence table is missing columns: {missing}")
    if frame.empty or frame["H3_INDEX"].isna().any() or not frame["H3_INDEX"].is_unique:
        raise ValueError("Anthropogenic confidence requires one non-null row per H3 cell.")
    if not frame["H3_RESOLUTION"].eq(int(resolution)).all():
        raise ValueError(f"Anthropogenic confidence contains non-r{resolution} rows.")
    if set(frame["H3_INDEX"].astype(str)) != set(feature_cells.astype(str)):
        raise ValueError("Anthropogenic feature and confidence H3 support differs.")
    for family in [*CONFIDENCE_FAMILIES, "ANTHROPOGENIC"]:
        if not frame[f"{family}_CONFIDENCE"].astype(int).between(0, 3).all():
            raise ValueError(f"Anthropogenic confidence is outside [0, 3]: {family}")


def _json_properties(properties: Mapping[str, Any]) -> str:
    clean: dict[str, Any] = {}
    for key, value in properties.items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        if isinstance(value, np.generic):
            value = value.item()
        clean[str(key)] = value
    return json.dumps(clean, sort_keys=True, default=str, separators=(",", ":"))


def _record(
    *,
    record_id: str,
    source_dataset: str,
    source_feature_id: str,
    jurisdiction: str,
    feature_class: str,
    feature_subtype: str | None,
    evidence_class: str,
    source_priority: int,
    confidence_class: int,
    geometry_precision_class: str,
    geometry: Any,
    supports_area: bool = False,
    supports_shoreline_denominator: bool = False,
    armoring_fraction_estimate: float | None = None,
    structure_count: float = 0.0,
    observation_year: int | None = None,
    properties: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "RECORD_ID": record_id,
        "SOURCE_DATASET": source_dataset,
        "SOURCE_FEATURE_ID": source_feature_id,
        "JURISDICTION": jurisdiction,
        "FEATURE_CLASS": feature_class,
        "FEATURE_SUBTYPE": feature_subtype,
        "EVIDENCE_CLASS": evidence_class,
        "OBSERVATION_YEAR": observation_year,
        "SOURCE_PRIORITY": source_priority,
        "CONFIDENCE_CLASS": confidence_class,
        "GEOMETRY_PRECISION_CLASS": geometry_precision_class,
        "SUPPORTS_AREA": supports_area,
        "SUPPORTS_SHORELINE_DENOMINATOR": supports_shoreline_denominator,
        "ARMORING_FRACTION_ESTIMATE": armoring_fraction_estimate,
        "STRUCTURE_COUNT": float(structure_count),
        "IS_CANONICAL": True,
        "DUPLICATE_OF_RECORD_ID": None,
        "SOURCE_PROPERTIES_JSON": _json_properties(properties or {}),
        "geometry": geometry,
    }


def classify_osm_tags(tags: Mapping[str, Any]) -> list[str]:
    """Map OSM/OpenSeaMap tags to the stable Seascape Toolkit feature ontology."""

    values = {str(key): str(value).strip().lower() for key, value in tags.items()}
    classes: set[str] = set()
    man_made = values.get("man_made")
    mapped_man_made = {
        "seawall": "seawall",
        "breakwater": "breakwater",
        "groyne": "jetty",
        "jetty": "jetty",
        "pier": "pier",
        "causeway": "causeway",
        "quay": "port",
    }.get(man_made)
    if mapped_man_made:
        classes.add(mapped_man_made)
    if values.get("amenity") == "ferry_terminal":
        classes.add("ferry_terminal")
    if values.get("leisure") == "marina":
        classes.add("marina")
    if values.get("industrial") == "port" or values.get("harbour") == "yes":
        classes.add("port")
    if values.get("landuse") == "aquaculture" or "aquaculture" in values:
        classes.add("aquaculture")
    seamark_type = values.get("seamark:type")
    seamark_classes = {
        "causeway": "causeway",
        "dredged_area": "dredged_channel",
        "dumping_ground": "disposal_site",
        "artificial_reef": "artificial_reef",
        "marine_farm": "aquaculture",
        "harbour": "port",
    }
    if seamark_type in seamark_classes:
        classes.add(seamark_classes[seamark_type])
    if seamark_type == "shoreline_construction":
        category = values.get("seamark:shoreline_construction:category", "")
        for item in re.split(r"[;,]", category):
            item = item.strip().replace(" ", "_")
            mapped = {
                "breakwater": "breakwater",
                "groyne": "jetty",
                "jetty": "jetty",
                "pier": "pier",
                "wharf": "pier",
                "seawall": "seawall",
            }.get(item)
            if mapped:
                classes.add(mapped)
    return sorted(classes)


def _osm_geometry(element: Mapping[str, Any], area_expected: bool) -> Any | None:
    if element.get("type") == "node":
        if element.get("lon") is None or element.get("lat") is None:
            return None
        return Point(float(element["lon"]), float(element["lat"]))
    center = element.get("center")
    if (
        isinstance(center, Mapping)
        and center.get("lon") is not None
        and center.get("lat") is not None
    ):
        return Point(float(center["lon"]), float(center["lat"]))
    if element.get("type") == "way":
        coordinates = [
            (float(value["lon"]), float(value["lat"]))
            for value in element.get("geometry", [])
            if value.get("lon") is not None and value.get("lat") is not None
        ]
        if len(coordinates) < 2:
            return None
        if area_expected and len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
            return make_valid(Polygon(coordinates))
        return LineString(coordinates)
    if element.get("type") == "relation":
        lines = []
        for member in element.get("members", []):
            coordinates = [
                (float(value["lon"]), float(value["lat"]))
                for value in member.get("geometry", [])
                if value.get("lon") is not None and value.get("lat") is not None
            ]
            if len(coordinates) >= 2:
                lines.append(LineString(coordinates))
        if not lines:
            return None
        if area_expected:
            polygons = list(polygonize(lines))
            if polygons:
                return make_valid(union_all(polygons))
        return make_valid(union_all(lines))
    return None


def _normalize_osm(path: Path, source_name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    document = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    area_classes = {"dredged_channel", "disposal_site", "aquaculture", "artificial_reef"}
    for element in document.get("elements", []):
        tags = element.get("tags") or {}
        classes = classify_osm_tags(tags)
        element_id = f"{element.get('type')}:{element.get('id')}"
        for feature_class in classes:
            geometry = _osm_geometry(element, feature_class in area_classes)
            if geometry is None or geometry.is_empty:
                continue
            rows.append(
                _record(
                    record_id=f"{source_name}:{element_id}:{feature_class}",
                    source_dataset=source_name,
                    source_feature_id=element_id,
                    jurisdiction="CROSS_BORDER",
                    feature_class=feature_class,
                    feature_subtype=str(tags.get("seamark:shoreline_construction:category") or "")
                    or None,
                    evidence_class=str(source.get("evidence_class", "volunteered_mapping")),
                    source_priority=10,
                    confidence_class=1,
                    geometry_precision_class="community_mapped_geometry",
                    geometry=geometry,
                    supports_area=feature_class in area_classes
                    and geometry.geom_type in {"Polygon", "MultiPolygon"},
                    structure_count=1.0 if feature_class in OVERWATER_CLASSES else 0.0,
                    observation_year=(
                        int(str(element["timestamp"])[:4]) if element.get("timestamp") else None
                    ),
                    properties={
                        "osm_type": element.get("type"),
                        "osm_id": element.get("id"),
                        "osm_version": element.get("version"),
                        "osm_timestamp": element.get("timestamp"),
                        "tags": tags,
                    },
                )
            )
    if not rows:
        raise ValueError(f"OSM source produced no recognized anthropogenic records: {path}")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _column(frame: pd.DataFrame, *names: str) -> str | None:
    lookup = {str(value).casefold(): str(value) for value in frame.columns}
    for name in names:
        if name.casefold() in lookup:
            return lookup[name.casefold()]
    return None


def _line_midpoint(geometry: Any) -> Any:
    if geometry.geom_type in {"LineString", "LinearRing"}:
        return geometry.interpolate(0.5, normalized=True)
    if geometry.geom_type == "MultiLineString":
        parts = list(geometry.geoms)
        longest = max(parts, key=lambda value: value.length)
        return longest.interpolate(0.5, normalized=True)
    return geometry.representative_point()


def _normalize_wa_shorezone(path: Path, source_name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = gpd.read_file(path).to_crs("EPSG:4326")
    id_column = _column(frame, "OBJECTID", "UNIT_ID")
    fraction_column = _column(frame, "SM_TOT_PCT")
    if id_column is None or fraction_column is None:
        raise ValueError("WA ShoreZone source is missing OBJECTID/SM_TOT_PCT fields.")
    rows: list[dict[str, Any]] = []
    for position, item in iter_frame_records(frame):
        geometry = item.geometry
        if geometry is None or geometry.is_empty:
            continue
        source_id = str(item[id_column])
        raw_fraction = pd.to_numeric(pd.Series([item[fraction_column]]), errors="coerce").iloc[0]
        fraction = (
            float(np.clip(raw_fraction / 100.0, 0.0, 1.0)) if pd.notna(raw_fraction) else None
        )
        properties = item.drop(labels=[frame.geometry.name]).to_dict()
        rows.append(
            _record(
                record_id=f"{source_name}:{source_id}:shoreline_survey",
                source_dataset=source_name,
                source_feature_id=source_id,
                jurisdiction="WA",
                feature_class="shoreline_survey",
                feature_subtype="shorezone_modification_segment",
                evidence_class=str(source.get("evidence_class")),
                source_priority=40,
                confidence_class=3,
                geometry_precision_class="systematic_shoreline_segment",
                geometry=geometry,
                supports_shoreline_denominator=fraction is not None,
                armoring_fraction_estimate=fraction,
                properties=properties,
            )
        )
        seed_classes: set[str] = set()
        for number in (1, 2, 3):
            type_column = _column(frame, f"SM{number}_TYPE")
            if type_column is None or pd.isna(item[type_column]):
                continue
            label = str(item[type_column]).strip().casefold()
            if any(value in label for value in ("bulkhead", "sheet pile", "seawall")):
                seed_classes.add("seawall")
        for feature_class in sorted(seed_classes):
            rows.append(
                _record(
                    record_id=f"{source_name}:{source_id}:{feature_class}",
                    source_dataset=source_name,
                    source_feature_id=source_id,
                    jurisdiction="WA",
                    feature_class=feature_class,
                    feature_subtype="mapped_shoreline_modification",
                    evidence_class=str(source.get("evidence_class")),
                    source_priority=40,
                    confidence_class=3,
                    geometry_precision_class="systematic_shoreline_segment",
                    geometry=geometry,
                    properties=properties,
                )
            )
        count_column = _column(frame, "PIERDOCK")
        count = (
            pd.to_numeric(pd.Series([item[count_column]]), errors="coerce").iloc[0]
            if count_column
            else 0
        )
        if pd.notna(count) and float(count) > 0:
            rows.append(
                _record(
                    record_id=f"{source_name}:{source_id}:pier",
                    source_dataset=source_name,
                    source_feature_id=source_id,
                    jurisdiction="WA",
                    feature_class="pier",
                    feature_subtype="pier_dock_count",
                    evidence_class=str(source.get("evidence_class")),
                    source_priority=40,
                    confidence_class=3,
                    geometry_precision_class="shoreline_segment_count_midpoint",
                    geometry=_line_midpoint(geometry),
                    structure_count=float(count),
                    properties=properties,
                )
            )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_bc_shorezone(path: Path, source_name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = gpd.read_file(path).to_crs("EPSG:4326")
    id_column = _column(
        frame,
        "OBJECTID",
        "PHYIDENT",
        "UNIT_KEY",
        "SHORE_UNIT_ID",
        "UNIT_ID",
        "FEATURE_CODE",
    )
    form_column = _column(frame, "FORM")
    rep_type_column = _column(frame, "REP_TYPE_NAME")
    if id_column is None or form_column is None:
        raise ValueError("BC ShoreZone source is missing its unit identifier or FORM field.")
    form_classes = {
        "a": "pier",
        "b": "breakwater",
        "f": "pier",
        "j": "jetty",
        "m": "marina",
        "n": "ferry_terminal",
        "p": "port",
        "s": "seawall",
        "w": "pier",
    }
    rows: list[dict[str, Any]] = []
    for position, item in iter_frame_records(frame):
        geometry = item.geometry
        if geometry is None or geometry.is_empty:
            continue
        source_id = str(item[id_column] if pd.notna(item[id_column]) else position)
        form = str(item[form_column]).strip() if pd.notna(item[form_column]) else ""
        representative = (
            str(item[rep_type_column]).strip().casefold()
            if rep_type_column and pd.notna(item[rep_type_column])
            else ""
        )
        man_made = representative in {"man-made", "man made", "manmade"} or form.startswith("A")
        properties = item.drop(labels=[frame.geometry.name]).to_dict()
        project_code = str(properties.get("PROJECT_CODE") or "").strip().upper()
        mapped = project_code != "UNMAPD" and representative not in {
            "",
            "- none -",
            "undefined",
        }
        fraction = (1.0 if man_made else 0.0) if mapped else None
        rows.append(
            _record(
                record_id=f"{source_name}:{source_id}:shoreline_survey",
                source_dataset=source_name,
                source_feature_id=source_id,
                jurisdiction="BC",
                feature_class="shoreline_survey",
                feature_subtype=representative or None,
                evidence_class=str(source.get("evidence_class")),
                source_priority=40,
                confidence_class=3,
                geometry_precision_class="systematic_shoreline_segment",
                geometry=geometry,
                supports_shoreline_denominator=mapped,
                armoring_fraction_estimate=fraction,
                properties=properties,
            )
        )
        if not man_made:
            continue
        codes = form[1:].casefold() if form.startswith("A") else form.casefold()
        for feature_class in sorted(
            {form_classes[value] for value in codes if value in form_classes}
        ):
            rows.append(
                _record(
                    record_id=f"{source_name}:{source_id}:{feature_class}",
                    source_dataset=source_name,
                    source_feature_id=source_id,
                    jurisdiction="BC",
                    feature_class=feature_class,
                    feature_subtype=form or None,
                    evidence_class=str(source.get("evidence_class")),
                    source_priority=40,
                    confidence_class=3,
                    geometry_precision_class="systematic_shoreline_segment",
                    geometry=geometry,
                    structure_count=1.0 if feature_class in OVERWATER_CLASSES else 0.0,
                    properties=properties,
                )
            )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalize_spatial_class(
    path: Path,
    source_name: str,
    source: Mapping[str, Any],
    feature_class: str,
):
    import geopandas as gpd

    frame = gpd.read_file(path).to_crs("EPSG:4326")
    id_column = _column(frame, "OBJECTID", "FID", "ID", "SITE_ID", "OBJNAM")
    rows: list[dict[str, Any]] = []
    for position, item in iter_frame_records(frame):
        geometry = item.geometry
        if geometry is None or geometry.is_empty:
            continue
        source_id = str(item[id_column] if id_column and pd.notna(item[id_column]) else position)
        properties = item.drop(labels=[frame.geometry.name]).to_dict()
        rows.append(
            _record(
                record_id=f"{source_name}:{source_id}:{feature_class}",
                source_dataset=source_name,
                source_feature_id=source_id,
                jurisdiction=(
                    "WA"
                    if source_name.startswith("wa_") or source_name.startswith("noaa_")
                    else "BC"
                ),
                feature_class=feature_class,
                feature_subtype=str(properties.get("OBJNAM") or properties.get("Name") or "")
                or None,
                evidence_class=str(source.get("evidence_class")),
                source_priority=50,
                confidence_class=3,
                geometry_precision_class="authoritative_mapped_geometry",
                geometry=make_valid(geometry),
                supports_area=geometry.geom_type in {"Polygon", "MultiPolygon"},
                properties=properties,
            )
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _normalized_column_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _find_csv_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    normalized = {_normalized_column_name(str(value)): str(value) for value in frame.columns}
    for candidate in candidates:
        candidate = _normalized_column_name(candidate)
        if candidate in normalized:
            return normalized[candidate]
    for key, original in normalized.items():
        if any(_normalized_column_name(candidate) in key for candidate in candidates):
            return original
    return None


def _normalize_aquaculture_csv(path: Path, source_name: str, source: Mapping[str, Any]):
    import geopandas as gpd

    frame = pd.read_csv(path, encoding="utf-8-sig")
    latitude = _find_csv_column(frame, ("latitude", "site latitude", "facility latitude"))
    longitude = _find_csv_column(frame, ("longitude", "site longitude", "facility longitude"))
    if latitude is None or longitude is None:
        raise ValueError(f"Aquaculture CSV lacks latitude/longitude columns: {list(frame.columns)}")
    identifier = _find_csv_column(
        frame,
        ("licence number", "license number", "facility reference number", "facility id"),
    )
    lon = pd.to_numeric(frame[longitude], errors="coerce")
    lat = pd.to_numeric(frame[latitude], errors="coerce")
    valid = lon.between(-180, 180) & lat.between(-90, 90)
    rows: list[dict[str, Any]] = []
    for position in frame.index[valid]:
        source_id = str(frame.loc[position, identifier]) if identifier else str(position)
        properties = frame.loc[position].to_dict()
        rows.append(
            _record(
                record_id=f"{source_name}:{source_id}:aquaculture",
                source_dataset=source_name,
                source_feature_id=source_id,
                jurisdiction="BC",
                feature_class="aquaculture",
                feature_subtype="licensed_facility",
                evidence_class=str(source.get("evidence_class")),
                source_priority=50,
                confidence_class=3,
                geometry_precision_class="licensed_facility_coordinate",
                geometry=Point(float(lon.loc[position]), float(lat.loc[position])),
                properties=properties,
            )
        )
    if not rows:
        raise ValueError(f"Aquaculture CSV contains no valid coordinate records: {path}")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def normalize_anthropogenic_inventory(frame: Any):
    """Validate the stable source-inventory schema and canonical data types."""

    import geopandas as gpd

    if not isinstance(frame, gpd.GeoDataFrame):
        frame = gpd.GeoDataFrame(frame, geometry="geometry")
    missing = sorted(set(INVENTORY_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Anthropogenic inventory is missing columns: {missing}")
    if frame.crs is None:
        raise ValueError("Anthropogenic inventory must retain CRS metadata.")
    frame = frame.loc[:, INVENTORY_COLUMNS].to_crs("EPSG:4326").copy()
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame["RECORD_ID"] = frame["RECORD_ID"].astype("string")
    if frame["RECORD_ID"].isna().any() or frame["RECORD_ID"].duplicated().any():
        raise ValueError("Anthropogenic RECORD_ID values must be unique and non-null.")
    if not frame["CONFIDENCE_CLASS"].astype(int).between(0, 3).all():
        raise ValueError("Anthropogenic confidence classes must be in [0, 3].")
    if not frame["ARMORING_FRACTION_ESTIMATE"].dropna().astype(float).between(0, 1).all():
        raise ValueError("Armoring fraction estimates must be null or in [0, 1].")
    frame["OBSERVATION_YEAR"] = pd.to_numeric(frame["OBSERVATION_YEAR"], errors="coerce").astype(
        "Int16"
    )
    frame["SOURCE_PRIORITY"] = frame["SOURCE_PRIORITY"].astype("int16")
    frame["CONFIDENCE_CLASS"] = frame["CONFIDENCE_CLASS"].astype("int8")
    frame["STRUCTURE_COUNT"] = pd.to_numeric(frame["STRUCTURE_COUNT"], errors="raise")
    for column in ("SUPPORTS_AREA", "SUPPORTS_SHORELINE_DENOMINATOR", "IS_CANONICAL"):
        frame[column] = frame[column].fillna(False).astype(bool)
    for column in (
        "SOURCE_DATASET",
        "SOURCE_FEATURE_ID",
        "JURISDICTION",
        "FEATURE_CLASS",
        "FEATURE_SUBTYPE",
        "EVIDENCE_CLASS",
        "GEOMETRY_PRECISION_CLASS",
        "DUPLICATE_OF_RECORD_ID",
        "SOURCE_PROPERTIES_JSON",
    ):
        frame[column] = frame[column].astype("string")
    return frame.sort_values("RECORD_ID").reset_index(drop=True)


def deduplicate_inventory(frame: Any, tolerance_m: float):
    """Keep authoritative geometry primary and retain overlapping OSM lineage."""

    frame = normalize_anthropogenic_inventory(frame)
    projected = frame.to_crs("EPSG:6933")
    for feature_class, rows in projected.groupby("FEATURE_CLASS", sort=False):
        authoritative = rows.loc[rows["SOURCE_PRIORITY"] > 10].sort_values(
            ["SOURCE_PRIORITY", "RECORD_ID"], ascending=[False, True]
        )
        volunteered = rows.loc[rows["SOURCE_PRIORITY"] <= 10]
        if authoritative.empty or volunteered.empty:
            continue
        spatial_index = authoritative.sindex
        for index, row in iter_frame_records(volunteered):
            candidates = list(
                spatial_index.query(row.geometry.buffer(tolerance_m), predicate="intersects")
            )
            if not candidates:
                continue
            matches = authoritative.iloc[candidates].copy()
            matches["_distance"] = matches.geometry.distance(row.geometry)
            match = matches.sort_values(
                ["SOURCE_PRIORITY", "_distance", "RECORD_ID"],
                ascending=[False, True, True],
            ).iloc[0]
            frame.loc[index, "IS_CANONICAL"] = False
            frame.loc[index, "DUPLICATE_OF_RECORD_ID"] = str(match["RECORD_ID"])
    return normalize_anthropogenic_inventory(frame)


def load_anthropogenic_inventory(config_path: str | Path = DEFAULT_CONFIG_PATH):
    """Load, normalize, combine, and deduplicate all configured source snapshots."""

    import geopandas as gpd

    download = load_habitat_download_config(SECTION_NAME, config_path)
    processing = _processing(config_path)
    frames = []
    dispatch = {
        "osm": _normalize_osm,
        "wa_shorezone": _normalize_wa_shorezone,
        "bc_shorezone": _normalize_bc_shorezone,
        "dredged_channel": lambda path, name, source: _normalize_spatial_class(
            path, name, source, "dredged_channel"
        ),
        "disposal_site": lambda path, name, source: _normalize_spatial_class(
            path, name, source, "disposal_site"
        ),
        "aquaculture": lambda path, name, source: _normalize_spatial_class(
            path, name, source, "aquaculture"
        ),
        "aquaculture_csv": _normalize_aquaculture_csv,
    }
    missing: list[Path] = []
    for name, source in download.sources.items():
        if not bool(source.get("enabled", True)):
            continue
        path = download.raw_dir / str(source["raw_filename"])
        if not path.exists():
            missing.append(path)
            continue
        normalizer = str(source.get("normalizer", "")).strip()
        if normalizer not in dispatch:
            raise ValueError(f"Unsupported anthropogenic normalizer {normalizer!r} for {name}.")
        frame = dispatch[normalizer](path, name, source)
        if frame.empty:
            raise ValueError(f"Anthropogenic source normalized to no records: {name}")
        frames.append(frame)
    if missing:
        raise FileNotFoundError(
            "Anthropogenic raw sources are missing; run download.py first: "
            + ", ".join(map(str, missing))
        )
    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    cross_border = combined["JURISDICTION"].eq("CROSS_BORDER")
    if cross_border.any():
        network = load_water_network_config(config_path)
        territorial = gpd.read_parquet(network.water_polygon_path).to_crs("EPSG:6933")
        canada = union_all(
            territorial.loc[territorial["NAME"].astype(str).eq("CANADA")].geometry.to_numpy()
        )
        united_states = union_all(
            territorial.loc[
                territorial["NAME"].astype(str).eq("UNITED_STATES")
                & territorial["AREA"].astype(str).eq("CONTIGUOUS")
            ].geometry.to_numpy()
        )
        points = combined.loc[cross_border].to_crs("EPSG:6933").geometry.representative_point()
        canada_distance = points.distance(canada).to_numpy(dtype="float64")
        us_distance = points.distance(united_states).to_numpy(dtype="float64")
        combined.loc[cross_border, "JURISDICTION"] = np.where(
            canada_distance <= us_distance, "BC", "WA"
        )
    return deduplicate_inventory(combined, float(processing["deduplication_tolerance_m"]))
