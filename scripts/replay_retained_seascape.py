"""Bounded scientific replays from retained Seascape sources; never publishes."""

import argparse
import os
from pathlib import Path


def run_habitats(root, output):
    import json

    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    from seascape.biogenic_habitat.kelp.extents import build_kelp_extents
    from seascape.biogenic_habitat.seagrass.extents import build_seagrass_extents
    from seascape.biogenic_habitat.seagrass.native import native_cell_geometries
    from seascape.reviewed_delivery import restore_native

    ROOT = root
    T = ROOT / "Toolkits/toolkit-seascape"
    D = ROOT / "Data/Seascape"
    OUT = output
    reports = {}
    for family, builder, ip in [
        (
            "seagrass",
            build_seagrass_extents,
            T
            / ".seascape/work/seagrass-consolidation-20261020/all-time-producer/SEAGRASS_SOURCE_INVENTORY.parquet",
        ),
        (
            "kelp",
            build_kelp_extents,
            T / ".seascape/work/history-2009-2026/kelp-audited-inventory.parquet",
        ),
    ]:
        inv = gpd.read_parquet(ip)
        for res in [6, 8]:
            static = restore_native(
                pq.read_table(D / f"{family}-r{res}-static.parquet")
            )
            meta = json.loads(static.schema.metadata[b"seascape_domain"])
            context = meta["source_context"]
            field = family.upper() + "_EXTENT_ALL_TIME_M2"
            if family == "kelp":
                expected = pq.read_table(D / f"kelp-r{res}-dynamic.parquet").to_pandas()
                value = "ANNUAL_KELP_EXTENT_M2"
                positives = (
                    expected.loc[expected[value].gt(0), "H3_INDEX"]
                    .drop_duplicates()
                    .sort_values()
                    .head(10)
                )
                absent = expected.groupby("H3_INDEX")[value].count()
                keys = list(positives) + list(
                    absent[absent.eq(0)].sort_index().head(10).index
                )
            else:
                expected = static.to_pandas()
                value = field
                keys = list(
                    expected.loc[expected[value].gt(0), "H3_INDEX"]
                    .sort_values()
                    .head(10)
                ) + list(
                    expected.loc[expected[value].isna(), "H3_INDEX"]
                    .sort_values()
                    .head(10)
                )
            geom, _ = native_cell_geometries(keys)
            cells = gpd.GeoDataFrame(
                {"H3_INDEX": keys, "H3_RESOLUTION": [res] * len(keys)},
                geometry=geom,
                crs=4326,
            )
            result = builder(inv, cells, source_context=context)
            actual = (
                result.tables.dynamic if family == "kelp" else result.tables.static
            ).to_pandas()
            print(family, res, actual.columns.tolist(), flush=True)
            indexes = ["H3_INDEX", "date"] if family == "kelp" else ["H3_INDEX"]
            if family == "kelp" and "YEAR" in actual:
                actual["date"] = pd.to_datetime(
                    actual.pop("YEAR").astype(str) + "-01-01"
                ).dt.date
            e = (
                expected.loc[expected.H3_INDEX.isin(keys)]
                .set_index(indexes)
                .sort_index()
            )
            a = actual.set_index(indexes).sort_index()
            assert a.index.equals(e.index)
            np.testing.assert_allclose(
                a[value], e[value], atol=1e-6, rtol=1e-10, equal_nan=True
            )
            common = sorted(set(a.columns) & set(e.columns))
            differing = []
            for c in common:
                try:
                    pd.testing.assert_series_equal(
                        a[c], e[c], check_dtype=False, check_names=False
                    )
                except AssertionError:
                    differing.append(c)
            report = {
                "status": "area_and_keys_and_nulls_match",
                "input": str(ip),
                "resolution": res,
                "rows": len(a),
                "cells": len(keys),
                "positive": int(a[value].gt(0).sum()),
                "null": int(a[value].isna().sum()),
                "max_abs_error": float((a[value] - e[value]).abs().max()),
                "all_common_fields": common,
                "differing_fields": differing,
                "years": sorted(set(x.year for x in a.index.get_level_values("date")))
                if family == "kelp"
                else None,
            }
            reports[f"{family}-r{res}"] = report
            print(report, flush=True)
            (OUT / "habitat-replays.json").write_text(
                json.dumps(reports, indent=2) + "\n"
            )


