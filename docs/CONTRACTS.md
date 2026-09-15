# Scientific and source contracts

## Ownership and inputs

The toolkit owns source acquisition and normalization, physical calculations, validation, product
catalogs and transactional releases. Applications own ecological interpretations, observation
processes and modeling. The checked-in configuration defines a regional case study; it is not a
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

Builds write to isolated candidates. Resume verifies configuration, upstream state and output
checksums. Release audit checks required family manifests, product schemas, policy and documentation
consistency, and water-network radius operators. Promotion uses atomic replacement and POSIX locks.
Weather products and weather policy are no longer part of a seascape release.

Reference catalog/policy files migrated from the original checkout describe earlier materialized
products; they are not a verified release of this new package. Regenerate these from the candidate
artifacts before promotion. Source geometry paths and formulas were not silently changed during
extraction. Full regional equality requires the retained rebuild comparison tool and source data;
that expensive acquisition/rebuild was not run during this migration.
