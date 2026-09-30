"""Import the installed wheel independently of a source checkout or OrcaCast."""

from __future__ import annotations

import argparse
import importlib
import importlib.abc
import importlib.metadata as metadata
import json
import pkgutil
import platform
import sys
from pathlib import Path

REQUIRED_FILES = (
    "products.py",
    "core/data/catalog.py",
    "core/data/contracts.py",
    "core/data/registry.py",
    "core/data/validation.py",
    "resources/config/common.yaml",
    "resources/config/data/project.yaml",
    "resources/config/data/environment_seascape.yaml",
    "resources/config/data/presentation_settings.yaml",
)


def check_location(location: Path, prefix: Path) -> None:
    if "site-packages" not in location.parts or not location.is_relative_to(prefix):
        raise RuntimeError(
            f"Expected this interpreter's installed wheel, imported: {location}"
        )


def check_resources(root: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing packaged resources: {missing}")
    for name in ("feature_catalog.yaml", "model_feature_policy.yaml"):
        assert not (root / "resources/config" / name).exists()


class BlockApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "orcacast" or fullname.startswith("orcacast."):
            raise ImportError(f"Unexpected application dependency: {fullname}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    sys.meta_path.insert(0, BlockApplication())
    import seascape

    location = Path(seascape.__file__).resolve()
    check_location(location, Path(sys.prefix).resolve())
    assert seascape.__version__ == metadata.version("toolkit-seascape")
    check_resources(location.parent)
    from seascape.core.data.registry import DATASETS

    assert len(tuple(DATASETS)) == 105
    dataset_ids = {dataset.dataset_id for dataset in DATASETS}
    assert {
        "environment.seascape.gebco_tid_r6",
        "environment.seascape.gebco_tid_r8",
        "environment.seascape.outlet_relationships_r8",
        "environment.seascape.nearshore_deep_components",
        "environment.seascape.passage_cross_sections",
        "environment.seascape.mapped_sills",
        "environment.seascape.gateway_relationships_r8",
        "environment.seascape.coast_complexity_r8",
        "environment.seascape.mapped_habitat_mosaic_r8",
    }.issubset(dataset_ids)
    count = 1
    for module in pkgutil.walk_packages(seascape.__path__, seascape.__name__ + "."):
        importlib.import_module(module.name)
        count += 1
    print(f"Imported {count} installed modules with OrcaCast blocked: {location}")
    if args.snapshot:
        import pyproj
        import rasterio
        import shapely

        args.snapshot.write_text(
            json.dumps(
                {
                    "python": sys.version,
                    "interpreter": sys.executable,
                    "prefix": sys.prefix,
                    "package": str(location),
                    "modules": count,
                    "system": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                    "gdal": rasterio.__gdal_version__,
                    "proj": pyproj.proj_version_str,
                    "geos": shapely.geos_version_string,
                    "distributions": {
                        dist.metadata["Name"]: dist.version
                        for dist in metadata.distributions()
                    },
                },
                indent=2,
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
