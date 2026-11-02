import json

import geopandas as gpd
import h3
import pandas as pd
import pyarrow as pa
import pytest
from shapely.geometry import Point

from seascape.anthropogenic.artificial_reefs import (
    cell_memberships,
    coordinate,
    enrich_native,
    inventory,
    noaa_sites,
    published_sites,
    reconcile,
)
from seascape.reviewed_delivery import project


def site(source, name, latitude=48, longitude=-123, identity=None):
    identity = identity or name
    return dict(
        source=source,
        name=name,
        record_id=f"{source}:{identity}",
        site_id=identity,
        latitude=latitude,
        longitude=longitude,
    )


def test_published_coordinate_formats_and_source_dates():
    records, sources = published_sites()
    assert len(records) == 15
    assert len({r["record_id"] for r in records}) == 15
    assert sum(r["source"] == "arsbc" for r in records) == 8
    assert sources["arsbc"]["sha256"] is None
    assert len(sources["wdfw"]["sha256"]) == 64
    church = next(r for r in records if r["site_id"] == "gb-church")
    assert church["latitude"] == pytest.approx(48.72205)
    assert church["longitude"] == pytest.approx(-123.35565)
    assert church["deployment_date"] == "1991-08-11"
    assert coordinate([48, 11, 9]) == pytest.approx(48.185833333333)
    for invalid in ([48, 60], [48, 1, 60], [float("nan"), 0], [91, 0]):
        with pytest.raises(ValueError):
            coordinate(invalid)


def test_reconciliation_preserves_conflicts_and_does_not_merge_nearby_distinct_sites():
    primary = [
        site("wdfw", "The Trees"),
        site("wdfw", "Alki", latitude=47),
        site("arsbc", "BC"),
    ]
    noaa = [
        site("noaa", "THE TREES (BOEING CREEK)", latitude=48.03),
        site("noaa", "WEST SEATTLE", latitude=47.0001),
        site("noaa", "Different reef", latitude=47.0002),
    ]
    records, checks = reconcile(primary, noaa)
    assert checks[0]["status"] == "coordinate_conflict_wdfw_preferred"
    assert checks[0]["distance_m"] > 3000
    assert checks[1]["status"] == "location_agrees"
    assert all(c["independent_confirmation"] is False for c in checks)
    assert records[3]["latitude"] == 48.03
    assert records[3]["canonical_record_id"] == records[0]["record_id"]
    assert records[-1]["canonical_record_id"] == records[-1]["record_id"]
    frame = inventory(records)
    assert len(frame) == 6 and frame.IS_CANONICAL.sum() == 4
    assert not frame.SUPPORTS_AREA.any()
    with pytest.raises(ValueError, match="Duplicate reef"):
        reconcile(primary, [primary[0]])
    with pytest.raises(ValueError, match="Multiple NOAA"):
        reconcile(
            primary, noaa + [site("noaa", "ALKI", identity="second-alki", latitude=47)]
        )


def test_noaa_selects_only_explicit_artificial_reef_and_keeps_lineage(
    monkeypatch, tmp_path
):
    tables = {
        "soc_dat": pd.DataFrame(
            {
                "HUNUM": [1, 2],
                "TYPE": ["ARTIFICIAL REEF", "DIVING"],
                "NAME": ["REEF", "NATURAL REEF"],
                "G_SOURCE": [10, 10],
                "A_SOURCE": [10, 10],
            }
        ),
        "socecon_point": gpd.GeoDataFrame(
            {"HUNUM": [1, 2, 2], "ID": [101, 102, 103]},
            geometry=[Point(-123, 48), Point(-123, 49), Point(-123, 49.1)],
            crs=4269,
        ),
        "sources": pd.DataFrame(
            {"SOURCE_ID": [10], "ORIGINATOR": ["WDFW"], "TIME_PERIOD": ["2005"]}
        ),
    }
    monkeypatch.setattr(gpd, "read_file", lambda path, layer: tables[layer])
    result = noaa_sites(tmp_path / "noaa.zip")
    assert len(result) == 1
    assert result[0]["site_id"] == "1"
    assert result[0]["source_context"]["source_crs"] == "EPSG:4269"
    assert result[0]["source_context"]["lineage"]["10"]["ORIGINATOR"] == "WDFW"
    tables["soc_dat"] = pd.concat([tables["soc_dat"], tables["soc_dat"].iloc[:1]])
    with pytest.raises(ValueError, match="unique HUNUM"):
        noaa_sites(tmp_path / "noaa.zip")