def run_physical(root, output):
    import json

    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    from seascape.benthic_substrate.areal import build_areal_class_fractions
    from seascape.hydrologic_connectivity.freshwater_sources.build import (
        _build_h3_features,
        load_river_mouth_build_config,
    )
    from seascape.reviewed_delivery import restore_native
    from seascape.seafloor_physiography.bathymetry.build import _aggregate_raster
    from seascape.seafloor_physiography.geomorphometry.build import (
        _native_raster_slope_summary,
    )
    from seascape.utils.geometry_quality import audit_polygon_inventory

    R = root
    T = R / "Toolkits/toolkit-seascape"
    D = R / "Data/Seascape"
    W = T / ".seascape/work/source-closure-20261016"
    P = W / "workspace/data/processed/domain/environmental_layer/seascape"
    OUT = output
    reports = {}

    def compare(name, actual, expected, cols):
        a = actual.set_index("H3_INDEX").sort_index()
        e = expected.set_index("H3_INDEX").loc[a.index].sort_index()
        errors = {}
        for c in cols:
            assert a[c].isna().equals(e[c].isna()), c
            if pd.api.types.is_numeric_dtype(a[c]):
                np.testing.assert_allclose(
                    a[c], e[c], atol=1e-6, rtol=1e-10, equal_nan=True
                )
                errors[c] = float((a[c] - e[c]).abs().max())
            else:
                pd.testing.assert_series_equal(
                    a[c], e[c], check_dtype=False, check_names=False
                )
        reports[name] = {
            "rows": len(a),
            "columns": cols,
            "max_absolute_errors": errors,
            "status": "matched",
        }
        print(name, reports[name], flush=True)
        (OUT / "physical-replays.json").write_text(json.dumps(reports, indent=2) + "\n")

    def native(area, res):
        return restore_native(
            pq.read_table(D / f"{area}-r{res}-static.parquet")
        ).to_pandas()

    raster = T / ".seascape/cache/regional/bathymetry/GEBCO_2026_COASTAL_CONTEXT.tif"
    e = native("bathymetry", 8)
    e.columns = [c.removeprefix("bathymetry__") for c in e]
    keys = e.sort_values("H3_INDEX").H3_INDEX.iloc[::2000].tolist()[:40]
    nb = pq.read_table(
        P / "spatial_support/water_network/H3_WATER_NEIGHBORHOODS_RES_8.parquet",
        filters=[("SOURCE_H3_INDEX", "in", keys)],
    ).to_pandas()
    halo = sorted(
        set(keys) | set(nb.loc[nb.MINIMUM_HOP_COUNT.le(2), "TARGET_H3_INDEX"])
    )
    a = _aggregate_raster(
        raster,
        halo,
        8,
        "positive_down",
        (0.1, 0.25, 0.75, 0.9),
        2,
        (),
        "EPSG:32610",
        nb,
    )
    a = a.loc[a.H3_INDEX.isin(keys)]
    cols = [c for c in a if c != "H3_INDEX" and c in e]
    compare("bathymetry-r8", a, e, cols)
    a = _native_raster_slope_summary(raster, set(keys), 8, 0.9)
    e = native("terrain", 8)
    e.columns = [c.removeprefix("geomorphometry__") for c in e]
    compare("terrain-native-slope-r8", a, e, [c for c in a if c != "H3_INDEX"])
    frame = (
        gpd.read_parquet(W / "DFO_BOTTOM_PATCHES_REGIONAL_SOURCE.parquet")
        .to_crs(6933)
        .rename(columns={"GEOMETRY_PROCESSING": "SOURCE_GEOMETRY_PROCESSING"})
    )
    inv = audit_polygon_inventory(frame, policy="make_valid").frame
    for res in [6, 8]:
        e = native("mapped-substrate-classes", res)
        keys = list(
            e.loc[e.MAPPED_SOURCE_COVERAGE_FRAC.gt(0), "H3_INDEX"]
            .sort_values()
            .head(10)
        ) + list(
            e.loc[e.MAPPED_SOURCE_COVERAGE_FRAC.eq(0), "H3_INDEX"]
            .sort_values()
            .head(10)
        )
        wet = gpd.read_parquet(
            P / f"spatial_support/water_geometry/H3_COASTAL_WATER_RES_{res}.parquet"
        )
        wet = wet.loc[wet.H3_INDEX.isin(keys)]
        a = build_areal_class_fractions(
            inv,
            wet,
            classes={"1": "HARD", "2": "MIXED", "3": "SOFT"},
            source_context={"rights": "Open Government Licence - Canada; DFO"},
            max_records=800000,
        ).to_pandas()
        compare(
            f"mapped-substrate-classes-r{res}",
            a,
            e,
            [c for c in a if c not in ("H3_INDEX", "H3_RESOLUTION") and c in e],
        )
    cfg = load_river_mouth_build_config(
        W / "workspace/config/data/environment_seascape.yaml"
    )
    mouths = gpd.read_parquet(D / "research/freshwater-mouth-inventory.parquet")
    e = native("freshwater", 8)
    e.columns = [c.removeprefix("freshwater_sources__") for c in e]
    support = e.sort_values("H3_INDEX").iloc[::2000].head(40)[["H3_INDEX"]]
    a = _build_h3_features(None, mouths, cfg, support)
    compare("freshwater-r8", a, e, [c for c in a if c != "H3_INDEX" and c in e])


