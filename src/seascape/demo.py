"""Portable synthetic bathymetry acceptance; every artifact belongs to the demo.

This calls the production bathymetry facade. It does not acquire sources, construct
regional spatial support, audit a whole release, or publish canonical products.
"""

from __future__ import annotations

import fcntl
import json
import os
import platform
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from typing import TypedDict

import h3
import numpy as np
import pandas as pd
import rasterio
import yaml
from rasterio.transform import from_bounds

from seascape.core.artifacts.checksums import checksum_path
from seascape.core.artifacts.contracts import atomic_write_json, atomic_write_text
from seascape.seafloor_physiography.bathymetry import run_pipeline
from seascape.utils.artifacts import atomic_write_parquet, validate_manifest

_RESOLUTION = 8
_BOUNDS = (-123.20, 48.40, -123.10, 48.50)
_OWNER = "toolkit-seascape synthetic demo v1\n"
_FILES = (
    "config/demo.yaml",
    "input/synthetic_bathymetry.tif",
    "input/H3_SUPPORT_RES_8.parquet",
    "input/H3_WATER_NEIGHBORHOODS_RES_8.parquet",
    "output/BATHYMETRY.parquet",
    "output/bathymetry_manifest.json",
    "report.json",
    "figures/input.png",
    "figures/output.png",
)
_LIMIT = "Synthetic software acceptance only; not a regional scientific validation or canonical release."


class DemoWorkspaceError(ValueError):
    """A demo destination cannot safely be used without risking existing files."""


@dataclass(frozen=True)
class DemoResult:
    """Inspectable paths, executed validation results, and execution metadata."""

    workspace: Path
    parquet_path: Path
    manifest_path: Path
    report_path: Path
    figure_paths: tuple[Path, Path]
    checks: dict[str, bool]
    metadata: dict[str, object]


class _Fixture(TypedDict):
    cells: list[str]
    controls: dict[str, str]
    flat_count: int


@contextmanager
def _environment(root: Path) -> Iterator[None]:
    updates = {
        "SEASCAPE_WORKSPACE": str(root),
        "SEASCAPE_CANDIDATE_ROOT": str(root),
        "MPLCONFIGDIR": str(root / "cache/matplotlib"),
    }
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _check_destination(root: Path, overwrite: bool) -> None:
    # Check lexical ancestors before resolving: resolve() alone would hide symlinks.
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise DemoWorkspaceError(f"Symlink in demo destination: {root}")
    if not root.exists():
        return
    if not overwrite:
        raise DemoWorkspaceError(
            f"Demo already exists: {root} (explicit --overwrite required)"
        )
    if not root.is_dir():
        raise DemoWorkspaceError(f"Demo destination is not a directory: {root}")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise DemoWorkspaceError(f"Symlink inside demo destination: {root}")
    marker = root / ".owner"
    if not marker.is_file() or marker.read_text() != _OWNER:
        raise DemoWorkspaceError(f"Demo ownership marker missing or invalid: {marker}")
    for name in (*_FILES, ".owner", ".demo.lock", "output/.publication.lock"):
        path = root / name
        if path.exists() and not path.is_file():
            raise DemoWorkspaceError(f"Expected a demo file: {path}")
        if any(
            parent.exists() and not parent.is_dir()
            for parent in path.parents
            if parent.is_relative_to(root)
        ):
            raise DemoWorkspaceError(f"Expected a demo directory for: {path}")
    # Existing publisher recovery journals can name arbitrary destinations. Do not
    # consume or remove unknown transactions, even in a directory named 'demo'.
    for name in ("output/.transactions", "output/.staging"):
        path = root / name
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise DemoWorkspaceError(f"Unreviewed publication state: {path}")


