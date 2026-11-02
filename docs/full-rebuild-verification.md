# Full-area rebuild and metric-format verification — 2026-11-01

This records the initial run. The subsequent [source recovery and row-count
investigation](source-rebuild-recovery.md) resolves the OSM/freshwater runtime
blockers and corrects habitat replay scope; consult it for the continuation.
The later [complete metrics CLI run](metric-rebuild.md) provides the successful
single-command rebuild and final 29-table verification.

This run rebuilds the delivered metric families in an isolated temporary workspace,
then compares their public schemas with the existing delivery. It does not publish
or replace `Data/Seascape`. Schema acceptance is separate from historical numerical
parity, identical geographic membership, complete provider acquisition and a clean
one-command CLI build.

## Inputs and execution

The default preflight still references absent legacy OrcaCast source paths. The
run instead uses the retained coastal-study configuration and its documented
regional/model extents. Outputs are confined to
`/private/tmp/seascape-full-rebuild-20261101-zyp8kvaq/workspace`.
The task manifest, configurations, bounded process logs and per-stage status files
are in the parent temporary directory. Retained inputs are referenced in place.

Missing agency inputs were fetched through toolkit acquisition functions into
`.seascape/cache/full-rebuild-20261101`: WA armoring, BC ShoreZone, NOAA channels,
WA and Canadian disposal sites, WA shellfish harvest classifications, both DFO
aquaculture licence tables, BC/US estuaries and HydroRIVERS North America.
The harvest-classification source remains distinct from cultivation evidence.
The original estuary query used a 75 km buffer; production rejected its maximum
distance, so both inventories were fetched again with a 250 km context and that
candidate passed.

All three configured Overpass providers timed out. The Anthropogenic candidate
therefore explicitly excludes OSM and uses the eight acquired agency inventories.
It is not a complete inventory of marine structures, and it does not rerun the
separate published-coordinate artificial-reef enrichment workflow.

Existing GEBCO/dbSEABED rasters, source coastline/land registries, mapped-substrate
polygons and normalized habitat inventories are scientific inputs. Habitat union
calculations are fresh; upstream habitat acquisition/classification is not rerun.
Freshwater's full-grid proximity/pressure calculation uses the retained mouth
inventory. Attempts to regenerate that inventory from the large BC/NHD inputs
exceeded the 2.5 GiB and 4 GiB process guards; those failures remain recorded.
Fresh HydroRIVERS acquisition, topology and marine fluvial distances completed.

Fresh coastal masks, native membership and canonical H3 geometry/graphs were also
generated. Other metric runs reuse verified retained support/graph inputs where
declared in their configurations. This is a set of full-area producer API runs,
not proof that every dependency was consumed from one newly built CLI generation.

## Runtime corrections

- Coastal buffering now dissolves small batches before the final union. The fresh
  mask completed in 93 seconds at approximately 0.9 GiB peak sampled RSS; the
  original attempt crossed its 3 GiB guard. Both native R6/R8 member sets match
  the retained masks. The geodesic envelope passes the unchanged 10 m tolerance.
  Reporting-mask symmetric difference is approximately 0.00634 km²; this is not
  byte-identical geometry or evidence of improved source cartographic accuracy.
- Shoreline proximity now stores unknown network/connector distances as nulls
  instead of NaN. Internal reasons remain available. Public export continues to
  reject nonfinite measurements and invalid scientific support parameters.
- Percentage conversion admits only endpoint interpolation roundoff: eight
  float64 spacings at 100 percent. A computed `100.00000000000003` becomes 1.0;
  materially invalid percentages still fail and nodata remains missing.

## Acceptance scope

**Result: all 29 metric Parquet files across 17 families pass schema and complete
row readback.** Filenames and metric names/order match the existing products after
the requested diagnostic omissions. There are no extra output files or coverage/QC
columns. All existing delivery hashes remain unchanged. Thirteen files have different
row counts under the explicitly configured coastal-study memberships; this is not
acceptance of identical historical rows or values. Complete fresh upstream CLI
regeneration remains unverified for the source/resource reasons above.

The independent readback compares filenames, exact metric spelling and column
order against the existing delivery, omitting only the requested diagnostics.
Annual Kelp retains `H3_INDEX`, `ANNUAL_KELP_EXTENT_M2`, `date`; habitat flags and
native field capitalization remain unchanged. Coverage, censoring, QC, source
counts, repeated resolution and processing-status columns are excluded.

Every generated row is checked for native H3 identity, sorted unique cell/date
grain and finite-or-null numeric measurements. Metadata must retain the delivery
projection receipt. Existing delivered bytes are hashed again to prove they are
unchanged. Row-count differences are reported separately: older files use mixed
memberships, including cells outside the current coastal reporting study. No
unsupported cell is filled with an invented value to force historical parity.

Detailed current results are in the task's `verification.json`, `summary.json`
and bounded logs. See [the metric-only contract](metric-only-exports.md) for the
implemented public layout and combination rules. The repository-local evidence
pointer is `.seascape/work/full-rebuild-20261101/summary.json`.

Software checks passed: 736 pytest tests with three expected materialized-artifact
skips; 26 copied installed-wheel regression tests; 217 installed-module imports
with OrcaCast blocked; Ruff lint/formatting; mypy's 21 configured modules; 81
documents/365 local links; 16 documentation tests; strict MkDocs; and diff whitespace
checks. The installed-wheel notebook passed 22 notebook and 15 production checks,
with no external network/acquisition attempts. These checks use existing system
scientific dependencies, not a new clean dependency solve or hosted CI run.
