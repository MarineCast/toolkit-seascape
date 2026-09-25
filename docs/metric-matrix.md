# H3 metric matrix export

`seascape export-metric-matrix` writes one Parquet file with one row per canonical
`(H3_INDEX, H3_RESOLUTION)` cell. It is a convenience product for downstream
inspection and joins, not a new seascape calculation or an ecological model.
The default includes R6 and R8. It names each field `<product_id>__<source_column>`
so columns from different families cannot collide. All cataloged physical variables,
states, coverage, evidence, and QC fields are retained. A field unavailable at a
resolution is null there; no missing value is replaced with zero. The Parquet schema
metadata key `seascape_metric_matrix` contains the field-to-source mapping, units,
roles, available resolutions, original field types by resolution, source table
checksums, and validation status. Compatible source types may widen in the combined
Parquet (for example, a year stored as integer at R6 and floating point at R8).

The input grain is the toolkit's canonical model-area H3 support at each resolution.
R8 cells have nonzero water overlap; R6 is the exact parent union of those cells and
may include a hierarchy-only parent. The exporter requires each source table to have
the same unique H3 support and validates every H3 index and declared resolution.
The matrix has no geometry or time axis. Its values describe static physical/source
snapshots, with source vintage and retrieval/build timing retained in the referenced
release and family manifests. Units and sign conventions remain those of each cataloged
field, including positive-down bathymetry where configured. Nulls, coverage, evidence,
and QC columns must be interpreted together; a null is not a surveyed zero or absence.
The export does not establish predictive eligibility or species habitat suitability.
Source rights and attribution continue to apply; a local export is not redistribution
approval.

## Validated toolkit release

Build and audit a schema-3 regional release first, then export using its archived
catalog and immutable products. The exporter calls the public `resolve_product` API
for each table, which verifies the release and source artifact checksums. It rejects
missing products, unexpected grain, catalog path disagreements, missing columns,
duplicate or invalid keys, and support mismatches. The output is written through a
temporary file and atomically replaced only when `--overwrite` is explicit.

```sh
seascape --workspace /path/to/seascape-workspace export-metric-matrix \
  --output /path/to/data/seascape/processed/seascape-h3-metrics.parquet
```

Pass `--resolution 8` to select only R8. Repeat `--resolution` for both. The default
is both. The caller chooses the output location; the toolkit never assumes an
OrcaCast checkout.

## Explicit legacy bridge

For retained schema-1 materializations only, pass `--legacy-unverified` and an
explicit catalog path. This path checks table structure and records source checksums,
but it cannot claim the current schema-3 release guarantees. The embedded metadata
sets `source_validation=legacy_structural_only`, carries the old release's
`model_policy_complete` value, and lists any family-manifest checksum mismatches.
Use a clearly marked output filename and keep it internal until a current release
replaces it.

```sh
seascape --workspace /path/to/legacy-workspace export-metric-matrix \
  --catalog /path/to/toolkit-seascape/config/feature_catalog.yaml \
  --legacy-unverified \
  --output /path/to/data/seascape/processed/seascape-h3-metrics-legacy-unverified.parquet
```

The retained OrcaCast schema-1 workspace has 46 structurally aligned R6/R8
tables, but its water-geometry family manifest differs from the release checksum.
Its release also records `model_policy_complete=false`. A bridge export from those
tables is therefore only an inspectable legacy artifact. It had 1,263 R6 and
43,393 R8 cells and 522 cataloged fields. OrcaCast's local data product now uses
a fresh audited schema-3 toolkit release through the validated path above; the
legacy bridge file was removed from its `data/seascape/processed/` directory.
