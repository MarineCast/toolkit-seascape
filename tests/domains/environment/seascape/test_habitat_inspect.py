from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from seascape.core.geo.h3 import grid_disk, latlng_to_cell
from seascape.utils.habitat_configuration import (
    HabitatSurfaceConfig,
)
from seascape.utils.habitat_inspect import (
    inspect_habitat_surface,
)


def _config(tmp_path: Path) -> HabitatSurfaceConfig:
    return HabitatSurfaceConfig(
        section_name="test_habitat",
        prefix="TEST",
        bbox={
            "min_lon": -124.0,
            "min_lat": 48.0,
            "max_lon": -123.0,
            "max_lat": 49.0,
        },
        native_resolution=8,
        model_resolution=6,
        equal_area_crs="EPSG:6933",
        reference_year=2026,
        marine_buffer_m=5_000.0,
        processed_dir=tmp_path,
        inventory_path=tmp_path / "inventory.parquet",
        feature_filename_template="FEATURE_RES_{res}.parquet",
        confidence_filename_template="CONFIDENCE_RES_{res}.parquet",
        manifest_path=tmp_path / "manifest.json",
        clipped_geometry_path=tmp_path / "geometry.parquet",
        parent_child_path=tmp_path / "crosswalk.parquet",
    )


def test_shared_inspector_embeds_one_geometry_payload_for_all_metrics(tmp_path):
    config = _config(tmp_path)
    first = latlng_to_cell(48.5, -123.5, 8)
    second = next(cell for cell in sorted(grid_disk(first, 1)) if cell != first)
    cells = [first, second]
    pd.DataFrame(
        {
            "H3_INDEX": cells,
            "H3_RESOLUTION": [8, 8],
            "VALUE": [1.0, 2.0],
            "ALL_NULL": [np.nan, np.nan],
        }
    ).to_parquet(config.feature_path(8), index=False)
    pd.DataFrame(
        {
            "H3_INDEX": cells,
            "H3_RESOLUTION": [8, 8],
            "TEST_CONFIDENCE": [3, 1],
            "TEST_UNMAPPED_AREA": [False, True],
            "TEST_SOURCE_DATASETS": ["official", "osm"],
        }
    ).to_parquet(config.confidence_path(8), index=False)

    output = inspect_habitat_surface(
        config,
        metrics=[("VALUE", "Mapped value"), ("ALL_NULL", "All-null value")],
        map_subdirectory="unused",
        map_stem="test",
        resolution=8,
        output_path=tmp_path / "map.html",
    )
    html = output.read_text(encoding="utf-8")

    assert html.count("FeatureCollection") == 1
    assert html.count("L.geoJson(null") == 1
    assert html.count('"H3_INDEX"') == len(cells)
    assert "Mapped value" in html
    assert "All-null value" not in html
    assert "Evidence confidence / provenance" in html
    assert "TEST_SOURCE_DATASETS" in html
    assert "habitat-metric-select" in html
    assert "sharedLayer.setStyle(styleFeature)" in html
    assert html.find("const metricConfigs") > html.find("L.geoJson(null")
