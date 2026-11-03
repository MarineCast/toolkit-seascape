# Single-command metric rebuild

`seascape build --profile metrics` is the complete producer path for the current
29 flat metric tables. It acquires or checksum-verifies configured scientific
sources, rebuilds coastal masks and H3 water graphs, executes all required
producers, and exports once through the normal metric-only writer. No previously
computed H3 measurements or graph products are source inputs. Reporting-key lists
are explicit spatial inputs; their full native polygons are reconstructed.

The configuration's `metric_rebuild` section declares pinned `sources` (path,
SHA256, role and optional download URL), habitat source inventories/qualification
contexts and independent native reporting keys, mapped substrate source/rights,
and optional original artificial-reef evidence. Cached raw/normalized scientific
inventories retain their source vintage and geometry audit; reuse of those inputs
is distinct from reusing any completed metric stage. Missing pinned sources fail
unless their configured acquisition can supply matching bytes. An upstream change
requires an explicit source-identity update, not a silent cache substitution.

All native intermediates live under the selected work root. Each producer runs in
a fresh subprocess with bounded logs, per-process-tree memory and time limits,
and a free-disk reserve. `metric_rebuild.limits.jobs` controls independent producer
concurrency (default 1); the graph/bathymetry dependencies finish first. Source
fingerprints and dependency-validated workflow stage state govern optional resume.
A full fresh run uses a new workspace/work root and omits `--resume`/`--skip`.

```sh
seascape --workspace /absolute/temporary-workspace build \
  --profile metrics --config config/data/project.yaml \
  --work-root /absolute/temporary-workspace/work \
  --output-dir /absolute/temporary-workspace/Data/Seascape
```

Before replacing the delivery, the final command checks the staged packaged
29-file metric-name/column-order contract,
unique sorted native H3/date keys, finite-or-null values and embedded provenance.
Coverage/quality diagnostics stay out of public columns. Null does not become zero.
Source identities and producer source receipts are checked again under the
delivery writer lock before replacement. A schema, source-pin or receipt failure
leaves the previous delivery and catalog unchanged. The verification receipt and
bounded logs stay outside `Data/Seascape`; the profile writes 29 Parquets and `catalog.json` there. Existing supported
`research/` objects and user `.txt`/`.md` review notes are preserved and permitted
by verification; unexpected files and unsafe research symlinks still fail. Schema verification does not assert historical numerical or grid
parity, source completeness, ecological absence or model readiness. The existing
configuration-driven general build remains available with `--profile default`.

Regional execution evidence is recorded below only after an actual CLI run.

## Source and reporting configuration

The ordinary family sections still configure their rasters, source vectors,
scientific parameters and native output paths. `metric_rebuild` adds the explicit
rebuild inputs below. Relative source paths resolve against the selected workspace.
Ordinary processed-output paths resolve into the work root through the existing
workflow renderer. Generated masks, H3 geometry, graphs and operators must point
to those work-root outputs, with no bindings to an older graph generation.

| Setting | Required content |
| --- | --- |
| `sources` | Each consumed source file: `name`, `path`, plain file `sha256`, `role` and original rights/qualification context. A directory uses the toolkit tree checksum. |
| `sources[].url` | Optional exact-file acquisition when a pinned cache entry is absent; acquired bytes must match the pin. |
| `sources[].acquisition` | Optional `source` (existing ArcGIS/WFS/HTTP source specification) and `bbox`, used when that raw file is absent. |
| `osm_acquisition` | Optional acquisition-config path for the existing Anthropogenic OSM downloader. Its selected JSON and receipt become checked inputs. |
| `habitats.{kelp,seagrass,bivalve}.inventory` | Audited normalized scientific source features, not H3 measurements. Follow the [Kelp](kelp.md), [Seagrass](seagrass.md) and [Bivalve](bivalve.md) admission/units/date contracts. |
| `habitats.*.source_context` | JSON retaining source identity, rights, methods, time support, completeness and recorded geometry handling. |
| `habitats.*.reporting_keys` | Independently specified R6/R8 paths to JSON lists of sorted unique H3 keys. This is a spatial grid definition, not measurements copied from delivery. |
| `habitats.kelp.additional_crims_pages` | Optional raw CRIMS pages appended through the existing normalizer after removing already retained exact geometries. No observation year is inferred. |
| `habitats.kelp.invalid_geometry_policy` | Explicit repair admission for newly normalized polygons; defaults to `reject`. Repairs remain recorded and do not certify sources. |
| `mapped_substrate` | `source`, `rights`, and explicit `invalid_geometry_policy`. A fresh spatial index is built from the mapped source polygons. |
| `artificial_reefs` | Optional `noaa_archive` and `wdfw_pdf`; the existing reviewed transcription, source reconciliation and direct native assignment run against those original inputs. |

