# Reviewed compact delivery

> Historical review/migration reference. The normal writer now follows the
> [metric-only contract](metric-only-exports.md): no audit dependency, no diagnostic
> columns and no null-to-zero imputation. Existing delivered files remain unchanged.


The 2026-10-25 user review approves smaller static tables for the five initial
areas and the twelve additional cores listed below. This changes delivery representation, not native
footprint calculations, source rights, geometry, survey years or model eligibility.

## Implemented schemas

| Static area | Public columns |
| --- | --- |
| Seagrass | `H3_INDEX`, `SEAGRASS_EXTENT_ALL_TIME_M2`, `SEAGRASS_EXTENT_BOOL` |
| Bivalve | `H3_INDEX`, `BIVALVE_EXTENT_ALL_TIME_M2`, `BIVALVE_EXTENT_BOOL` |
| Kelp | `H3_INDEX`, `KELP_EXTENT_ALL_TIME_M2`, `KELP_EXTENT_BOOL` |
| Bathymetry | Existing columns except `H3_RESOLUTION` |
| Freshwater | Existing columns except `H3_RESOLUTION` |

Habitat area is the existing all-time mapped union in square metres. Positive
values are unchanged; source nulls become `0.0` by explicit user policy. The
`*_EXTENT_BOOL` fields are **int64 0 or 1**, calculated as `area > 0`, with no
nulls. Zero means no mapped positive evidence, including unknown coverage. It
does not establish surveyed absence, current presence or complete inventory
coverage. These are evidence flags, not ecological occurrence targets.

Rows and native H3 support do not change. Resolution remains encoded in H3 keys,
filenames and metadata, and is verified against the retained native audit.
Kelp dynamic retains its existing cell/survey-year grain, fields, values, nulls
and dates; its review is still pending. January 1 remains a year label.
Freshwater remains native R8. Native R6 would require a separate source-backed
calculation; averaging R8 distances or pressure would change their meaning.

## Required audit and replay

Every compact file has `seascape_review` schema metadata with policy
`reviewed-static-v1` (the initial five areas) or `reviewed-core-static-v2`
(the twelve additional areas), area, absolute audit path, audit SHA-256 and native shape.
The immutable external Parquet retains all original columns, Arrow types,
metadata, row order, QC, source details and original nulls. This is required
support, not a disposable browser cache. Relocating data requires keeping the
audit, updating bindings and revalidating the public projection.

Normal `write_areas` writes audits below
`output.parent.parent/.marinecast-work/seascape/<destination-hash>/audit`.
Transaction staging/backups remain disposable; `audit/` must be retained.
An explicit `audit_root=` selects another retained location outside delivery.
For new cores, the full table entering compact publication is audited before
older flat-only field removal. Anthropogenic retains its existing presence
derivation and nullable-source companions. Audits promote before the public directory within the existing recoverable
transaction. Failed writes preserve previous delivery. Adjacent `.txt` and
`.md` user notes and separately keyed `research/` tables survive replacements.

`read_area` verifies the audit and returns the compact public table. `write_areas`
accepts native tables or verified compact inputs; compact input is restored
before native validation and reprojection.

```python
from seascape import read_area
from seascape.reviewed_delivery import restore_native

public = read_area("seagrass", resolution=6, output="Data/Seascape")
original = restore_native(public)
```

`restore_native` checks the audit checksum and recomputes the complete public
projection, including metadata, before returning original native data. Missing
audits, altered public values/metadata and changed audits fail. Historical export
restores source support before extraction and creates new bound audits for its
compact outputs; filled delivery zeros never become original evidence.

## Migrate existing delivery

```sh
seascape compact-reviewed --output-dir /absolute/path/to/Data/Seascape --audit-root /absolute/path/to/retained/audit
```

This migrates the seventeen reviewed static areas, without acquisition or scientific
recomputation. Annual Kelp, notes, research files and source-update
timestamps survive. The existing catalog records `delivery_schema`. Repeating
the command verifies bindings and makes no writes.

The independent Data Explorer reader verifies bindings without importing the
toolkit, restores resolution and source qualifiers for transport/Details, and
displays delivered filled areas plus three integer presence fields. Audit checksums
enter source fingerprints; audit loss or modification invalidates cached reads.
Restored QC describes original source evidence, including unknowns.

## Twelve approved compact cores

[The approved core column reference](simplification-assessment.md) lists exact
names, meanings and units for Anthropogenic, Coast Complexity, Coastal Bounds,
Estuary, Fluvial Connectivity, Mapped Substrate Classes, Nearshore Transitions,
Shoreline, Spatial Support, Substrate, Terrain and Waterbody Morphometry.
These files use `h3_index` and lower_snake_case metric names. The initial five
areas retain their already-approved column names and schemas.

Only retained core variables are selectable in the Explorer. Source QC and
alternative arrays remain inspectable through the bound native audit. Boolean
core fields become int64 0/1 without filling nulls. Anthropogenic's four existing
presence flags retain their earlier explicit false-fill policy; source-null
versions stay in the audit. Other values, types, nulls and native rows are
unchanged. Fluvial count/order columns retain their original numeric storage.
Nearshore's uniform depth threshold and band width move to
`seascape_domain.core_schema.parameters`; varying parameters fail projection.
R6 Shoreline has no invented overall distance field. Terrain ring 2 remains an
explicit compact-scale choice, not a demonstrated predictive optimum.

Native required fields must be present and unambiguous. Namespace changes can
match a unique native field suffix; unrelated measured quantities never substitute
for the approved modeled substrate outputs. Identity-only support tables remain
validated join inputs, not empty metric products. Source schemas outside the
approved core contract fail explicitly rather than producing a partial core.

The independent Explorer reader carries a matching public schema contract,
verifies audit values, units and nearshore parameters, and hides restored audit
fields from selectors. Renamed fields use their new names in feature IDs; a
retired selection may fall back to a current field. Annual Kelp and additional
Freshwater/R6 proposals remain outside this second migration.
