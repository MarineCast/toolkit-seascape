"""Execution helpers for the bounded San Juan data-explorer notebook."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box
import yaml


NATURAL_EARTH_LAND_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
)


def prepare_workspace(
    toolkit_root: Path,
    workspace_root: Path,
    bbox: tuple[float, float, float, float],
    resolutions: tuple[int, ...],
    *,
    force_downloads: bool,
) -> Path:
    """Copy and specialize config so every generated artifact stays in the notebook workspace."""

    workspace_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(toolkit_root / "config", workspace_root / "config", dirs_exist_ok=True)
    bbox_config = dict(zip(("min_lon", "min_lat", "max_lon", "max_lat"), bbox, strict=True))

    common_path = workspace_root / "config/common.yaml"
    common = yaml.safe_load(common_path.read_text(encoding="utf-8"))
    for area in common["areas"].values():
        area["bbox_wgs84"] = dict(bbox_config)
    common_path.write_text(yaml.safe_dump(common, sort_keys=False), encoding="utf-8")

    domain_path = workspace_root / "config/data/environment_seascape.yaml"
    domain = yaml.safe_load(domain_path.read_text(encoding="utf-8"))
    domain["water_geometry"]["build"]["area"] = "model_area"
    domain["h3_geometry"].update(
        {"area": "model_area", "resolutions": list(resolutions), "max_workers": 4}
    )
    domain["water_network"].update(
        {
            "area": "model_area",
            "model_area": "model_area",
            "resolutions": list(resolutions),
            "max_workers": 4,
        }
    )
    domain["bathymetry"]["area"] = "model_area"
    domain["bathymetry"]["source"]["overwrite"] = force_downloads
    domain_path.write_text(yaml.safe_dump(domain, sort_keys=False), encoding="utf-8")
    os.environ["SEASCAPE_WORKSPACE"] = str(workspace_root)
    return Path("config/data/project.yaml")


def _environment(toolkit_root: Path, workspace_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["SEASCAPE_WORKSPACE"] = str(workspace_root)
    source_root = str(toolkit_root / "src")
    current = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source_root if not current else os.pathsep.join((source_root, current))
    return environment


def run_command(
    command: list[str],
    *,
    toolkit_root: Path,
    workspace_root: Path,
    enabled: bool,
) -> None:
    print("$", shlex.join(command))
    if not enabled:
        print("Skipped by the notebook configuration switch.")
        return
    subprocess.run(
        command,
        cwd=workspace_root,
        env=_environment(toolkit_root, workspace_root),
        check=True,
        text=True,
    )


def seascape_command(workspace_root: Path, *arguments: str | Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "seascape",
        "--workspace",
        str(workspace_root),
        *(str(argument) for argument in arguments),
    ]


def module_command(module: str, *arguments: str | Path) -> list[str]:
    return [sys.executable, "-m", module, *(str(argument) for argument in arguments)]


def _download_file(url: str, destination: Path, *, overwrite: bool) -> Path:
    if destination.is_file() and not overwrite:
        print(f"Using cached download: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=180) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Downloaded: {destination}")
    return destination


def build_exploratory_water_mask(
    workspace_root: Path,
    bbox: tuple[float, float, float, float],
    *,
    force_downloads: bool,
) -> Path:
    """Subtract Natural Earth land from the AOI for a non-canonical explorer mask."""

    raw_root = workspace_root / "data/raw/natural_earth"
    archive_path = _download_file(
        NATURAL_EARTH_LAND_URL,
        raw_root / "ne_10m_land.zip",
        overwrite=force_downloads,
    )
    extract_root = raw_root / "ne_10m_land"
    if force_downloads and extract_root.exists():
        shutil.rmtree(extract_root)
    if not extract_root.exists():
        extract_root.mkdir(parents=True)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                target = (extract_root / member.filename).resolve()
                if not target.is_relative_to(extract_root.resolve()):
                    raise ValueError(f"Unsafe archive member: {member.filename}")
            archive.extractall(extract_root)
    shapefile = next(extract_root.rglob("ne_10m_land.shp"))
    area = box(*bbox)
    land = gpd.read_file(shapefile, bbox=bbox).to_crs(4326)
    water = area if land.empty else area.difference(land.geometry.union_all())
    if water.is_empty:
        raise ValueError("Exploratory water mask is empty after subtracting land.")
    output = (
        workspace_root
        / "data/processed/domain/environmental_layer/seascape/spatial_support"
        / "water_geometry/TERRITORIAL_WATER_POLYGON.parquet"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        {"AREA": ["SAN_JUAN_EXPLORATORY_NATURAL_EARTH_10M"]},
        geometry=[water],
        crs=4326,
    ).to_parquet(output, index=False)
    print(f"Exploratory water mask: {output}")
    return output


def run_downloads(
    toolkit_root: Path,
    workspace_root: Path,
    project_config: Path,
    bbox: tuple[float, float, float, float],
    *,
    enabled: bool,
    force_downloads: bool,
) -> Path:
    mask = (
        build_exploratory_water_mask(
            workspace_root, bbox, force_downloads=force_downloads
        )
        if enabled
        else workspace_root
        / "data/processed/domain/environmental_layer/seascape/spatial_support"
        / "water_geometry/TERRITORIAL_WATER_POLYGON.parquet"
    )
    run_command(
        seascape_command(
            workspace_root, "download", "bathymetry", "--config", project_config
        ),
        toolkit_root=toolkit_root,
        workspace_root=workspace_root,
        enabled=enabled,
    )
    return mask


def run_processing(
    toolkit_root: Path,
    workspace_root: Path,
    project_config: Path,
    resolutions: tuple[int, ...],
    *,
    enabled: bool,
) -> None:
    resolution_args = tuple(
        item for resolution in resolutions for item in ("--resolution", str(resolution))
    )
    commands = (
        module_command(
            "seascape.spatial_support.h3_geometry.build",
            "--config",
            project_config,
            *resolution_args,
        ),
        module_command(
            "seascape.spatial_support.water_network.build",
            "--config",
            project_config,
            *resolution_args,
            "--overwrite",
        ),
        module_command(
            "seascape.seafloor_physiography.bathymetry",
            "--config",
            project_config,
            "--skip-download",
            "--skip-map",
        ),
    )
    for command in commands:
        run_command(
            command,
            toolkit_root=toolkit_root,
            workspace_root=workspace_root,
            enabled=enabled,
        )


def run_postprocessing(
    toolkit_root: Path,
    workspace_root: Path,
    project_config: Path,
    output_html: Path,
    *,
    enabled: bool,
) -> None:
    run_command(
        seascape_command(
            workspace_root,
            "inspect",
            "bathymetry",
            "--config",
            project_config,
            "--output",
            output_html,
        ),
        toolkit_root=toolkit_root,
        workspace_root=workspace_root,
        enabled=enabled,
    )


def validate_outputs(workspace_root: Path, output_html: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    bathymetry_root = (
        workspace_root
        / "data/processed/domain/environmental_layer/seascape/seafloor_physiography/bathymetry"
    )
    products = {
        "exploratory water mask": workspace_root
        / "data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry/TERRITORIAL_WATER_POLYGON.parquet",
        "H3 r6 support": workspace_root
        / "data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_MODEL_AREA_SUPPORT_RES_6.parquet",
        "H3 r8 support": workspace_root
        / "data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry/H3_MODEL_AREA_SUPPORT_RES_8.parquet",
        "bathymetry r6": bathymetry_root / "BATHYMETRY_RES_6.parquet",
        "bathymetry r8": bathymetry_root / "BATHYMETRY.parquet",
        "interactive HTML": output_html,
    }
    artifacts = pd.DataFrame(
        [(name, path, path.exists()) for name, path in products.items()],
        columns=["artifact", "path", "exists"],
    )
    if not artifacts["exists"].all():
        missing = artifacts.loc[~artifacts["exists"], "artifact"].tolist()
        raise FileNotFoundError(f"Required notebook outputs are missing: {missing}")

    quality = []
    for resolution in (6, 8):
        frame = pd.read_parquet(products[f"bathymetry r{resolution}"])
        numeric = [
            column
            for column in frame.columns
            if column != "H3_INDEX" and pd.api.types.is_numeric_dtype(frame[column])
        ]
        if frame.empty or frame["H3_INDEX"].isna().any() or not frame["H3_INDEX"].is_unique:
            raise ValueError(f"Invalid H3 identity contract at resolution {resolution}.")
        if np.isinf(frame[numeric].to_numpy(dtype="float64")).any():
            raise ValueError(f"Infinite bathymetry value at resolution {resolution}.")
        quality.append(
            {
                "H3 resolution": resolution,
                "rows": len(frame),
                "numeric variables": len(numeric),
                "cells with mean depth": int(frame["BATHYMETRY"].notna().sum()),
                "minimum mean depth m": frame["BATHYMETRY"].min(),
                "maximum mean depth m": frame["BATHYMETRY"].max(),
            }
        )
    return artifacts, pd.DataFrame(quality)
