# Bounded San Juan exploratory pilot — passed

PILOT-01 / SS-10, September 27, 2026. Two fresh local realizations of the approved cached-input
bathymetry/support path passed numerical, provenance, resource and visual acceptance. This is
an exploratory family pilot, not a complete audited regional release or model-readiness claim.
It reuses the existing [explorer helper](../../notebooks/_san_juan_workflow.py) and production APIs.
Do not execute the whole explorer to reproduce this zero-download run: its acquisition switches
still default to enabled. [Progress](../roadmap/PROGRESS.md) retains failed/intermediate checks.

## Approved scope and stop conditions

Nominal W/S/E/N extent **(-123.35, 48.38, -122.70, 49.02)**; H3 R8/R6. Same production quantiles,
positive-down depths, water-neighborhood anomaly and parent band aggregation. Natural Earth land
is an **exploratory 1:10 million cartographic mask**, not territorial/navigation/legal authority.
Its schema-3 mask manifest records actual source version/checksum, partial completeness and
model-ineligible lineage, propagated through the H3/network/bathymetry family manifests.
Future GEBCO metadata uses corrected public-domain terms/acknowledgement; old manifests are intact.

The user approved the exact prepared plan with “Let's do it”: fresh disposable workspaces
`/private/tmp/seascape-pilot-01-20260927/replicate-1` and `replicate-2`; only exploratory
mask/H3/network/R6+R8 bathymetry family publication. `skip_download=True, skip_map=True` still
publishes the family. No whole-release promotion, retained release replacement, source acquisition,
export/upload, new source release, regional expansion or additional product family was authorized.
Two runs were capped at 600 s each, 32 MiB inputs including extraction, 256 MiB owned workspace,
2 GiB sampled aggregate process-tree RSS and four workers. Original plan/approval hashes,
source pins, existing-API phase recipe and watchdog are retained in
`/private/tmp/seascape-pilot-01-readiness`; approved paths now contain actual products and must not
be reused as fresh destinations. Any future realization needs a separately agreed fresh path/scope.

The outer watchdog samples wall/disk/process-tree RSS every 0.25 s and kills the process group on
breach or sampler failure; polling can miss peaks/overshoot and is not an OS memory reservation.
Python socket/child guard and `PROJ_NETWORK=OFF` prevent intended source acquisition paths; native
extensions are not OS-firewalled and network bytes were not metered. No source downloads occurred.
Do not fall back to global download if these cached identities are absent or fail verification.
Canonical preflight still fails on six missing water inputs; the validated exploratory route does
not make that canonical plan READY. See [scientific contracts](../CONTRACTS.md).

## Source and historical evidence

These identities describe the available local cache, not files distributed with the package.
The paths below are relative to the explorer's ignored `notebooks/outputs` workspace.

| Input | Identity and support | Size and identity check |
| --- | --- | --- |
| `data/raw/bathymetry/GEBCO_2026_MODEL_AREA.tif` | GEBCO 2026, DOI `10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa`, created 2026-04-17; 15 arc seconds, 156 × 154, one int16 band | 55,932 bytes; production `checksum_path`: `1d99f5e6a7553679446cf88e8b2685dba32ccff3349165d72afa682c6605257c` |
| `data/raw/natural_earth/ne_10m_land.zip` | Natural Earth land, extracted version 5.1.1; **1:10 million cartographic scale**, not 10-meter resolution | 3,269,070 bytes; plain file SHA-256: `e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc` |

The GeoTIFF header reports EPSG:4326, meters, positive-up elevation relative to sea level,
vertical CRS EPSG:5831 and nodata -32767. Preserve its native alignment: actual W/S/E/N bounds
are (-123.35, 48.37916666666665, -122.70, 49.020833333333336), slightly beyond the nominal crop.
The [GEBCO 2026 reference](https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2026-grid)
matches the embedded DOI; grid spacing is not measurement resolution or accuracy. The header
does not establish uniform survey coverage or independently verify vertical datum accuracy.
The [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/) describe public-domain
data. Preserve provider acknowledgement and never imply provider endorsement or navigation safety.

Read-only inventory found 46 cached files / 22,717,798 bytes. All seven references in the historical
bathymetry family manifest matched production `checksum_path` (source, four upstream artifacts,
two products). It records 4,660 R8 and 134 R6 cells and resolved-config hash
`d77976293e6f4f76bd4f7374c8d04e8f420f9f7b17b81a1339d52bfecc2fd8ac`.
These are historical metadata/identity checks, not a fresh execution, full release audit or
numerical/visual acceptance. In particular, the manifest retains the incorrect rights label.
Production artifact checksums are not interchangeable with plain file SHA-256.

