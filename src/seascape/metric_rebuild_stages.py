"""Production API adapters for the complete metrics CLI profile."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

from seascape.core.config.paths import project_root
from seascape.metric_rebuild import BASE, settings


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_path(value):
    return (project_root() / Path(value).expanduser()).resolve()


def verify_source(item):
    import pyarrow.parquet as pq

    from seascape.core.artifacts.checksums import checksum_path

    path = source_path(item["path"])
    expected = item.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"A pinned SHA256 is required: {path}")
    members = sorted(path.rglob("*")) if path.is_dir() else [path]
    if path.is_dir() and any(member.is_symlink() for member in members):
        raise ValueError(
            f"Pinned source directories cannot contain symbolic links: {path}"
        )
    actual = checksum_path(path) if path.is_dir() else digest(path)
    if actual != expected:
        raise ValueError(f"Scientific source checksum mismatch: {path}")
    for member in members:
        if not member.is_file() or member.suffix.lower() not in {
            ".parquet",
            ".geoparquet",
        }:
            continue
        names = set(pq.read_schema(member).names)
        if names & {"h3_index", "H3_INDEX"} and (
            item.get("role") != "reporting_keys"
            or names - {"h3_index", "H3_INDEX", "H3_RESOLUTION"}
        ):
            raise ValueError(
                f"Computed H3 measurements cannot be rebuild inputs: {member}"
            )
    return {**item, "path": str(path), "sha256": actual}


def configured_source_paths(cfg):
    """Enumerate direct metric-profile inputs independently of the pin registry."""
    paths = []
    for habitat_cfg in cfg.get("habitats", {}).values():
        paths.extend([habitat_cfg["inventory"], habitat_cfg["source_context"]])
        paths.extend(habitat_cfg["reporting_keys"].values())
        paths.extend(habitat_cfg.get("additional_crims_pages", []))
    if cfg.get("mapped_substrate"):
        paths.append(cfg["mapped_substrate"]["source"])
    if cfg.get("artificial_reefs"):
        paths.extend(
            cfg["artificial_reefs"][key] for key in ("wdfw_pdf", "noaa_archive")
        )
    return [source_path(path) for path in paths]


def require_registered(paths, sources):
    """Accept exact pinned files or members of a pinned directory tree."""
    registered = [source_path(item["path"]) for item in sources]
    for value in paths:
        path = Path(value).resolve()
        if not any(
            path == pin or (pin.is_dir() and path.is_relative_to(pin))
            for pin in registered
        ):
            raise ValueError(f"Consumed scientific input is not registered: {path}")
        if not path.exists():
            raise FileNotFoundError(path)


def verify_consumed_sources(ctx, sources):
    """Cross-check producer receipts, keeping generated candidate dependencies separate."""
    from seascape.core.artifacts.checksums import checksum_path

    require_registered(configured_source_paths(settings(ctx.config_path)), sources)
    candidate = ctx.candidate_root.resolve()
    from seascape.metric_rebuild import metric_stages

    output_roots = tuple(
        (candidate / relative).resolve()
        for stage in metric_stages()
        for relative in stage.declared_outputs
    )

    def output_path(path):
        return path.is_relative_to(candidate) and any(
            path.is_relative_to(root) for root in output_roots
        )

    manifests = {
        path.resolve(): json.loads(path.read_text())
        for path in sorted((candidate / BASE).rglob("*manifest*.json"))
    }
    # Location alone never proves generation. Admit exact producer outputs with
    # checksum receipts, plus their producer manifests as upstream dependencies.
    generated = {}
    for manifest, payload in manifests.items():
        artifacts = payload.get("artifacts", [])
        if artifacts and not output_path(manifest):
            raise ValueError(f"Producer manifest escapes declared outputs: {manifest}")
        for artifact in artifacts:
            value, checksum = artifact.get("path"), artifact.get("checksum")
            if not value or not checksum:
                raise ValueError(f"Incomplete generated artifact receipt: {manifest}")
            path = (candidate / Path(value).expanduser()).resolve()
            if not output_path(path):
                raise ValueError(f"Generated artifact escapes declared outputs: {path}")
            if path in generated and generated[path] != checksum:
                raise ValueError(f"Conflicting generated artifact receipts: {path}")
            generated[path] = checksum
        if artifacts:
            generated[manifest] = checksum_path(manifest)

    for payload in manifests.values():
        for section in ("sources", "upstream_artifacts"):
            for item in payload.get(section, []):
                value = item.get("path")
                if not value or "://" in str(value):
                    continue
                path = Path(value).expanduser()
                if not path.is_absolute():
                    path = (
                        candidate / path
                        if (candidate / path).exists()
                        else source_path(path)
                    )
                path = path.resolve()
                expected = item.get("checksum")
                if path in generated:
                    if not expected or expected != generated[path]:
                        raise ValueError(
                            f"Consumed generated artifact has no matching receipt: {path}"
                        )
                else:
                    require_registered([path], sources)
                if expected and checksum_path(path) != expected:
                    raise ValueError(
                        f"Consumed source differs from producer receipt: {path}"
                    )


def acquire_sources(ctx):
    import requests

    from seascape.utils.habitat_acquisition import (
        _download_arcgis,
        _download_http_file,
        _download_wfs,
        download_habitat_sources,
    )

    cfg = settings(ctx.config_path)
    sources = []
    with requests.Session() as session:
        for item in cfg["sources"]:
            path = source_path(item["path"])
            acquisition = item.get("acquisition")
            if not path.exists() and acquisition:
                path.parent.mkdir(parents=True, exist_ok=True)
                source = acquisition["source"]
                kwargs = {
                    "bbox": acquisition["bbox"],
                    "timeout": 180,
                    "page_size": 2000,
                }
                if source["kind"] == "arcgis":
                    _download_arcgis(session, source, path, **kwargs)
                elif source["kind"] == "wfs":
                    _download_wfs(session, source, path, **kwargs)
                else:
                    _download_http_file(session, source, path, timeout=180)
            elif not path.exists() and item.get("url"):
                path.parent.mkdir(parents=True, exist_ok=True)
                _download_http_file(
                    session, item, path, timeout=float(item.get("timeout_seconds", 180))
                )
            sources.append(verify_source(item))
    if cfg.get("osm_acquisition"):
        paths, manifest = download_habitat_sources(
            "anthropogenic_seascape", source_path(cfg["osm_acquisition"])
        )
        for path in [*paths, manifest]:
            sources.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "sha256": digest(path),
                    "role": "acquired_osm_source",
                    "license": "ODbL-1.0",
                }
            )
    require_registered(configured_source_paths(cfg), sources)
    path = ctx.candidate_root / ".seascape/metric-sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "sources": sources,
                "scope": "Pinned raw or normalized scientific sources; no prior metric or graph artifacts",
            },
            indent=2,
        )
        + "\n"
    )


def verify_sources(ctx):
    receipt = json.loads(
        (ctx.candidate_root / ".seascape/metric-sources.json").read_text()
    )
    for item in receipt["sources"]:
        verify_source(item)
    verify_consumed_sources(ctx, receipt["sources"])
    return receipt


def _publish_tables(
    directory, outputs, *, context, source_paths=(), generated_paths=()
):
    import pyarrow.parquet as pq

    from seascape.publication import TransactionalSeascapePublisher
    from seascape.utils.artifacts import (
        build_manifest,
        capture_staged_parquet_artifact,
        checksum_artifact,
    )

    directory.mkdir(parents=True, exist_ok=True)
    with TransactionalSeascapePublisher(directory) as writer:
        artifacts = []
        for name, table in outputs.items():
            target = directory / name
            staged = writer.stage_path(target)
            pq.write_table(table, staged, compression="zstd")
            artifacts.append(capture_staged_parquet_artifact(writer, target))
        artifacts.extend(Path(path) for path in generated_paths)
        manifest = build_manifest(
            dataset_family="environment.seascape.metric_profile",
            run_id=writer.run_id,
            resolved_config={"profile": "metrics"},
            artifacts=artifacts,
            project_root=project_root(),
            sources=[
                {
                    "name": Path(p).name,
                    "path": str(p),
                    "checksum": checksum_artifact(Path(p)),
                    "license": context.get(
                        "rights", "Per-source terms retained in source context"
                    ),
                }
                for p in source_paths
            ],
            attribution=[
                {
                    "text": "Per-source attribution retained in source_context",
                    "license": context.get("rights", "Per-source terms"),
                }
            ],
            source_completeness="partial",
            upstream_artifacts=[],
            metadata={"source_context": context},
        )
        writer.write_manifest(directory / "metric_profile_manifest.json", manifest)
        writer.publish()


def _habitat_inventory(family, cfg):
    import geopandas as gpd
    import pandas as pd

    from seascape.utils.geometry_quality import audit_polygon_inventory

    inventory = gpd.read_parquet(source_path(cfg["inventory"]))
    context = json.loads(source_path(cfg["source_context"]).read_text())
    if family == "kelp" and cfg.get("additional_crims_pages"):
        from seascape.biogenic_habitat.kelp.build import _records

        frames = [
            gpd.read_file(source_path(p)).to_crs(4326)
            for p in cfg["additional_crims_pages"]
        ]
        raw = gpd.GeoDataFrame(
            pd.concat(frames, ignore_index=True), geometry="geometry", crs=4326
        )
        previous = inventory.loc[inventory.SOURCE_DATASET.eq("BC_CRIMS_KELP_BEDS")]
        raw = raw.loc[
            ~raw.geometry.to_wkb().isin(set(previous.geometry.to_wkb()))
        ].copy()
        raw = _records(
            raw,
            source_dataset="BC_CRIMS_KELP_BEDS",
            feature_id_column="KELP_ID",
            evidence_class="generalized_mapping",
            composition_eligible=True,
            supports_area=True,
            confidence=2,
            survey_method="legacy CRIMS source compilation",
            spatial_precision="mapped_polygon",
            temporal_precision="source_date_not_standardized",
        )
        raw.RECORD_ID = "WFS20261020:" + raw.RECORD_ID
        audit = audit_polygon_inventory(
            raw, policy=cfg.get("invalid_geometry_policy", "reject")
        )
        inventory = gpd.GeoDataFrame(
            pd.concat([inventory, audit.frame], ignore_index=True),
            geometry="geometry",
            crs=4326,
        )
        context = {**context, "rebuild_additional_geometry_audit": audit.report}
    if inventory.crs is None or not inventory.geometry.is_valid.all():
        raise ValueError(
            "Habitat input must retain valid, explicitly audited source geometry"
        )
    context.update(
        {
            "rebuild_source_inventory": cfg["inventory"],
            "rebuild_source_inventory_sha256": digest(source_path(cfg["inventory"])),
            "spatial_support": "Explicit independent full native H3 reporting grids; no clipping or metric values reused",
        }
    )
    return inventory, context


def habitat(family, ctx):
    import geopandas as gpd

    from seascape.biogenic_habitat.bivalve.extents import build_bivalve_extents
    from seascape.biogenic_habitat.kelp.extents import build_kelp_extents
    from seascape.biogenic_habitat.seagrass.extents import build_seagrass_extents
    from seascape.biogenic_habitat.seagrass.native import native_cell_geometries

    cfg = settings(ctx.config_path)["habitats"][family]
    inventory, context = _habitat_inventory(family, cfg)
    outputs = {}
    inputs = [
        source_path(cfg["inventory"]),
        source_path(cfg["source_context"]),
        *[source_path(p) for p in cfg.get("additional_crims_pages", [])],
    ]
    for res in (6, 8):
        path = source_path(cfg["reporting_keys"][res])
        keys = json.loads(path.read_text())
        if keys != sorted(set(keys)):
            raise ValueError("Reporting keys must be sorted and unique")
        geometries, _ = native_cell_geometries(keys)
        full = gpd.GeoDataFrame(
            {"H3_INDEX": keys, "H3_RESOLUTION": res}, geometry=geometries, crs=4326
        )
        result = {
            "kelp": build_kelp_extents,
            "seagrass": build_seagrass_extents,
            "bivalve": build_bivalve_extents,
        }[family](
            inventory,
            full,
            source_context={**context, "reporting_keys_sha256": digest(path)},
        )
        outputs[f"{family}-r{res}-static.parquet"] = result.tables.static
        if result.tables.dynamic is not None:
            outputs[f"{family}-r{res}-dynamic.parquet"] = result.tables.dynamic
        inputs.append(path)
    _publish_tables(
        ctx.candidate_root / BASE / "biogenic_habitat" / family,
        outputs,
        context=context,
        source_paths=inputs,
    )


def mapped_substrate(ctx):
    import pyarrow.parquet as pq

    from seascape.benthic_substrate.areal_stream import build_index, produce

    cfg = settings(ctx.config_path)["mapped_substrate"]
    source = source_path(cfg["source"])
    index = ctx.candidate_root / ".seascape/indices/mapped-substrate"
    # Every fresh run builds its own source index. Resume is governed by the workflow.
    build_index(
        source,
        digest(source),
        index,
        operation="current",
        geometry_policy=cfg.get("invalid_geometry_policy", "reject"),
    )
    output = {}
    for res in (6, 8):
        support = (
            ctx.candidate_root
            / BASE
            / "spatial_support/water_geometry"
            / f"H3_COASTAL_WATER_RES_{res}.parquet"
        )
        keys = sorted(
            pq.read_table(support, columns=["H3_INDEX"])["H3_INDEX"].to_pylist()
        )
        output[f"mapped-substrate-classes-r{res}-static.parquet"] = produce(
            index, support, digest(support), keys, rights=cfg["rights"], batch_size=128
        )
    _publish_tables(
        ctx.candidate_root / BASE / "benthic_substrate/mapped_classes",
        output,
        context=cfg,
        source_paths=[source],
    )


def anthropogenic(ctx):
    import pyarrow.parquet as pq

    from seascape.anthropogenic.artificial_reefs import (
        enrich_native,
        inventory,
        noaa_sites,
        published_sites,
        reconcile,
    )
    from seascape.anthropogenic.build import build_anthropogenic_seascape

    build_anthropogenic_seascape(ctx.config_path)
    cfg = settings(ctx.config_path).get("artificial_reefs")
    if not cfg:
        return
    primary, sources = published_sites()
    if digest(source_path(cfg["wdfw_pdf"])) != sources["wdfw"]["sha256"]:
        raise ValueError(
            "WDFW reviewed coordinate transcription differs from source PDF"
        )
    records, checks = reconcile(primary, noaa_sites(source_path(cfg["noaa_archive"])))
    directory = ctx.candidate_root / BASE / "anthropogenic"
    normalized = directory / "ARTIFICIAL_REEF_SOURCE_INVENTORY.parquet"
    inventory(records).to_parquet(normalized, index=False)
    evidence = {
        "inventory_path": str(normalized),
        "inventory_sha256": digest(normalized),
        "sources": sources,
        "cross_checks": checks,
        "noaa_archive_sha256": digest(source_path(cfg["noaa_archive"])),
    }
    core_manifest = json.loads((directory / "anthropogenic_manifest.json").read_text())
    output = {}
    for res in (6, 8):
        path = directory / f"ANTHROPOGENIC_RES_{res}.parquet"
        table = pq.read_table(path)
        metadata = dict(table.schema.metadata or {})
        metadata[b"seascape_domain"] = json.dumps(
            {
                "source_context": {
                    "core_manifest": core_manifest,
                    "core_table_sha256": digest(path),
                }
            }
        ).encode()
        enriched, _ = enrich_native(
            table.replace_schema_metadata(metadata), records, evidence=evidence
        )
        output[path.name] = enriched
    _publish_tables(
        directory / "enriched",
        output,
        context=evidence,
        source_paths=[
            source_path(cfg["wdfw_pdf"]),
            source_path(cfg["noaa_archive"]),
            normalized,
        ],
        generated_paths=[normalized],
    )


def _combine(tables):
    import pyarrow as pa

    from seascape.domain_parquets import METADATA_KEY

    contexts = {
        str(t["H3_RESOLUTION"][0].as_py()): json.loads(t.schema.metadata[METADATA_KEY])
        for t in tables
    }
    context = dict(next(iter(contexts.values())))
    context.pop("report", None)
    context["resolution_contexts"] = contexts
    return pa.concat_tables(
        tables, promote_options="permissive"
    ).replace_schema_metadata({METADATA_KEY: json.dumps(context).encode()})


def export_metrics(ctx):
    import pyarrow.parquet as pq
    import yaml

    from seascape.domain_parquets import AreaTables, export_domain_parquets
    from seascape.maintenance.update_seascape_feature_catalog import (
        PRODUCTS,
        common_name,
        role,
        scientific_metadata,
        unit,
        variable_kind,
    )
    from seascape.spatial_support.water_network import load_model_area_support

    products = {}
    root = ctx.candidate_root
    canonical = {}
    for res in (6, 8):
        path = root / f"config/metric-canonical-r{res}.parquet"
        path.parent.mkdir(exist_ok=True)
        load_model_area_support(res, ctx.config_path).to_parquet(path, index=False)
        canonical[res] = str(path.relative_to(root))
    ids = (
        "h3_marine_support",
        "bathymetry",
        "geomorphometry",
        "shoreline_proximity",
        "shoreline_characterization",
        "nearshore_transitions",
        "coast_complexity",
        "exposure_and_enclosure",
        "waterbody_morphometry",
        "fluvial_connectivity",
        "freshwater_sources",
        "estuarine_connectivity",
        "anthropogenic",
        "benthic_substrate",
    )
    for pid in ids:
        spec = PRODUCTS[pid]
        paths = dict(spec.paths)
        if pid == "h3_marine_support":
            paths = canonical
        if pid == "anthropogenic" and settings(ctx.config_path).get("artificial_reefs"):
            paths = {
                res: str(Path(p).parent / "enriched" / Path(p).name)
                for res, p in paths.items()
            }
        schemas = {res: pq.read_schema(root / p) for res, p in paths.items()}
        features = {}
        for name in sorted(
            set().union(*(set(s.names) for s in schemas.values()))
            - {"H3_INDEX", "H3_RESOLUTION"}
        ):
            resolutions = [
                res for res, schema in schemas.items() if name in schema.names
            ]
            field = schemas[resolutions[0]].field(name)
            field_role = role(name, pid, field)
            features[name] = {
                "common_name": common_name(name),
                "collection_paths": {res: paths[res] for res in resolutions},
                "unit": unit(name, field),
                "role": field_role,
                "variable_kind": variable_kind(pid, field_role),
                "available_resolutions": resolutions,
                **scientific_metadata(pid, name, spec),
            }
        products[pid] = {"collection": {"paths": paths}, "features": features}
    catalog = root / "config/feature_catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"schema_version": 4, "products": products}, sort_keys=False)
    )
    additions = {}
    for area in ("kelp", "seagrass", "bivalve", "mapped-substrate-classes"):
        directory = (
            root
            / BASE
            / (
                f"biogenic_habitat/{area}"
                if area != "mapped-substrate-classes"
                else "benthic_substrate/mapped_classes"
            )
        )
        variants = {}
        for kind in ("static", "dynamic"):
            paths = sorted(directory.glob(f"{area}-r*-{kind}.parquet"))
            if paths:
                variants[kind] = _combine([pq.read_table(p) for p in paths])
        additions[area] = AreaTables(**variants)
    output = ctx.output_dir or ctx.canonical_root / "Data/Seascape"
    report = {}

    def validate_staged(staged):
        report.update(verify_metrics(staged))
        report["sources_verified_after_build"] = len(verify_sources(ctx)["sources"])

    export_domain_parquets(
        workspace=root,
        output=output,
        catalog_path=catalog,
        additional_areas=additions,
        _validate_staged=validate_staged,
    )
    path = root / ".seascape/metric-verification.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Verified {len(report['files'])} current metric Parquets: {output}", flush=True
    )


def verify_metrics(output):
    """Check the independent packaged schema and every public row in bounded batches."""
    import h3
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    output = Path(output)
    contract = json.loads(
        files("seascape").joinpath("resources/metric_delivery_schema.json").read_text()
    )["files"]
    from seascape.domain_parquets import _catalog

    catalog = _catalog(output)
    catalog_files = {
        name
        for record in catalog.values()
        for kind in ("static", "dynamic")
        for name in record.get(kind, {}).values()
    }
    if catalog_files != set(contract):
        raise ValueError(
            "The metric output file set differs from the 29-table contract"
        )
    report = {}
    for name, expected in contract.items():
        path = output / name
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows == 0:
            raise ValueError(f"Empty metric product: {name}")
        if parquet.schema_arrow.names != expected:
            raise ValueError(
                f"Metric names/order differ: {name}: {parquet.schema_arrow.names}"
            )
        res = int(name.split("-r")[-1].split("-", 1)[0])
        key = "H3_INDEX" if "H3_INDEX" in expected else "h3_index"
        previous = None
        for batch in parquet.iter_batches(batch_size=32768):
            table = pa.Table.from_batches([batch])
            dates = (
                table["date"].to_pylist() if "date" in expected else [None] * len(table)
            )
            for cell, day in zip(table[key].to_pylist(), dates, strict=True):
                grain = (cell, day) if "date" in expected else (cell,)
                if (
                    not h3.is_valid_cell(cell)
                    or h3.get_resolution(cell) != res
                    or (previous is not None and grain <= previous)
                ):
                    raise ValueError(
                        f"Invalid/unsorted/duplicate native identity: {name}"
                    )
                previous = grain
            for field in table.schema:
                if (
                    pa.types.is_floating(field.type)
                    and pc.any(
                        pc.fill_null(pc.invert(pc.is_finite(table[field.name])), False)
                    ).as_py()
                ):
                    raise ValueError(f"Nonfinite metric: {name}/{field.name}")
        context = json.loads(
            (parquet.schema_arrow.metadata or {}).get(b"seascape_domain", b"{}")
        )
        if not context.get("delivery_projection"):
            raise ValueError(f"Missing projection provenance: {name}")
        report[name] = {
            "rows": parquet.metadata.num_rows,
            "columns": expected,
            "sha256": digest(path),
        }
    return {"status": "passed", "files": report}


def execute(name, ctx):
    from seascape import workflow

    calls = {
        "sources": acquire_sources,
        "water-geometry": lambda c: __import__(
            "seascape.spatial_support.coastal_policy_build",
            fromlist=["build_coastal_policy"],
        ).build_coastal_policy(c.config_path),
        "water-network": workflow._run_h3_marine_spatial_support,
        "bathymetry": workflow._run_seascape_bathymetry,
        "terrain": workflow._run_seascape_geomorphometry,
        "shoreline-proximity": workflow._run_seascape_shoreline_proximity,
        "coast-complexity": lambda c: __import__(
            "seascape.coastal_configuration.coast_complexity_build",
            fromlist=["build_coast_complexity"],
        ).build_coast_complexity(c.config_path),
        "nearshore": lambda c: __import__(
            "seascape.coastal_configuration.nearshore_build",
            fromlist=["build_nearshore_transitions"],
        ).build_nearshore_transitions(c.config_path),
        "coastal-bounds": workflow._run_seascape_exposure_and_enclosure,
        "waterbody": workflow._run_seascape_waterbody_morphometry,
        "shoreline": workflow._run_seascape_shoreline_characterization,
        "freshwater": workflow._run_seascape_freshwater_sources,
        "fluvial": workflow._run_seascape_fluvial_connectivity,
        "estuary": workflow._run_seascape_estuarine_connectivity,
        "anthropogenic": anthropogenic,
        "substrate": workflow._run_seascape_substrate_classification,
        "mapped-substrate": mapped_substrate,
        "kelp": lambda c: habitat("kelp", c),
        "seagrass": lambda c: habitat("seagrass", c),
        "bivalve": lambda c: habitat("bivalve", c),
        "export": export_metrics,
    }
    if name != "sources":
        receipt = json.loads(
            (ctx.candidate_root / ".seascape/metric-sources.json").read_text()
        )
        require_registered(
            configured_source_paths(settings(ctx.config_path)), receipt["sources"]
        )
    calls[name](ctx)
