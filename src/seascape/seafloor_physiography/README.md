# Seafloor physiography

## Purpose and non-goals

This family describes depth, terrain shape, and classified geomorphic units. It does not treat a
terrain class as habitat presence or collapse bathymetry and geomorphometry into an opaque score.

## Sources, dependencies, and resolutions

GEBCO bathymetry is processed against canonical marine support. Bathymetry is materialized at R8
and R6; geomorphometry and geomorphic units are R8 products. Geomorphic units consume explicit
depth/terrain inputs and are fully materialized, not planned work. Source authority and versions
remain in configuration and leaf manifests.

### GEBCO source rights (reviewed September 27, 2026)

The [official terms](https://www.gebco.net/data-products/gridded-bathymetry/terms-of-use)
place GEBCO grids in the public domain with source acknowledgement, conditions and disclaimers;
this is not a CC BY or CC0 grant. Newly generated source and attribution records share that
statement and terms reference. Runtime metadata creation is offline. Historical manifests retain
their original labels and checksums; no archive migration is performed. Unknown providers retain
unverified rights, and synthetic fixtures retain their explicit software/fixture attribution.

For the configured [GEBCO 2026 release](https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2026-grid),
acknowledge GEBCO Bathymetric Compilation Group 2026, the GEBCO_2026 Grid, NERC EDS BODC NOC,
DOI `10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa`. Cite the matching release's documentation
for other configured releases; never substitute the 2026 DOI for another grid. Grid spacing is
not measurement accuracy. These data are unsuitable for navigation or safety at sea; do not imply
provider endorsement. Source-data rights are separate from toolkit-seascape's Apache-2.0 license.

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

## Geomorphic classification method v2 (scientific hardening)

The classifier treats missing required inputs as ineligible for that class. A row with no
positive eligible class is `UNCLASSIFIED`, with `CLASSIFICATION_QC_REASON` set to
`depth_unavailable` or `insufficient_evidence`. `CLASSIFICATION_CONFIDENCE` is a bounded
heuristic support score for the **published** label, including any minimum-mapping-unit
change; it is not a calibrated probability. Missing width does not imply a narrow channel,
missing slope does not imply flat terrain, and missing contour/sill distance does not imply
proximity. When broad-neighborhood variance is zero but focal prominence is nonzero,
standardized broad terrain position is undefined rather than neutral.

This changes label, confidence, and QC semantics from historical outputs. Existing immutable
releases keep their original meanings. Build a fresh candidate and use its method-versioned
manifest for new results; do not reinterpret old labels as v2.