def run_geometry(root, output):
    import json

    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    import rasterio
    import shapely
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    from seascape.coastal_configuration.coast_complexity import summarize_coast
    from seascape.coastal_configuration.coast_complexity_build import (
        _coast_chunks,
        load_coast_complexity_config,
    )
    from seascape.coastal_configuration.nearshore_build import load_nearshore_config
    from seascape.coastal_configuration.nearshore_transitions import (
        nearshore_depth_areas,
    )
    from seascape.reviewed_delivery import restore_native
    from seascape.spatial_support.water_network import load_model_area_geometry

    R = root
    T = R / "Toolkits/toolkit-seascape"
    D = R / "Data/Seascape"
    W = T / ".seascape/work/source-closure-20261016/workspace"
    config = W / "config/data/environment_seascape.yaml"
    reports = {}

    def expected(area):
        e = restore_native(pq.read_table(D / f"{area}-r8-static.parquet")).to_pandas()
        e.columns = [c.split("__")[-1] for c in e]
        return e

    def compare(area, actual, e):
        a = pd.DataFrame(actual).set_index("H3_INDEX").sort_index()
        e = e.set_index("H3_INDEX").loc[a.index]
        errors = {}
        for c in a:
            aa = pd.to_numeric(a[c])
            ee = pd.to_numeric(e[c])
            assert aa.isna().equals(ee.isna()), c
            np.testing.assert_allclose(aa, ee, rtol=1e-9, atol=1e-6, equal_nan=True)
            errors[c] = float((aa - ee).abs().max())
        reports[area] = {
            "rows": len(a),
            "max_absolute_errors": errors,
            "status": "matched",
        }
        print(area, reports[area], flush=True)
        (output / "geometry-replays.json").write_text(
            json.dumps(reports, indent=2) + "\n"
        )

    for area, loader in [
        ("nearshore-transitions", load_nearshore_config),
        ("coast-complexity", load_coast_complexity_config),
    ]:
        cfg = loader(config)
        e = expected(area)
        keys = e.sort_values("H3_INDEX").H3_INDEX.head(20).tolist()
        cells = load_model_area_geometry(8, config).to_crs(cfg.projected_crs)
        cells = cells.loc[cells.H3_INDEX.isin(keys)]
        water = (
            gpd.read_parquet(cfg.water_path)
            .to_crs(cfg.projected_crs)
            .geometry.union_all()
        )
        shore = gpd.read_parquet(cfg.shoreline_path).to_crs(cfg.projected_crs)
        rows = []
        if area == "nearshore-transitions":
            interest = cells.geometry.union_all().buffer(cfg.band_width_m + 1)
            line = shore.loc[shore.geometry.intersects(interest)].geometry.union_all()
            print("nearshore local lines ready", flush=True)
            with rasterio.open(cfg.depth_raster_path) as source:
                with WarpedVRT(
                    source, crs=cfg.projected_crs, resampling=Resampling.nearest
                ) as depth:
                    for cell in cells.itertuples():
                        a = nearshore_depth_areas(
                            cell.geometry,
                            water,
                            line,
                            depth,
                            depth_threshold_m=cfg.threshold_m,
                            band_width_m=cfg.band_width_m,
                            raster_depth_convention="negative_elevation",
                        )
                        rows.append(
                            {
                                "H3_INDEX": cell.H3_INDEX,
                                "NEARSHORE_ELIGIBLE_AREA_M2": a.eligible_area_m2,
                                "NEARSHORE_VALID_BATHYMETRY_AREA_M2": a.valid_area_m2,
                                "NEARSHORE_DEEP_WATER_AREA_M2": a.deep_area_m2,
                                "NEARSHORE_DEEP_WATER_FRAC_OF_VALID": a.deep_fraction_of_valid,
                                "NEARSHORE_BATHYMETRY_COVERAGE_FRAC": a.bathymetry_coverage_fraction,
                            }
                        )
        else:
            interest = cells.geometry.union_all()
            shore = shore.loc[shore.geometry.intersects(interest)]
            chunks = _coast_chunks(shore)
            land = gpd.read_parquet(cfg.land_components_path).to_crs(cfg.projected_crs)
            land = land.loc[land.IS_ISLAND_CANDIDATE]
            context = (
                gpd.read_parquet(cfg.source_context_path)
                .to_crs(cfg.projected_crs)
                .geometry.union_all()
            )
            for cell in cells.itertuples():
                local = chunks.iloc[
                    chunks.sindex.query(cell.geometry, predicate="intersects")
                ]
                fragments = [
                    p
                    for g in local.geometry.intersection(cell.geometry)
                    for p in shapely.get_parts(g)
                    if p.geom_type == "LineString"
                ]
                islands = land.iloc[
                    land.sindex.query(cell.geometry, predicate="intersects")
                ]
                a = summarize_coast(
                    fragments,
                    cell.geometry,
                    water,
                    dict(zip(islands.LAND_COMPONENT_ID, islands.geometry)),
                    context.boundary,
                    minimum_island_area_m2=cfg.minimum_island_area_m2,
                    normal_probe_m=cfg.orientation_probe_m,
                )
                rows.append(
                    {
                        "H3_INDEX": cell.H3_INDEX,
                        "SHORELINE_LENGTH_M": a.shoreline_length_m,
                        "SHORELINE_LENGTH_DENSITY_M_PER_KM2": a.shoreline_length_density_m_per_km2,
                        "SHORELINE_AXIAL_SIN_2THETA": a.axial_sin_2theta,
                        "SHORELINE_AXIAL_COS_2THETA": a.axial_cos_2theta,
                        "SHORELINE_ORIENTATION_CONCENTRATION": a.orientation_concentration,
                        "ISLAND_COUNT": a.island_count,
                        "ISLAND_FRACTION_OF_SUPPORT": a.island_fraction_of_support,
                    }
                )
        compare(area, rows, e)


