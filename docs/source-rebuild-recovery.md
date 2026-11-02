# Source download, memory and reporting-grid recovery — 2026-11-01

This records the earlier source/API recovery. The subsequent
[complete single-command metrics CLI run](metric-rebuild.md)
rebuilds every required stage from scientific source inputs and verifies all 29 tables.

This continues the [full-area rebuild](full-rebuild-verification.md) in
`/private/tmp/seascape-source-rebuild-20261101-sxpkewkc`. Existing delivery is an
immutable comparison target. Source caches remain in the owning toolkit cache;
no candidate is published to `Data/Seascape`.

## Source acquisition

The Overpass probe received an upstream queue-capacity error and repeated read
timeouts, including for a small query. Increasing the regional timeout did not
resolve provider availability. The default Anthropogenic source now uses the
[Geofabrik regional extracts](https://download.geofabrik.de/north-america/canada/british-columbia.html)
for BC, Washington and Oregon instead. This run fetched 1,869,139,672 bytes,
verified provider MD5 identities and retained independent SHA256 checksums.

Install native `osmium-tool` on `PATH` before regional acquisition. The package's
Python dependencies include `ijson` and explicit `pyogrio`; install the updated
package normally to obtain them. The optional native tool is not needed for the
synthetic demo, output readers or cached raw-JSON normalization.

`anthropogenic_seascape.download.sources.osm_cross_border_anthropogenic` now has
`kind: osm_pbf`, `extracts`, `tag_filters`, `supported_bbox` and `geometry_mode: center`.
An extract can specify `url`/`md5_url` or an explicit local `path`/`sha256`.
Remote files are stored under MD5-bound names in the configured extract cache;
cached selected JSON retains its original snapshot receipt and retrieval time.
Changing extraction settings requires a new matching receipt or explicit refresh.
A region outside `supported_bbox` fails until suitable extracts are configured.

[Osmium tag filtering](https://docs.osmcode.org/osmium/latest/osmium-tags-filter.html)
retains referenced nodes and relation members. Unselected reference objects lose
their tags so they cannot become spurious source features. The parser resolves
complete object bounds, retains node locations, and emits way/relation bounding-box
centers. It handles site relations as well as polygons. Bounds must intersect the
source extent; this selection is recorded explicitly. Missing references and cycles
fail acquisition. Center records establish locations, never polygon footprints or
complete survey coverage. OSM retains its ODbL attribution and limitations.

The acquisition enforces a 20 GiB disk reserve, 2 GiB per remote source by default,
a processing timeout, referenced-node/tagged-object budgets and a selected-JSON
byte budget. The real three-extract filter completed in 15.3 seconds at 2.17 GiB
peak sampled process-tree RSS after downloading the PBFs. Overpass remains an
optional configured source kind; runtime-error responses containing partial
`elements` now retry the next endpoint rather than publishing an incomplete result.

## Freshwater memory

The original producer materialized whole vector inputs and a second full normalized
river-system DataFrame. The corrected reader streams GeoJSON, WKB GeoParquet and
GDAL Arrow batches, transforms and clips each batch, and preserves nullable integer
identities. It keeps only qualified NHD/HydroRIVERS terminal candidates for mouth
construction. BC route candidates remain available for global downstream-route
selection; source terminal-QC counts include all selected U.S. raw features.
A nonempty source with no qualified terminals is available with unknown/no qualified
terminal evidence, rather than incorrectly classified as an empty raw source.

The complete river-system inventory is independently streamed to GeoParquet,
including nonterminal segments. Stable segment IDs use global per-source part
ordinals across batches. Metadata contains the full written bounding box. This
internal source inventory uses source order, rather than a global lexicographic ID
sort; part ordinals can differ from older whole-frame spatial-index clipping.
Public H3 products retain their sorted unique keys. It is not truncated to
mouth candidates.

The final full regional run completed in 346.2 seconds with 2.14 GiB peak sampled RSS,
under the 3 GiB supervisor guard. It produced 17,977 mapped mouths, 430 measured
mapped widths, 1,133,827 river segments and 81,380 native R8 feature rows. Configured
default widths remain estimated. These mixed-source mapped mouths are neither
physical discharge nor a complete census, and their count is not historical value
parity with the previously retained mouth inventory.

## Why thirteen files differed

The earlier replay applied the current coastal/native or canonical parent grid to
products with different historical reporting memberships. All differences below
are exact key-set differences, not duplicates. Kelp annual files retain all 35
historical year labels; their row loss is the cell loss multiplied by 35.

| File | Existing rows | Earlier replay rows | Missing / added native cells |
| --- | ---: | ---: | ---: |
| anthropogenic-r6-static | 2,621 | 2,445 | 192 / 16 |
| anthropogenic-r8-static | 88,243 | 81,380 | 7,363 / 500 |
| bivalve-r6-static | 2,621 | 2,427 | 201 / 7 |
| bivalve-r8-static | 88,243 | 81,380 | 7,363 / 500 |
| estuary-r8-static | 88,243 | 81,380 | 7,363 / 500 |
| kelp-r6-static | 2,628 | 2,427 | 201 / 0 |
| kelp-r6-dynamic | 91,980 | 84,945 | 201 / 0 |
| kelp-r8-static | 88,743 | 81,380 | 7,363 / 0 |
| kelp-r8-dynamic | 3,106,005 | 2,848,300 | 7,363 / 0 |
| seagrass-r6-static | 2,448 | 2,427 | 21 / 0 |
| shoreline-r6-static | 2,621 | 2,445 | 192 / 16 |
| shoreline-r8-static | 88,243 | 81,380 | 7,363 / 500 |
| substrate-r6-static | 2,621 | 2,445 | 192 / 16 |

At R6, the historical core grid has 2,621 cells, independent native coastal grid
2,427, and structural parent grid 2,445. The latter and native grid differ by
21 parent-only and three native-only cells. At R8 the historical core has 88,243
cells and the current coastal/structural grid 81,380. All 7,363 historical-only R8
cells have no intersection with the current reporting mask; 500 coastal cells
were absent from that older grid. The investigation does not infer that the older
source geometries were wrong or approve discarding their evidence.

Existing Kelp membership is exactly the union of the historical core and current
native coastal grid at each resolution. Seagrass membership is exactly the union
of the structural parent and independent native grid. Those policies are explicit
in their embedded source context. The earlier uniform-grid replay omitted known
positive evidence: 288 R8 Bivalve cells, 147 R8 all-time Kelp cells, 236 R8 Kelp
cell-years, and one R6 Seagrass cell, among others. These are material scope changes.

The continuation therefore uses the existing habitat identity grids as explicit
reporting inputs, reconstructs full native H3 polygons, and calculates values from
source inventories. No delivered metric values are computation inputs. It also
re-normalizes the later six raw BC CRIMS pages, adding 8,746 geometries absent from
the older Kelp inventory: 52,096 source records in total. Raw checksums, geometry
repair decisions and undated-source qualifications remain attached. Core historical
versus current study membership remains an explicit comparison, not automatic
publication or fabricated values to force equal counts.

## Evidence and limits

`manifest.json`, `evidence/row-count-investigation.json`, source receipts and
bounded stage logs are retained in the temporary task root. The continuation
references previously completed, checksum-bound source-derived producer stages
from the same rebuild, rather than rerunning unrelated work. Retained normalized
Seagrass/Bivalve and mapped-substrate source inventories remain source inputs;
this is not a new download of every historical provider file or a clean one-command
CLI run. Default legacy path configuration is separate from these explicit regional
producer configurations. Source availability and schema acceptance do not establish
scientific completeness, current ecological condition or modeling readiness.

## Final candidate verification

The continued candidate is complete: **29 Parquets across 17 families**, plus the
single `catalog.json`, at
`/private/tmp/seascape-source-rebuild-20261101-sxpkewkc/workspace/Data/Seascape`.
Independent complete row readback passes exact existing metric names/column order
after diagnostic removal, valid native H3 identity, sorted unique H3/date grain,
finite-or-null measurements and embedded projection provenance. There are no extra
files, coverage or quality columns. All 30 original delivery-file checksums,
including the catalog, remain unchanged.

Seven of the thirteen row-count differences are resolved by the explicit habitat
reporting inputs. All eight habitat tables now have exactly the existing H3/date
keys; every previously positive amount matches exactly and no positive row is lost.
The static positive-cell counts are 523/2,869 for Bivalve, 519/4,102 for Kelp and
424/3,572 for Seagrass at R6/R8. Kelp retains 1,983/15,649 positive cell-years.
The producer represents unknown positive extent as null, where the older compact
static encoding used zero for no positive evidence. This is not a claim of exact
zero/null encoding parity or evidence of surveyed absence. Floating-point totals
can differ by accumulation roundoff even when individual positive amounts agree.

Six core variants still use the current study support: Anthropogenic R6/R8,
Shoreline R6/R8, Estuary R8 and modeled Substrate R6. Their row counts are the
current-study counts in the table above. This report explains those differences;
it does not approve a historical reporting-grid migration or claim to reproduce
all historical values. Reproducing those older memberships requires choosing
that explicit reporting input, rather than treating current study membership as
an interchangeable grid.

The Anthropogenic run includes all nine configured OSM/agency sources and completed
in 553.4 seconds at 2.02 GiB peak sampled RSS. The separate ARSBC/WDFW/NOAA source
normalization and reconciliation also ran against their retained original evidence,
then enriched only the new candidate's reef field. It retains 25 records/18 sites,
17 positive R6 and 16 positive R8 cells, with the outside-support Trees location
explicitly retained in provenance. These inventories remain partial.

The completed mapped-substrate variants are resumed from this same rebuild's
source-derived candidates after verifying candidate, raw-source and spatial-index
checksums. Other completed producers are staged as immutable same-filesystem input
aliases inside the temporary workspace, with exact source paths/checksums recorded;
the exporter keeps its normal workspace-confinement checks. No original delivery
measurements are used to fill the candidate.

Local checks pass: 752 tests with three expected regional-artifact skips; 42 copied
installed-wheel regressions; 219 guarded installed-module imports and 219 source
files matching the built wheel; Ruff lint and 352-file format check; mypy's 21
configured modules; documentation checks/tests and strict MkDocs. The final-wheel
notebook passes 22 notebook and 15 production checks without acquisition/network
attempts. The wheel is built from the sdist, with packaged resource identity checked.
The regional/main wheel environments reuse installed scientific dependencies.
A separate clean runtime quick start passes the source install from the transferred
sdist, `pip check`, all 15 synthetic demo checks and the dry-run plan with source
checkout imports and acquisition blocked. This is one fresh unconstrained runtime
solve, not the paired constrained/unconstrained release matrix or hosted CI.

The required dependency audit initially reported 53 findings across four inherited
packages. Updating those four packages only in the temporary consumer produced an
audited toolkit runtime/test/quality closure with no known vulnerabilities. The
shared scientific environment and repository compatibility baseline were not changed;
unrelated inherited Streamlit/virtualenv constraints are outside that audited closure.
No clean whole-environment dependency-consistency claim follows.

Final replay evidence is retained at
`.seascape/work/source-rebuild-20261101/summary.json`, with independent schema,
habitat/key comparisons, source receipts, code/environment versions and bounded
logs referenced from the temporary task manifest. No manual deletion or promotion
was performed. Named research tables, application integration and hosted CI are
outside this metric rebuild.
