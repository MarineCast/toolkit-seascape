# Spatial support

## Purpose and non-goals

This family defines the marine geometry and graph identity used by every seascape producer. It
does not create ecological predictors or infer water where source geometry is missing.

## Sources, dependencies, and resolutions

Configured U.S./Canadian territorial-water and land boundaries feed `water_geometry`. The H3
geometry and water-network builders produce canonical R8 support and its exact R6 parent union.
See [`water_network/DATA_SOURCES.md`](water_network/DATA_SOURCES.md) for source authority and
licensing. Graph edges are water-passable H3-neighbor segments; terminal connectors and component
lineage are published separately from reachability.

## Commands

```bash
python -m seascape.spatial_support.water_geometry.build
python -m seascape.spatial_support.h3_geometry.build
python -m seascape.spatial_support.water_network.build --overwrite
python -m seascape.spatial_support.water_network.inspect --resolution 8
```

## Artifacts and publication

Artifacts live under `data/processed/domain/environmental_layer/seascape/spatial_support/` and
include the territorial-water polygon, H3 geometry, R6/R8 support, passable edges, parent-child
crosswalk, and bounded neighborhoods. Multi-output builds stage the full set and write the
manifest last.

`H3_GRIDS_*` and `H3_GRIDS_CLIPPED_*` are broad R4-R8 geometry-build intermediates. The released,
cataloged spatial contract begins with `H3_MARINE_*`, `H3_MODEL_AREA_SUPPORT_*`, and the R6/R8
water-network products; model and family builders must not treat the intermediate grids as the
canonical marine universe.

## Missingness, QC, and aggregation

Partial water is retained. A dry R6 geometric parent may remain as a hierarchy-only identity.
Disconnected cells keep null network results and explicit connector/QC lineage; no infinity is
published. R6 support is derived from R8 parent identity, not a separate polygon fill.

## Inspection and validation

Inspectors use shared presentation settings and support bounded map extents. Validation checks
unique H3 identity, exact parent unions, edge symmetry/passability, finite weights, component
lineage, checksums, and canonical-support equality.
