import geopandas as gpd
import pytest
from shapely.geometry import Point, box

from seascape.coastal_configuration.passage_build import qualify_section_depths
from seascape.coastal_configuration.research_geometry import (
    bank_section,
    source_water_path,
)
from seascape.hydrologic_connectivity.fluvial_connectivity.selected_outlets_build import (
    select_outlet_inventory,
)


def test_water_axis_routes_around_island_and_has_physical_banks():
    island = box(40, 15, 60, 35)
    water = box(0, 0, 100, 50).difference(island)
    line, evidence = source_water_path(
        water, [(10, 25), (90, 25)], grid_m=2, margin_m=20, max_cells=10000
    )
    assert water.covers(line)
    assert line.intersection(island).is_empty
    assert line.length > 80
    gate = bank_section(water, line, half_length_m=100, tangent_m=5)
    assert water.covers(gate)
    assert all(
        Point(c).distance(water.boundary) < 1e-7
        for c in [gate.coords[0], gate.coords[-1]]
    )
    assert evidence["water_path_valid"]
    with pytest.raises(ValueError, match="budget"):
        source_water_path(
            water, [(10, 25), (90, 25)], grid_m=2, margin_m=20, max_cells=1
        )


def test_unqualified_datum_never_populates_physical_depths():
    row = {
        field: 123.0
        for field in [
            "CROSS_SECTION_AREA_M2",
            "VALID_INTEGRAL_AREA_M2",
            "MAX_DEPTH_M",
            "WIDTH_AT_DEPTH_THRESHOLD_M",
            "MAX_CONTIGUOUS_WIDTH_AT_DEPTH_THRESHOLD_M",
        ]
    }
    row["BATHYMETRY_STATUS"] = "complete"
    result = qualify_section_depths(row, datum_qualified=False)
    assert result["MAX_DEPTH_M"] is None
    assert result["CROSS_SECTION_AREA_M2"] is None
    assert result["NOMINAL_MAX_DEPTH_M"] == 123.0
    assert result["BATHYMETRY_STATUS"] == "vertical_datum_unqualified"
    assert qualify_section_depths(row, datum_qualified=True)["MAX_DEPTH_M"] == 123.0


def test_reviewed_outlet_keeps_coordinate_provenance():
    frame = gpd.GeoDataFrame(
        {
            "FLUVIAL_MOUTH_ID": ["HYDRORIVERS_V10_1"],
            "RIVER_BASIN_ID": [1],
            "SOURCE_ID": ["BC FWA"],
            "SOURCE_VERSION": ["snapshot"],
            "SOURCE_FEATURE_ID": ["OBJECTID:42"],
            "RIGHTS": ["BC OGL"],
        },
        geometry=[Point(-126, 49)],
        crs=4326,
    )
    result = select_outlet_inventory(frame, ("HYDRORIVERS_V10_1",))
    assert result.SOURCE_ID.iloc[0] == "BC FWA"
    assert result.SOURCE_FEATURE_ID.iloc[0] == "OBJECTID:42"
    with pytest.raises(ValueError, match="complete coordinate"):
        select_outlet_inventory(frame.drop(columns="RIGHTS"), ("HYDRORIVERS_V10_1",))


def test_passage_parent_denominator_keeps_children_outside_analysis_extent():
    import h3

    from seascape.coastal_configuration.passage_build import passage_parent_support

    parent = h3.latlng_to_cell(48, -123, 6)
    children = sorted(h3.cell_to_children(parent, 8))[:2]
    all_cells = gpd.GeoDataFrame(
        {"H3_INDEX": children}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs=32610
    )
    support = passage_parent_support(all_cells, all_cells.iloc[:1])
    assert support.geometry.area.iloc[0] == 2
    assert support.H3_INDEX.iloc[0] == parent


def test_per_passage_depth_sources_do_not_share_datum_qualification(tmp_path):
    from types import SimpleNamespace

    from seascape.coastal_configuration.passage_build import passage_depth_source

    config = SimpleNamespace(
        depth_raster_path=tmp_path / "nominal.tif",
        depth_vertical_datum="heterogeneous chart datum",
        depth_datum_qualified=False,
    )
    default = SimpleNamespace(
        VERTICAL_DATUM="heterogeneous chart datum", DEPTH_DATUM_QUALIFIED=False
    )
    assert not passage_depth_source(config, default)["qualified"]
    known = SimpleNamespace(
        VERTICAL_DATUM="NAVD88",
        DEPTH_DATUM_QUALIFIED=True,
        DEPTH_RASTER_PATH=str(tmp_path / "noaa.tif"),
        DEPTH_SOURCE_ID="NOAA",
        DEPTH_SOURCE_VERSION="2014",
        DEPTH_RIGHTS="US government",
        DEPTH_SOURCE_VERTICAL_DATUM="NAVD88",
        DEPTH_UNITS="m",
        DEPTH_ELEVATION_CONVENTION="positive_up",
    )
    assert passage_depth_source(config, known)["qualified"]
    known.VERTICAL_DATUM = "MLLW"
    with pytest.raises(ValueError, match="datums disagree"):
        passage_depth_source(config, known)
    known.VERTICAL_DATUM = "NAVD88"
    known.DEPTH_UNITS = "rendered byte"
    with pytest.raises(ValueError, match="metres"):
        passage_depth_source(config, known)
