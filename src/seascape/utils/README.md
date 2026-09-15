# Seascape utilities

`utils` contains source-agnostic infrastructure; it does not own ecological rules or publish a
feature family. Supported helpers are intentionally small and explicit.

## Public helpers

- `artifacts`: staged `PublishedArtifact` capture, `stage_parquet_family`,
  `portable_artifact_path`, manifest-v3 construction and strict checksum validation. The durable
  `TransactionalFamilyPublisher` primitive is owned by `seascape.core.artifacts`; the lock-aware
  seascape publisher and snapshot reader are owned by `seascape.publication`.
- `spatial`: `expanded_bbox_polygon`, `load_polygon_layer`, `project_h3_centers`,
  `prepare_water_land_context`, canonical-support alignment, and H3-set hashing.
- `acquisition`: generic habitat source loading/downloading and the common leaf CLI invocation.
- `habitat_configuration`: habitat configuration and canonical geometry alignment.
- `habitat_surface`: within-cell evidence metrics; `habitat_aggregation`: feature-aware R8-to-R6
  aggregation; `habitat_publication`: family orchestration. Graph-radius logic is owned by
  `spatial_support.water_network`.
- `values`: optional-text cleaning, row-record iteration, and deterministic pipe-delimited unions.
- `vector_inspect` and habitat inspector modules: shared basemap, scalar serialization, legend,
  routing, and output-writing primitives used by thin family inspectors.

Functions whose names begin with `_` are implementation details and are not supported APIs.
Compatibility-only wrappers and façade re-exports were removed in the manifest-v3 migration.

## Publication semantics

Callers stage every member, capture checksum and structural metadata from those exact bytes, build
the manifest from the captured records, then promote the artifacts and terminal manifest in one
journaled transaction. A stale manifest plus changed artifacts fails the independent release audit.

## Non-goals and validation

Utilities do not normalize a source ontology, decide habitat evidence, choose aggregation rules,
or style a family map. Tests preserve null and evidence states, reject incomplete publication, and
cover rollback, crash recovery, manifest-last promotion, and reader/writer isolation.