For example, a pinned reporting-grid entry is ordinary configuration data:

```yaml
metric_rebuild:
  limits:
    jobs: 2
    memory_gib: 3
    seconds: 1800
    disk_reserve_gib: 20
    log_mib: 8
  sources:
    - name: kelp_native_r6_membership
      path: inputs/kelp-r6-keys.json
      sha256: REPLACE_WITH_THE_ACTUAL_FILE_SHA256
      role: reporting_keys
```

The full profile also needs the remaining declared inputs/settings from the table.
A registry entry with H3 measurement columns is rejected even if mislabeled as a
source inventory or reporting grid. Cached normalized source features remain
scientific input data; their raw acquisition and earlier normalization are retained
provenance, not falsely reported as repeated downloads or fresh classification.

`--dry-run --check-inputs --json` performs read-only path-level inspection for this
profile. It does not hash large datasets or certify sources. The acquisition stage
checks every declared SHA256 before any scientific builder, and the final stage
checks those identities again before publication. Newly acquired OSM inputs retain their
own original extraction and retrieval receipt. Resume remains an explicit option;
the full regional test below uses neither resume nor skipped stages.

## Graph neighborhood memory correction

The first CLI attempt crossed the 3 GiB guard while accumulating over four million
Python neighborhood-row dictionaries. The graph builder now validates and writes
complete-source batches directly to Parquet. Hop limits, passability, connectors,
minimum-hop/distance selection and final source/hop/target ordering are preserved.

The fresh graph rebuild completed in 119 seconds at 1.22 GiB peak sampled process-tree
RSS under the same guard. Independent bounded readback compared all 4,075,608 R8
and 66,655 R6 rows with the earlier source-derived graph: native identities, hops,
statuses, null masks, order and numeric distances match exactly. The in-memory
helper remains available for small fixtures; regional construction uses the stream.
These are graph-computation checks, not evidence of complete physical connectivity
or more accurate source shorelines.

## Completed full CLI run — 2026-11-01

The installed wheel completed this single command with exit code **0** in a new
work directory, with no resume, skipped stages, graph seeding or previous H3
measurements as inputs:

```sh
/private/tmp/seascape-cli-rebuild-20261101-axofug1g/consumer/bin/seascape \
  --workspace /private/tmp/seascape-cli-rebuild-20261101-axofug1g/workspace \
  build --profile metrics --config config/data/project.yaml \
  --work-root /private/tmp/seascape-cli-rebuild-20261101-axofug1g/workspace/work \
  --output-dir /private/tmp/seascape-cli-rebuild-20261101-axofug1g/workspace/Data/Seascape
```

All six workflow stages and 21 isolated workers completed. The six stages are
source acquisition/verification, coastal geometry, water graphs, bathymetry,
current metric producers and final export/verification. The source stage checks
60 pinned source assets plus the OSM selected-source/receipt pair, and the export
stage rechecks all 62 identities. Raw GIS/raster caches and normalized historical
scientific inventories are inputs; historical acquisitions/classifications are
not falsely reported as repeated downloads or newly observed data.

**All 29 Parquets across 17 families pass both built-in and independent complete
row readback.** Metric spelling, key capitalization and column order match the
existing delivery after the requested diagnostic omissions. There are no extra
files or coverage/quality columns. Native H3/date keys are sorted and unique;
measurements are finite or null; source/projection metadata remains embedded.
All 30 original delivery-file hashes, including the catalog, are unchanged.

