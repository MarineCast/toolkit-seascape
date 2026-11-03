# Artificial reef mapped presence

The artificial reef metric is `has_mapped_artificial_reef`: 1/True when at least
one retained, qualified artificial reef location falls in a native H3 cell;
0/False otherwise. False means no mapped evidence in these partial inventories,
not surveyed absence. This is an undated static location inventory, not current
reef condition, activity, footprint area or a historical daily presence series.
The existing R6 and R8 cell memberships are preserved; each resolution is assigned
directly from coordinates rather than deriving R6 by H3 parent membership.

## Sources and reconciliation

- ARSBC's 2016 *Wreck Trek* brochure, PDF page 2: eight BC locations and their
  deployment dates. The San Diego Yukon is outside the regional inventory.
  The factual coordinate transcription is packaged with its source URL and
  locator. Original PDF bytes could not be downloaded (HTTP 465); its original
  checksum is unavailable. The transcription was checked against the source
  text returned by the web reader on 2026-11-01. No brochure artwork or prose
  is redistributed and no open licence for the brochure is asserted.
- WDFW's 2025 commercial salmon regulations, PDF page 54 (printed page 48):
  seven artificial fishing reef coordinates. The original PDF and checksum
  remain in the producer source cache. Only the factual coordinate table is
  normalized; conservation areas and natural reefs are excluded.
- NOAA's 2006 Puget Sound ESI geodatabase: join `socecon_point.HUNUM` to
  `soc_dat.HUNUM`, selecting exactly `ARTIFICIAL REEF`. Preserve feature ID,
  HUNUM and source-table lineage. Transform the declared NAD83 geometry to
  EPSG:4326. NOAA declares CC0; its underlying inventory dates are historical.

ARSBC and WDFW do not state a coordinate datum in the tables. Their coordinates
are treated as nominal EPSG:4326 for mapping, with that uncertainty retained.
Do not buffer locations to invent reef footprints or snap them to water cells.

Cross-check WDFW and NOAA by reviewed site-name aliases and WGS84 geodesic
distance. Within 250 m is positional agreement, not proof of independent
confirmation: NOAA's reef lineage itself cites WDFW's 2005 inventory. Prefer the
2025 WDFW coordinate for the same site. Retain every NOAA coordinate and report
larger disagreements explicitly; do not turn an alternate coordinate for one
site into another positive cell. Unmatched NOAA artificial reef sites contribute
their own locations. NOAA's Washington atlas cannot confirm absence of BC reefs.

## Execution and storage

`scripts/integrate_artificial_reefs.py` reads the retained NOAA archive and the
packaged coordinate transcription. It writes a bounded source/cross-check report
and validates a candidate before an explicitly requested `--publish`. Publication
updates only the two Anthropogenic files and their catalog entry under the
existing transaction lock. Other measurements, cell identity/order and source
records are preserved. Existing compact delivery keeps its checked audit contract;
this scoped reef enrichment does not rebuild or migrate unrelated measurements.
This updater accepts the currently delivered compact contract only; it rejects a
different delivery schema rather than silently migrating it. Sources, checksums,
reconciliation and per-cell record membership are retained outside Data and
bound from embedded metadata. No live network access occurs during publication.

The explorer presents the compact 0/1 metric as False/True and keeps exports as
their delivered 0/1 values. This does not change modeling eligibility.

Run from an installed source checkout, using the existing Seascape environment:

```sh
python scripts/integrate_artificial_reefs.py \
  --cache .seascape/cache/artificial-reefs-20261101 \
  --delivery /absolute/MarineCast/Data/Seascape \
  --work .seascape/work/artificial-reefs-20261101
# Add --publish only when replacing the delivered reef metric is authorized.
```

The retained cache must contain `wdfw_2025.pdf`, `PugetSnd_2006_GDB.zip` and the
NOAA acquisition receipt. The WDFW checksum must match the reviewed transcription.
The normalized inventory implements the existing Anthropogenic source-inventory
schema and can also be supplied to the regional physical producer; canonical and
duplicate source identities remain explicit. The updater never downloads sources.

## Validation on 2026-11-01

The locally published integration has 25 source records (8 ARSBC, 7 WDFW, 10 NOAA), reconciled to 18
sites. Six WDFW/NOAA pairs agree within 250 m. The Trees differs by about 2,848 m;
the WDFW coordinate is preferred and the NOAA alternate is retained as a conflict.
NOAA adds Possession Point, Toliva Shoal and Itsami Ledge. All eight BC points are
outside the Washington NOAA atlas's cross-check scope.

Direct native assignment gives 17 positive R6 cells from 18 sites and 16 positive
R8 cells from 17 sites. WDFW's The Trees coordinate falls in R8 cell
`8828d54737fffff`, outside the existing delivered R8 membership. It remains in the
source inventory and is reported as outside support; no coordinate correction,
nearest-water snap, grid expansion or new footprint is inferred. Counts of sites
and occupied H3 cells differ because multiple sites can share a cell.

Both delivered files passed the independent explorer audit reader and lossless
browser encoding readback. Every positive H3 polygon was independently checked
to contain a canonical source point. All 53 unrelated native fields per resolution
and 41 unrelated delivery files remained exact. Source and output checksums,
input audit locations, code hashes, environment versions and cross-check records
are retained in `.seascape/work/artificial-reefs-20261101/summary.json`.

The producer suite passed 719 tests with three expected materialized-regional-input
skips. Explorer's full suite passed 523 tests; the subsequent loader regression
passed with all 24 loader tests. Python reader checks, lint/format, configured
types, documentation link/tests, and the explorer build passed. Native browser
interaction, a full regional rebuild and a new installed-wheel acceptance were
not run for this scoped update. Strict MkDocs was unavailable because MkDocs is
not installed in the active environment.
