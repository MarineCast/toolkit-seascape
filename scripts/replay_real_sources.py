"""Bounded acceptance of newly acquired public sources; never edits delivery."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from seascape.anthropogenic.sources import (
    _normalize_spatial_class,
    _normalize_wa_shorezone,
    normalize_anthropogenic_inventory,
)
from seascape.coastal_configuration.shoreline_characterization.build import (
    normalize_inventory,
)
from seascape.regional.contract import digest
from seascape.reviewed_delivery import restore_native


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source-cache", "support-root", "delivery", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument(
        "--historical-substrate-points",
        action="store_true",
        help="Use retained audited point coordinates; does not replay upstream support",
    )
    a = p.parse_args()
    a.output.mkdir(exist_ok=False, parents=True)
    out = a.output
    cache = a.source_cache
    support = {
        r: pq.read_table(
            a.support_root / "h3_geometry" / f"H3_MODEL_AREA_SUPPORT_RES_{r}.parquet"
        ).to_pandas()
        for r in (6, 8)
    }

    def selected(r):
        s = support[r]
        return s.loc[
            s.REPRESENTATIVE_POINT_LONGITUDE.between(-122.65, -122.35)
            & s.REPRESENTATIVE_POINT_LATITUDE.between(47.85, 48.05)
            & s.HAS_WATER_OVERLAP
            & ~s.IS_HIERARCHY_ONLY_PARENT
        ].sort_values("H3_INDEX")

    reports = {}
    for family, r in [
        ("shoreline", 6),
        ("shoreline", 8),
        ("anthropogenic", 6),
        ("anthropogenic", 8),
        ("estuary", 8),
        ("substrate", 6),
    ]:
        work = out / f"{family}-r{r}"
        work.mkdir()
        s = selected(r)
        s = s.iloc[np.linspace(0, len(s) - 1, min(40, len(s)), dtype=int)]
        delivered = restore_native(
            pq.read_table(a.delivery / f"{family}-r{r}-static.parquet")
        ).to_pandas()
        s = s.loc[s.H3_INDEX.isin(delivered.H3_INDEX)]
        keys = sorted(s.H3_INDEX)
        assert keys
        if family == "substrate" and a.historical_substrate_points:
            historical = delivered.set_index("H3_INDEX")
            for coordinate in (
                "REPRESENTATIVE_POINT_LONGITUDE",
                "REPRESENTATIVE_POINT_LATITUDE",
            ):
                s[coordinate] = historical.loc[
                    s.H3_INDEX, "SUBSTRATE_MODEL__" + coordinate
                ].to_numpy()
        reporting = work / "reporting.txt"
        reporting.write_text("\n".join(keys) + "\n")
        sp = work / "support.parquet"
        s.to_parquet(sp, index=False)
        inputs = {}

        def pin(
            name,
            path,
            rights="Retained MarineCast source support; see source manifest",
            coverage="bounded real-data sample",
        ):
            inputs[name] = dict(
                path=str(path.resolve()),
                sha256=digest(path),
                qualification=dict(
                    rights=rights,
                    spatial_support="native source; see source receipts and candidate method",
                    coverage_status=coverage,
                    observation_period=None,
                ),
            )

        pin("reporting", reporting)
        pin("support", sp)
        if family == "substrate" and a.historical_substrate_points:
            inputs["support"]["qualification"]["spatial_support"] = (
                "Historical audited sample coordinates; current overlap flags; upstream support not replayed"
            )
            pin(
                "historical_coordinate_source",
                a.delivery / "substrate-r6-static.parquet",
                coverage="Only historical coordinate columns consumed from restored native audit",
            )
        if family == "shoreline":
            inv = normalize_inventory(
                {
                    "wa_physical": (
                        cache
                        / "NOAA_SHORELINES_2018/SHSTMP_PS_Marine_Shorelines_2018.shp",
                        {"normalizer": "wa_physical", "observation_date": "2018"},
                    )
                }
            )
            ip = work / "inventory.parquet"
            inv.to_parquet(ip, index=False)
            pin(
                "inventory",
                ip,
                "NOAA NWFSC SHSTMP 2018; US Government public domain",
                "WA physical shoreline only; BC excluded",
            )
            pin(
                "raw_source",
                cache / "NOAA_SHORELINES_2018.zip",
                "NOAA NWFSC; US Government public domain",
            )
        elif family == "anthropogenic":
            fs = [
                _normalize_wa_shorezone(
                    cache / "WA_ARMORING_SMALL.geojson",
                    "wa_dnr_shoreline_modification",
                    {"evidence_class": "systematic_shoreline_mapping"},
                ),
                _normalize_spatial_class(
                    cache / "NOAA_DREDGED.geojson",
                    "noaa_coastal_maintained_channels",
                    {"evidence_class": "authoritative_navigation_mapping"},
                    "dredged_channel",
                ),
            ]
            inv = normalize_anthropogenic_inventory(
                gpd.GeoDataFrame(pd.concat(fs, ignore_index=True), crs=4326)
            )
            ip = work / "inventory.parquet"
            inv.to_parquet(ip, index=False)
            pin(
                "inventory",
                ip,
                "WA DNR agency open data; NOAA public domain",
                "DNR bounded full extract and NOAA bounded channels; other source families excluded",
            )
            pin(
                "water", a.support_root / "water_geometry/COASTAL_CONTEXT_WATER.parquet"
            )
            for n in ["WA_ARMORING_SMALL", "NOAA_DREDGED"]:
                pin(
                    "raw_" + n,
                    cache / (n + ".geojson"),
                    "WA DNR agency open data / NOAA public domain",
                )
        elif family == "estuary":
            inv = gpd.read_file(cache / "PMEP_ESTUARY.geojson")
            assert (
                inv.geometry.is_valid.all() and inv.geometry.geom_type.eq("Point").all()
            )
            xy = inv.to_crs(32610)
            ip = work / "inventory.parquet"
            pd.DataFrame(
                dict(
                    SOURCE_ID="PMEP:" + inv.PMEP_EstuaryID.astype(str),
                    X_M=xy.geometry.x,
                    Y_M=xy.geometry.y,
                )
            ).to_parquet(ip, index=False)
            pin(
                "inventory",
                ip,
                "Pacific Marine and Estuarine Fish Habitat Partnership public point inventory",
                "103 PMEP points in receipt bbox; BC excluded",
            )
            pin(
                "raw_source",
                cache / "PMEP_ESTUARY.geojson",
                "PMEP public point inventory",
            )
        else:
            for n in ("rock", "gravel", "sand", "mud"):
                pin(
                    n,
                    cache / f"DBSEABED_{n.upper()}_PERCENT.tif",
                    "dbSEABED/HUB Ocean ver202512 CC-BY-4.0",
                    "global 0.1 degree model; point support",
                )
            pin(
                "source_rights",
                cache / "HUB_SUBSTRATE_STAC.json",
                "HUB Ocean public metadata",
            )
        spec = dict(
            schema=1,
            operator=family,
            resolution=r,
            domain=dict(
                id="puget-sound-bounded-acceptance",
                revision="2026-10-29-new-source",
                support="native H3",
                coverage_status="bounded sample; no historical parity assumed",
            ),
            inputs=inputs,
            output=str((work / "candidate").resolve()),
            limits=dict(
                seconds=180,
                memory_bytes=1536 * 1024**2,
                staging_bytes=32 * 1024**2,
                batch_rows=16,
            ),
        )
        specpath = work / "spec.json"
        specpath.write_text(json.dumps(spec, indent=2) + "\n")
        for extra in [["--preflight"], []]:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "seascape",
                    "regional",
                    "--spec",
                    str(specpath),
                    *extra,
                ],
                capture_output=True,
                text=True,
            )
            (work / ("preflight.log" if extra else "run.log")).write_text(
                result.stdout + result.stderr
            )
            if result.returncode:
                raise RuntimeError(f"{family} failed: {result.stderr}")
        actual = (
            pq.read_table(work / "candidate/metrics.parquet")
            .to_pandas()
            .set_index("H3_INDEX")
            .sort_index()
        )
        expected = delivered.set_index("H3_INDEX").loc[actual.index]
        comparisons = {}
        for c in actual:
            matches = [e for e in expected if e == c or e.endswith("__" + c)]
            if family == "estuary" and c == "MINIMUM_DISTANCE_M":
                matches = [
                    "ESTUARY__DISTANCE_TO_QUALIFIED_NORMALIZED_MAPPED_ESTUARY_POINT_M"
                ]
            if len(matches) != 1:
                continue
            e = expected[matches[0]]
            v = actual[c]
            if not pd.api.types.is_numeric_dtype(v):
                continue
            ok = v.notna() & e.notna()
            delta = (v[ok].astype(float) - e[ok].astype(float)).abs()
            comparisons[c] = dict(
                delivered_field=matches[0],
                both_present=int(ok.sum()),
                candidate_nulls=int(v.isna().sum()),
                delivered_nulls=int(e.isna().sum()),
                null_mismatches=int((v.isna() != e.isna()).sum()),
                max_abs_error=float(delta.max()) if len(delta) else None,
                values_different=int(
                    (
                        ~np.isclose(
                            v[ok].astype(float),
                            e[ok].astype(float),
                            rtol=1e-9,
                            atol=1e-6,
                        )
                    ).sum()
                ),
            )
        report = dict(
            status="real_source_to_candidate_completed",
            rows=len(actual),
            source_vintage="new download; historical identity unproven",
            comparisons=comparisons,
            spec=str(specpath.resolve()),
        )
        reports[f"{family}-r{r}"] = report
        (out / "comparisons.json").write_text(json.dumps(reports, indent=2) + "\n")
        print(family, r, len(actual), "comparisons", len(comparisons), flush=True)


if __name__ == "__main__":
    main()
