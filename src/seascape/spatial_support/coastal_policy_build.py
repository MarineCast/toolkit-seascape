"""Build a source-identified coastal mask, native memberships and wider graph context."""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import Transformer
from shapely.ops import transform

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root
from seascape.publication import TransactionalSeascapePublisher
from seascape.utils.artifacts import (
    build_manifest,
    checksum_artifact,
    stage_parquet_artifact,
)

from . import coastal_policy


def build_coastal_policy(config_path: str | Path) -> tuple[Path, ...]:
    """Publish a locally configured, bounded source-scale geometry family atomically."""
    raw = load_data_config(config_path, domains="SEASCAPE_LAYER")
    section = raw.get("coastal_policy")
    if not isinstance(section, dict):
        raise ValueError("Configure coastal_policy source registries before building")
    root = project_root().resolve()
    names = (
        "coastline_path",
        "marine_water_path",
        "inland_water_path",
        "source_context_path",
    )
    if any(not section.get(name) for name in names):
        raise ValueError(
            "Coastal-policy build requires four explicit source registry paths"
        )
    paths = {name: (root / str(section[name])).resolve() for name in names}
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    output = (
        root
        / str(
            section.get(
                "output_dir",
                "data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry",
            )
        )
    ).resolve()
    if not output.is_relative_to(root):
        raise ValueError("Coastal-policy output escapes workspace")
    if any(path.is_relative_to(output) for path in paths.values()):
        raise ValueError("Coastal-policy inputs must be separate from output")
    resolutions = tuple(section.get("resolutions", (5, 6, 7, 8)))
    if (
        not resolutions
        or len(set(resolutions)) != len(resolutions)
        or any(type(r) is not int or not 0 <= r <= 15 for r in resolutions)
    ):
        raise ValueError("Coastal native resolutions must be distinct H3 resolutions")
    context_buffer_m = float(section.get("graph_context_buffer_m", 60000))
    if not math.isfinite(context_buffer_m) or context_buffer_m <= 0:
        raise ValueError("Graph context buffer must be positive and finite")
    fingerprints = {str(path): checksum_artifact(path) for path in paths.values()}
    frames = {name: gpd.read_parquet(path) for name, path in paths.items()}
    code_paths = (Path(__file__), Path(coastal_policy.__file__))
    code = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in code_paths
    }
    result = coastal_policy.build_coastal_mask(
        *(frames[name] for name in names),
        distance_m=float(section.get("offshore_distance_m", 22224)),
        tolerance_m=float(section.get("numerical_tolerance_m", 5)),
        max_vertices=int(section.get("max_vertices", 2000000)),
    )
    metric = Transformer.from_crs(4326, 32610, always_xy=True).transform
    geographic = Transformer.from_crs(32610, 4326, always_xy=True).transform
    context_region = transform(
        geographic, transform(metric, result.geometry).buffer(context_buffer_m)
    )
    source_context = frames["source_context_path"].geometry.union_all()
    if not source_context.covers(context_region):
        raise ValueError("Graph context is truncated by its source context")
    water = context_region.intersection(
        frames["marine_water_path"].geometry.union_all()
    )
    if water.is_empty or not water.is_valid:
        raise ValueError("Graph context water is empty or invalid")
    report_frame = gpd.GeoDataFrame(
        {
            "AREA": ["COASTAL_POLICY_REPORTING"],
            "SOURCE_SCALE_QUALIFICATION": ["static_cartographic_reference"],
        },
        geometry=[result.geometry],
        crs=4326,
    )
    context_frame = gpd.GeoDataFrame(
        {
            "AREA": ["COASTAL_POLICY_CONTEXT"],
            "SOURCE_SCALE_QUALIFICATION": ["static_cartographic_reference"],
        },
        geometry=[water],
        crs=4326,
    )
    outputs: list[tuple[Any, Path]] = [
        (report_frame, output / "COASTAL_REPORTING_MASK.parquet"),
        (context_frame, output / "COASTAL_CONTEXT_WATER.parquet"),
    ]
    membership = {}
    for resolution in resolutions:
        full, wet = coastal_policy.native_mask_membership(
            result, resolution, max_cells=int(section.get("max_cells", 500000))
        )
        outputs.extend(
            (
                (full, output / f"H3_COASTAL_FULL_RES_{resolution}.parquet"),
                (wet, output / f"H3_COASTAL_WATER_RES_{resolution}.parquet"),
            )
        )
        membership[str(resolution)] = {
            "native_cells": len(full),
            "source_water_area_m2": float(wet.WATER_AREA_M2.sum()),
            "r6_support_role": "direct_native_polygon_intersection_not_R8_parent_union"
            if resolution == 6
            else "native_positive_area_intersection",
        }
    for path in paths.values():
        if checksum_artifact(path) != fingerprints[str(path)]:
            raise ValueError("Coastal-policy source changed during processing")
    if any(
        hashlib.sha256(path.read_bytes()).hexdigest() != code[str(path)]
        for path in code_paths
    ):
        raise ValueError("Coastal-policy code changed during processing")
    with TransactionalSeascapePublisher(output) as publisher:
        artifacts = [
            stage_parquet_artifact(publisher, frame, path) for frame, path in outputs
        ]
        manifest = build_manifest(
            dataset_family="environment.seascape.coastal_policy_water_geometry",
            run_id=publisher.run_id,
            resolved_config=section,
            artifacts=artifacts,
            project_root=root,
            sources=[
                {
                    "name": name,
                    "path": str(paths[name]),
                    "checksum": fingerprints[str(paths[name])],
                    "license": " | ".join(
                        sorted(frames[name].RIGHTS.astype(str).unique())
                    ),
                }
                for name in names
            ],
            upstream_artifacts=[],
            attribution=[
                {
                    "text": "Source cartography and IDs retained in input registries; GSHHG Wessel/Smith and Marine Regions IHO where configured",
                    "license": "See source records",
                }
            ],
            source_completeness="partial",
            metadata={
                "support_kind": "coastal_policy_context",
                "reporting_membership": "positive_area_intersection",
                "mask_method": result.report["method"],
                "model_eligible": False,
                "coastal_policy": result.report,
                "native_memberships": membership,
                "code_sha256": code,
                "graph_context_buffer_m": context_buffer_m,
                "context_buffer_method": "EPSG:32610 processing margin; not the geodesic reporting boundary",
            },
        )
        path = output / "water_geometry_manifest.json"
        publisher.stage_manifest(path, manifest)
        publisher.publish()
    return tuple([path for _, path in outputs] + [path])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    for path in build_coastal_policy(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
