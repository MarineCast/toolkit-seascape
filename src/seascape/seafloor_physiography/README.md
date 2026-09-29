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
band pixel counts remain counts. Every canonical bathymetry statistic at each resolution uses
the same direct pixel-to-H3 assignment. R6 means, quantiles, counts, and bands are computed from
the pixels assigned directly to R6, not from R8 children. A water-support cell with no direct
sample retains null depth, count, and band values; this includes hierarchy-only parents at H3
boundary disagreements. A completely nonoverlapping source fails instead of producing a
misleading all-null product. Earlier R6 releases could contain direct moments with hierarchical
counts; they remain immutable and must not be silently interpreted as the direct-support v2
contract. No R6 geomorphometry or unit table is implied.

Distances to requested isobaths use native-raster marching-square **segments** in the configured
metric CRS and H3 center straight-line distance, not a water-network route. A raster square is
eligible only when all four corners are marine and finite, so a segment cannot bridge land or
nodata. Four-crossing saddle squares use the bilinear-center sign to choose two segments.
`DISTANCE_TO_ISOBATH_*_STATUS` distinguishes a measured contour within the source crop from one
not found there. The latter has null distance while valid depth statistics remain available;
it cannot prove that a contour is absent outside the crop. Distances to contours near crop edges
are lower bounds on distance to the **nearest contour within the crop**, not globally complete
distances. Old point-crossing distances in retained releases keep their historical meaning.

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

## Geomorphometry curvature and flat-terrain method v2

Curvature fits a quadratic surface to negative-depth **elevation** at the H3 center and its
water-connected neighbors in the configured metric CRS. Horizontal x increases east and y north;
the H3 depth-slope `ASPECT` is the direction of increasing depth, clockwise from north. The
curvature derivatives are evaluated at the focal cell. First derivatives are dimensionless,
second derivatives and the reported curvatures are inverse metres. At least six independent
sample positions (full-rank quadratic design) are required. Plan, profile, and tangential
curvature are undefined on a flat fitted gradient. `GENERAL_CURVATURE` is the negative elevation
Laplacian, so a convex elevation dome is positive. `CURVATURE` retains the historical raw
elevation-Laplacian sign.

Let elevation derivatives be `p=z_x`, `q=z_y`, `r=z_xx`, `s=z_xy`, `t=z_yy`, and
`g=p²+q²`. For `g>0`, horizontal plan curvature is
`-(r q² - 2 s p q + t p²)/g^(3/2)`; tangential surface curvature divides that
same numerator by `g sqrt(1+g)`; profile curvature is
`-(r p² + 2 s p q + t q²)/(g (1+g)^(3/2))`. These names follow the distinction
between horizontal plan and surface-tangent curvature in the
[GRASS r.param.scale manual](https://grass.osgeo.org/grass-stable/manuals/r.param.scale.html)
and [GRASS r.slope.aspect manual](https://grass.osgeo.org/grass-stable/manuals/r.slope.aspect.html),
but the H3 fit and sign convention here are specified above and do not assert numerical
equivalence to either tool. Historical `PLAN_CURVATURE` used the tangential expression; new
candidates expose it as `TANGENTIAL_CURVATURE` and correct `PLAN_CURVATURE` under
`geomorphometry_curvature_tpi_v2`. Existing releases remain unchanged.

Zero-slope facets supply vertical normals to vector ruggedness even though aspect is undefined.
Standardized terrain position is zero only when focal position and neighbor variance are both
zero. A nonzero focal position with zero neighbor variance stays available in metres but has null
standardized value and `zero_neighbor_variance_nonzero_position` QC reason. This also propagates
as missing standardized evidence in geomorphic classification.
