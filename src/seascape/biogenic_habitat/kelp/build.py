"""Build kelp composition, proximity, persistence, and confidence at H3 r8/r6."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from seascape.utils.habitat_acquisition import (
    load_habitat_download_config,
)
from seascape.utils.habitat_configuration import (
    load_habitat_surface_config,
)
from seascape.utils.habitat_inventory import (
    NORMALIZED_INVENTORY_COLUMNS,
    normalize_inventory,
)
from seascape.utils.habitat_publication import build_habitat_products

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

LOGGER = logging.getLogger(__name__)
PREFIX = "KELP"
YEAR_PATTERN = re.compile(r"(?:19|20)\d{2}")


def _records(
    frame: Any,
    *,
    source_dataset: str,
    feature_id_column: str | None = None,
    status: Any = "present",
    year: Any = None,
    source_persistence_ratio: Any = None,
    evidence_class: str,
    composition_eligible: bool,
    supports_area: bool,
    confidence: int,
    survey_method: str,
    spatial_precision: str,
    temporal_precision: str,
) -> Any:
    import geopandas as gpd

    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if frame.crs is None:
        raise ValueError(f"{source_dataset} source geometry has no CRS.")
    frame = frame.to_crs("EPSG:4326")
    if frame.empty:
        return gpd.GeoDataFrame(
            columns=NORMALIZED_INVENTORY_COLUMNS, geometry="geometry", crs=frame.crs
        )
    ids = (
        frame[feature_id_column].astype("string")
        if feature_id_column and feature_id_column in frame
        else pd.Series(frame.index.astype(str), index=frame.index, dtype="string")
    )
    statuses = (
        pd.Series([status] * len(frame), index=frame.index, dtype="string")
        if isinstance(status, str)
        else pd.Series(status, index=frame.index, dtype="string")
    )
    years = (
        pd.Series([year] * len(frame), index=frame.index)
        if year is None or np.isscalar(year)
        else pd.Series(year, index=frame.index)
    )
    persistence = (
        pd.Series([source_persistence_ratio] * len(frame), index=frame.index)
        if source_persistence_ratio is None or np.isscalar(source_persistence_ratio)
        else pd.Series(source_persistence_ratio, index=frame.index)
    )
    return gpd.GeoDataFrame(
        {
            "RECORD_ID": [f"{source_dataset}:{value}:{index}" for index, value in enumerate(ids)],
            "HABITAT_TYPE": "floating_kelp",
            "SOURCE_DATASET": source_dataset,
            "SOURCE_FEATURE_ID": ids.to_numpy(),
            "EVIDENCE_CLASS": evidence_class,
            "OBSERVED_VS_MODELED": "observed",
            "OBSERVATION_STATUS": statuses.to_numpy(),
            "OBSERVATION_YEAR": years.to_numpy(),
            "COMPOSITION_ELIGIBLE": composition_eligible,
            "SUPPORTS_AREA": supports_area,
            "COVERAGE_WEIGHT": 1.0,
            "SOURCE_PERSISTENCE_RATIO": persistence.to_numpy(),
            "CONFIDENCE_CLASS": confidence,
            "SURVEY_METHOD": survey_method,
            "SPATIAL_PRECISION_CLASS": spatial_precision,
            "TEMPORAL_PRECISION_CLASS": temporal_precision,
        },
        geometry=frame.geometry.to_numpy(),
        crs=frame.crs,
    ).loc[:, NORMALIZED_INVENTORY_COLUMNS]


def _source_path(config: Any, source_name: str) -> Path:
    return config.raw_dir / str(config.sources[source_name]["raw_filename"])


def _read_optional(path: Path):
    import geopandas as gpd

    if not path.exists():
        LOGGER.warning("Optional kelp source is absent: %s", path)
        return None
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"Kelp source has no CRS: {path}")
    return frame.to_crs("EPSG:4326")


def _is_annual_polygon_frame(frame: Any) -> bool:
    """Return whether a geodatabase layer is spatial annual canopy coverage."""

    import geopandas as gpd

    return bool(
        isinstance(frame, gpd.GeoDataFrame)
        and frame.crs is not None
        and "geometry" in frame
        and frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any()
    )


def _annual_kelp_inventory(config: Any) -> list[Any]:
    import geopandas as gpd

    source = config.sources["wa_dnr_annual_floating_kelp"]
    root = config.raw_dir / str(source.get("extract_directory", "WA_floating_kelp"))
    if not root.exists():
        return []
    candidates: list[tuple[int, Any, str]] = []
    for database in sorted(root.rglob("*.gdb")):
        for layer in gpd.list_layers(database)["name"].astype(str):
            match = YEAR_PATTERN.search(layer)
            if match and "kelp" in layer.lower():
                frame = gpd.read_file(database, layer=layer)
                if _is_annual_polygon_frame(frame):
                    candidates.append((int(match.group()), frame, layer))
    for shapefile in sorted(root.rglob("*.shp")):
        match = YEAR_PATTERN.search(shapefile.stem)
        if match and "kelp" in shapefile.stem.lower():
            frame = gpd.read_file(shapefile)
            if frame.crs is not None:
                candidates.append((int(match.group()), frame, shapefile.stem))
    if not candidates:
        LOGGER.warning("No annual polygon layers were discovered beneath %s", root)
        return []
    latest_year = max(year for year, _frame, _name in candidates)
    outputs = []
    for year, frame, name in candidates:
        outputs.append(
            _records(
                frame,
                source_dataset=f"WA_DNR_FLOATING_KELP_{year}",
                year=year,
                evidence_class="direct_observation",
                composition_eligible=year == latest_year,
                supports_area=True,
                confidence=3,
                survey_method="annual aerial floating-canopy inventory",
                spatial_precision=(
                    "approximately_4m_processing"
                    if year >= 2010
                    else "approximately_20m_processing"
                ),
                temporal_precision="survey_year",
            )
        )
    return outputs


def _require_annual_inventory(
    annual_frames: list[Any],
    *,
    allow_generalized_only: bool,
) -> None:
    if annual_frames or allow_generalized_only:
        return
    raise FileNotFoundError(
        "The required WA DNR annual floating-kelp inventory is unavailable. Run "
        "kelp/download.py (the annual archive is included by default), or explicitly use "
        "--allow-generalized-only for a non-production generalized-mapping build."
    )


def load_kelp_inventory(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    allow_generalized_only: bool = False,
):
    """Normalize annual observations separately from generalized kelp mapping."""

    import geopandas as gpd

    config = load_habitat_download_config(SECTION_NAME, config_path)
    annual_frames = _annual_kelp_inventory(config)
    _require_annual_inventory(
        annual_frames,
        allow_generalized_only=allow_generalized_only,
    )
    frames: list[Any] = list(annual_frames)

    persistence = _read_optional(_source_path(config, "wa_dnr_kelp_persistence"))
    if persistence is not None:
        category = pd.to_numeric(persistence["PROP_CATEGORY"], errors="coerce")
        persistence_ratio = category.map({1: 0.1, 2: 0.3, 3: 0.5, 4: 0.7, 5: 0.9})
        frames.append(
            _records(
                persistence,
                source_dataset="WA_DNR_FLOATING_KELP_PERSISTENCE_CLASS",
                feature_id_column="OBJECTID",
                source_persistence_ratio=persistence_ratio,
                evidence_class="generalized_mapping",
                composition_eligible=False,
                supports_area=False,
                confidence=2,
                survey_method="multi-year floating-kelp synthesis",
                spatial_precision="mapped_persistence_polygon",
                temporal_precision="multi_year_binned_class",
            )
        )

    shorezone = _read_optional(_source_path(config, "wa_dnr_shorezone_floating_kelp"))
    if shorezone is not None:
        values = shorezone["FLOATKELP"].astype(str).str.upper()
        shorezone = shorezone.loc[values.isin(["CONTINUOUS", "PATCHY", "ABSENT"])].copy()
        status = np.where(
            shorezone["FLOATKELP"].astype(str).str.upper().eq("ABSENT"),
            "absent",
            "present",
        )
        frames.append(
            _records(
                shorezone,
                source_dataset="WA_DNR_SHOREZONE_FLOATING_KELP",
                feature_id_column="OBJECTID",
                status=status,
                evidence_class="generalized_mapping",
                composition_eligible=False,
                supports_area=False,
                confidence=2,
                survey_method="ShoreZone aerial/video interpretation",
                spatial_precision="shoreline_segment",
                temporal_precision="legacy_compilation",
            )
        )

    bc = _read_optional(_source_path(config, "bc_crims_kelp"))
    if bc is not None:
        frames.append(
            _records(
                bc,
                source_dataset="BC_CRIMS_KELP_BEDS",
                feature_id_column="OBJECTID",
                evidence_class="generalized_mapping",
                composition_eligible=True,
                supports_area=True,
                confidence=2,
                survey_method="legacy CRIMS source compilation",
                spatial_precision="mapped_polygon",
                temporal_precision="source_date_not_standardized",
            )
        )
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        raise FileNotFoundError("No kelp sources are available. Run kelp/download.py.")
    inventory = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs="EPSG:4326"
    )
    return normalize_inventory(inventory)


def build_kelp_habitat(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    allow_generalized_only: bool = False,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    inventory = load_kelp_inventory(
        config_path,
        allow_generalized_only=allow_generalized_only,
    )
    annual_available = bool(
        inventory["SOURCE_DATASET"].astype(str).str.fullmatch(r"WA_DNR_FLOATING_KELP_\d{4}").any()
    )
    return build_habitat_products(
        inventory,
        config,
        config_path,
        source_completeness={
            "required_source": "wa_dnr_annual_floating_kelp",
            "annual_observations_available": annual_available,
            "allow_generalized_only": allow_generalized_only,
            "status": ("complete" if annual_available else "generalized_only_explicit_override"),
            "included_source_datasets": sorted(
                set(inventory["SOURCE_DATASET"].dropna().astype(str))
            ),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--allow-generalized-only",
        action="store_true",
        help="Build without annual observations and record the explicit incomplete-source state.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in build_kelp_habitat(
        args.config,
        allow_generalized_only=args.allow_generalized_only,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
