# Biogenic habitat

## Purpose and non-goals

This family keeps seagrass, kelp, rocky reef, mapped bivalve-bed proxy, and unavailable deep
coral/sponge evidence distinct. The composite is a panel, not a synthetic habitat-quality score.

## Sources, dependencies, and resolutions

Leaf `DATA_SOURCES.md` files define source authority: Sentinel-2 generic seagrass, configured kelp
inventories, dbSEABED rocky substrate, and generalized mapped bivalve beds. All families process
at R8 and aggregate explicitly to R6 on canonical marine support. Water-network distances and
5-km quantities use the canonical graph.

## Commands

```bash
python -m seascape.biogenic_habitat.composite.download
python -m seascape.biogenic_habitat.seagrass.build
python -m seascape.biogenic_habitat.kelp.build
python -m seascape.biogenic_habitat.reef.build
python -m seascape.biogenic_habitat.composite.build
python -m seascape.biogenic_habitat.composite.inspect --resolution 6
```

## Artifacts and publication

Each family writes a normalized inventory, R8/R6 features, matching confidence tables, and a
manifest. Multi-output publication stages and validates the complete set before promotion; the
manifest is the final commit marker.

## Missingness, QC, and R8 to R6 aggregation

Mapped presence, explicit absence, and unsurveyed are mutually exclusive. Zero area alone is not
absence. Deep coral/sponge remains null with explicit unavailability. R6 area is summed, fractions
are recomputed from child water area, distances use minima, local maxima remain maxima, and
persistence follows surveyed-year or source-basis weighting without mixing evidence bases.

## Inspection and validation

Inspectors expose each ecological family and confidence state separately. Validation covers
three-state evidence, fraction bounds, feature-aware aggregation, graph lineage, complete support,
and no accidental family collapse.
