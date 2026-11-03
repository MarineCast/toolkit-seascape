"""One Seagrass feature: all-history geometric union with source-date provenance."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from seascape.utils.habitat_acquisition import load_habitat_download_config
from seascape.utils.habitat_configuration import load_habitat_surface_config

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME
from .sources import mapped_inventory, raster_inventory

LOGGER = logging.getLogger(__name__)
PREFIX = "SEAGRASS"


def load_seagrass_inventory(config_path: str | Path = DEFAULT_CONFIG_PATH):
    """Read configured local source files; no acquisition occurs during a build."""
    import geopandas as gpd

    download = load_habitat_download_config(SECTION_NAME, config_path)
    frames = []
    for key, source in download.sources.items():
        if not source.get("enabled", True):
            continue
        path = download.raw_dir / str(source["raw_filename"])
        if not path.exists():
            raise FileNotFoundError(
                f"Configured Seagrass source unavailable: {path}; acquire explicitly or disable its source"
            )
        if key.startswith("global_sentinel2_seagrass_"):
            years = tuple(
                map(int, key.removeprefix("global_sentinel2_seagrass_").split("_"))
            )
            frames.append(
                raster_inventory(
                    path, source=key.upper(), period=years, bbox=download.bbox
                )
            )
        else:
            raw = gpd.read_file(path)
            if key == "bc_crims_eelgrass":
                frames.append(
                    mapped_inventory(
                        raw,
                        source="BC_CRIMS_EELGRASS",
                        year=None,
                        method="Legacy CRIMS eelgrass compilation; map date is not observation date",
                        species_column="SPECIES",
                        map_date_column="MAP_DATE",
                    )
                )
            elif key in {
                "wa_dnr_intertidal_eelgrass_1995",
                "wa_dnr_intertidal_eelgrass_1996",
            }:
                year = int(key.rsplit("_", 1)[1])
                # Validate the provider vegetation class even when reading retained files.
                raw = (
                    raw.loc[raw.IVEG_CD.eq("eel")]
                    if year == 1995
                    else raw.loc[raw.GRID_CODE.eq(5)]
                )
                frames.append(
                    mapped_inventory(
                        raw,
                        source=key.upper(),
                        year=year,
                        method=f"WA DNR {year} intertidal vegetation inventory; remotely mapped eelgrass class footprint",
                    )
                )
            else:
                raise ValueError(f"Unreviewed Seagrass source: {key}")
    if not frames:
        raise ValueError("No configured Seagrass polygon evidence")
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=4326
    )


def build_seagrass_habitat(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    inventory: Any = None,
    full_cells: dict[int, Any] | None = None,
    output: str | Path | None = None,
    source_context: dict[str, Any] | None = None,
) -> tuple[Path, ...]:
    """Produce only the static Seagrass All Time union.

    Explicit audited inventory/full-cell inputs support bounded replay without
    downloads. Every eligible historical record and its original date qualification is retained.
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

    from .extents import build_seagrass_extents

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
        inventory = load_seagrass_inventory(config_path)
    if "GEOMETRY_PROCESSING" not in inventory:
        audit = prepare_mixed_habitat_inventory(
            inventory, policy=config.invalid_geometry_policy if config else "reject"
        )
        inventory, geometry_report = audit.frame, audit.report
    else:
        if not inventory.geometry.is_valid.all():
            raise ValueError(
                "Previously audited seagrass geometry is invalid; inspect its recorded audit"
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
            "Canonical Seagrass requires independently supplied R6 and R8 full-cell support"
        )
    sources = (
        load_habitat_download_config(SECTION_NAME, config_path).sources
        if config
        else {}
    )
    download = (
        load_habitat_download_config(SECTION_NAME, config_path) if config else None
    )
    context = {
        "rights": "Per-source declared public data terms",
        "sources": sources,
        "input_hashes": {
            str(download.raw_dir / str(spec["raw_filename"])): checksum_artifact(
                download.raw_dir / str(spec["raw_filename"])
            )
            for spec in sources.values()
            if spec.get("enabled", True)
        }
        if config
        else {},
        "geometry_audit": geometry_report,
        **(source_context or {}),
    }
    results = {
        res: build_seagrass_extents(
            inventory,
            cells,
            source_context=context,
        )
        for res, cells in sorted(full_cells.items())
    }
    destination = Path(output).resolve() if output else config.processed_dir
    paths = []
    identity = hashlib.sha256(str(destination).encode()).hexdigest()[:16]
    control = destination.parent / f".seagrass-publication-{identity}"
    with TransactionalFamilyPublisher(control) as writer:
        staged_family = writer.stage_path(destination)
        staged_family.mkdir()
        for res, result in results.items():
            for table in (result.tables.static,):
                name = f"SEAGRASS_RES_{res}.parquet"
                path = destination / name
                staged = staged_family / name
                pq.write_table(table, staged, compression="zstd")
                if not pq.read_table(staged).equals(table, check_metadata=True):
                    raise ValueError(f"Seagrass serialization mismatch: {name}")
                paths.append(path)
        inventory_path = destination / "SEAGRASS_SOURCE_INVENTORY.parquet"
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
            dataset_family="environment.seascape.seagrass_habitat",
            run_id=writer.run_id,
            resolved_config={
                "method": "seagrass_positive_extent_union_v2",
            },
            artifacts=artifacts,
            project_root=project_root(),
            sources=[
                {
                    "name": "retained_normalized_seagrass_inventory",
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
                    "text": "Washington DNR; Province of British Columbia; Peng et al. (2026)",
                    "license": context["rights"],
                }
            ],
            source_completeness="partial",
            metadata={
                "source_context": context,
                "scientific_method_version": "seagrass_positive_extent_union_v2",
                "scientific_features": ["Seagrass Extent (All Time)"],
                "reports": {str(res): result.report for res, result in results.items()},
            },
        )
        manifest_path = destination / "seagrass_habitat_manifest.json"
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
    for path in build_seagrass_habitat(
        args.config,
        inventory=gpd.read_parquet(args.inventory) if args.inventory else None,
        full_cells=cells,
        output=args.output,
        source_context=context,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