The eight habitat tables have exactly their original H3/date keys and retain all
positive rows. Positive amounts match exactly. The earlier compact static encoding
used zero for no mapped positive evidence; new outputs retain the producer's
unknown/null convention. The [six remaining historical core-grid differences](source-rebuild-recovery.md#why-thirteen-files-differed)
remain separate from column-layout acceptance: Anthropogenic R6/R8, Shoreline
R6/R8, Estuary R8 and modeled Substrate R6 use the current study support. This run
does not authorize changing their canonical historical grid or claim all historical
measurements are identical.

Every worker remained below its 3 GiB process-tree limit. The highest worker peak
was 2.66 GiB during final export; freshwater peaked at 2.14 GiB, Anthropogenic at
1.98 GiB, and the newly streamed water graph at 1.22 GiB. Independent jobs ran two
at a time, so these per-worker peaks are not a claimed aggregate process-tree peak
for the entire CLI. Disk space stayed above the configured 20 GiB reserve.

Local validation passes: 766 source tests with three expected materialized-artifact
skips, 45 copied installed-wheel regressions, 221 guarded installed-module imports,
Ruff lint/355-file formatting, mypy's 21 configured modules, documentation checks
and strict MkDocs. The copied installed-wheel notebook passes 22 notebook and 15
production checks with no network/acquisition attempts. The clean source-install
quick start passes dependency consistency, 15 synthetic checks and CLI planning.
The separate corrected acceptance environment's toolkit closure audit reports no
known vulnerabilities; the running regional scientific environment was not modified.
These local checks are distinct from hosted CI, a release platform matrix, source
accuracy/completeness, model readiness and application/browser integration.

The temporary workspace retains final products, explicit processing checkpoints,
source registry, per-worker resource receipts and bounded logs. The earlier failed
attempt is separately retained, including its stopped graph checkpoint and wheel.
Small replay evidence is retained at
`.seascape/work/cli-rebuild-20261101/summary.json`. No manual deletion, canonical
Data overwrite, research-table rebuild, external publication, commit or push was
performed.


<a id="publication-hardening"></a>
## Publication and source-registration hardening — 2026-11-03

The final schema/row checks now run on the staged delivery inside the existing
writer transaction, followed by source verification, before any delivery replacement.
The 29-table set is checked against the validated catalog; supported research
objects and review notes are not counted as H3 products. Their preservation does
not certify their scientific content.

Every direct metrics-profile habitat inventory, qualification context, reporting
key file, additional CRIMS page, mapped-substrate source and configured reef
source must be registered. Acquisition checks registration after verifying pins;
workers check it before dispatch. A source can be an exact registered file or a
member of a registered directory whose tree checksum is verified. Directory pins
reject symbolic-link members and apply the same schema admission rules to every
nested `.parquet`/`.geoparquet` file. Computed H3 measurements are rejected even
when nested or labeled `reporting_keys`; that role permits H3 identity columns only.

Before publication, local external `sources` and `upstream_artifacts` recorded
in producer manifests are also required to belong to the registry. Recorded
producer checksums, when present, must still match. Generated candidate dependencies
require an exact checksum-bearing artifact record in a producer manifest under
a declared metrics output directory, plus a matching consumer receipt and current
bytes. A producer manifest with artifact records can itself be an upstream
dependency when its consumer checksum matches. Conflicting records, escaped
output paths and missing consumer checksums fail. Merely residing under the work
root never exempts raw inputs from registration or receipt checks. The generated
reef inventory is now explicitly recorded as an artifact. URL-only attribution records are
not treated as local files. This relies on producers recording their consumed
inputs and is not a filesystem-access sandbox. Unregistered inputs fail closed;
add their reviewed pins rather than suppressing the check.

Metrics path preflight resolves relative paths against the selected workspace,
matching execution, and expands `~`. It remains a path-only check, not a checksum
or regional validation. The portable validation notebook remains unchanged: it
exercises bathymetry/demo APIs, not this publication gate. Dedicated offline
regressions cover publication rollback, companion preservation, source registration,
receipt checks and workspace-relative preflight. No regional rebuild or canonical
`Data/Seascape` update is implied by those tests.

Current local checks: 776 tests passed with three expected absent-materialized-data
skips; Ruff lint/355-file formatting, mypy's 21 configured modules, documentation
checks and strict MkDocs passed. A wheel built from the updated sdist passed
distribution inspection and 221 installed-module imports with OrcaCast blocked.
The installed check uses a task-owned virtual environment with inherited existing
dependencies; it is not a fresh runtime-only dependency installation. The copied
installed-wheel notebook passed 22 notebook and 15 production checks with no
external network/acquisition attempts. The captured test/quality dependency closure
had no known vulnerabilities in the strict audit. Hosted CI,
regional acquisition/rebuilding and the native/platform acceptance matrix were
not run for this change.


<a id="source-validation-closure"></a>
### Second-review source-validation closure — 2026-11-03

Both remaining source-admission findings are fixed: candidate-root placement no
longer grants an exemption, and directory pins no longer bypass H3 schema checks.
Regression fixtures cover raw sources inside/outside declared output folders,
registered inputs with incorrect receipts, legitimate generated outputs and
manifest dependencies, changed/missing/conflicting generated receipts, nested
Parquet/GeoParquet measurements, identity-only reporting grids, directory changes,
symlink members and failed publication preserving the prior delivery. Generated
receipts establish producer lineage within this workflow, not a security sandbox
against forged manifests or scientific source completeness. These checks do not
run regional acquisition or authorize a change to existing delivery.

Closure validation: 815 source tests passed, with three expected missing-regional-
artifact skips and two existing pandas deprecation warnings. The metric regression
module passed all 40 tests both from source and against the installed wheel outside
the checkout. Ruff lint/357-file formatting, mypy (21 configured modules), docs
checks, strict MkDocs, distribution inspection, 222 installed imports and the
copied notebook (22 notebook/15 production checks) passed. The consumer reused
existing dependencies. No regional rebuild, live acquisition, fresh dependency
installation or hosted/platform CI run was performed. SHA-256 comparison verified
all 44 existing delivery files, including research and catalog, were unchanged.
