# Seafloor physiography

## Purpose and non-goals

This family describes depth, terrain shape, and classified geomorphic units. It does not treat a
terrain class as habitat presence or collapse bathymetry and geomorphometry into an opaque score.

## Sources, dependencies, and resolutions

GEBCO bathymetry is processed against canonical marine support. Bathymetry is materialized at R8
and R6; geomorphometry and geomorphic units are R8 products. Geomorphic units consume explicit
depth/terrain inputs and are fully materialized, not planned work. Source authority and versions
remain in configuration and leaf manifests.

## Commands

```bash
python -m seascape.seafloor_physiography.bathymetry.pipeline
python -m seascape.seafloor_physiography.geomorphometry.build
python -m seascape.seafloor_physiography.geomorphic_units.build
```

## Artifacts and publication

Products are stored beneath `seafloor_physiography/{bathymetry,geomorphometry,geomorphic_units}/`
in the processed seascape root. Single tables use atomic Parquet replacement and atomically write
their manifest last.

## Missingness, QC, and R8 to R6 aggregation

Raster nodata remains null. Depth-band fractions use valid contributing pixels as the denominator;
band pixel counts remain counts. R6 bathymetry is recomputed with feature-aware summaries rather
than averaging every R8 output column. No R6 geomorphometry or unit table is implied.

## Inspection and validation

Inspectors use shared basemaps and palettes while retaining terrain-specific legends. Tests cover
depth-band closure, finite geomorphometry, water-connected neighborhoods, classification rules,
schema contracts, and canonical support.
