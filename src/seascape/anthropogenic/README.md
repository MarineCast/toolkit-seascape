# Anthropogenic features

## Purpose and non-goals

This family measures mapped shoreline modification, overwater structures, dredging, disposal,
artificial reef, and aquaculture context. It is an ecological covariate layer, not a navigation,
regulatory, or inventory-completeness product.

## Sources, dependencies, and resolutions

OpenStreetMap/OpenSeaMap provides a cross-border backbone and authoritative government datasets
replace or supplement it where available. [`DATA_SOURCES.md`](DATA_SOURCES.md) is the authority for
provenance, licences, normalization, and interpretation. Processing occurs at R8 and aggregates to
R6 using canonical support, water geometry, shoreline denominators, and the water graph.

## Commands

```bash
python -m seascape.anthropogenic.download
python -m seascape.anthropogenic.build
python -m seascape.anthropogenic.inspect --resolution 8
```

## Artifacts and publication

The family writes a normalized source inventory, R8/R6 feature and confidence tables, and a
manifest under processed `anthropogenic/`. All five Parquet outputs are staged as one release and
the manifest is atomically written last.

## Missingness, QC, and R8 to R6 aggregation

Mapped distance does not imply complete coverage. Armoring fractions use only systematic
shoreline denominators. Artificial-reef and aquaculture non-detections remain null unless the
source supports absence. R6 fractions recompute numerator/denominator totals, presence uses mapped
evidence, distances use child minima, and graph-neighborhood metrics use child-water-area weights.

## Inspection and validation

The inspector retains feature classes and confidence/QC context while sharing map routing and
presentation defaults. Validation covers deduplication, source-class rules, denominators, graph
attachment, R8 to R6 aggregation, finite values, schemas, and checksums.
