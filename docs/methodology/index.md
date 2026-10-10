# Processing and methodology

The workflow begins with reviewed source data and a selected marine area. It builds canonical water support, processes independent feature families, validates candidate products, then optionally promotes an audited release. [Workflow operations](../WORKFLOWS.md) describe command effects; [scientific contracts](../CONTRACTS.md) define the output obligations.

[Regional processing lessons](processing-lessons.md) record source semantics, precision and performance findings, regression evidence, and limits learned from bounded cached-source runs.

[Coarse-first v1 plan](coarse-v1-plan.md) defines the approved regional scope, source qualification, ownership boundaries and release acceptance ledger.

## Spatial support and units

- H3 R8 model-area cells have nonzero water overlap. R6 is the exact parent union of those R8 cells, including possible hierarchy-only parents. Full H3 geometry, water-clipped geometry, and model-area support have different meanings.
- Geographic source data and projected measurements retain declared CRS and vertical datum. Planar meter/area calculations reject geographic or non-meter projected axes.
- Bathymetry uses an explicit positive-down depth convention where configured. A source elevation value must not be silently treated as depth.
- Different products use different neighborhoods: direct pixel-to-H3 assignment, water-connected graph paths, configured metric distances, or source inventory overlays. A common H3 key does not make their support identical.

## How representative products are made

| Product | Processing choice | Consequence |
| --- | --- | --- |
| Bathymetry R8/R6 | Valid native marine raster pixel centers are assigned directly to each requested H3 resolution for all statistics, counts and depth bands. | A hierarchy-only R6 parent with no direct sample stays null. Native pixel spacing is not improved by H3 reporting. |
| Native-raster slope | Land/nodata are masked before finite differences; interior central differences need valid neighbors, edges use one-sided differences. | Coastal or nodata-adjacent slope support can be absent; the method is not a geodesic derivative. |
| H3 terrain curvature | A quadratic fit uses the H3 center and water-connected neighbors in a metric CRS, requiring a full-rank design. | Curvature and aspect can be undefined on flat or insufficient support; retain method-versioned signs and QC. |
| Shoreline character | Mapped segments are classified only when source labels support the class; fractions divide by classified length. | Unclassified length changes coverage and does not mean no shoreline. Overlapping classes need not sum to one. |
| Geometric fetch | R8 straight-line rays follow 16 bearings up to a configured limit. | A ray reaching the limit is censored, and fetch is not wind or wave exposure. |
| Substrate | Modeled dbSEABED rock presence and CoDA sediment texture are kept separate. | A point sample cannot establish areal coverage; unsupported fractions remain null. |
| Habitat evidence | Source footprints and survey opportunity are carried separately from mapped positives. | A positive-only map does not establish surveyed absence; R6 aggregation recomputes evidence by child water area. |

These are summaries of implemented methods, not substitutes for [the seafloor guide](https://github.com/MarineCast/toolkit-seascape/blob/main/src/seascape/seafloor_physiography/README.md), [coastal guide](https://github.com/MarineCast/toolkit-seascape/blob/main/src/seascape/coastal_configuration/README.md), and [family source notes](../data-sources/index.md). They state method versions and caveats in greater detail.

## Missingness, provenance, and publication

Unknown, unavailable, disconnected, unmapped, not applicable, and observed zero remain distinct. A null value must be read with its coverage/QC or status field and denominator. Source vintage, acquisition/build timestamps, configuration and code identity, manifests, and checksums support reproducibility. Candidate products are isolated; a completed schema-3 release is addressable by an immutable release ID. The [public API](../api/index.md) resolves exact product/resolution artifacts and validates checksums.
