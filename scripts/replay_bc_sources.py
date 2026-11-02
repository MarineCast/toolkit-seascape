"""Bounded real BC provider cases, independent of publication."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely

from seascape.anthropogenic.presentation import (
    PRESENCE_LABELS,
    anthropogenic_presentation,
)
from seascape.anthropogenic.sources import (
    _normalize_aquaculture_csv,
    _normalize_bc_shorezone,
    _normalize_spatial_class,
    normalize_anthropogenic_inventory,
)
from seascape.coastal_configuration.shoreline_characterization.build import (
    normalize_inventory,
)
from seascape.regional.contract import digest
from seascape.regional.geometry import cells
from seascape.reviewed_delivery import restore_native

parser = argparse.ArgumentParser(description=__doc__)
for name in ("source-cache", "support-root", "delivery", "output"):
    parser.add_argument("--" + name, type=Path, required=True)
args = parser.parse_args()
cache = args.source_cache
base = args.support_root
delivery = args.delivery
out = args.output
out.mkdir(parents=True, exist_ok=False)
reports = {}


def pin(path, rights, coverage):
    return dict(
        path=str(path.resolve()),
        sha256=digest(path),
        qualification=dict(
            rights=rights,
            coverage_status=coverage,
            spatial_support="Native source geometry; source-relative mapped evidence",
            observation_period=None,
        ),
    )


shore = normalize_inventory(
    {
        "bc_shorezone_shore_units": (
            cache / "BC_SHOREZONE_COMPLETE.geojson",
            {"normalizer": "bc_shorezone"},
        )
    }
)
shorepath = out / "bc-physical-inventory.parquet"
shore.to_parquet(shorepath, index=False)
aq = _normalize_aquaculture_csv(
    cache / "BC_DFO_SHELLFISH_LICENCES.csv",
    "bc_dfo_shellfish_licences",
    {"evidence_class": "authoritative_inventory"},
)
bc = _normalize_bc_shorezone(
    cache / "BC_SHOREZONE_COMPLETE.geojson",
    "bc_shorezone_shore_units",
    {"evidence_class": "systematic_shoreline_mapping"},
)
disposal = _normalize_spatial_class(
    cache / "CA_DISPOSAL_SMALL.geojson",
    "ca_active_disposal_sites",
    {"evidence_class": "authoritative_inventory"},
    "disposal_site",
)
inventory = normalize_anthropogenic_inventory(
    gpd.GeoDataFrame(
        pd.concat([aq, bc, disposal], ignore_index=True), geometry="geometry", crs=4326
    )
)
invpath = out / "bc-combined-inventory.parquet"
inventory.to_parquet(invpath, index=False)
for family, res in [("shoreline", 8), ("anthropogenic", 6), ("anthropogenic", 8)]:
    d = (
        restore_native(pq.read_table(delivery / f"{family}-r{res}-static.parquet"))
        .to_pandas()
        .set_index("H3_INDEX")
    )
    support = (
        pq.read_table(base / "h3_geometry" / f"H3_MODEL_AREA_SUPPORT_RES_{res}.parquet")
        .to_pandas()
        .set_index("H3_INDEX")
    )
    eligible = set(d.index) & set(
        support.loc[support.HAS_WATER_OVERLAP & ~support.IS_HIERARCHY_ONLY_PARENT].index
    )
    if family == "shoreline":
        possible = sorted(
            {
                h3.latlng_to_cell(
                    g.representative_point().y, g.representative_point().x, res
                )
                for g in shore.geometry
            }
            & eligible
        )
        geo = cells(possible)
        inside = geo.geometry.within(shapely.box(-123.42, 48.62, -123.35, 48.68))
        keys = geo.loc[inside, "H3_INDEX"].tolist()[:20]
        ip = shorepath
    else:
        keys = set()
        for frame in (aq, disposal):
            selected = sorted(
                {
                    h3.latlng_to_cell(
                        g.representative_point().y, g.representative_point().x, res
                    )
                    for g in frame.geometry
                }
                & eligible
            )
            keys.update(selected[:12])
        keys = sorted(keys)
        ip = invpath
    assert keys
    work = out / f"bc-{family}-r{res}"
    work.mkdir()
    reporting = work / "reporting.txt"
    reporting.write_text("\n".join(keys) + "\n")
    sp = work / "support.parquet"
    support.loc[keys].reset_index().to_parquet(sp, index=False)
    inputs = {
        "reporting": pin(reporting, "MarineCast support", "bounded reporting sample"),
        "support": pin(sp, "MarineCast support", "current retained support"),
        "inventory": pin(
            ip,
            "Open Government Licence BC / Canada",
            "bounded source inventories; no global absence",
        ),
    }
    for n in ["BC_SHOREZONE_COMPLETE.geojson"] + (
        ["BC_DFO_SHELLFISH_LICENCES.csv", "CA_DISPOSAL_SMALL.geojson"]
        if family == "anthropogenic"
        else []
    ):
        inputs["raw_" + n] = pin(
            cache / n,
            "Open Government Licence BC / Canada",
            "provider record extent; see receipt",
        )
    if family == "anthropogenic":
        inputs["water"] = pin(
            base / "water_geometry/COASTAL_CONTEXT_WATER.parquet",
            "MarineCast qualified water context",
            "current support vintage",
        )
    spec = dict(
        schema=1,
        operator=family,
        resolution=res,
        domain=dict(
            id="bounded-bc-positive-source-acceptance",
            revision="2026-10-29",
            support="native H3",
            coverage_status="source-relative not complete",
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
    spc = work / "spec.json"
    spc.write_text(json.dumps(spec, indent=2) + "\n")
    r = subprocess.run(
        [sys.executable, "-m", "seascape", "regional", "--spec", str(spc)],
        capture_output=True,
        text=True,
    )
    (work / "run.log").write_text(r.stdout + r.stderr)
    assert r.returncode == 0, r.stderr
    x = (
        pq.read_table(work / "candidate/metrics.parquet")
        .to_pandas()
        .set_index("H3_INDEX")
    )
    comparisons = {}
    for c in x:
        matches = [v for v in d if v == c or v.endswith("__" + c)]
        if len(matches) != 1 or not pd.api.types.is_numeric_dtype(x[c]):
            continue
        e = d.loc[keys, matches[0]]
        v = x.loc[keys, c]
        ok = e.notna() & v.notna()
        diff = (e[ok].astype(float) - v[ok].astype(float)).abs()
        comparisons[c] = dict(
            null_mismatches=int((v.isna() != e.isna()).sum()),
            values_different=int(
                (
                    ~np.isclose(
                        e[ok].astype(float), v[ok].astype(float), rtol=1e-9, atol=1e-6
                    )
                ).sum()
            ),
            max_abs_error=float(diff.max()) if len(diff) else None,
        )
    positive = {}
    if family == "anthropogenic":
        positive = {
            "aquaculture_cells": int(
                x.AQUACULTURE_MAPPED_POSITIVE_EVIDENCE.eq(True).sum()
            ),
            "disposal_cells": int(x.DISPOSAL_SITE_MAPPED_AREA_M2.gt(0).sum()),
        }
        assert min(positive.values()) > 0
        geom = cells(keys).to_crs(6933)
        aa = aq.to_crs(6933)
        dd = disposal.to_crs(6933)
        water = gpd.read_parquet(
            base / "water_geometry/COASTAL_CONTEXT_WATER.parquet"
        ).to_crs(6933)
        wg = water.geometry.to_numpy()
        tree = shapely.STRtree(wg)
        errors = []
        for k, g in zip(keys, geom.geometry, strict=True):
            assert (True if aa.intersects(g).any() else None) == (
                None
                if pd.isna(x.loc[k, "AQUACULTURE_MAPPED_POSITIVE_EVIDENCE"])
                else bool(x.loc[k, "AQUACULTURE_MAPPED_POSITIVE_EVIDENCE"])
            )
            wet = shapely.union_all(
                [z.intersection(g) for z in wg[tree.query(g, predicate="intersects")]]
            )
            area = shapely.union_all(
                [
                    z.intersection(g).intersection(wet)
                    for z in dd.loc[dd.intersects(g)].geometry
                ]
            ).area
            errors.append(abs(area - x.loc[k, "DISPOSAL_SITE_MAPPED_AREA_M2"]))
        assert max(errors) < 1e-4
        positive["independent_disposal_max_abs_error_m2"] = max(errors)
        positive["independent_aquaculture_intersections_agree"] = True
    public = {}
    if family == "anthropogenic":
        presented = anthropogenic_presentation(
            pq.read_table(work / "candidate/metrics.parquet")
        )
        pq.write_table(presented, work / "public-presentation-candidate.parquet")
        pf = presented.to_pandas().set_index("H3_INDEX")
        for field in PRESENCE_LABELS:
            public[field] = dict(
                rows=len(keys),
                matching=int(
                    pf.loc[keys, field].eq(d.loc[keys, "ANTHROPOGENIC__" + field]).sum()
                ),
                candidate_positive=int(pf[field].sum()),
                source_unknown=int(pf[field + "_SOURCE_NULLABLE"].isna().sum()),
            )
    reports[f"{family}-r{res}"] = dict(
        rows=len(keys),
        positive_cases=positive,
        comparisons=comparisons,
        public_presence_comparisons=public,
        status="new-source candidate validated; historical differences retained",
    )
    (out / "bc-comparisons.json").write_text(json.dumps(reports, indent=2) + "\n")
    print(family, res, reports[f"{family}-r{res}"], flush=True)
