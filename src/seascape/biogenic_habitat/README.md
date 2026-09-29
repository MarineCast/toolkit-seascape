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

Mapped presence, explicit absence, unknown area, and mixed/partial evidence are separate states.
Zero area alone is not absence. `PRESENT_AREA_FRAC`, `ABSENT_AREA_FRAC`, and `UNKNOWN_AREA_FRAC`
close on water support; point/line observations retain presence evidence without inventing area.
Only an explicitly registered complete survey-event footprint supplies surveyed area or inferred
absence outside mapped positives. Presence-only annual polygons leave survey completeness unknown.
The as-of year filters future observation periods and known availability years before exports;
unknown source availability means historical outputs are retrospective, not operational replay.
Different survey years can form a last-known spatial mosaic, labeled `spatiotemporal_mosaic`, not
a contemporaneous complete survey. R6 evidence fractions are recomputed by child water area;
one absent child beside an unknown child is partial absence. Deep coral/sponge remains null with
explicit unavailability. Persistence uses actual registered survey opportunity or its separately
labeled source basis, never treating positive-only map years as complete survey years.

## Inspection and validation

Inspectors expose each ecological family and confidence state separately. Validation covers
partial evidence, fraction closure, feature-aware aggregation, graph lineage, complete support,
and no accidental family collapse. Retained releases keep their historical three-state columns;
the v2 observation-state fields and method identity distinguish new candidates.