def _prepare_fixture(root: Path) -> _Fixture:
    """Reuse the validation notebook's 48x48 negative-elevation fixture recipe.

    Controls add constant depth, exact sea level (excluded by the production
    marine mask), nodata-only support, and one cell outside raster coverage.
    Neighborhoods are synthetic H3 hops, not a real coastal water network.
    """
    for name in ("input", "output", "config", "figures"):
        (root / name).mkdir(parents=True, exist_ok=True)
    rows, columns = np.indices((48, 48), dtype="float32")
    elevation = -(5.0 + 145.0 * columns / 47 + 80.0 * rows / 47)
    elevation[:12, :12] = -5.0
    elevation[:12, -12:] = 0.0
    elevation[-12:, -12:] = -9999.0
    transform = from_bounds(*_BOUNDS, 48, 48)
    with rasterio.open(
        root / _FILES[1],
        "w",
        driver="GTiff",
        height=48,
        width=48,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as target:
        target.write(elevation.astype("float32"), 1)
    longitudes = transform.c + (columns + 0.5) * transform.a
    latitudes = transform.f + (rows + 0.5) * transform.e
    pixel_cells = np.array(
        [
            h3.latlng_to_cell(float(lat), float(lon), _RESOLUTION)
            for lat, lon in zip(latitudes.ravel(), longitudes.ravel(), strict=True)
        ]
    ).reshape(48, 48)
    outside_cell = h3.latlng_to_cell(49.0, -124.0, _RESOLUTION)
    cells = sorted({*pixel_cells.ravel(), outside_cell})
    atomic_write_parquet(pd.DataFrame({"H3_INDEX": cells}), root / _FILES[2])
    neighborhoods = []
    edge_length = float(h3.average_hexagon_edge_length(_RESOLUTION, unit="m"))
    for source in cells:
        for target in cells:
            hops = int(h3.grid_distance(source, target))
            if hops <= 2:
                neighborhoods.append(
                    {
                        "SOURCE_H3_INDEX": source,
                        "TARGET_H3_INDEX": target,
                        "MINIMUM_HOP_COUNT": hops,
                        "NETWORK_DISTANCE_M": hops * edge_length,
                    }
                )
    atomic_write_parquet(pd.DataFrame(neighborhoods), root / _FILES[3])
    # Read defaults from the wheel's packaged resource, never from a checkout.
    defaults = yaml.safe_load(
        files("seascape")
        .joinpath("resources/config/data/environment_seascape.yaml")
        .read_text(encoding="utf-8")
    )
    bathymetry = defaults["bathymetry"]
    bathymetry.pop("area", None)
    bathymetry["bbox_wgs84"] = dict(
        zip(("min_lon", "min_lat", "max_lon", "max_lat"), _BOUNDS, strict=True)
    )
    bathymetry["source"].update(
        {
            "provider": "SYNTHETIC",
            "release": "seascape-demo-v1",
            "grid_name": "synthetic_48x48",
            "data_source_name": "synthetic_fixture",
            "api_base_url": "https://synthetic.invalid/no-acquisition",
            "native_resolution_arc_seconds": 7.5,
            "raw_dir": str(root / "input"),
            "raw_filename": "synthetic_bathymetry.tif",
        }
    )
    bathymetry["processing"].update(
        {
            "h3_resolution": _RESOLUTION,
            "h3_grid_path_template": str(root / "input/H3_SUPPORT_RES_{res}.parquet"),
            # Unused by this facade; keep its configured path confined too.
            "water_polygon_path": str(root / "input/UNUSED_WATER_POLYGON.parquet"),
            "processed_path": str(root / _FILES[4]),
            "additional_exports": [],
            "bathymetry_sign": "positive_down",
        }
    )
    configuration = {
        "base_directory": str(root),
        "bathymetry": bathymetry,
        "water_network": {
            "output_dir": str(root / "input"),
            "neighborhood_filename_template": "H3_WATER_NEIGHBORHOODS_RES_{res}.parquet",
        },
    }
    atomic_write_text(
        root / _FILES[0], yaml.safe_dump(configuration, sort_keys=False), overwrite=True
    )
    controls = {
        "flat": str(pixel_cells[6, 6]),
        "sea_level": str(pixel_cells[6, 42]),
        "nodata": str(pixel_cells[42, 42]),
        "outside": outside_cell,
    }
    # Prove selected control cells lie entirely within their constant patches.
    for name, expected in (("flat", -5.0), ("sea_level", 0.0), ("nodata", -9999.0)):
        samples = elevation[pixel_cells == controls[name]]
        if not len(samples) or not np.all(samples == expected):
            raise AssertionError(
                f"Synthetic control cell is not wholly inside {name} patch"
            )
    return {
        "cells": cells,
        "controls": controls,
        "flat_count": int(np.count_nonzero(pixel_cells == controls["flat"])),
    }


def _validate(root: Path, fixture: _Fixture) -> dict[str, bool]:
    output = pd.read_parquet(root / _FILES[4])
    manifest = json.loads((root / _FILES[5]).read_text())
    validate_manifest(manifest, project_root=root, verify_artifacts=True)
    required = {
        "H3_INDEX",
        "BATHYMETRY",
        "BATHYMETRY_PIXEL_COUNT",
        "BATHYMETRY_STD",
        "BATHYMETRY_RANGE",
    }
    if (
        output.empty
        or not required.issubset(output)
        or output["H3_INDEX"].isna().any()
        or not output["H3_INDEX"].is_unique
    ):
        raise AssertionError(
            "Demo requires nonempty output with unique nonnull H3 keys and depth schema"
        )
    indexed = output.set_index("H3_INDEX")
    controls = fixture["controls"]
    flat = indexed.loc[controls["flat"]]
    depths = output["BATHYMETRY"].dropna()
    fractions = output.filter(regex=r"^BATHYMETRY_FRAC_")
    valid_fractions = fractions.loc[output["BATHYMETRY"].notna()]
    checks = {
        "nonempty_valid_depth": not depths.empty,
        "marine_pixel_count": output["BATHYMETRY_PIXEL_COUNT"].sum() == 2016,
        "finite_or_null_numeric_values": not np.isinf(
            output.select_dtypes(include="number").to_numpy(dtype=float)
        ).any(),
        "exact_support_and_resolution": sorted(output["H3_INDEX"]) == fixture["cells"]
        and output["H3_INDEX"].map(h3.get_resolution).eq(_RESOLUTION).all(),
        "known_constant_depth_m": abs(float(flat["BATHYMETRY"]) - 5.0) <= 1e-6
        and flat["BATHYMETRY_PIXEL_COUNT"] == fixture["flat_count"],
        "observed_zero_statistics": flat["BATHYMETRY_STD"] == 0.0
        and flat["BATHYMETRY_RANGE"] == 0.0
        and flat["BATHYMETRY_FRAC_10_30_M"] == 0.0,
        "nodata_and_unavailable_remain_null": all(
            indexed.loc[controls[name], ["BATHYMETRY", "BATHYMETRY_PIXEL_COUNT"]]
            .isna()
            .all()
            for name in ("nodata", "outside")
        ),
        "sea_level_excluded_by_existing_marine_mask": indexed.loc[
            controls["sea_level"], ["BATHYMETRY", "BATHYMETRY_PIXEL_COUNT"]
        ]
        .isna()
        .all(),
        "positive_down_meters_and_bounds": not depths.empty
        and np.isfinite(depths).all()
        and depths.between(5.0, 230.1).all()
        and manifest["metadata"]["bathymetry_sign"] == "positive_down",
        "valid_depth_band_partition": not valid_fractions.empty
        and len(fractions.columns) == 6
        and np.isfinite(valid_fractions).all().all()
        and np.allclose(valid_fractions.sum(axis=1), 1.0, atol=1e-12, rtol=0),
        "synthetic_provenance": manifest["metadata"].get("synthetic") is True
        and all(
            source["name"].startswith("SYNTHETIC ")
            and "synthetic" in source["license"].lower()
            for source in manifest["sources"]
        )
        and "GEBCO" not in json.dumps(manifest),
        "family_and_checksums": manifest["dataset_family"]
        == "environment.seascape.bathymetry"
        and bool(manifest["sources"])
        and manifest["sources"][0]["checksum"] == checksum_path(root / _FILES[1])
        and all(
            (root / item["path"]).resolve().is_relative_to(root)
            and item["checksum"] == checksum_path(root / item["path"])
            for item in manifest["upstream_artifacts"]
        ),
    }
    with rasterio.open(root / _FILES[1]) as raster:
        checks["input_crs_sign_nodata"] = (
            raster.crs.to_epsg() == 4326
            and raster.nodata == -9999.0
            and raster.count == 1
            and raster.shape == (48, 48)
            and int(np.ma.count_masked(raster.read(1, masked=True))) == 144
        )
    return {name: bool(value) for name, value in checks.items()}


def _figures(root: Path) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.collections import PolyCollection
    from matplotlib.figure import Figure

    with rasterio.open(root / _FILES[1]) as source:
        values = source.read(1, masked=True)
    figure = Figure(figsize=(7, 5), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    image = axis.imshow(
        values, extent=(_BOUNDS[0], _BOUNDS[2], _BOUNDS[1], _BOUNDS[3]), cmap="Blues_r"
    )
    image.cmap = image.cmap.with_extremes(bad="lightgrey")
    axis.set(
        title="SYNTHETIC input: negative elevation (m)",
        xlabel="longitude",
        ylabel="latitude",
    )
    figure.colorbar(image, ax=axis, label="Elevation (m); grey = nodata")
    figure.savefig(root / _FILES[7])
    output = pd.read_parquet(root / _FILES[4])
    # Exclude the deliberately out-of-coverage control from the map extent.
    output = output[output["H3_INDEX"] != h3.latlng_to_cell(49.0, -124.0, _RESOLUTION)]
    polygons = [
        [(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]
        for cell in output["H3_INDEX"]
    ]
    figure = Figure(figsize=(7, 5), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    collection = PolyCollection(
        polygons,
        array=np.ma.masked_invalid(output["BATHYMETRY"].to_numpy(dtype=float)),
        cmap="Blues",
        edgecolors="grey",
        linewidths=0.3,
    )
    collection.cmap = collection.cmap.with_extremes(bad="lightgrey")
    axis.add_collection(collection)
    axis.autoscale_view()
    axis.set(
        title="SYNTHETIC H3 r8: positive-down depth (m)",
        xlabel="longitude",
        ylabel="latitude",
    )
    figure.colorbar(collection, ax=axis, label="Depth (m); grey = unavailable")
    figure.savefig(root / _FILES[8])


def run_demo(workspace: str | Path, *, overwrite: bool = False) -> DemoResult:
    """Run offline acceptance in ``<workspace>/.seascape/demo`` and retain results.

    Refuses existing output by default. Overwrite requires the exact ownership
    marker, rejects symlinks and unreviewed publication state, and replaces only
    known demo files. Unrelated files are preserved. Expected failures raise;
    once computation starts, report.json records RUNNING, FAIL, or PASS.
    Process environment overrides are restored even on failure. Like the existing
    family APIs, environment selection is process-global: do not run concurrently
    with other workspace operations in the same Python process.
    """
    root = Path(workspace).expanduser().absolute() / ".seascape/demo"
    _check_destination(root, overwrite)
    if not root.exists():
        try:
            root.mkdir(parents=True)
        except FileExistsError as exc:
            raise DemoWorkspaceError(
                f"Demo destination appeared during creation: {root}"
            ) from exc
    root = root.resolve()
    with _environment(root):
        with (root / ".demo.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DemoWorkspaceError(f"Demo is busy: {root}") from exc
            atomic_write_text(root / ".owner", _OWNER, overwrite=True)
            started = time.perf_counter()
            metadata = {"synthetic": True, "scope": _LIMIT}
            checks = {}
            report = root / "report.json"
            atomic_write_json(
                report, {"status": "RUNNING", "metadata": metadata}, overwrite=True
            )
            try:
                metadata.update(
                    {
                        "synthetic": True,
                        "scope": _LIMIT,
                        "units": "m",
                        "bathymetry_sign": "positive_down",
                        "vertical_datum": "synthetic; no real-world datum",
                        "h3_resolution": _RESOLUTION,
                        "bbox_wgs84": _BOUNDS,
                        "neighborhood": "synthetic H3 minimum hops <= 2; not a real water network",
                        "python": sys.version,
                        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
                        "package_version": version("toolkit-seascape"),
                        "gdal": rasterio.__gdal_version__,
                    }
                )
                fixture = _prepare_fixture(root)
                raw, processed, map_path = run_pipeline(
                    config_path=root / _FILES[0],
                    skip_download=True,
                    skip_map=True,
                    overwrite=True,
                )
                checks = _validate(root, fixture)
                checks["production_paths"] = (
                    raw == root / _FILES[1]
                    and processed == root / _FILES[4]
                    and map_path is None
                )
                failed = [name for name, passed in checks.items() if not passed]
                if failed:
                    raise AssertionError("Demo validation failed: " + ", ".join(failed))
                _figures(root)
                metadata["elapsed_seconds"] = time.perf_counter() - started
                atomic_write_json(
                    report,
                    {
                        "status": "PASS",
                        "checks": checks,
                        "metadata": metadata,
                        "paths": list(_FILES),
                        "controls": fixture["controls"],
                        "row_count": len(fixture["cells"]),
                    },
                    overwrite=True,
                )
            except Exception as exc:
                atomic_write_json(
                    report,
                    {
                        "status": "FAIL",
                        "checks": checks,
                        "metadata": metadata,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    overwrite=True,
                )
                raise
    return DemoResult(
        root,
        root / _FILES[4],
        root / _FILES[5],
        report,
        (root / _FILES[7], root / _FILES[8]),
        checks,
        metadata,
    )
