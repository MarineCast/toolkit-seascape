"""Build one Kelp dataset with annual extent and an all-history polygon union."""

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
            "RECORD_ID": [
                f"{source_dataset}:{value}:{index}" for index, value in enumerate(ids)
            ],
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


def _source_path(config: Any, source_name: str) -> Path | None:
    source = config.sources[source_name]
    return (
        config.raw_dir / str(source["raw_filename"])
        if source.get("enabled", True)
        else None
    )


def _read_optional(path: Path | None):
    import geopandas as gpd

    if path is None:
        return None
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
    if not source.get("enabled", True):
        return []
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
    outputs = []
    for year, frame, name in candidates:
        outputs.append(
            _records(
                frame,
                source_dataset=f"WA_DNR_FLOATING_KELP_{year}",
                year=year,
                evidence_class="direct_observation",
                # The latest mapped year must be chosen for each location,
                # not once for the entire cross-border archive.
                composition_eligible=True,
                supports_area=True,
                confidence=3,
                survey_method="annual aerial floating-canopy inventory",
                spatial_precision=(
                    "approximately_4m_raster_processing_2010_2024"
                    if year >= 2010
                    else "vector_CAD_processing_1989_1992"
                    if year <= 1992
                    else "approximately_20m_raster_processing_1994_2009"
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
    wa_enabled = bool(
        config.sources["wa_dnr_annual_floating_kelp"].get("enabled", True)
    )
    annual_frames = _annual_kelp_inventory(config)
    _require_annual_inventory(
        annual_frames,
        allow_generalized_only=allow_generalized_only or not wa_enabled,
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
        shorezone = shorezone.loc[
            values.isin(["CONTINUOUS", "PATCHY", "ABSENT"])
        ].copy()
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
    inventory: Any = None,
    full_cells: dict[int, Any] | None = None,
    output: str | Path | None = None,
    source_context: dict[str, Any] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    include_undated: bool | None = None,
) -> tuple[Path, ...]:
    """Produce static/dynamic Kelp tables together; no separate footprint producer.

    Explicit audited inventory/full-cell inputs support bounded replay without
    downloads. With no year bounds every available historical year is retained.
    Internal source inventory and quality manifest remain separate from features.
    """
    import hashlib
    import json

    import pyarrow.parquet as pq

    from seascape.core.artifacts import PublishedArtifact, TransactionalFamilyPublisher
    from seascape.core.config.paths import project_root
    from seascape.spatial_support.water_network.config import load_water_network_config
    from seascape.utils.artifacts import (
        build_manifest,
        checksum_artifact,
        parquet_contract,
    )
    from seascape.utils.geometry_quality import prepare_mixed_habitat_inventory

    from .extents import build_kelp_extents

    explicit_replay = (
        inventory is not None
        and full_cells is not None
        and output is not None
        and source_context is not None
    )
    config = (
        None
        if explicit_replay
        else load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    )
    if inventory is None:
        inventory = load_kelp_inventory(
            config_path, allow_generalized_only=allow_generalized_only
        )
    if "GEOMETRY_PROCESSING" not in inventory:
        audit = prepare_mixed_habitat_inventory(
            inventory, policy=config.invalid_geometry_policy if config else "reject"
        )
        inventory, geometry_report = audit.frame, audit.report
    else:
        if not inventory.geometry.is_valid.all():
            raise ValueError(
                "Previously audited kelp geometry is invalid; inspect its recorded audit"
            )
        geometry_report = {
            "policy": "retained_recorded_audit",
            "retained_records": len(inventory),
            "repaired_records": int(
                inventory.GEOMETRY_PROCESSING.eq(
                    "made_valid_not_source_certified"
                ).sum()
            ),
        }
    if full_cells is None:
        import geopandas as gpd

        network = load_water_network_config(config_path)
        full_cells = {
            res: gpd.read_parquet(network.full_geometry_path(res)) for res in (6, 8)
        }
    if set(full_cells) != {6, 8}:
        raise ValueError(
            "Canonical Kelp requires independently supplied R6 and R8 full-cell support"
        )
    sources = (
        load_habitat_download_config(SECTION_NAME, config_path).sources
        if config
        else {}
    )
    context = {
        "rights": "Per-source declared public data terms",
        "sources": sources,
        "geometry_audit": geometry_report,
        **(source_context or {}),
    }
    results = {
        res: build_kelp_extents(
            inventory,
            cells,
            source_context=context,
            start_year=start_year,
            end_year=end_year,
            include_undated=include_undated,
        )
        for res, cells in sorted(full_cells.items())
    }
    destination = Path(output).resolve() if output else config.processed_dir
    paths = []
    identity = hashlib.sha256(str(destination).encode()).hexdigest()[:16]
    control = destination.parent / f".kelp-publication-{identity}"
    with TransactionalFamilyPublisher(control) as writer:
        staged_family = writer.stage_path(destination)
        staged_family.mkdir()
        for res, result in results.items():
            for kind, table in (
                ("static", result.tables.static),
                ("dynamic", result.tables.dynamic),
            ):
                if table is None:
                    continue
                name = f"KELP{'_ANNUAL' if kind == 'dynamic' else ''}_RES_{res}.parquet"
                path = destination / name
                staged = staged_family / name
                pq.write_table(table, staged, compression="zstd")
                if not pq.read_table(staged).equals(table, check_metadata=True):
                    raise ValueError(f"Kelp serialization mismatch: {name}")
                paths.append(path)
        inventory_path = destination / "KELP_SOURCE_INVENTORY.parquet"
        inventory.to_parquet(
            staged_family / inventory_path.name, index=False, compression="zstd"
        )
        paths.append(inventory_path)
        artifacts = []
        for path in paths:
            staged = staged_family / path.name
            contract = parquet_contract(staged)
            artifacts.append(
                PublishedArtifact(
                    path=path,
                    checksum=checksum_artifact(staged),
                    size_bytes=staged.stat().st_size,
                    schema=tuple(contract.get("fields", ())),
                    row_count=int(contract["row_count"]),
                    h3_cell_count=contract.get("unique_h3_count"),
                    h3_cell_set_hash=contract.get("h3_cell_set_hash"),
                    h3_resolutions=tuple(contract.get("h3_resolutions", ())),
                )
            )
        manifest = build_manifest(
            dataset_family="environment.seascape.kelp_habitat",
            run_id=writer.run_id,
            resolved_config={
                "method": "kelp_positive_extent_union_v2",
                "start_year": start_year,
                "end_year": end_year,
                "include_undated": include_undated,
            },
            artifacts=artifacts,
            project_root=project_root(),
            sources=[
                {
                    "name": "retained_normalized_kelp_inventory",
                    "license": context["rights"],
                    "observation_period": "Per-record observed years; unknown legacy dates remain unknown",
                }
            ],
            upstream_artifacts=[
                {"path": path, "checksum": checksum}
                for path, checksum in context.get("input_hashes", {}).items()
            ],
            attribution=[
                {
                    "text": "Washington DNR; Province of British Columbia",
                    "license": context["rights"],
                }
            ],
            source_completeness="partial",
            metadata={
                "source_context": context,
                "scientific_method_version": "kelp_positive_extent_union_v2",
                "scientific_features": ["Annual Kelp Extent", "Kelp Extent (All Time)"],
                "reports": {str(res): result.report for res, result in results.items()},
            },
        )
        manifest_path = destination / "kelp_habitat_manifest.json"
        (staged_family / manifest_path.name).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        writer.publish()
    return (*paths, manifest_path)


def main() -> int:
    import json

    import geopandas as gpd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--allow-generalized-only", action="store_true")
    parser.add_argument(
        "--inventory",
        help="Retained normalized/audited inventory; never downloaded implicitly",
    )
    parser.add_argument(
        "--full-cells", action="append", default=[], metavar="RES=PARQUET"
    )
    parser.add_argument(
        "--source-context",
        help="JSON retaining source hashes, dates, rights and geometry audit",
    )
    parser.add_argument(
        "--output",
        help="Internal staged producer directory; final delivery is a separate promotion",
    )
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument(
        "--include-undated", action=argparse.BooleanOptionalAction, default=None
    )
    args = parser.parse_args()
    cells = {
        int(item.split("=", 1)[0]): gpd.read_parquet(item.split("=", 1)[1])
        for item in args.full_cells
    } or None
    context = (
        json.loads(Path(args.source_context).read_text())
        if args.source_context
        else None
    )
    for path in build_kelp_habitat(
        args.config,
        allow_generalized_only=args.allow_generalized_only,
        inventory=gpd.read_parquet(args.inventory) if args.inventory else None,
        full_cells=cells,
        output=args.output,
        source_context=context,
        start_year=args.start_year,
        end_year=args.end_year,
        include_undated=args.include_undated,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
