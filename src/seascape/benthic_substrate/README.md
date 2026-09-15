# Benthic substrate

## Purpose and non-goals

This family preserves modeled seafloor composition and a transparent derived hardness index. It
does not present interpolated dbSEABED values as direct survey observations or acoustic hardness.

## Sources, dependencies, and resolutions

The classification uses the pinned cross-border dbSEABED rock, gravel, sand, and mud rasters.
Bottom hardness is a deterministic weighted derivative. See leaf `DATA_SOURCES.md` files for
source versions, licensing, and interpretation. Both products publish native R8 and model R6
features with parallel confidence/evidence tables.

## Commands

```bash
python -m seascape.benthic_substrate.classification.download
python -m seascape.benthic_substrate.classification.build
python -m seascape.benthic_substrate.bottom_hardness.build
python -m seascape.benthic_substrate.classification.inspect --resolution 8
```

## Artifacts and publication

Each leaf stores inventory, R8/R6 feature and confidence tables, and a manifest beneath processed
`benthic_substrate/`. The complete family is staged and promoted before the manifest commit.

## Missingness, QC, and R8 to R6 aggregation

Raster nodata remains null and sets unmapped/evidence state. Fractions close only where modeled
composition exists. R6 composition uses contributing support and recomputes derived values; it is
not a blind mean of child fields. Confidence never upgrades modeled evidence to observation.

## Inspection and validation

Inspectors keep composition classes and hardness separate. Validation checks percentage bounds,
composition closure, confidence range, canonical H3 identity, finite outputs, R8 to R6 parity,
and source/artifact checksums.
