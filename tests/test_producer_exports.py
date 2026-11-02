"""Producer-to-export checks use native schemas, independently of core specifications."""

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import rasterio
import yaml
from rasterio.transform import from_origin
from shapely.geometry import Point

from seascape.anthropogenic.build import _mapped_evidence_fields
from seascape.benthic_substrate.classification.build import _native_delivery_samples
from seascape.coastal_configuration.shoreline_proximity.build import (
    _nullable_network_distances,
)
from seascape.domain_parquets import export_domain_parquets, read_area
from seascape.utils.habitat_raster import validate_percentage


def export_producer(tmp_path, product, tables):
    products = {"h3_marine_support": {"collection": {"paths": {}}, "features": {}}}
    entry = products[product] = {"collection": {"paths": {}}, "features": {}}
    for resolution, table in tables.items():
        cell = h3.latlng_to_cell(48.5, -123, resolution)
        keys = pa.table({"H3_INDEX": [cell], "H3_RESOLUTION": [resolution]})
        pq.write_table(keys, tmp_path / f"support-r{resolution}.parquet")
        products["h3_marine_support"]["collection"]["paths"][resolution] = (
            f"support-r{resolution}.parquet"
        )
        values = (
            table
            if isinstance(table, pa.Table)
            else pa.Table.from_pandas(table, preserve_index=False)
        )
        for name in values.column_names:
            if name not in keys.column_names:
                keys = keys.append_column(name, values[name])
                entry["features"].setdefault(
                    name, {"role": "predictor", "collection_paths": {}}
                )["collection_paths"][resolution] = f"source-r{resolution}.parquet"
        pq.write_table(keys, tmp_path / f"source-r{resolution}.parquet")
        entry["collection"]["paths"][resolution] = f"source-r{resolution}.parquet"
    catalog = tmp_path / "features.yaml"
    catalog.write_text(yaml.safe_dump({"products": products}))
    output = tmp_path / "Data/Seascape"
    export_domain_parquets(workspace=tmp_path, catalog_path=catalog, output=output)
    return output


def test_normal_anthropogenic_fields_export_as_current_compact_metrics(tmp_path):
    cell = h3.latlng_to_cell(48.5, -123, 8)
    inventory = gpd.GeoDataFrame(
        {
            "FEATURE_CLASS": ["artificial_reef"],
            "IS_CANONICAL": [True],
            "SUPPORTS_AREA": [False],
        },
        geometry=[Point(-123, 48.5)],
        crs=4326,
    )
    fields = _mapped_evidence_fields(inventory, [cell], 8)
    fields["SHORELINE_ARMORING_FRAC"] = [0.75]
    fields["SOURCE_QC"] = ["not public"]
    output = export_producer(tmp_path, "anthropogenic", {8: pd.DataFrame(fields)})
    result = read_area("anthropogenic", resolution=8, output=output)
    assert result.column_names == [
        "h3_index",
        "has_mapped_aquaculture",
        "has_mapped_artificial_reef",
        "has_mapped_disposal_site",
        "has_mapped_dredged_channel",
        "shoreline_armoring_fraction",
    ]
    assert result["has_mapped_artificial_reef"].to_pylist() == [1]
    assert result["shoreline_armoring_fraction"].to_pylist() == [0.75]


def test_unknown_shoreline_network_distances_are_null_before_export(tmp_path):
    fields = {
        "SHORELINE_TOTAL_MAPPED_LENGTH_M": [10.0],
        "SHORELINE_DISTANCE_M": [5.0],
        "WATER_NETWORK_DISTANCE_M": [np.nan],
        "NETWORK_CONNECTOR_DISTANCE_M": [np.nan],
        "NETWORK_DISTANCE_QC_REASON": ["disconnected"],
    }
    for token in ("ROCKY", "SANDY", "GRAVEL", "CLIFF", "BLUFF", "DELTAIC", "ESTUARINE"):
        fields[token + "_SHORE_FRAC"] = [1.0 if token == "ROCKY" else 0.0]
    native = _nullable_network_distances(pl.DataFrame(fields)).to_arrow()
    assert native["WATER_NETWORK_DISTANCE_M"].to_pylist() == [None]
    assert native["NETWORK_CONNECTOR_DISTANCE_M"].to_pylist() == [None]
    assert native["NETWORK_DISTANCE_QC_REASON"].to_pylist() == ["disconnected"]
    output = export_producer(tmp_path, "shoreline_characterization", {8: native})
    result = read_area("shoreline", resolution=8, output=output)
    assert result["distance_to_mapped_shoreline_m"].to_pylist() == [5.0]
    assert not any("network" in name for name in result.column_names)


def test_nonfinite_public_measurement_still_fails_export(tmp_path):
    with pytest.raises(ValueError, match="Nonfinite metric"):
        export_producer(
            tmp_path, "bathymetry", {8: pd.DataFrame({"BATHYMETRY": [np.inf]})}
        )


def test_percent_validation_accepts_endpoint_roundoff_and_keeps_missingness():
    values = np.array([-1e-15, 0.0, 50.0, 100.00000000000003, np.nan])
    np.testing.assert_allclose(
        validate_percentage(values, "rock"), [0.0, 0.0, 0.5, 1.0, np.nan]
    )
    for invalid in (-1e-9, 100.000000001):
        with pytest.raises(ValueError, match="percent values"):
            validate_percentage(np.array([invalid]), "rock")


def test_normal_substrate_export_uses_direct_r6_samples_and_omits_internal_r8(tmp_path):
    inventory = []
    for variable, percent in (("rock", 60), ("gravel", 20), ("sand", 30), ("mud", 50)):
        path = tmp_path / (variable + ".tif")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype="float32",
            crs=4326,
            transform=from_origin(-124, 49, 0.5, 0.5),
            nodata=-99,
        ) as source:
            source.write(np.full((4, 4), percent, dtype=np.float32), 1)
        inventory.append({"VARIABLE": variable, "PATH": str(path)})
    support = pd.DataFrame(
        {
            "REPRESENTATIVE_POINT_LONGITUDE": [-123.0],
            "REPRESENTATIVE_POINT_LATITUDE": [48.5],
        }
    )
    fields = _native_delivery_samples(pd.DataFrame(inventory), support)
    output = export_producer(
        tmp_path,
        "benthic_substrate",
        {6: pd.DataFrame(fields), 8: pd.DataFrame({"SUBSTRATE_ROCK_FRAC": [0.1]})},
    )
    result = read_area("substrate", resolution=6, output=output)
    assert result.column_names == [
        "h3_index",
        "modeled_rock_presence_score",
        "modeled_gravel_fraction",
        "modeled_sand_fraction",
        "modeled_mud_fraction",
    ]
    assert [result[n][0].as_py() for n in result.column_names[1:]] == [
        0.6,
        0.2,
        0.3,
        0.5,
    ]
    assert not (output / "substrate-r8-static.parquet").exists()


def test_normal_estuary_native_distance_has_the_existing_public_name(tmp_path):
    output = export_producer(
        tmp_path,
        "estuarine_connectivity",
        {
            8: pd.DataFrame(
                {
                    "DISTANCE_TO_ESTUARY_M": [123.0],
                    "NETWORK_CONNECTOR_DISTANCE_M": [4.0],
                    "WATER_NETWORK_DISTANCE_TO_ESTUARY_M": [234.0],
                }
            )
        },
    )
    result = read_area("estuary", resolution=8, output=output)
    assert result.column_names == ["h3_index", "distance_to_mapped_estuary_point_m"]
    assert result["distance_to_mapped_estuary_point_m"].to_pylist() == [123.0]