def test_native_resolution_not_parent_assignment_and_outside_support():
    # H3 cells at different resolutions are not geometrically nested.
    point = next(
        (lat, lon)
        for lat in [48 + i / 100 for i in range(30)]
        for lon in [-123 + i / 100 for i in range(30)]
        if h3.latlng_to_cell(lat, lon, 6)
        != h3.cell_to_parent(h3.latlng_to_cell(lat, lon, 8), 6)
    )
    records, _ = reconcile([site("arsbc", "BC", *point)], [])
    direct = h3.latlng_to_cell(*point, 6)
    parent = h3.cell_to_parent(h3.latlng_to_cell(*point, 8), 6)
    memberships, outside = cell_memberships(records, [direct, parent], 6)
    assert memberships[direct] == ["arsbc:BC"] and memberships[parent] == []
    assert outside == []
    memberships, outside = cell_memberships(records, [parent], 6)
    assert memberships[parent] == [] and outside[0]["native_cell"] == direct


def test_enrichment_preserves_other_metrics_unknowns_and_old_positives():
    records, _ = reconcile([site("arsbc", "BC")], [])
    key = h3.latlng_to_cell(48, -123, 6)
    keys = [key, *sorted(set(h3.grid_disk(key, 1)) - {key})[:2]]
    prefix = "ANTHROPOGENIC__"
    reef = prefix + "ARTIFICIAL_REEF_MAPPED_POSITIVE_EVIDENCE"
    table = pa.table(
        {
            "H3_INDEX": keys,
            "H3_RESOLUTION": [6] * 3,
            reef: [False, True, False],
            reef + "_SOURCE_NULLABLE": pa.array([None, True, None], type=pa.bool_()),
            prefix + "ARTIFICIAL_REEF_PRESENCE_QC": ["unknown", "positive", "unknown"],
            prefix + "AQUACULTURE_MAPPED_POSITIVE_EVIDENCE": [True, False, False],
            prefix + "DISPOSAL_SITE_MAPPED_POSITIVE_EVIDENCE": [False, False, False],
            prefix + "DREDGED_CHANNEL_MAPPED_POSITIVE_EVIDENCE": [False, False, False],
            prefix + "SHORELINE_ARMORING_FRAC": [0.2, None, 0.0],
        }
    )
    updated, report = enrich_native(
        table,
        records,
        evidence={"inventory_path": "/source.parquet", "inventory_sha256": "a" * 64},
    )
    assert updated[reef].to_pylist() == [True, True, False]
    assert updated[reef + "_SOURCE_NULLABLE"].to_pylist() == [True, True, None]
    assert updated[prefix + "SHORELINE_ARMORING_FRAC"].equals(
        table[prefix + "SHORELINE_ARMORING_FRAC"]
    )
    assert report["positive_cells"] == 2
    public = project("anthropogenic", updated)
    assert public["has_mapped_artificial_reef"].to_pylist() == [1, 1, 0]
    assert public["h3_index"].to_pylist() == keys
    context = json.loads(public.schema.metadata[b"seascape_domain"])
    assert (
        context["artificial_reef_inventory"]["source_records"][0]["record_id"]
        == "arsbc:BC"
    )
    assert (
        "not confirmed absence"
        in context["fields"]["has_mapped_artificial_reef"]["definition"]
    )
