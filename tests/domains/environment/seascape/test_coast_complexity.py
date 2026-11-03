from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, Polygon, box

from seascape.coastal_configuration.coast_complexity import (
    headland_candidates,
    sample_line_positions,
    shoreline_sinuosity,
    summarize_coast,
)


def test_source_line_sampling_and_sinuosity_match_direct_geometry():
    from shapely.ops import substring

    from seascape.coastal_configuration.coast_complexity_build import _local_sinuosity

    line = LineString([(0, 0), (0, 0), (300, 400), (700, 400), (700, 100), (700, 100)])
    positions = [0, 100, 500, 900, 1200, 1400]
    points = sample_line_positions(line, positions)
    assert all(
        point.distance(line.interpolate(position)) < 1e-9
        for point, position in zip(points, positions, strict=True)
    )
    scale = 250.0
    values = [
        shoreline_sinuosity(substring(line, start, start + scale))
        for start in range(0, 1000, 250)
    ]
    assert _local_sinuosity(line, scale) == pytest.approx(sum(values) / len(values))


def test_coast_query_chunks_preserve_source_length_and_orientation():
    import geopandas as gpd

    from seascape.coastal_configuration.coast_complexity_build import _coast_chunks

    line = LineString([(index, math.sin(index / 10)) for index in range(201)])
    frame = gpd.GeoDataFrame(geometry=[line], crs=32610)
    chunks = _coast_chunks(frame)
    assert len(chunks) == 4 and set(chunks.SOURCE_COAST_INDEX) == {0}
    support = box(40, -2, 140, 2)
    water = box(-1, -3, 202, 3)
    context = water.boundary
    original = summarize_coast(
        [line],
        support,
        water,
        {},
        context,
        minimum_island_area_m2=0,
        normal_probe_m=0.1,
    )
    indexed = summarize_coast(
        list(chunks.geometry),
        support,
        water,
        {},
        context,
        minimum_island_area_m2=0,
        normal_probe_m=0.1,
    )
    assert indexed.shoreline_length_m == pytest.approx(original.shoreline_length_m)
    assert indexed.axial_orientation_deg == pytest.approx(
        original.axial_orientation_deg
    )


def test_coast_producer_publishes_source_attribution(tmp_path, monkeypatch):
    import json

    import geopandas as gpd
    import h3

    from seascape.coastal_configuration import coast_complexity_build as module

    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    key = h3.latlng_to_cell(49, -125, 8)
    full = gpd.GeoDataFrame(
        {"H3_INDEX": [key]},
        geometry=[Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(key)])],
        crs=4326,
    ).to_crs(32610)
    xmin, ymin, xmax, ymax = full.geometry.iloc[0].bounds
    mid = (xmin + xmax) / 2
    rights = {
        "SOURCE_ID": ["synthetic coast"],
        "SOURCE_VERSION": ["1"],
        "RIGHTS": ["synthetic fixture"],
    }
    frames = {
        "coast": gpd.GeoDataFrame(
            {"SEGMENT_ID": ["coast"], **rights},
            geometry=[LineString([(mid, ymin - 100), (mid, ymax + 100)])],
            crs=32610,
        ),
        "land": gpd.GeoDataFrame(
            {
                "LAND_COMPONENT_ID": ["mainland"],
                "IS_ISLAND_CANDIDATE": [False],
                **rights,
            },
            geometry=[box(xmin - 100, ymin - 100, mid, ymax + 100)],
            crs=32610,
        ),
        "context": gpd.GeoDataFrame(
            rights,
            geometry=[box(xmin - 2000, ymin - 2000, xmax + 2000, ymax + 2000)],
            crs=32610,
        ),
        "water": gpd.GeoDataFrame(
            rights,
            geometry=[box(mid, ymin - 2000, xmax + 2000, ymax + 2000)],
            crs=32610,
        ),
    }
    cells = full.copy()
    cells.geometry = cells.geometry.intersection(frames["water"].geometry.iloc[0])
    frames["cells"] = cells
    paths = {name: tmp_path / (name + ".parquet") for name in frames}
    for name, frame in frames.items():
        frame.to_parquet(paths[name], index=False)
    config = module.CoastComplexityConfig(
        shoreline_path=paths["coast"],
        land_components_path=paths["land"],
        source_context_path=paths["context"],
        water_path=paths["water"],
        clipped_r8_path=paths["cells"],
        output_dir=tmp_path / "out",
        projected_crs="EPSG:32610",
        sinuosity_scales_m=(50.0,),
        minimum_island_area_m2=0,
        orientation_probe_m=1,
        headland_smoothing_m=50,
        headland_station_spacing_m=25,
        headland_minimum_turn_degrees=20,
        max_cells=10,
        max_coast_segments=10,
        max_headland_candidates=100,
        selected_h3_indices=(),
    )
    monkeypatch.setattr(module, "load_coast_complexity_config", lambda _: config)
    monkeypatch.setattr(
        module, "load_model_area_geometry", lambda *a, **k: cells.copy()
    )
    outputs = module.build_coast_complexity("unused")
    assert all(path.exists() for path in outputs)
    manifest = json.loads((tmp_path / "out/coast_complexity_manifest.json").read_text())
    assert manifest["attribution"] == [
        {"text": "synthetic coast, version 1", "license": "synthetic fixture"}
    ]


