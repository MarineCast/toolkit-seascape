"""Collect NOAA and BC ShoreZone snapshots, or validate local inputs offline."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from seascape.core.config.data import load_data_config
from seascape.core.config.paths import project_root, resolve_config_path
from seascape.utils.config import (
    require_mapping,
    resolve_project_path,
)

DEFAULT_CONFIG_PATH = "config/data/environment_seascape.yaml"


def load_source_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load the physical-shoreline source definitions."""

    raw = load_data_config(resolve_config_path(config_path), domains="SEASCAPE_LAYER")
    section = require_mapping(
        raw.get("shoreline_characterization"),
        "shoreline_characterization",
    )
    sources = require_mapping(section.get("sources"), "shoreline_characterization.sources")
    configured_base = Path(str(raw.get("base_directory", "."))).expanduser()
    base_dir = (
        configured_base if configured_base.is_absolute() else project_root() / configured_base
    ).resolve()
    return {"base_dir": base_dir, "sources": sources}


def resolve_shoreline_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    """Return existing local source paths and fail with all missing snapshots."""

    config = load_source_config(config_path)
    output: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    missing: list[Path] = []
    for name, raw_source in sorted(config["sources"].items()):
        source = require_mapping(raw_source, f"shoreline_characterization.sources.{name}")
        if "path" not in source:
            raise ValueError(f"Shoreline source {name!r} is missing path.")
        path = resolve_project_path(source["path"], config["base_dir"])
        if not path.exists():
            missing.append(path)
        output[name] = (path, source)
    if missing:
        raise FileNotFoundError(
            "Missing shoreline source snapshots: " + ", ".join(str(path) for path in missing)
        )
    return output


def collect_shoreline_sources(
    config_path: str | Path = DEFAULT_CONFIG_PATH, *, overwrite: bool = False
) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    """Collect both configured inventories, then install validated source components.

    Existing differing datasets require explicit overwrite. The collection manifest
    retains query identity, retrieval time and checksums in the acquisition cache.
    """
    import shutil
    import tempfile

    import geopandas as gpd

    from seascape.core.artifacts.checksums import checksum_path
    from seascape.utils.habitat_acquisition import (
        download_habitat_sources,
        load_habitat_download_config,
    )

    download_habitat_sources("shoreline_characterization", config_path, overwrite=overwrite)
    acquired = load_habitat_download_config("shoreline_characterization", config_path)
    config = load_source_config(config_path)
    installs = []
    for name, source in config["sources"].items():
        destination = resolve_project_path(source["path"], config["base_dir"])
        spec = acquired.sources[name]
        if spec.get("extract"):
            matches = list((acquired.raw_dir / spec["extract_directory"]).rglob(destination.name))
            if len(matches) != 1:
                raise ValueError(f"Expected one archive dataset named {destination.name}")
            origin = matches[0]
        else:
            origin = acquired.raw_dir / spec["raw_filename"]
        frame = gpd.read_file(origin)
        if (
            frame.empty
            or frame.crs is None
            or not frame.geometry.geom_type.isin(["LineString", "MultiLineString"]).all()
        ):
            raise ValueError(f"Invalid shoreline geometry: {origin}")
        components = (
            list(origin.parent.glob(origin.stem + ".*")) if origin.suffix == ".shp" else [origin]
        )
        if origin.suffix == ".shp" and not {".shp", ".shx", ".dbf", ".prj"}.issubset(
            {p.suffix.lower() for p in components}
        ):
            raise ValueError(f"Incomplete shoreline shapefile: {origin}")
        for component in components:
            target = destination.parent / component.name if origin.suffix == ".shp" else destination
            if target.exists() and not overwrite:
                if checksum_path(target) != checksum_path(component):
                    raise ValueError(f"Existing shoreline differs: {target}; use --overwrite")
                continue
            installs.append((component, target))
    # Validation above completes before any consumed source is replaced.
    for origin, target in installs:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
            temporary = Path(temp.name)
        try:
            shutil.copyfile(origin, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return resolve_shoreline_sources(config_path)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    result = (
        resolve_shoreline_sources(args.config)
        if args.validate_only
        else collect_shoreline_sources(args.config, overwrite=args.overwrite)
    )
    for name, (path, _source) in result.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
