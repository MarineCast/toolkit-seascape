"""Species-neutral Seascape features in flat per-area Parquet tables."""

from importlib.metadata import version

from .products import AreaTables, list_areas, output_root, read_area, write_areas
from .study import (
    load_study_config,
    load_study_membership,
    read_study_area,
    read_study_research,
)

__version__ = version("toolkit-seascape")

__all__ = [
    "AreaTables",
    "__version__",
    "list_areas",
    "load_study_config",
    "load_study_membership",
    "read_study_area",
    "read_study_research",
    "output_root",
    "read_area",
    "write_areas",
]