## Reproduce configuration-only preparation and preflight

Use this checkout and an existing isolated development interpreter with runtime dependencies.
No pytest/Jupyter is needed for these commands. This research helper is checkout-based; the
[installed-wheel offline demo](../demo.md) remains the portable no-checkout first-result path.
Run from the repository root. The fresh temporary directory owns **only copied configurations
and inspection reports**. It must not be the old explorer workspace, canonical data or a retained
release directory. The cached raster is read in place; nothing is downloaded or copied from it.

```sh
export SEASCAPE_PILOT_ROOT="$(mktemp -d /tmp/seascape-san-juan-preflight.XXXXXX)"
python - <<'PY'
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

root = Path.cwd().resolve()
workspace = Path(os.environ["SEASCAPE_PILOT_ROOT"]).resolve()
assert workspace.is_dir() and not any(workspace.iterdir()), "Use a fresh empty workspace"
for key in ("SEASCAPE_COMMON_CONFIG", "SEASCAPE_CANDIDATE_ROOT"):
    os.environ.pop(key, None)
sys.path.insert(0, str(root / "notebooks"))
from _san_juan_workflow import prepare_workspace
from seascape.core.artifacts.checksums import checksum_path
from seascape.seafloor_physiography.bathymetry import load_bathymetry_config
from seascape.utils.config import stable_config_hash

prepare_workspace(root, workspace, (-123.35, 48.38, -122.70, 49.02), (6, 8), force_downloads=False)
domain_path = workspace / "config/data/environment_seascape.yaml"
domain = yaml.safe_load(domain_path.read_text())
raw_dir = root / "notebooks/outputs/data/raw/bathymetry"
domain["bathymetry"]["source"]["raw_dir"] = str(raw_dir)
domain_path.write_text(yaml.safe_dump(domain, sort_keys=False))
config = load_bathymetry_config(workspace / "config/data/project.yaml")
assert config.bbox == {"min_lon": -123.35, "min_lat": 48.38, "max_lon": -122.70, "max_lat": 49.02}
assert all(domain[s]["resolutions"] == [6, 8] and domain[s]["max_workers"] == 4
           for s in ("h3_geometry", "water_network"))
assert config.h3_resolution == 8 and [e.h3_resolution for e in config.additional_exports] == [6]
assert not config.overwrite and config.bathymetry_sign == "positive_down"
assert config.processed_path.is_relative_to(workspace)
assert all(e.processed_path.is_relative_to(workspace) for e in config.additional_exports)
assert config.raw_path == raw_dir / "GEBCO_2026_MODEL_AREA.tif"
assert checksum_path(config.raw_path) == "1d99f5e6a7553679446cf88e8b2685dba32ccff3349165d72afa682c6605257c"
record = {"status": "CONFIGURATION_ONLY", "resolved_config": asdict(config),
          "resolved_config_hash": stable_config_hash(asdict(config))}
(workspace / "configuration-inspection.json").write_text(json.dumps(record, default=str, indent=2))
print(record["resolved_config_hash"])
PY
env -u SEASCAPE_COMMON_CONFIG -u SEASCAPE_CANDIDATE_ROOT \
  python scripts/consumer_guard.py --forbid-root "$SEASCAPE_PILOT_ROOT/forbidden" \
  --module seascape -- --workspace "$SEASCAPE_PILOT_ROOT" build \
  --only seascape-bathymetry --dry-run --check-inputs --json \
  --candidate-root "$SEASCAPE_PILOT_ROOT/candidate" \
  > "$SEASCAPE_PILOT_ROOT/preflight.json" 2> "$SEASCAPE_PILOT_ROOT/preflight.stderr"
```

The final command is expected to return **1** with valid JSON `status: failed`: six canonical
water inputs are `missing_external` (Canadian regions, WSDOT shorelines, Washington marine
shoreline type, US coastline, territorial zones and US waters). Intermediates are
`generated_by_plan`; resume/publication checks are `not_applicable`, not validated. The cached
raster's path/header check is ready. It is not a failed scientific calculation or a ready build. Stop here;
this configuration-only recipe authorizes no producer command by itself; the executed pilot used
the separately approved scope below. The existing Python guard denies outbound
calls/children; its forbidden path is a probe, not checkout isolation, because preparation and
inspection deliberately read this checkout/cache. Native extensions are not OS-firewalled.
Store the interpreter, code commit, exact argv/exits and stderr with the reports. The resolved
hash includes absolute paths and therefore changes across fresh workspaces; archive the resolved
configuration and per-file fingerprints rather than expecting the historical hash to match.

