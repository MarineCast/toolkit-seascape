# Flat H3 domain tables

The flat H3 output consists of `<area>-r<resolution>-static.parquet`, optional
`<area>-r<resolution>-dynamic.parquet`, and `catalog.json`. Each area and native resolution has at most two files.
Names never include dates or versions, and updates replace the current files.
There is no data-release directory, publication receipt or separate manifest.

An optional `research/` child contains separately keyed named-object and long relationship tables,
referenced by the study registry. These objects are outside the H3 area catalog. Rebuilds and
historical replacement preserve that directory byte-for-byte; arbitrary extra directories and
symbolic links are rejected. Domain products stay canonical under `Data/Seascape/`, while study
definitions, masks and H3 registries remain separate from their selected products.

Static grain is `(H3_INDEX, H3_RESOLUTION)` with metric columns and no time axis.
Dynamic grain adds a nonnull Arrow `date32` column named `date`. Native R6 and R8
rows are stored in separate files. Each file has exactly one native resolution; no resampling occurs.
Missing measurements remain null. Padding columns explicitly unavailable at a
resolution are omitted from its file. Physical values, evidence,
coverage and QC stay together. Unknown coverage never becomes zero or absence.

Directional quantities become separate columns for each native bearing. Annual
observations use January 1 as a year index label, with explicit year precision in
Parquet metadata; that label never claims an observed survey day. Annual data are
not expanded into daily rows or forward filled. Exact duplicate convenience
aliases and row-level release IDs are omitted during migration.

The `seascape_domain` Parquet schema metadata contains definitions, units, source
context, limitations and temporal support. `catalog.json` is deliberately small:

```json
{
  "kelp": {
    "last_updated_utc": "2026-10-14T12:00:00+00:00",
    "static": {"6": "kelp-r6-static.parquet", "8": "kelp-r8-static.parquet"},
    "dynamic": {"6": "kelp-r6-dynamic.parquet", "8": "kelp-r8-dynamic.parquet"}
  }
}
```

The timestamp records when these outputs were successfully updated, not source
observation time or newly established accuracy. Untouched areas retain their
files and timestamp. Failed writes preserve previous files and the catalog.
`export` replaces only the variants supplied by its producer catalog. An existing
annual variant remains unchanged when the supplied source has only static data;
its embedded source/update context is preserved.
Temporary processing, locks and recovery journals stay outside the output
folder; successful normal builds remove their scratch products.

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build
seascape --workspace "$SEASCAPE_WORKSPACE" export
```

`export` converts existing producer tables using their generated feature catalog,
without data-release resolution. `--output-dir` selects a flat output directory.
A catalog product can declare `temporal_column: date` or `temporal_column: OBSERVATION_YEAR`
for existing dated producer tables. These are validated on cell/date keys, with no
implicit daily expansion. Undated snapshots remain static.
See [the current Python API](API.md#current-area-tables). The old
`export-metric-matrix` command is a historical migration helper only.

To migrate an existing consolidated directory, run `python scripts/migrate_flat_data.py
--source /absolute/path/to/old-consolidated-directory --output /absolute/path/to/staging`.
It verifies source checksums, preserves retained arrays and missingness, pivots
native bearings and writes the annual table. It never deletes input files.
Review readback before replacing an old data tree.

## Substrate feature projection

The prepared `substrate` area omits these reviewed native field names from its
feature columns: `SOURCE_OBSERVATION_DATE_STATUS`, `SEDIMENT_TEXTURE_STATUS`,
`SAND_POINT_SAMPLE_STATUS`, `SAND_MASK_STATUS`, `ROCK_POINT_SAMPLE_STATUS`,
`ROCK_MASK_STATUS`, `POINT_SUPPORT_STATUS`, `MUD_POINT_SAMPLE_STATUS`,
`MUD_MASK_STATUS`, `H3_AREAL_SUBSTRATE_COVERAGE`, `GRAVEL_POINT_SAMPLE_STATUS`,
`GRAVEL_MASK_STATUS`, `UNSUPPORTED_PHYSICAL_METRICS_REASON`,
`SOURCE_OBSERVATION_PERIOD`, and `SOURCE_GRID_DEGREES`. In the retained native R6
product these have the `SUBSTRATE_MODEL__` namespace. The current benthic
producer's equivalent `SUBSTRATE_SEDIMENT_TEXTURE_STATUS` spelling is also
projected out. Other substrate measurements and evidence remain unchanged.

`write_areas` applies this projection after native table validation, including
when called by `export_domain_parquets` or the retained-data migration helper.
Missing cataloged native fields still fail producer validation; no null columns
are synthesized. The projection changes neither scientific calculations nor
retained values, Arrow types, nulls, keys or native resolution. Prepared field
definitions and qualifier references omit the removed columns. Embedded
`source_context` preserves the original source manifests, dictionaries and method
scope, including the 0.1-degree point support and unknown observation dates;
native source contracts are unchanged. `delivery_projection` records the policy
and omitted names. The explorer regenerates its checked encoding when current
catalog/Parquet bindings change, so removed features disappear from its picker
and a previous removed selection uses the existing available-feature fallback.

Offline checks: `python -m pytest -q tests/test_delivery_projection.py
tests/test_domain_parquets.py`. This projection does not establish regional
scientific validation or improve physical hardness or surveyed-coverage support.
