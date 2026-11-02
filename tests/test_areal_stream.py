"""Indexed polygons preserve overlaps and missing mapped evidence."""

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import box

from seascape.benthic_substrate.areal import build_areal_class_fractions
from seascape.benthic_substrate.areal_stream import build_index, produce
from seascape.regional.contract import digest


def test_index_matches_unchunked_including_empty_spatial_batch(tmp_path):
    keys = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123, 6), 1))[:2]
    support = gpd.GeoDataFrame(
        {"H3_INDEX": keys, "H3_RESOLUTION": [6, 6]},
        geometry=[box(0, 0, 10, 10), box(100, 100, 110, 110)],
        crs=6933,
    )
    inventory = gpd.GeoDataFrame(
        {"RECORD_ID": ["a", "b"], "CLASS_CODE": ["1", "2"]},
        geometry=[box(0, 0, 7, 10), box(5, 0, 10, 10)],
        crs=6933,
    )
    source = tmp_path / "source.parquet"
    wet = tmp_path / "wet.parquet"
    inventory.to_parquet(source)
    support.to_parquet(wet)
    index = tmp_path / "index"
    build_index(source, digest(source), index, batch_size=1)
    actual = (
        produce(index, wet, digest(wet), keys, rights="test", batch_size=1)
        .to_pandas()
        .sort_values("H3_INDEX")
        .reset_index(drop=True)
    )
    reference = build_areal_class_fractions(
        inventory,
        support,
        classes={"1": "HARD", "2": "MIXED", "3": "SOFT"},
        source_context={"rights": "test"},
    ).to_pandas()
    pd.testing.assert_frame_equal(actual, reference, check_exact=True)
    assert pd.isna(actual.iloc[1].MAPPED_SUBSTRATE_AREA_M2)
    assert actual.iloc[1].SOURCE_RECORD_COUNT == 0
    assert actual.iloc[0].AREAL_CLASS_QC == "source_class_conflict"
    with pytest.raises(ValueError, match="checksum"):
        produce(index, wet, "0" * 64, keys, rights="test")
    with pytest.raises(ValueError, match="EPSG:3005"):
        build_index(
            source,
            digest(source),
            tmp_path / "bad",
            operation="historical-no-grid",
        )


def test_public_cli_forwards_source_arguments(monkeypatch):
    from seascape.benthic_substrate import areal_stream
    from seascape.cli import main

    seen = []
    monkeypatch.setattr(areal_stream, "run", lambda args: seen.append(args) or 0)
    args = ["mapped-substrate"]
    for name in [
        "source",
        "support",
        "keys",
        "work",
        "output",
        "source-sha256",
        "support-sha256",
        "rights",
    ]:
        args.extend(["--" + name, "fixture"])
    assert main(args) == 0
    assert str(seen[0].source) == "fixture"
