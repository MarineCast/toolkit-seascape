from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from seascape.core.config.presentation import PresentationSettings
from seascape.core.geo.h3 import cell_to_children, latlng_to_cell
from seascape.coastal_configuration.shoreline_characterization import (
    inspect as shoreline_inspect,
)
from seascape.coastal_configuration.shoreline_characterization.build import (
    CLASS_TOKENS,
    SHORELINE_LENGTH_COLUMNS,
    _aggregate_lengths,
    recompute_parent_shoreline_lengths,
)


def test_shoreline_fractions_use_classified_length_and_allow_overlap() -> None:
    records = []
    for segment_id, geometry, classified, rocky, sandy in (
        ("classified", LineString([(0, 0), (10, 0)]), True, True, True),
        ("unmapped", LineString([(0, 10), (10, 10)]), False, False, False),
    ):
        record = {
            "SEGMENT_ID": segment_id,
            "IS_PHYSICALLY_CLASSIFIED": classified,
            "geometry": geometry,
        }
        for token in CLASS_TOKENS:
            record[f"IS_{token}_SHORE"] = (token == "ROCKY" and rocky) or (
                token == "SANDY" and sandy
            )
        records.append(record)
    inventory = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:3857")
    geometry = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:3857"
    )
    support = pd.DataFrame({"H3_INDEX": ["cell"]})

    result = _aggregate_lengths(
        inventory,
        geometry,
        support,
        projected_crs="EPSG:3857",
    ).iloc[0]
    assert result["SHORELINE_TOTAL_MAPPED_LENGTH_M"] == pytest.approx(20.0)
    assert result["SHORELINE_CLASSIFIED_LENGTH_M"] == pytest.approx(10.0)
    assert result["SHORELINE_CLASSIFIED_COVERAGE_FRAC"] == pytest.approx(0.5)
    assert result["ROCKY_SHORE_FRAC"] == pytest.approx(1.0)
    assert result["SANDY_SHORE_FRAC"] == pytest.approx(1.0)


def test_no_classified_shoreline_has_null_fraction_denominator() -> None:
    record = {
        "SEGMENT_ID": "unmapped",
        "IS_PHYSICALLY_CLASSIFIED": False,
        "geometry": LineString([(0, 0), (10, 0)]),
        **{f"IS_{token}_SHORE": False for token in CLASS_TOKENS},
    }
    inventory = gpd.GeoDataFrame([record], geometry="geometry", crs="EPSG:3857")
    geometry = gpd.GeoDataFrame(
        {"H3_INDEX": ["cell"]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:3857"
    )
    result = _aggregate_lengths(
        inventory,
        geometry,
        pd.DataFrame({"H3_INDEX": ["cell"]}),
        projected_crs="EPSG:3857",
    ).iloc[0]
    assert pd.isna(result["ROCKY_SHORE_FRAC"])


def test_parent_shoreline_fractions_are_recomputed_from_child_lengths() -> None:
    parent_cell = latlng_to_cell(48.4, -123.2, 6)
    child_cells = sorted(cell_to_children(parent_cell, 8))[:2]
    child_rows = []
    for cell, total, classified, rocky in (
        (child_cells[0], 10.0, 5.0, 5.0),
        (child_cells[1], 30.0, 15.0, 5.0),
    ):
        row = {
            "H3_INDEX": cell,
            **{column: 0.0 for column in SHORELINE_LENGTH_COLUMNS},
        }
        row.update(
            {
                "SHORELINE_TOTAL_MAPPED_LENGTH_M": total,
                "SHORELINE_CLASSIFIED_LENGTH_M": classified,
                "ROCKY_SHORE_LENGTH_M": rocky,
            }
        )
        child_rows.append(row)
    parent = pd.DataFrame(
        [
            {
                "H3_INDEX": parent_cell,
                **{column: 0.0 for column in SHORELINE_LENGTH_COLUMNS},
            }
        ]
    )

    result = recompute_parent_shoreline_lengths(
        pd.DataFrame(child_rows),
        parent,
        parent_resolution=6,
    ).iloc[0]

    assert result["SHORELINE_TOTAL_MAPPED_LENGTH_M"] == pytest.approx(40.0)
    assert result["SHORELINE_CLASSIFIED_LENGTH_M"] == pytest.approx(20.0)
    assert result["SHORELINE_CLASSIFIED_COVERAGE_FRAC"] == pytest.approx(0.5)
    assert result["ROCKY_SHORE_FRAC"] == pytest.approx(0.5)


def test_inspector_uses_shared_presentation_and_output_routing(monkeypatch, tmp_path) -> None:
    inventory = gpd.GeoDataFrame(
        {
            "SEGMENT_ID": ["segment"],
            "SOURCE_DATASET": ["fixture"],
            "RAW_CLASSIFICATION": ["rock"],
            **{f"IS_{token}_SHORE": [token == "ROCKY"] for token in CLASS_TOKENS},
        },
        geometry=[LineString([(-123.3, 48.4), (-123.2, 48.5)])],
        crs="EPSG:4326",
    )
    inventory_path = tmp_path / "inventory.parquet"
    inventory.to_parquet(inventory_path, index=False)
    expected = tmp_path / "maps" / shoreline_inspect.MAP_EXPORT_SUBDIRECTORY / "result.html"
    settings = PresentationSettings(
        base_export_directory=tmp_path / "maps",
        color_maps={"default": ("#000000", "#ffffff")},
        basemap_tile_layer="OpenStreetMap",
        basemap_attribution=None,
        default_zoom=5,
        static_color="#38A9AA",
    )
    monkeypatch.setattr(
        shoreline_inspect,
        "load_shoreline_config",
        lambda _path: SimpleNamespace(inventory_path=inventory_path, sources={}),
    )
    captured = {}

    def fake_settings(path):
        captured["presentation_path"] = path
        return settings

    monkeypatch.setattr(shoreline_inspect, "load_presentation_settings", fake_settings)

    result = shoreline_inspect.build_shoreline_characterization_map(
        "fixture.yaml",
        presentation_config_path="presentation.yaml",
        output_path=expected,
    )

    assert captured["presentation_path"] == "presentation.yaml"
    assert result == expected.resolve()
    assert result.exists()