## Acceptance and measured envelope

Execution HEAD `5d9faaf83aaccffe61a7eb97acd27c01ec6c62a7`; production installed wheel matches
all 190 package files at tested `232ac308f7f2229c2f4047ab9fe204d95b8a6bf9` exactly. CPython 3.14.6,
macOS 26.6.2 ARM64, GDAL 3.12.4 / PROJ 9.8.1 / GEOS 3.13.1. The research helper reads this
checkout's config; this is not a no-checkout pilot claim. The installed-wheel demo remains portable.

Each run: 4,660 R8 cells, 4,384 mean values / 276 nulls, means 1–354 m; 134 R6 cells, 127 values /
7 nulls, means 1.7647058824–243.4271844660 m. Source: 24,024 valid pixels, 18,478 negative,
5,515 positive, 31 zero, zero nodata. Selected support receives 18,226 marine samples; this is not
an independent survey-coverage measurement. Source bytes/header, native affine, EPSG:4326,
source EPSG:5831, meters/sign and nodata -32767 are preserved. This crop exercises no nodata
pixels; software nodata-only fixtures remain separate evidence. Existing consumers validate
support, edges, neighborhoods, radius operator and reachable area; all four family manifests
verify sources/upstream/product bytes. QC retained, including low water support, hierarchy-only
parents and a land-crossing connector. Null QC labels remain JSON null, never zero.

All 23 Parquet tables and the radius operator match exactly by H3 keys, including geometry,
values and nulls; scientific configs match after workspace-path normalization. Of 24 product
records, 22 raw checksums match. Existing threaded `H3_GRIDS_6/8` output row order varies; sorted
Arrow values including original geometry WKB and schema metadata match exactly. Their distinct
raw hashes/sizes stay separately recorded/verified. Run/time/absolute-path/config-hash identities
also differ and are retained. No scientific value is normalized to hide a discrepancy.

R6 means/quantiles are direct raster samples; parent composition counts/fractions are recomputed
from R8 child counts. At cell `8628d1047ffffff`, direct mean is null but parent composition has
one sample. Production assignment helpers show that the R8 child `8828d10425fffff` belongs to
that hierarchical parent while the same pixel is assigned directly to R6 `8628d1057ffffff`.
Retain this support distinction; never infer mean availability from the parent count. Parent
recomputation is exact; available depth-band fractions sum to 1 within absolute 1e-12.

| Realization | Producer phases incl. preparation | Completion elapsed | Sampled peak aggregate RSS | Final workspace |
| --- | --- | --- | --- | --- |
| 1 | 13.3264 s | 115.5035 s incl. evidence-script correction; initial attempt 16.0276 s, acceptance-only retry 2.6996 s | 446,021,632 bytes | 17,387,048 bytes |
| 2 | 10.8242 s | 13.5285 s | 444,366,848 bytes | 17,387,323 bytes |

Each phase retains `/usr/bin/time -l` wall/maximum RSS (macOS bytes) in stderr; sampled process-tree
RSS includes concurrent descendants. No cap termination. Shared machine/filesystem caches and
sampling limits preclude independent-machine stability or regional scaling promises. First producer
phases all exited 0; initial acceptance exited 1 only on pandas-NA JSON serialization. Corrected
reporting-only retry exited 0 under the original deadline; initial logs/products preserved.
Comparison/reporting development failures and the R6 availability assumption are recorded in progress.

Actually opened and inspected all six offline source/R8/R6 PNGs: north-up extent, source positive-up
versus positive-down output, units/legend, coarse coastal alignment and gray unavailable support.
Channels/islands are consistent between runs; coastline generalization against the raster is visible.
No source vertical accuracy, survey completeness, navigation/legal/model validity or tile-backed
browser-render claim. Figures remain in each workspace's `acceptance/`; no datasets/images uploaded.

Exact phase argv/exits and source/config/artifact hashes are under the evidence root in
`execution-summary.json`, `commands.json`, `replicate-*-resources*.json`, `repeatability.json`,
`additional-acceptance.json`, `parent-availability-evidence.json`, `visual-inspection.json` and
`HANDOFF_EXECUTION.md`. The original 46 cached files / 22,717,798 bytes are byte-identical.
[Hosted run 36352109541](https://github.com/MarineCast/toolkit-seascape/actions/runs/36352109541)
passed all nine jobs for execution HEAD. Stop after this task: ACCEPT-01 still requires the
unavailable unfamiliar-human trial and owner decisions; no release action is implied.