def test_sinuosity_and_axial_wraparound() -> None:
    assert shoreline_sinuosity(LineString([(0, 0), (100, 0)])) == 1
    semicircle = LineString(
        [
            (100 * math.cos(t), 100 * math.sin(t))
            for t in [math.pi * k / 100 for k in range(101)]
        ]
    )
    assert shoreline_sinuosity(semicircle) == pytest.approx(math.pi / 2, rel=1e-4)
    lines = [
        LineString([(0, 0), (100, 1)]),
        LineString([(100, 20), (0, 21)]),
    ]
    support = box(-10, -10, 110, 40)
    water = box(-10, -10, 110, 10)
    island = box(20, 0, 40, 5)
    result = summarize_coast(
        lines,
        support,
        water,
        {"source:island": island},
        box(-100, -100, 200, 200).boundary,
        minimum_island_area_m2=10,
        normal_probe_m=1,
    )
    assert result.axial_orientation_deg is not None
    assert min(result.axial_orientation_deg, 180 - result.axial_orientation_deg) < 1
    assert result.orientation_concentration == pytest.approx(1, rel=1e-3)
    assert result.island_count == 1
    assert result.island_ids == ("source:island",)
    assert result.island_area_within_support_m2 == 100
    clipped = summarize_coast(
        lines,
        support,
        water,
        {"mainland?": box(100, 0, 250, 10)},
        box(-100, -100, 200, 200).boundary,
        minimum_island_area_m2=10,
        normal_probe_m=1,
    )
    assert clipped.island_count == 0
    assert clipped.boundary_censored_island_ids == ("mainland?",)


def test_land_sided_headland_excludes_bay() -> None:
    headland = LineString([(0, 0), (1, 1), (0, 2)])
    headland_land = Polygon([(-5, -5), (0, 0), (1, 1), (0, 2), (-5, 5)])
    candidates = headland_candidates(
        "coast-1",
        headland,
        headland_land,
        smoothing_distance_m=1,
        station_spacing_m=0.1,
        minimum_turn_degrees=30,
        side_probe_m=0.1,
    )
    assert candidates
    bay = LineString([(0, 0), (-1, 1), (0, 2)])
    bay_land = Polygon([(-5, -5), (0, 0), (-1, 1), (0, 2), (-5, 5)])
    assert not headland_candidates(
        "coast-2",
        bay,
        bay_land,
        smoothing_distance_m=1,
        station_spacing_m=0.1,
        minimum_turn_degrees=30,
        side_probe_m=0.1,
    )
