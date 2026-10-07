"""Provider processing history stays separate from dates and geometry values."""

from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from seascape.biogenic_habitat.kelp.build import (
    _annual_kelp_inventory,
    annual_spatial_processing,
)


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (1989, "vector_CAD_processing_1989_1992"),
        (1992, "vector_CAD_processing_1989_1992"),
        (1994, "approximately20m_raster_processing_1994_2009"),
        (2009, "approximately20m_raster_processing_1994_2009"),
        (2010, "approximately4m_raster_processing_2010_2024"),
        (2024, "approximately4m_raster_processing_2010_2024"),
    ],
)
def test_provider_processing_era_boundaries(year, expected):
    assert annual_spatial_processing(year) == expected


@pytest.mark.parametrize("year", [1988, 1993, 2025])
def test_unqualified_or_unsurveyed_year_has_no_processing_label(year):
    with pytest.raises(ValueError, match="No qualified DNR annual processing era"):
        annual_spatial_processing(year)


def test_annual_loader_preserves_observation_year_and_geometry_across_eras(
    tmp_path, monkeypatch
):
    database = tmp_path / "WA_floating_kelp" / "fixture.gdb"
    database.mkdir(parents=True)
    years = [1989, 1992, 1994, 2009, 2010, 2024]
    source = gpd.GeoDataFrame(
        {"source_id": [7]}, geometry=[box(-123.1, 48.1, -123.0, 48.2)], crs=4326
    )
    monkeypatch.setattr(
        gpd,
        "list_layers",
        lambda _: pd.DataFrame({"name": [f"kelp{y}" for y in years]}),
    )
    monkeypatch.setattr(gpd, "read_file", lambda *_args, **_kwargs: source.copy())
    config = SimpleNamespace(
        raw_dir=tmp_path,
        sources={
            "wa_dnr_annual_floating_kelp": {"extract_directory": "WA_floating_kelp"}
        },
    )

    inventory = _annual_kelp_inventory(config)

    assert len(inventory) == len(years)
    for year, records in zip(years, inventory, strict=True):
        assert records.OBSERVATION_YEAR.tolist() == [year]
        assert records.SPATIAL_PRECISION_CLASS.tolist() == [
            annual_spatial_processing(year)
        ]
        assert records.geometry.to_wkb().tolist() == source.geometry.to_wkb().tolist()
        assert records.TEMPORAL_PRECISION_CLASS.tolist() == ["survey_year"]
        assert records.SOURCE_DATASET.tolist() == [f"WA_DNR_FLOATING_KELP_{year}"]
