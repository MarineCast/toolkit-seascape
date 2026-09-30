# Variable catalog

Use this page to choose a family, then consult the [full product and field index](../products.md) for checked-in names, units, resolutions, and output paths. That index is generated from `config/feature_catalog.yaml`, a **historical reference catalog**. It is not evidence that a field is present in a current audited release. A new candidate regenerates its own catalog from materialized artifacts.

| Category | Representative implemented fields or products | Source and support | Important interpretation |
| --- | --- | --- | --- |
| Bathymetry | `BATHYMETRY`, `BATHYMETRY_Q90`, `BATHYMETRY_PIXEL_COUNT`, depth-band fractions | GEBCO raster; direct native-pixel assignment to H3 R8 and R6 | Depth is positive down when configured; a cell without a valid marine pixel has null depth and count. |
| Terrain | `ASPECT`, curvature and terrain-position fields; geomorphic units | Bathymetry and water-connected H3 neighborhoods; R8 terrain/unit products | Derivatives depend on neighborhood support and method version. |
| Substrate | `SUBSTRATE_MODELED_ROCK_PRESENCE_SCORE`, sediment texture fields | dbSEABED modeled 0.1° rasters sampled at a water-support point | Rock score and sediment percentages do not form one observed composition. |
| Shoreline and coastal form | Shoreline distance and physical-character fractions, `GEOMETRIC_FETCH_*_M`, width/sill fields | Water/land geometry and mapped shoreline inventories; family-specific R8/R6 | Geometric fetch can be censored; unclassified shoreline is excluded from physical-class denominator. |
| Freshwater and water paths | River mouth, barrier, estuarine and water-network features | Reviewed inventories and canonical graph; family-specific R8/R6 | A disconnected route is null, not zero or straight-line distance. |
| Mapped habitats | Seagrass, kelp, reef and composite feature/evidence tables | Source inventories on marine support; R8 with explicit R6 aggregation | Presence, surveyed absence, partial evidence, and unknown area differ. |
| Built environment | Shoreline modification, pier, port and other mapped structure features | OSM/OpenSeaMap and jurisdictional inventories; R8/R6 | Distances and counts are limited by mapped source coverage. |

The exact availability of a field depends on the selected stage, regional inputs, release, and resolution. Use [product discovery](../API.md#consumer-facade) to inspect an audited release instead of assuming the historical file list applies to it.

## New optional structural products

The [SV-01–SV-07 reference](../structural-variables.md) documents selected outlets, nearshore transitions, passage sections, geographic gateways, coast complexity, and mapped habitat mosaic stages. Their registered product IDs, field equations, keys, support, and missingness are described there. They are **not** in the older checked-in catalog; all six producers are fixture tested, and no new regional candidate or audited release was run for them. Some outputs are long tables keyed by an object or class as well as H3; they are not automatically scalar predictor columns.

## Reading a field correctly

For a scientific or modeling use, check the candidate or release catalog and family manifest for:

1. **Identity and grain:** product ID, column name, H3 resolution, object key if present.
2. **Meaning and units:** sign convention, denominator, native source resolution, output support.
3. **Method:** source dependency, transformation, aggregation, method version.
4. **Evidence:** source vintage, rights, coverage/QC/status, missingness, uncertainty availability.

New candidate catalogs record detailed definitions and support metadata; older archived catalogs may lack them. Missing metadata means **not documented**, not zero uncertainty or complete coverage. See [metric matrix metadata](../metric-matrix.md) for namespaced export fields and [capability coverage](../capability-coverage.md) for deferred or unavailable work.
