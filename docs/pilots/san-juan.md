# Bounded San Juan pilot — execution blocked

SS-10 preparation, September 27, 2026. This is a checked configuration and blocked runbook,
not a reproduced real-data run or a measured operating envelope. No source acquisition,
producer, publication, release audit or regional visual QA was performed for this task.
It uses the existing [San Juan explorer](../../notebooks/01_DATA_EXPLORER.ipynb) and
[preparation helper](../../notebooks/_san_juan_workflow.py); do not execute the whole explorer
for preparation: its acquisition and processing switches default to enabled.

## Scope and stop conditions

Nominal W/S/E/N extent: **(-123.35, 48.38, -122.70, 49.02)**. Products would be H3 R8 and R6
bathymetry and supporting water geometry/network. Reuse the production APIs and scientific
settings, including positive-down depth, quantiles, water-neighborhood anomaly and parent
band aggregation. No new geomorphology, habitat inference, regional expansion or comparison
with a different source release is proposed. See the [family guide](../../src/seascape/seafloor_physiography/README.md)
and [scientific contracts](../CONTRACTS.md).

Future GEBCO metadata was corrected by FIX-01: source and attribution now use the official
public-domain terms and acknowledgement context. Historical manifests still retain CC BY 4.0;
their bytes/checksums were not rewritten. This removes the future-producer rights-label blocker,
not the need to validate source identity and rights for an actual pilot. No pilot has run.

Two execution gates remain open:

1. The standard bathymetry plan requires canonical multi-source water geometry. Those inputs
   are missing in the fresh pilot workspace. Natural Earth is an **exploratory land-mask proxy**,
   not canonical territorial waters or a navigation/legal boundary. A future exploratory
   recipe must retain that label in support and provenance and explicitly validate its reuse;
   it must not bypass the canonical planner's input/reuse checks to obtain a ready report.
2. `bathymetry.run_pipeline(skip_download=True, skip_map=True)` still performs transactional
   family publication. It has no publication-off option. [SS-10 step 5](../roadmap/SEASCAPE_CODEX_ROADMAP.md#ss-10-prepare-a-bounded-real-data-pilot-and-measured-operating-envelope)
   requires an approved disposable workspace and explicit publication scope for this path.
   That approval is pending. Proposed scope is only new exploratory support/network and R6/R8
   bathymetry artifacts and family manifests in two new disposable workspaces; no whole-release
   promotion, retained release replacement, export, upload or redistribution.

Local cached inputs are available; new download permission is **not** needed to read them.
The proposed future limits are zero acquisition/network bytes, at most 32 MiB of reused inputs,
256 MiB total workspace storage per replicate, two runs capped at 10 minutes and 2 GiB peak
memory each, and at most four workers. These are planning limits, **not approved or measured
capacity**. Before execution, arrange monitored termination/resource enforcement and approve
the exact fresh paths and local publication scope. Existing downloaders do not enforce response
or extracted-byte caps: GEBCO queues a crop then streams/unzips it; Natural Earth fetches a
global archive regardless of the AOI. Timeouts alone do not bound total disk/runtime/memory.
Any live-source alternative needs separate source/release/bounds/workspace/resource approval;
do not fall back to a global download when local data is absent or fails identity checks.

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
no producer command is authorized by this recipe. The existing Python guard denies outbound
calls/children; its forbidden path is a probe, not checkout isolation, because preparation and
inspection deliberately read this checkout/cache. Native extensions are not OS-firewalled.
Store the interpreter, code commit, exact argv/exits and stderr with the reports. The resolved
hash includes absolute paths and therefore changes across fresh workspaces; archive the resolved
configuration and per-file fingerprints rather than expecting the historical hash to match.

## Acceptance after the gates are resolved

Create two independent owned workspaces, pin the same source identities and resolved scientific
settings, and use existing production support and bathymetry builders/publication validators.
Label the exploratory mask, reject conflicting H3 keys/joins and empty or unexpectedly all-null
products, and validate nonempty R6/R8 support, sign/meters, CRS/datum/alignment, nodata preservation,
valid-water counts/coverage, null versus zero, finite numeric values, parent band recomputation,
neighborhood support, QC and source/upstream/product hashes. Inspect source/attribution and
support identities in the generated manifests; do not call a family manifest a whole release audit.

Time each producer phase with macOS `/usr/bin/time -l` (Linux `/usr/bin/time -v`), retaining stderr
and exit codes. Record wall time, before/after file bytes and peak RSS with platform units.
Those tools' child accounting does **not** establish aggregate simultaneous worker peak RSS;
report that excluded measurement unless a process-tree sampler supplies it. Apply the approved
resource cap independently. Compare two runs' keys and numerical values with justified tolerances,
excluding timestamps/path identities, before claiming repeatability. No regional scaling promises.

Render offline maps and actually inspect extent/orientation, elevation/depth sign and legend,
coastline alignment, unavailable versus zero display and artifacts. Record visual inspection
separately from file generation; opening a tile/CDN-backed HTML map would exceed zero-network
scope. Preserve sources outside tracked examples and preserve all old datasets/releases.

Current measurements: cached input storage only. Processing time, output storage, peak memory,
repeatability, source pixel/coverage validation and map generation/inspection are **not_run**.
The [progress record](../roadmap/PROGRESS.md) supplies executed commands, evidence paths,
environment and exact code identity. SS-10's blocked-runbook alternative is prepared; the
real-data gate remains unsatisfied. SS-11 may only proceed with that limitation explicit.
