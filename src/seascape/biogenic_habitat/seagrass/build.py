"""Build generic seagrass habitat from the Sentinel-2 global 10 m map."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from seascape.utils.config import load_processing_config
from seascape.utils.habitat_acquisition import (
    load_habitat_download_config,
)
from seascape.utils.habitat_configuration import (
    load_habitat_surface_config,
)
from seascape.utils.habitat_inventory import (
    NORMALIZED_INVENTORY_COLUMNS,
)
from seascape.utils.habitat_publication import build_habitat_products
from seascape.utils.habitat_raster import (
    discover_geotiffs,
    positive_raster_polygons,
)

from .download import DEFAULT_CONFIG_PATH, SECTION_NAME

LOGGER = logging.getLogger(__name__)
PREFIX = "SEAGRASS"


def load_seagrass_inventory(config_path: str | Path = DEFAULT_CONFIG_PATH):
    """Polygonize positive Sentinel-2 seagrass pixels inside the model area."""

    import geopandas as gpd

    download = load_habitat_download_config(SECTION_NAME, config_path)
    processing = load_processing_config(config_path, SECTION_NAME)
    source = download.sources["global_sentinel2_seagrass_2023_2024"]
    archive_path = download.raw_dir / str(source["raw_filename"])
    raster_paths = discover_geotiffs(archive_path)
    polygons, crs = positive_raster_polygons(
        raster_paths,
        bbox=download.bbox,
        positive_values=processing.get("positive_values", [1]),
    )
    frame = gpd.GeoDataFrame(
        {
            "RECORD_ID": [
                f"GLOBAL_SENTINEL2_SEAGRASS_2023_2024:{index}" for index in range(len(polygons))
            ],
            "HABITAT_TYPE": "seagrass",
            "SOURCE_DATASET": "GLOBAL_SENTINEL2_SEAGRASS_2023_2024",
            "SOURCE_FEATURE_ID": pd.Series(range(len(polygons)), dtype="string"),
            "EVIDENCE_CLASS": "modeled_occurrence",
            "OBSERVED_VS_MODELED": "modeled",
            "OBSERVATION_STATUS": "present",
            "OBSERVATION_YEAR": 2024,
            "COMPOSITION_ELIGIBLE": True,
            "SUPPORTS_AREA": True,
            "COVERAGE_WEIGHT": 1.0,
            "SOURCE_PERSISTENCE_RATIO": np.nan,
            "CONFIDENCE_CLASS": 1,
            "SURVEY_METHOD": "Sentinel-2 deep-learning shallow-water classification",
            "SPATIAL_PRECISION_CLASS": "10_m_raster",
            "TEMPORAL_PRECISION_CLASS": "2023_2024_composite",
        },
        geometry=polygons,
        crs=crs,
    ).to_crs("EPSG:4326")
    if frame.empty:
        raise ValueError("Sentinel-2 source produced no seagrass polygons in the model area.")
    return frame.loc[:, NORMALIZED_INVENTORY_COLUMNS]


def build_seagrass_habitat(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    config = load_habitat_surface_config(SECTION_NAME, PREFIX, config_path)
    download = load_habitat_download_config(SECTION_NAME, config_path)
    source = download.sources["global_sentinel2_seagrass_2023_2024"]
    archive_path = download.raw_dir / str(source["raw_filename"])
    return build_habitat_products(
        load_seagrass_inventory(config_path),
        config,
        config_path,
        manifest_metadata={
            "source_detail": {
                "dataset": "Peng et al. global Sentinel-2 seagrass extent",
                "period": "2023-2024",
                "doi": "10.5281/zenodo.18612240",
                "license": source.get("license"),
                "archive_path": str(archive_path),
                "archive_bytes": archive_path.stat().st_size,
                "archive_expected_md5": source.get("md5"),
                "positive_values": load_processing_config(config_path, SECTION_NAME).get(
                    "positive_values", [1]
                ),
            },
            "evidence_contract": (
                "Binary satellite-model occurrence contributes to mapped area and distance, "
                "but never claims field-observed presence or surveyed absence."
            ),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    for path in build_seagrass_habitat(args.config):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
