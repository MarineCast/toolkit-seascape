# Scientific and source contracts

## Ownership and inputs

The toolkit owns source acquisition and normalization, physical calculations, validation, product
catalogs, static feature eligibility and transactional releases. Applications own ecological
interpretations, observation processes, predictive feature/scale selection, temporal validation,
model fitting and evaluation. The checked-in configuration defines a regional case study; it is not a
claim of worldwide input coverage. Source-specific acquisition and licensing notes remain beside
each producer in `src/seascape/**/DATA_SOURCES.md`. Retain required source attribution and verify
redistribution rights before distributing any downloaded data. Software retains its originating
Apache-2.0 license; software licensing does not grant rights to source datasets.

## Identity, spatial support and units

Canonical gridded features use `H3_INDEX` and the documented H3 resolution. Full-cell, water-clipped,
and model-area support are different products. Preserve unique keys and explicit join cardinality.
Vector inventories retain their source IDs. Graph nodes, edges and parent-child tables retain their
own documented grain; do not join by row order. Preserve horizontal CRS and source vertical datum.
Bathymetry's `bathymetry_sign` distinguishes positive-down depth from negative elevation. Preserve
meter, square-meter, degree and dimensionless fraction units as declared in the catalog and each
producer. Neighborhood and aggregation scales remain explicit configuration.

## Coverage, time and missingness

These are mostly static source snapshots, not a time-varying forecast. Manifests carry source,
retrieval/build timestamps, configuration fingerprints, support versions and artifact checksums.
A source's publication vintage differs from acquisition time. Unknown, unavailable, disconnected,
not-applicable and observed zero remain distinct. Unreachable graph distances retain null values
and QC reasons. Survey coverage does not imply observed absence outside that coverage.

## Validation and publication

Producer tests retain dimensional, geometry, alignment, provenance, finite-value, missingness,
connectivity and duplicate-key checks. Manifest schema and release checks are retained from the
originating implementation. Source metadata's legacy `_orcacast` JSON key is retained for cache
compatibility; it does not import or depend on OrcaCast.

Builds write to isolated candidates. Resume verifies configuration, package code identity,
file-backed source/upstream identities, upstream state and output checksums. A changed commit or
dirty source-tree hash invalidates reuse. Release audit checks required family manifests, product
schemas, species-neutral feature eligibility, documentation consistency, and water-network radius
operators. Alternate physical scale groups are documented without blocking the physical release;
applications choose among them. Promotion uses atomic replacement and POSIX locks.
Weather products and weather policy are no longer part of a seascape release.

The checked-in feature catalog is reference metadata from an earlier materialization, not a
certified release. `seascape init` copies only editable producer configuration; candidate catalog,
feature eligibility and product documentation are regenerated from materialized candidate artifacts
before promotion. Source geometry paths and formulas were not silently changed during
extraction. Full regional equality requires the retained rebuild comparison tool and source data;
that expensive acquisition/rebuild was not run during this migration.

## Hardened calculation and release contracts

Composite feature and confidence tables must have identical unique, nonnull
`(H3_INDEX, H3_RESOLUTION)` support at the requested resolution. Confidence is aligned by keys
before masks or array calculations; missing support fails instead of reducing the output universe.

Terrain and sill calculations require explicitly configured positive-down bathymetry and reject
negative depth values. Missing depth remains missing. Planar meter/area calculations reject
geographic and non-meter projected axes. Q90 remains exactly the 0.90 quantile.

Native-raster slope supports one-band, unrotated north-up EPSG:4326 rasters of at least 3 by 3
pixels. Land and nodata are masked before gradients. Interior central-difference stencils with
land/nodata neighbors have no slope sample; raster edges use one-sided differences. Valid marine
samples are aggregated to H3. The angular-to-meter approximation is unchanged; this is not a new
geodesic derivative. The manifest records `marine_only_central_differences_v2` and edge/affine
policy. Coastal values and sample support may change; rebuild affected terrain products.

Release manifest schema 3 retains products, family manifests and governed metadata in a copied,
release-addressed generation. Publication transactionally commits this generation and the mutable
canonical compatibility paths. Product resolution returns generation paths, including after a later
release. Schema-2 workspaces must republish before using the resolver. No automatic generation
cleanup is provided; deleting or manually modifying retained files breaks their lifetime guarantee.
See [API contracts](API.md) and [remediation evidence](review-remediation.md).
