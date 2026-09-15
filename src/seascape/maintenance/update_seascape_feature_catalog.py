"""Regenerate the artifact-verified seascape feature catalog.

The catalog is intentionally generated from the materialized Parquet schemas so
that a producer cannot add a model, evidence, coverage, or QC column without the
catalog audit noticing it. Product metadata remains explicit here; columns and
resolution availability come from the artifacts themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from seascape.core.config.paths import project_root
from seascape.modeling.feature_policy import (
    infer_scale_group,
    infer_topology,
)

DEFAULT_OUTPUT_PATH = Path("config/feature_catalog.yaml")
SEASCAPE_ROOT = Path("data/processed/domain/environmental_layer/seascape")
KEY_COLUMNS = {"H3_INDEX", "H3_RESOLUTION"}
METRIC_FAMILY = "seascape"
FEATURE_VARIABLE_ROLES = {"predictor", "categorical", "state"}


@dataclass(frozen=True)
class ProductSpec:
    common_name: str
    category: str
    paths: dict[int, str]
    producer: str
    grain: str = "one row per canonical marine-support H3 cell"
    null_policy: str | None = None


def _paths(template: str, resolutions: tuple[int, ...] = (6, 8)) -> dict[int, str]:
    return {
        resolution: template.format(resolution=resolution) for resolution in resolutions
    }


PRODUCTS: dict[str, ProductSpec] = {
    "h3_marine_support": ProductSpec(
        "Canonical marine H3 support",
        "spatial_support",
        _paths(
            "data/processed/domain/environmental_layer/seascape/spatial_support/"
            "h3_geometry/H3_MODEL_AREA_SUPPORT_RES_{resolution}.parquet"
        ),
        "seascape.spatial_support.water_network.build",
        null_policy=(
            "Disconnected cells retain explicit graph status and QC rather than being removed."
        ),
    ),
    "bathymetry": ProductSpec(
        "Bathymetry",
        "seafloor_physiography",
        {
            6: "data/processed/domain/environmental_layer/seascape/"
            "seafloor_physiography/bathymetry/BATHYMETRY_RES_6.parquet",
            8: "data/processed/domain/environmental_layer/seascape/"
            "seafloor_physiography/bathymetry/BATHYMETRY.parquet",
        },
        "seascape.seafloor_physiography.bathymetry.build",
    ),
    "geomorphometry": ProductSpec(
        "Seafloor geomorphometry",
        "seafloor_physiography",
        {
            8: "data/processed/domain/environmental_layer/seascape/"
            "seafloor_physiography/geomorphometry/GEOMORPHOMETRY_RES_8.parquet"
        },
        "seascape.seafloor_physiography.geomorphometry.build",
    ),
    "geomorphic_units": ProductSpec(
        "Seafloor geomorphic units",
        "seafloor_physiography",
        {
            8: "data/processed/domain/environmental_layer/seascape/"
            "seafloor_physiography/geomorphic_units/GEOMORPHIC_UNITS_RES_8.parquet"
        },
        "seascape.seafloor_physiography.geomorphic_units.build",
    ),
    "shoreline_proximity": ProductSpec(
        "Shoreline proximity",
        "coastal_configuration",
        {
            8: "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "shoreline_proximity/SHORELINE_PROXIMITY_RES_8.parquet"
        },
        "seascape.coastal_configuration.shoreline_proximity.build",
    ),
    "shoreline_characterization": ProductSpec(
        "Physical shoreline characterization",
        "coastal_configuration",
        _paths(
            "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "shoreline_characterization/SHORELINE_CHARACTERIZATION_RES_{resolution}.parquet"
        ),
        "seascape.coastal_configuration." "shoreline_characterization.build",
        null_policy=(
            "Fractions are null without classified shoreline; disconnected network distances "
            "remain null with a QC reason."
        ),
    ),
    "exposure_and_enclosure": ProductSpec(
        "Marine exposure and enclosure",
        "coastal_configuration",
        {
            8: "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "exposure_and_enclosure/EXPOSURE_AND_ENCLOSURE_RES_8.parquet"
        },
        "seascape.coastal_configuration.exposure_and_enclosure.build",
    ),
    "waterbody_morphometry": ProductSpec(
        "Waterbody morphometry",
        "coastal_configuration",
        {
            8: "data/processed/domain/environmental_layer/seascape/coastal_configuration/"
            "waterbody_morphometry/WATERBODY_MORPHOMETRY_RES_8.parquet"
        },
        "seascape.coastal_configuration.waterbody_morphometry.build",
    ),
    "freshwater_sources": ProductSpec(
        "Freshwater source setting",
        "hydrologic_connectivity",
        {
            8: "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
            "freshwater_sources/RIVER_MOUTH_FEATURES_RES_8.parquet"
        },
        "seascape.hydrologic_connectivity.freshwater_sources.build",
    ),
    "fluvial_connectivity": ProductSpec(
        "Fluvial-marine connectivity",
        "hydrologic_connectivity",
        {
            8: "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
            "fluvial_connectivity/FLUVIAL_CONNECTIVITY_RES_8.parquet"
        },
        "seascape.hydrologic_connectivity.fluvial_connectivity.build",
        null_policy="Unreachable cells retain explicit structural-discontinuity and QC state.",
    ),
    "fluvial_barriers": ProductSpec(
        "Fluvial barriers and passage",
        "hydrologic_connectivity",
        _paths(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
            "fluvial_barriers/FLUVIAL_BARRIERS_RES_{resolution}.parquet"
        ),
        "seascape.hydrologic_connectivity.fluvial_barriers.build",
        null_policy="No mapped barrier record remains null rather than becoming a zero count.",
    ),
    "fluvial_barriers_confidence": ProductSpec(
        "Fluvial barrier evidence",
        "hydrologic_connectivity_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
            "fluvial_barriers/FLUVIAL_BARRIERS_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.hydrologic_connectivity.fluvial_barriers.build",
    ),
    "estuarine_connectivity": ProductSpec(
        "Estuarine connectivity",
        "hydrologic_connectivity",
        {
            8: "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
            "estuarine_connectivity/ESTUARINE_CONNECTIVITY_RES_8.parquet"
        },
        "seascape.hydrologic_connectivity.estuarine_connectivity.build",
    ),
    "anthropogenic": ProductSpec(
        "Anthropogenic seascape structures",
        "anthropogenic",
        _paths(
            "data/processed/domain/environmental_layer/seascape/anthropogenic/"
            "ANTHROPOGENIC_RES_{resolution}.parquet"
        ),
        "seascape.anthropogenic.build",
        null_policy="Unmapped artificial reefs and aquaculture remain null, not absence.",
    ),
    "anthropogenic_confidence": ProductSpec(
        "Anthropogenic evidence",
        "anthropogenic_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/anthropogenic/"
            "ANTHROPOGENIC_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.anthropogenic.build",
    ),
    "benthic_substrate": ProductSpec(
        "Benthic substrate composition",
        "benthic_substrate",
        _paths(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/"
            "classification/BENTHIC_SUBSTRATE_CLASSIFICATION_RES_{resolution}.parquet"
        ),
        "seascape.benthic_substrate.classification.build",
        null_policy="dbSEABED nodata remains null and is accompanied by modeled confidence.",
    ),
    "benthic_substrate_confidence": ProductSpec(
        "Benthic substrate evidence",
        "benthic_substrate_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/"
            "classification/BENTHIC_SUBSTRATE_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.benthic_substrate.classification.build",
    ),
    "bottom_hardness": ProductSpec(
        "Derived bottom hardness",
        "benthic_substrate",
        _paths(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/"
            "bottom_hardness/BOTTOM_HARDNESS_RES_{resolution}.parquet"
        ),
        "seascape.benthic_substrate.bottom_hardness.build",
    ),
    "bottom_hardness_confidence": ProductSpec(
        "Bottom hardness evidence",
        "benthic_substrate_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/benthic_substrate/"
            "bottom_hardness/BOTTOM_HARDNESS_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.benthic_substrate.bottom_hardness.build",
    ),
    "seagrass": ProductSpec(
        "Sentinel-2 seagrass habitat",
        "biogenic_habitat",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "seagrass/SEAGRASS_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.seagrass.build",
        null_policy="Satellite non-detection is not interpreted as field-confirmed absence.",
    ),
    "seagrass_confidence": ProductSpec(
        "Seagrass evidence",
        "biogenic_habitat_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "seagrass/SEAGRASS_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.seagrass.build",
    ),
    "kelp": ProductSpec(
        "Kelp habitat",
        "biogenic_habitat",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "kelp/KELP_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.kelp.build",
        null_policy="Unsurveyed cells remain distinct from explicit absence.",
    ),
    "kelp_confidence": ProductSpec(
        "Kelp evidence",
        "biogenic_habitat_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "kelp/KELP_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.kelp.build",
    ),
    "reef_habitat": ProductSpec(
        "Reef habitat",
        "biogenic_habitat",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "reef/REEF_HABITAT_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.reef.build",
        null_policy="Rocky, biogenic, and deep-coral/sponge evidence remain distinct.",
    ),
    "reef_habitat_confidence": ProductSpec(
        "Reef habitat evidence",
        "biogenic_habitat_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "reef/REEF_HABITAT_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.reef.build",
    ),
    "benthic_habitat_panel": ProductSpec(
        "Model-ready benthic habitat panel",
        "biogenic_habitat",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "composite/BENTHIC_HABITAT_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.composite.build",
        null_policy="This is an assembly panel; it does not replace distinct habitat families.",
    ),
    "benthic_habitat_panel_confidence": ProductSpec(
        "Benthic habitat panel evidence",
        "biogenic_habitat_evidence",
        _paths(
            "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
            "composite/BENTHIC_HABITAT_CONFIDENCE_RES_{resolution}.parquet"
        ),
        "seascape.biogenic_habitat.composite.build",
    ),
}

SUPPORTING_PRODUCTS = {
    "territorial_water_geometry": {
        "common_name": "Canonical territorial-water geometry",
        "path": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "water_geometry/TERRITORIAL_WATER_POLYGON.parquet",
        "role": "geometry_support",
    },
    "h3_marine_full_cell_geometry": {
        "common_name": "Full marine-support H3 geometry",
        "path_template": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "h3_geometry/H3_MARINE_FULL_CELL_GEOMETRY_RES_{resolution}.parquet",
        "resolutions": [6, 8],
        "role": "geometry_support",
    },
    "h3_full_marine_support": {
        "common_name": "Full-area marine graph support",
        "path_template": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "h3_geometry/H3_MARINE_SUPPORT_RES_{resolution}.parquet",
        "resolutions": [6, 8],
        "role": "network_support",
    },
    "h3_marine_water_clipped_geometry": {
        "common_name": "Water-clipped marine H3 geometry",
        "path_template": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "h3_geometry/H3_MARINE_WATER_CLIPPED_GEOMETRY_RES_{resolution}.parquet",
        "resolutions": [6, 8],
        "role": "geometry_support",
    },
    "h3_water_passable_edges": {
        "common_name": "Canonical water-passable H3 edges",
        "path_template": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "water_network/H3_WATER_PASSABLE_EDGES_RES_{resolution}.parquet",
        "resolutions": [6, 8],
        "role": "network_support",
    },
    "h3_water_connectors": {
        "common_name": "Terminal water-network connectors",
        "path_template": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "water_network/H3_WATER_CONNECTORS_RES_{resolution}.parquet",
        "resolutions": [6, 8],
        "role": "network_support",
    },
    "h3_water_neighborhoods": {
        "common_name": "Bounded water-passable H3 neighborhoods",
        "path_template": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "water_network/H3_WATER_NEIGHBORHOODS_RES_{resolution}.parquet",
        "resolutions": [6, 8],
        "role": "network_support",
    },
    "h3_water_radius_operator_r8_5000m": {
        "common_name": "Canonical 5 km water-network radius operator",
        "path": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "water_network/H3_WATER_RADIUS_OPERATOR_RES_8_5000M.npz",
        "role": "aggregation_support",
    },
    "h3_reachable_water_area_r8_5000m": {
        "common_name": "Reachable water area within 5 km",
        "path": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "water_network/H3_REACHABLE_WATER_AREA_RES_8_5000M.parquet",
        "role": "aggregation_support",
    },
    "h3_parent_child_r8_to_r6": {
        "common_name": "H3 R8-to-R6 marine parent-child crosswalk",
        "path": "data/processed/domain/environmental_layer/seascape/spatial_support/"
        "h3_geometry/H3_PARENT_CHILD_RES_8_TO_RES_6.parquet",
        "role": "aggregation_support",
    },
    "watershed_marine_crosswalk_r8": {
        "common_name": "Watershed-to-marine H3 crosswalk",
        "path": "data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/"
        "fluvial_connectivity/WATERSHED_MARINE_CROSSWALK_RES_8.parquet",
        "role": "network_support",
    },
}


def producer_column_contracts() -> dict[str, set[str]]:
    """Return explicit producer schemas that must match materialized products."""

    from seascape.coastal_configuration.exposure_and_enclosure.build import (
        OUTPUT_COLUMNS as exposure_columns,
    )
    from seascape.coastal_configuration.shoreline_proximity.build import (
        OUTPUT_COLUMNS as shoreline_columns,
    )
    from seascape.coastal_configuration.waterbody_morphometry.build import (
        OUTPUT_COLUMNS as morphometry_columns,
    )
    from seascape.hydrologic_connectivity.estuarine_connectivity.build import (
        FEATURE_COLUMNS as estuary_columns,
    )

    return {
        "shoreline_proximity": set(shoreline_columns),
        "exposure_and_enclosure": set(exposure_columns),
        "waterbody_morphometry": set(morphometry_columns),
        "estuarine_connectivity": set(estuary_columns),
    }


def metric_subfamily(category: str) -> str:
    """Map detailed product categories to the shared metric taxonomy."""

    if category.startswith("benthic_substrate") or category.startswith(
        "biogenic_habitat"
    ):
        return "benthic"
    if category.startswith("anthropogenic"):
        return "anthropogenic"
    if category.startswith("hydrologic_connectivity"):
        return "hydrologic_connectivity"
    return category


COMMON_NAME_OVERRIDES = {
    "BATHYMETRY": "Mean bathymetric elevation",
    "BATHYMETRY_MIN": "Minimum bathymetric elevation",
    "BATHYMETRY_MAX": "Maximum bathymetric elevation",
    "BATHYMETRY_STD": "Bathymetric elevation standard deviation",
    "DISTANCE_TO_ISOBATH_6_1_M": "Distance to 6.1 m isobath",
    "SLOPE": "Mean seafloor slope",
    "ASPECT": "Mean seafloor aspect",
    "TERRAIN_POSITION": "Local bathymetric terrain position",
    "RELIEF": "Local bathymetric relief",
    "RUGGEDNESS": "Seafloor ruggedness",
    "GEOMORPHIC_UNIT": "Dominant geomorphic unit",
    "SHORELINE_DISTANCE_M": "Straight-line distance to shoreline",
    "WATER_NETWORK_DISTANCE_M": "Water-network distance to shoreline",
    "OPEN_OCEAN_INDEX": "Open-ocean exposure index",
    "OPENNESS_TO_OCEAN_INDEX": "Openness to ocean index",
    "DISTANCE_TO_RIVER_MOUTH_M": "Distance to mapped river mouth",
    "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M": (
        "Water-network distance to fluvial mouth"
    ),
    "DISTANCE_TO_ESTUARY_M": "Straight-line distance to mapped estuary",
    "WATER_NETWORK_DISTANCE_TO_ESTUARY_M": "Water-network distance to mapped estuary",
    "BOTTOM_HARDNESS_INDEX": "Derived bottom hardness index",
    "POTENTIAL_ROCKY_REEF_SUITABILITY": "Potential rocky-reef suitability",
    "BENTHIC_HABITAT_RICHNESS": "Benthic habitat-family richness",
}

UNIT_OVERRIDES = {
    "BATHYMETRY": "m",
    "BATHYMETRY_MEDIAN": "m",
    "BATHYMETRY_MIN": "m",
    "BATHYMETRY_MAX": "m",
    "BATHYMETRY_STD": "m",
    "BATHYMETRY_RANGE": "m",
    "BATHYMETRY_LOCAL_ANOMALY": "m",
    "BATHYMETRY_Q10": "m",
    "BATHYMETRY_Q25": "m",
    "BATHYMETRY_Q75": "m",
    "BATHYMETRY_Q90": "m",
    "SLOPE": "degrees",
    "ASPECT": "degrees",
    "SLOPE_MEAN_NATIVE_RASTER": "degrees",
    "SLOPE_Q90_NATIVE_RASTER": "degrees",
}

ACRONYMS = {
    "aoi": "AOI",
    "h3": "H3",
    "id": "ID",
    "mad": "MAD",
    "qc": "QC",
    "q10": "Q10",
    "q25": "Q25",
    "q75": "Q75",
    "q90": "Q90",
    "std": "standard deviation",
    "tpi": "TPI",
}


def common_name(column: str) -> str:
    """Return a stable human-readable label while preserving scale tokens."""

    if column in COMMON_NAME_OVERRIDES:
        return COMMON_NAME_OVERRIDES[column]
    tokens = column.casefold().split("_")
    if len(tokens) >= 3 and tokens[-3:] == ["m", "per", "km2"]:
        tokens = tokens[:-3]
    elif len(tokens) >= 2 and tokens[-2:] == ["per", "km2"]:
        tokens = tokens[:-2]
    elif tokens and tokens[-1] in {"m", "km", "m2", "km2", "deg"}:
        tokens = tokens[:-1]
    words = []
    for token in tokens:
        if token in ACRONYMS:
            words.append(ACRONYMS[token])
        elif token == "m2":
            words.append("m²")
        elif token == "km2":
            words.append("km²")
        elif re.fullmatch(r"\d+km", token):
            words.append(f"{token[:-2]} km")
        elif token == "frac":
            words.append("fraction")
        else:
            words.append(token)
    label = " ".join(words)
    return label[:1].upper() + label[1:]


def unit(column: str, field: pa.Field) -> str:
    """Infer the storage unit from repository naming conventions."""

    if column in UNIT_OVERRIDES:
        return UNIT_OVERRIDES[column]
    # Semantic families must be checked before terminal suffixes. Depth-band
    # names encode the threshold unit (metres), not the stored fraction/count.
    if column.startswith("BATHYMETRY_FRAC_"):
        return "proportion"
    if column.startswith("BATHYMETRY_PIXEL_COUNT_"):
        return "count"
    if "SURFACE_AREA_RATIO" in column:
        return "dimensionless"
    if (
        "COUNT_IN_COMPONENT" in column
        or column.endswith("_COMPONENT_COUNT")
        or "_COUNT_WITHIN_" in column
    ):
        return "count"
    if column.endswith("_M_PER_KM2"):
        return "m_per_km2"
    if column.endswith("_DENSITY_PER_KM2"):
        return "count_per_km2"
    if column.endswith("_AREA_KM2") or column.endswith("_KM2"):
        return "km2"
    if column.endswith("_AREA_M2") or column.endswith("_M2"):
        return "m2"
    if column.endswith("_KM"):
        return "km"
    if column.endswith("_M"):
        return "m"
    if column.endswith("_DEG") or "OPENNESS_DEG" in column:
        return "degrees"
    if column.endswith("_YEAR") or column.endswith("_YEARS"):
        return "year"
    if column.endswith("_COUNT") or column.endswith("_CELL_COUNT"):
        return "count"
    if column.endswith("_FRAC") or column.endswith("_FRACTION"):
        return "proportion"
    if column.endswith("_RATIO") or column.endswith("_INDEX"):
        return "dimensionless"
    if "CONFIDENCE" in column:
        return "ordinal"
    if pa.types.is_boolean(field.type):
        return "boolean"
    if pa.types.is_string(field.type) or pa.types.is_large_string(field.type):
        return "category_or_text"
    return "not_encoded"


def role(column: str, product_id: str, field: pa.Field) -> str:
    """Separate predictors from states, identifiers, and evidence/QC fields."""

    if product_id.endswith("confidence") or product_id.endswith("_evidence"):
        return "evidence"
    if column.endswith("_ID") or "_ID_" in column or column.endswith("_H3_INDEX"):
        return "identifier"
    if any(
        token in column
        for token in (
            "SOURCE_DATASET",
            "EVIDENCE",
            "CONFIDENCE",
            "UNMAPPED",
            "SURVEY_METHOD",
            "PRECISION_CLASS",
            "OBSERVED_VS_MODELED",
            "QC_REASON",
            "DERIVATION_METHOD",
            "CONNECTOR_METHOD",
            "VERSION",
            "OBSERVED_PRESENCE",
            "OBSERVED_ABSENCE",
        )
    ):
        return "evidence"
    if any(
        token in column
        for token in (
            "WATER_COMPONENT_ID",
            "CONNECTOR_DISTANCE",
            "GRAPH_",
            "STRUCTURAL_DISCONTINUITY",
            "CROSSWALK_METHOD",
            "INVENTORY_STATE",
            "PERSISTENCE_BASIS",
            "TOPOLOGY_GAP",
        )
    ):
        return "support_or_qc"
    if any(
        token in column
        for token in (
            "COVERAGE",
            "PIXEL_COUNT",
            "NATIVE_CHILD_WATER_AREA",
            "SURVEYED_LENGTH",
            "SURVEYED_AREA",
            "SOURCE_COUNT",
            "YEARS_SURVEYED",
            "YEARS_OBSERVED",
            "LATEST_SURVEY_YEAR",
            "LATEST_ASSESSMENT_YEAR",
            "FIRST_YEAR",
            "LAST_YEAR",
            "RECENCY_YEARS",
            "ASSESSED_SITE_COUNT",
            "UNKNOWN_STATUS_COUNT",
            "MAPPING_UNIT",
            "NATIVE_RASTER_RESOLUTION",
            "TOTAL_MAPPED_LENGTH",
            "CLASSIFIED_LENGTH",
            "UNSURVEYED",
        )
    ):
        return "coverage"
    if (
        pa.types.is_boolean(field.type)
        or any(token in column for token in ("PRESENCE", "ABSENCE", "REACHABLE"))
        or column.startswith(("IS_", "INTERSECTS_"))
    ):
        return "state"
    if pa.types.is_string(field.type) or pa.types.is_large_string(field.type):
        return "categorical"
    return "predictor"


def variable_kind(product_id: str, field_role: str) -> str:
    """Classify substantive model variables separately from metadata and diagnostics."""

    if product_id == "h3_marine_support":
        return "metadata"
    return "feature_variable" if field_role in FEATURE_VARIABLE_ROLES else "metadata"


def _relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def build_catalog(root: Path) -> dict[str, Any]:
    """Build the full catalog and fail if any configured artifact is missing."""

    products: dict[str, Any] = {}
    producer_contracts = producer_column_contracts()
    feature_entry_count = 0
    unique_columns: set[str] = set()
    for product_id, spec in PRODUCTS.items():
        schemas: dict[int, pa.Schema] = {}
        paths: dict[int, str] = {}
        for resolution, configured_path in sorted(spec.paths.items()):
            path = (root / configured_path).resolve()
            if not path.exists():
                raise FileNotFoundError(
                    f"Configured seascape artifact is missing: {path}"
                )
            schemas[resolution] = pq.read_schema(path)
            paths[resolution] = _relative(path, root)
        expected_columns = producer_contracts.get(product_id)
        if expected_columns is not None:
            for resolution, schema in schemas.items():
                observed_columns = set(schema.names)
                if observed_columns != expected_columns:
                    missing = sorted(expected_columns - observed_columns)
                    unexpected = sorted(observed_columns - expected_columns)
                    raise ValueError(
                        f"{product_id} r{resolution} artifact disagrees with its producer "
                        f"contract; missing={missing}, unexpected={unexpected}"
                    )
        columns = sorted(
            {
                column
                for schema in schemas.values()
                for column in schema.names
                if column not in KEY_COLUMNS
            }
        )
        features: dict[str, Any] = {}
        for column in columns:
            available = [
                resolution
                for resolution, schema in schemas.items()
                if column in schema.names
            ]
            reference = schemas[available[0]].field(column)
            field_role = role(column, product_id, reference)
            features[column] = {
                "common_name": common_name(column),
                "metric_family": METRIC_FAMILY,
                "metric_subfamily": metric_subfamily(spec.category),
                "column": column,
                "collection_paths": {
                    resolution: paths[resolution] for resolution in available
                },
                "unit": unit(column, reference),
                "role": field_role,
                "variable_kind": variable_kind(product_id, field_role),
                "topology": infer_topology(product_id, column),
                "scale_group": infer_scale_group(column),
                "available_resolutions": available,
            }
            feature_entry_count += 1
            unique_columns.add(column)
        variable_kind_counts = {
            kind: sum(feature["variable_kind"] == kind for feature in features.values())
            for kind in ("feature_variable", "metadata")
        }
        product: dict[str, Any] = {
            "common_name": spec.common_name,
            "metric_family": METRIC_FAMILY,
            "metric_subfamily": metric_subfamily(spec.category),
            "category": spec.category,
            "collection": {
                "paths": paths,
                "index_columns": ["H3_INDEX"],
                "resolutions": sorted(paths),
            },
            "producer": spec.producer,
            "grain": spec.grain,
            "feature_count": len(features),
            "variable_kind_counts": variable_kind_counts,
            "features": features,
        }
        if spec.null_policy:
            product["null_policy"] = spec.null_policy
        products[product_id] = product
    return {
        "schema_version": 4,
        "catalog_id": "environment.seascape",
        "generated_from_materialized_schemas": True,
        "catalog_contract": {
            "scope": (
                "Every non-key column in the canonical materialized seascape feature, evidence, "
                "coverage, state, and QC tables listed below."
            ),
            "collection_lookup": (
                "Each feature records collection_paths.<resolution> as the Parquet path and "
                "column as the exact collection column; product-level paths are the same contract."
            ),
            "common_name_lookup": (
                "Use products.<product>.features.<column>.common_name for a human-readable name."
            ),
            "metric_taxonomy": (
                "metric_family is the cross-domain family (seascape here); metric_subfamily "
                "groups related seascape mechanisms such as anthropogenic or benthic."
            ),
            "metric_family_vocabulary": [
                "seascape",
                "meteorological",
                "oceanographic",
            ],
            "metric_subfamily_vocabulary": [
                "spatial_support",
                "seafloor_physiography",
                "coastal_configuration",
                "hydrologic_connectivity",
                "anthropogenic",
                "benthic",
            ],
            "excluded_key_columns": sorted(KEY_COLUMNS),
            "roles": {
                "predictor": "Model-facing numeric covariate.",
                "categorical": "Model-facing categorical value.",
                "state": "Presence, absence, reachability, or another explicit state.",
                "coverage": "Sampling or aggregation coverage field.",
                "evidence": "Confidence, provenance, or survey evidence.",
                "support_or_qc": "Spatial-support, connector, lineage, or QC field.",
                "identifier": "Foreign key or source identity; not a numeric predictor.",
            },
            "variable_kinds": {
                "feature_variable": (
                    "A substantive metric, category, or state that may be considered for a "
                    "model after policy and leakage review."
                ),
                "metadata": (
                    "Coverage, survey or evidence quality, provenance, identifiers, support, "
                    "bookkeeping, and QC; never a default model feature."
                ),
            },
        },
        "product_count": len(products),
        "feature_entry_count": feature_entry_count,
        "unique_column_count": len(unique_columns),
        "superseded_products": {
            "eelgrass": {
                "status": "superseded_artifact_not_current_catalog",
                "replacement": "seagrass",
                "reason": (
                    "The current contract uses the Sentinel-2 generic seagrass product in place "
                    "of the earlier jurisdictionally uneven eelgrass layer."
                ),
                "legacy_paths": {
                    6: "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
                    "eelgrass/EELGRASS_RES_6.parquet",
                    8: "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
                    "eelgrass/EELGRASS_RES_8.parquet",
                },
                "legacy_confidence_paths": {
                    6: "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
                    "eelgrass/EELGRASS_CONFIDENCE_RES_6.parquet",
                    8: "data/processed/domain/environmental_layer/seascape/biogenic_habitat/"
                    "eelgrass/EELGRASS_CONFIDENCE_RES_8.parquet",
                },
            }
        },
        "supporting_products": {
            product_id: {**product, "variable_kind": "metadata"}
            for product_id, product in SUPPORTING_PRODUCTS.items()
        },
        "products": products,
    }


def main() -> int:
    import argparse
    import yaml
    from contextlib import nullcontext
    from seascape.publication import SeascapeSnapshot

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--materialization-root")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = project_root()
    materialization_root = (
        Path(args.materialization_root).resolve() if args.materialization_root else root
    )
    with SeascapeSnapshot(root) if materialization_root == root else nullcontext():
        catalog = build_catalog(materialization_root)
    rendered = yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True, width=100)
    destination = root / args.output
    if args.check:
        if not destination.exists() or destination.read_text() != rendered:
            raise SystemExit(f"Seascape feature catalog is stale: {destination}")
        return 0
    from seascape.core.artifacts import atomic_write_text

    atomic_write_text(destination, rendered, overwrite=True)
    print(f"Wrote {catalog['product_count']} seascape products -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
