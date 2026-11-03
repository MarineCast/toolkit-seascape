import hashlib
import json
import os
from pathlib import Path

import geopandas as gpd
import h3
from shapely.geometry import Polygon, box
from shapely.ops import unary_union


def _build_study_fixture(tmp_path):
    fixture = Path(__file__).with_name("fixtures") / "study.pending.json"
    config = json.loads(fixture.read_text())
    data = tmp_path / "Data"
    data.mkdir()
    path = tmp_path / "study.json"
    a = h3.latlng_to_cell(48.1, -123.1, 7)
    b = next(c for c in sorted(h3.grid_disk(a, 1)) if c != a)
    polygons = [
        Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(c)]) for c in [a, b]
    ]
    extent = unary_union(polygons)
    xmin, ymin, xmax, ymax = extent.bounds
    water = extent.intersection(
        box(xmin - 0.1, ymin - 0.1, xmax + 0.1, (ymin + ymax) / 2)
    )
    land = extent.difference(water)
    mask = polygons[0].intersection(water)
    files = {"mask": mask, "extent": extent, "water": water, "land": land}
    for name, geom in files.items():
        gpd.GeoDataFrame(geometry=[geom], crs=4326).to_parquet(
            data / (name + ".parquet"), index=False
        )
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    config["storage"]["data_root"] = "Data"
    config["domain"].update(
        status="approved",
        geometry_status="source_relative_validated",
        approval={
            "approved_at": "2026-10-16T00:00:00Z",
            "source_message_id": "synthetic-test",
            "scope": "source_relative_coastal_geometry",
            "statement": "Synthetic software test only",
        },
    )
    config["domain"]["selection_policy"]["mask_status"] = "source_relative_validated"
    memberships = []
    for resolution, role, ids in [
        (5, "water_reporting", [h3.cell_to_parent(a, 5)]),
        (6, "water_reporting", [h3.cell_to_parent(a, 6)]),
        (7, "water_reporting", [a]),
        (7, "land_source", [a, b]),
        (7, "water_source", [a, b]),
    ]:
        artifact = data / (role + str(resolution) + ".txt")
        artifact.write_bytes(("\n".join(sorted(ids)) + "\n").encode())
        memberships.append(
            {
                "resolution": resolution,
                "role": role,
                "count": len(ids),
                "relative_path": os.path.relpath(artifact, tmp_path),
                "sha256": sha(artifact),
            }
        )
    registry = config["grid_registry"]
    registry.update(
        status="validated",
        mask_revision="synthetic-mask",
        mask_sha256=sha(data / "mask.parquet"),
        mask_relative_path="Data/mask.parquet",
        mask_hash_policy="sha256_exact_file_bytes",
        manifest_relative_path="Data/manifest.json",
        memberships=memberships,
    )
    manifest = {
        k: registry[k]
        for k in ["mask_revision", "mask_sha256", "mask_hash_policy", "memberships"]
    }
    manifest["producer_source_extents"] = {
        "viewshed": {
            "relative_path": "Data/extent.parquet",
            "sha256": sha(data / "extent.parquet"),
            "bbox_wgs84": list(extent.bounds),
            "producer_buffer": config["producer_buffers"]["viewshed"],
        }
    }
    manifest["physical_context"] = {
        role: {
            "relative_path": "Data/" + name + ".parquet",
            "sha256": sha(data / (name + ".parquet")),
        }
        for role, name in [
            ("land_polygon_path", "land"),
            ("water_polygon_path", "water"),
        ]
    }
    config["products"]["seascape"]["catalog_relative_path"] = (
        "Data/Seascape/catalog.json"
    )
    manifest_path = data / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    registry["manifest_sha256"] = sha(manifest_path)
    path.write_text(json.dumps(config))
    return path, config, manifest, (a, b)


import pytest


@pytest.fixture
def study_fixture():
    return _build_study_fixture
