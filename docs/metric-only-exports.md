# Metric-only final exports

The normal `seascape.write_areas` interface keeps existing scientific metric names
and layout and omits diagnostic columns. Compact core families use `h3_index`;
bathymetry, freshwater and mapped habitat extents retain `H3_INDEX` and their existing
metric spellings. Annual Kelp retains `ANNUAL_KELP_EXTENT_M2` and `date`. Each file
contains one native H3 resolution, verified from the cell IDs. Resolution is recorded
in metadata and the filename, not a repeated column.

Metric nulls remain null, including habitat unknowns and unavailable physical values.
Coverage, censoring, QC, source-record counts, provenance and processing-status columns
are excluded. Physical quantities such as water fraction and depth-band area fraction
remain metrics; coverage fraction is a diagnostic. No synthetic absent-source values
are introduced. Units/definitions and temporal precision remain embedded metadata;
source-mask identity used by historical selection is also retained in the catalog.
Source versions, checksums, rights, code identity, scientific limits and field-level
source bindings remain embedded metadata, without additional table columns.
Partial updates preserve this context for untouched resolution/date variants.

Shoreline proximity stores unknown network and connector distances as Arrow nulls,
with the internal reason retained. Nonfinite public measurements still fail before
publication. dbSEABED percentage conversion admits only endpoint interpolation
roundoff (eight float64 spacings at 100 percent); materially out-of-range values
still fail, and source missingness is preserved.

See the [1 November full-area rebuild verification](full-rebuild-verification.md)
for current source acquisition, producer execution and schema readback evidence.

The 2026-11-01 output decision retains existing metric names rather than renaming
every field to lower case. Coverage, censoring, QC, confidence, source counts and
processing status are omitted from new final tables. Declared nonmetric fields
are excluded even when numeric. Native producer diagnostics may remain in scratch.
Existing delivered files are not rewritten by this code change. Habitat extent
presence flags retain their existing names; new writes preserve unknown extent
as a null flag rather than guessing absence.

## Producer alignment and combination rules — 2026-11-01

The normal Anthropogenic producer emits qualified mapped evidence at each native
H3 resolution. Point locations use direct cell assignment without water snapping;
polygon evidence requires positive overlap. The final four mapped-presence fields
and `shoreline_armoring_fraction` keep the compact public names.
Normal Substrate delivery samples each R6 representative point directly from the
four source rasters. Legacy child-aggregated `SUBSTRATE_*` fields remain internal;
they are not substituted for the direct R6 product. Estuary's native
`DISTANCE_TO_ESTUARY_M` maps to `distance_to_mapped_estuary_point_m` and retains its
point-distance/source-CRS context. Internal producer scales do not create extra
public resolution variants.

Shoreline lengths measure unique physical line locations; duplicate evidence
cannot increase lengths or class fractions. Classes remain nonexclusive.
Armoring uses the maximum available **dataset estimate for the cell**. Within each
dataset, unique line locations are length-weighted; coincident estimates use the
maximum at that location. Dataset estimates of 0% and 100% combine to 100%.
Missing estimates contribute neither a zero nor a denominator; all missing stays
null. R6 first combines child lengths within each dataset, then takes the dataset
maximum. These method changes require recomputation before claiming regional values.

The normal writer and historical date selector do not open or require historical audit
outputs. Required scientific raster/vector inputs, water geometry, native membership
and their source identity checks remain producer dependencies. Source receipts and
optional diagnostic outputs are separate from final metric tables. Existing legacy
compacted inputs may have filled nulls; they are rejected for new writes rather than
silently accepting those filled values. Rebuild from scientific inputs. Explicit legacy
migration/restoration tools remain available for historical evidence only.

```python
from seascape import AreaTables, write_areas

# native_metrics: a producer's Arrow table with H3_INDEX/H3_RESOLUTION and metrics
write_areas({"bathymetry": AreaTables(static=native_metrics)}, output="candidate/Data/Seascape")
```

Annual and composite date labels retain their temporal precision; they do not imply
daily observations. Composite interval definitions are stored in metadata, avoiding
extra final data columns. Historical selection still rejects unknown temporal precision
or conflicting mask identities.

Validation on 2026-10-30 covers software tests and separate candidate exports. The
original delivered files/catalogs are unchanged. This schema change does not resolve
regional source gaps, the three unsupported R6 cells, or historical terrain differences.
See [full-study scope](full-study-reproduction.md) and
[installed nearshore acceptance](installed-nearshore-memory.md).

## Verified installed export scope (2026-10-30)

The installed wheel exported retained real-data producer candidates for bathymetry R8,
bivalve R8, annual kelp R6, nearshore R8 and terrain R8. Keys, metric values and null
masks matched exactly after sorting by identity. The four R8 tables each contain
81,380 rows; annual kelp contains 84,945 dated R6 rows. No audit directory was created.
Peak memory was 545 MB and total candidate output was 9.3 MB. This is an export
acceptance check, not a fresh scientific producer run or proof of historical terrain
parity. The terrain export used the retained pre-centering native candidate.

The source suite passed 708 tests with three expected regional-artifact skips.
Lint, formatting, configured types, documentation links, strict MkDocs, installed
imports and the installed validation notebook passed. Full installed terrain and
substrate production still require the bounded-path integration described in the
full-study report; do not interpret this export check as closing that work.
