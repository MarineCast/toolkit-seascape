# Bounded water-graph execution

Private edge and neighborhood iterators support regional source-relative processing without
accumulating every result dictionary in memory. Existing materializing functions remain compatible.
Edges retain native H3 adjacency, water-clipped representative points, WGS84 geodesic lengths,
100 m densification and the configured outside-water computational tolerance. Optional edge and
connector path evaluators must call the same water-path calculation against exact local source
piece unions; they cannot substitute center-only classification or unrestricted H3 neighbors.

Neighborhood batches select output source cells while keeping the complete input graph and
accepted terminal connectors available to each traversal. They preserve minimum hop count and
the minimum distance among paths with that hop count. Filtering graph context before traversal
would change the scientific method and is prohibited. Source lists must be unique members of the
input graph; batch sizes must be positive.
Partial-source validation checks every selected source and its self row while validating targets
against full canonical support. The default validator still requires all support sources.

Inputs and outputs retain the existing native R6/R8 support, edge, connector and neighborhood
grains, units and source rights. No acquisition, new source classification or metric definition is
introduced. A mapped passability tolerance is not a physical coastline accuracy claim. Source
extent, missing native area footprints and insufficient connector/halo context remain explicit;
bounded processing does not establish global graph completeness. A static two-hop depth anomaly
still requires finite native full-H3 mean depths for its compute context and preserves null values
when depth or valid neighbors are unavailable.

Validate streamed results against independently retained earlier graph artifacts before a
regional run, then pin code, source, settings and actual output bytes. Scoped data validation does
not certify completion of the full toolkit catalog. The validation notebook remains a bathymetry
client; these private execution helpers do not change its public workflow.