def run_support(root, output):
    import json

    import numpy as np
    import pyarrow.parquet as pq

    from seascape.reviewed_delivery import restore_native
    from seascape.spatial_support.water_network.build import (
        _build_geometry_and_base_support,
        _load_water_geometry,
    )
    from seascape.spatial_support.water_network.config import load_water_network_config

    R = root
    T = R / "Toolkits/toolkit-seascape"
    D = R / "Data/Seascape"
    C = (
        T
        / ".seascape/work/source-closure-20261016/workspace/config/data/environment_seascape.yaml"
    )
    cfg = load_water_network_config(C)
    water, aoi = _load_water_geometry(cfg)
    e = restore_native(
        pq.read_table(D / "spatial-support-r8-static.parquet")
    ).to_pandas()
    e.columns = [c.split("__")[-1] for c in e]
    keys = list(e.sort_values("H3_INDEX").H3_INDEX.iloc[::4000].head(20))
    _, _, a = _build_geometry_and_base_support(water, aoi, 8, cfg, cells=keys)
    a = a.set_index("H3_INDEX").sort_index()
    e = e.set_index("H3_INDEX").loc[a.index]
    report = {
        "rows": len(a),
        "source": str(cfg.water_polygon_path),
        "producer": "water_network.build._build_geometry_and_base_support",
        "fields": {},
    }
    for c in ["WATER_AREA_M2", "WATER_FRACTION", "INTERSECTS_SHORELINE"]:
        np.testing.assert_allclose(a[c], e[c], rtol=1e-10, atol=1e-6, equal_nan=True)
        report["fields"][c] = {
            "max_abs_error": float(
                (a[c].astype(float) - e[c].astype(float)).abs().max()
            )
        }
    (output / "support-replay.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report)


def run_kelp_static(root, output):
    import json

    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    from seascape.biogenic_habitat.kelp.build import _records
    from seascape.biogenic_habitat.kelp.extents import build_kelp_extents
    from seascape.biogenic_habitat.seagrass.native import native_cell_geometries
    from seascape.reviewed_delivery import restore_native

    R = root
    T = R / "Toolkits/toolkit-seascape"
    D = R / "Data/Seascape"
    inv = gpd.read_parquet(
        T / ".seascape/work/history-2009-2026/kelp-audited-inventory.parquet"
    )
    raw = gpd.GeoDataFrame(
        pd.concat(
            [
                gpd.read_file(p)
                for p in sorted(
                    (T / ".seascape/cache/kelp-consolidation-20261020").glob(
                        "BC_CRIMS_KELP_BEDS_*.geojson"
                    )
                )
            ],
            ignore_index=True,
        ),
        crs=4326,
    )
    bc = _records(
        raw,
        source_dataset="BC_CRIMS_KELP_BEDS",
        feature_id_column="OBJECTID",
        evidence_class="generalized_mapping",
        composition_eligible=True,
        supports_area=True,
        confidence=2,
        survey_method="legacy CRIMS source compilation",
        spatial_precision="mapped_polygon",
        temporal_precision="source_date_not_standardized",
    )
    # Current complete retained BC pull replaces the earlier subset; no duplicate area is added.
    inv = gpd.GeoDataFrame(
        pd.concat(
            [inv.loc[~inv.SOURCE_DATASET.eq("BC_CRIMS_KELP_BEDS")], bc],
            ignore_index=True,
        ),
        crs=4326,
    )
    reports = {}
    for res in [6, 8]:
        table = restore_native(pq.read_table(D / f"kelp-r{res}-static.parquet"))
        e = table.to_pandas()
        field = "KELP_EXTENT_ALL_TIME_M2"
        positive = e.loc[e[field].gt(0)].sort_values("H3_INDEX")
        keys = list(
            positive.H3_INDEX.iloc[:: max(1, len(positive) // 20)].head(20)
        ) + list(e.loc[e[field].isna(), "H3_INDEX"].sort_values().head(10))
        geom, _ = native_cell_geometries(keys)
        cells = gpd.GeoDataFrame(
            {"H3_INDEX": keys, "H3_RESOLUTION": [res] * len(keys)},
            geometry=geom,
            crs=4326,
        )
        a = (
            build_kelp_extents(
                inv,
                cells,
                source_context=json.loads(table.schema.metadata[b"seascape_domain"])[
                    "source_context"
                ],
            )
            .tables.static.to_pandas()
            .set_index("H3_INDEX")
            .sort_index()
        )
        e = e.set_index("H3_INDEX").loc[a.index]
        np.testing.assert_allclose(
            a[field], e[field], atol=1e-6, rtol=1e-10, equal_nan=True
        )
        assert a[field].isna().equals(e[field].isna())
        reports[str(res)] = {
            "cells": len(a),
            "positive": int(a[field].gt(0).sum()),
            "null": int(a[field].isna().sum()),
            "max_abs_area_error_m2": float((a[field] - e[field]).abs().max()),
            "scope": "area, nulls and keys only; reconstructed BC records replace prior subset; record-count/source-ID qualifier parity not asserted",
        }
        print(reports[str(res)], flush=True)
    (output / "kelp-static-replays.json").write_text(
        json.dumps(reports, indent=2) + "\n"
    )


def run_rays(root, output):
    import json

    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq

    from seascape.coastal_configuration.exposure_and_enclosure.build import (
        _build_output,
        _directional_fetch_matrix,
        _spatial_support,
        load_exposure_enclosure_config,
    )
    from seascape.coastal_configuration.waterbody_morphometry.build import (
        _directional_shore_distances,
        _width_metrics,
        load_waterbody_morphometry_config,
    )
    from seascape.coastal_configuration.waterbody_morphometry.build import (
        _spatial_support as body_support,
    )
    from seascape.reviewed_delivery import restore_native

    R = root
    T = R / "Toolkits/toolkit-seascape"
    D = R / "Data/Seascape"
    W = T / ".seascape/work/source-closure-20261016/workspace"
    C = W / "config/data/environment_seascape.yaml"
    P = (
        W
        / "data/processed/domain/environmental_layer/seascape/spatial_support/h3_geometry"
    )
    support = (
        pq.read_table(P / "H3_MARINE_SUPPORT_RES_8.parquet")
        .to_pandas()
        .set_index("H3_INDEX")
    )
    reports = {}
    for area in ["coastal-bounds", "waterbody-morphometry"]:
        e = restore_native(pq.read_table(D / f"{area}-r8-static.parquet")).to_pandas()
        e.columns = [c.split("__")[-1] for c in e]
        keys = [
            k
            for k in e.sort_values("H3_INDEX").H3_INDEX.iloc[::4000].head(20)
            if k in support.index
        ]
        lineage = support.loc[keys]
        lat = lineage.REPRESENTATIVE_POINT_LATITUDE.to_numpy()
        lon = lineage.REPRESENTATIVE_POINT_LONGITUDE.to_numpy()
        if area == "coastal-bounds":
            cfg = load_exposure_enclosure_config(C)
            water = _spatial_support(cfg)[4]
            rays = _directional_fetch_matrix(
                keys, lat, lon, water, cfg.maximum_fetch_km
            )
            a = _build_output(
                keys,
                rays,
                np.zeros(len(keys)),
                cfg,
                lineage,
                np.array(["review"] * len(keys)),
            ).to_pandas()
            cols = [
                "OPENNESS_TO_OCEAN_INDEX",
                "EMBAYMENT_INDEX",
                "OPEN_WATER_ANGULAR_APERTURE_DEG",
            ]
        else:
            cfg = load_waterbody_morphometry_config(C)
            water = body_support(cfg)[4]
            rays = _directional_shore_distances(
                keys, lat, lon, water, cfg.maximum_shore_search_km
            )
            a = pd.DataFrame(
                {
                    "H3_INDEX": keys,
                    **_width_metrics(rays, cfg.maximum_shore_search_km * 1000),
                }
            )
            cols = [
                "LOCAL_WATERBODY_WIDTH_M",
                "WATERBODY_WIDTH_MEAN_M",
                "WATERBODY_WIDTH_CENSORED_FRACTION",
            ]
        a = a.set_index("H3_INDEX").sort_index()
        e = e.set_index("H3_INDEX").loc[a.index]
        errors = {}
        for c in cols:
            np.testing.assert_allclose(
                a[c], e[c], rtol=1e-10, atol=1e-6, equal_nan=True
            )
            errors[c] = float((a[c] - e[c]).abs().max())
        reports[area] = {
            "rows": len(a),
            "max_absolute_errors": errors,
            "scope": "local directional geometry only; network distances not replayed",
        }
        print(reports, flush=True)
        (output / "ray-replays.json").write_text(json.dumps(reports, indent=2) + "\n")


def run_network(root, output):
    import json

    import geopandas as gpd
    import numpy as np
    import pyarrow.parquet as pq

    from seascape.hydrologic_connectivity.fluvial_connectivity.build import (
        _snap_mouths_to_graph,
    )
    from seascape.hydrologic_connectivity.fluvial_connectivity.topology import (
        _spatial_support,
        load_fluvial_connectivity_config,
    )
    from seascape.reviewed_delivery import restore_native
    from seascape.spatial_support.water_network.graph import target_graph_mapping
    from seascape.spatial_support.water_network.load import (
        load_water_graph,
        multi_source_shortest_paths,
    )

    R = root
    T = R / "Toolkits/toolkit-seascape"
    W = T / ".seascape/work/source-closure-20261016/workspace"
    C = W / "config/data/environment_seascape.yaml"
    P = W / "data/processed/domain/environmental_layer/seascape"
    cfg = load_fluvial_connectivity_config(C)
    _, water, box, _, _ = _spatial_support(cfg)
    graph = load_water_graph(8, C, bbox=tuple(box.bounds))
    print("graph", len(graph.cells), flush=True)
    mouths = gpd.read_parquet(
        P
        / "hydrologic_connectivity/fluvial_connectivity/FLUVIAL_NETWORK_MOUTHS.parquet"
    )
    m = (
        _snap_mouths_to_graph(mouths, graph, water, cfg)
        .sort_values("FLUVIAL_MOUTH_ID")
        .reset_index(drop=True)
    )
    m = m.loc[m._GRAPH_INDEX.ge(0)].reset_index(drop=True)
    dist, owner = multi_source_shortest_paths(
        graph,
        [
            (
                str(graph.cells[int(row._GRAPH_INDEX)]),
                float(row.GRAPH_SNAP_DISTANCE_M),
                int(i),
            )
            for i, row in m.iterrows()
        ],
    )
    e = restore_native(
        pq.read_table(R / "Data/Seascape/fluvial-connectivity-r8-static.parquet")
    ).to_pandas()
    e.columns = [c.split("__")[-1] for c in e]
    e = e.sort_values("H3_INDEX").iloc[::2000].head(40)
    keys = e.H3_INDEX.tolist()
    mapped, connectors, qc = target_graph_mapping(graph, keys)
    values = np.full(len(keys), np.nan)
    valid = mapped >= 0
    reachable = valid.copy()
    reachable[valid] &= owner[mapped[valid]] >= 0
    values[reachable] = dist[mapped[reachable]] + connectors[reachable]
    field = "WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M"
    np.testing.assert_allclose(values, e[field], rtol=1e-10, atol=1e-6, equal_nan=True)
    report = {
        "rows": len(keys),
        "reachable": int(reachable.sum()),
        "graph_nodes": len(graph.cells),
        "attached_mouths": len(m),
        "max_abs_distance_error_m": float(
            np.nanmax(np.abs(values - e[field].to_numpy()))
        ),
        "scope": "retained normalized mouth inventory -> current source attachment, shortest paths and target connectors; raw HydroRIVERS topology and derived basin attributes not replayed",
    }
    (output / "network-replay.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--group",
        choices=[
            "habitats",
            "physical",
            "geometry",
            "support",
            "kelp_static",
            "rays",
            "network",
        ],
        required=True,
    )
    args = parser.parse_args()
    args.workspace = args.workspace.resolve()
    args.output = args.output.resolve()
    delivery = args.workspace / "Data"
    if args.output == delivery or delivery in args.output.parents:
        parser.error("Review output must be outside Data delivery")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["SEASCAPE_WORKSPACE"] = str(
        args.workspace
        / "Toolkits/toolkit-seascape/.seascape/work/source-closure-20261016/workspace"
    )
    globals()["run_" + args.group](args.workspace, args.output)


if __name__ == "__main__":
    main()
