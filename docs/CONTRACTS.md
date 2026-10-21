# Scientific and source contracts

## Ownership and inputs

The toolkit owns source acquisition and normalization, physical calculations, validation, product
catalogs, static feature eligibility and validated Parquet outputs. Applications own ecological
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

These are mostly static source snapshots, not a time-varying forecast. Embedded Parquet metadata carries source,
retrieval/build timestamps, configuration fingerprints, support versions and artifact checksums.
A source's publication vintage differs from acquisition time. Unknown, unavailable, disconnected,
not-applicable and observed zero remain distinct. Unreachable graph distances retain null values
and QC reasons. Survey coverage does not imply observed absence outside that coverage.

## Validation and publication

The optional [structural-variable contracts](structural-variables.md) define the
SV-01–SV-06 product grains, equations, R8/R6 support, source requirements,
missingness and fixture-only validation status. Their long-form object
relationships retain object IDs; they are not one-row-per-H3 predictor columns.
No regional materialization or independent ecological validation is inferred
from registration or a synthetic fixture.

Producer tests retain dimensional, geometry, alignment, provenance, finite-value, missingness,
connectivity and duplicate-key checks. Manifest schema and release checks are retained from the
originating implementation. Source metadata's legacy `_orcacast` JSON key is retained for cache
compatibility; it does not import or depend on OrcaCast.

Builds use isolated temporary computation paths. Resume verifies configuration,
package code identity, file-backed source/upstream identities and output checksums.
Producer checks and generated column contracts remain in force. Native H3 support,
key uniqueness and finite values are checked before flat output replacement.
Definitions, units, source context and missingness are embedded in each Parquet;
`catalog.json` records per-area update times and stable filenames. There are no data
release IDs, retained generations or release-promotion steps in normal builds.

The optional `research/` directory holds separately keyed named-object and long relationship
tables. It is outside the flat H3 area catalog. Area rebuilds and historical snapshot replacement
preserve its bytes; it must be a local directory without symbolic links. Other unexpected files
and directories still fail catalog validation. A study registry references canonical domain
products; study selection does not require a second copy of their tables.

The checked-in feature catalog is reference metadata from an earlier materialization, not a
certified release. `seascape init` copies only editable producer configuration; candidate catalog,
feature eligibility and product documentation are regenerated from materialized candidate artifacts
before promotion. Source geometry paths and formulas were not silently changed during
extraction. Full regional equality requires the retained rebuild comparison tool and source data;
that expensive acquisition/rebuild was not run during this migration.

## Hardened calculation and release contracts

Release audits now use audit schema 3 with an `audited_inputs` checksum inventory
covering processed artifacts, family manifests and governed scientific metadata.
Promotion requires a literal boolean PASS and the same inventory, rechecks after
taking the writer lock, and verifies the staged generation and compatibility copies
before committing. A changed or legacy unbound candidate must be audited again.
This does not change release-manifest schema 3 or invalidate already retained releases.

Passage method `passage_cross_section_shoal_candidate_v2` separates threshold runs
across below-threshold gaps. Complete bank status requires every clipped wet-interval
endpoint to lie on the supplied water boundary, away from section endpoints
(1e-7 m numerical tolerance). Passage-polygon extent alone cannot establish a bank.
Source water boundaries still need reviewed coverage. Complete area becomes null
when banks are censored; valid partial integral remains separate. Rebuild affected
passage products before a new scientific release; historical products are unchanged.

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

Historical release manifests can be read explicitly through `seascape.legacy_products`
while migrating old workspaces. Current output grain and storage are described in
[flat domain tables](metric-matrix.md); scientific qualifications are not upgraded
by that storage conversion.

## Source-derived research channel geometry

When an agency supplies names and shorelines but no passage boundary, an explicitly selected
research axis may follow the named channel shown by the source chart. Analyst-selected route
anchors are inputs, not published agency centerlines. A bounded metric grid searches only source
water; every resulting segment must be covered by the source water polygon. Grid spacing,
anchor displacement, processing extent, source hashes and geometry QA accompany the registry.
The analysis footprint is source water between declared endcaps; it is not the complete named
waterbody. Gateway sections use a contiguous water interval with both endpoints on physical
source banks. Islands and alternative channels remain in the canonical graph.

Nominal bathymetry diagnostics with unresolved contributing vertical datums are separately named.
They cannot populate qualified depth, cross-sectional area, depth-threshold width or sill fields.
Horizontal source-scale width and water-path results remain usable with their explicit limits;
research geometry does not establish navigation clearance, current shoreline accuracy or model
eligibility. Mapped and confirmed sills require separate evidence.

Legacy USGS NHD HU4 archives are a static reference alternative to unavailable map services.
Their NHDFlowlineVAA terminal fields may be entirely null. The native adapter uses an explicit
NHDFlow network-end record (direction 713, receiving identifier 0); direction 709 ending at 0
may be an extraction boundary and cannot establish a terminal. Conflicting network records stay
unknown. Repeated permanent IDs require matching geometry and feature/name attributes; conflicting
versions are quarantined with source occurrence IDs. Archive dates are not observation years.

Selected-outlet production detours compare geodesic graph/terminal route length with the WGS84
geodesic straight-line lower bound. Projected Euclidean distance is retained as a separate
diagnostic; projection scale cannot make a geodesic route artificially shorter than its detour
reference. The generic planar fixture API retains its explicit projected-distance mode when no
WGS84 coordinate fields are provided. Mixing partial geographic coordinate fields fails.

## Kelp extent cadence variants

The [canonical Kelp contract](kelp.md) has two scientific extent fields in one
static/dynamic area dataset. Full-native-H3 mapped polygon area, observed survey
years, All Time geometric union, undated source support and unknown absence are
separate quantities. Legacy current-habitat fractions and confidence products
are not regenerated from the All Time union.

## Seagrass All Time extent

The [Seagrass contract](seagrass.md) exposes only `SEAGRASS_EXTENT_ALL_TIME_M2`, presented as **Seagrass Extent (All Time)** within **Biogenic Habitats**. It is native H3 with a geometric union over all eligible history, not an annual product. Original WA observation years, BC map dates and composite periods remain provenance. Modeled generic seagrass remains distinct from mapped eelgrass methods/species resolution. Missing positive evidence is unknown; no contemporaneous fraction or surveyed absence follows. Both native resolutions use independently reconstructed full cells, edge-densified at 0.001° before EPSG:6933 measurement. Retired annual delivery has scoped rollback; its geometry is retained in All Time.

## Bivalve mapped-bed extent

[Bivalve](bivalve.md) exposes one static All-Time geometric union in m². Only documented mapped-bed polygon sources enter; generalized observation units, regulatory areas and potential habitat do not. Original dates remain provenance; no absence or completeness is inferred. The distinct producer identity remains `bivalve` within the Biogenic Habitats presentation.


### Presentation families (2026-10-20)

Biogenic Habitats exposes Annual Kelp Extent, Kelp Extent (All Time), Seagrass
Extent (All Time), and Bivalve Extent (All-Time). Mapped Substrate Classes joins
Substrate. Shoreline, Coast Complexity and Nearshore Transitions join Coastal
Environment. These are catalog groups, not numerical aggregation or producer
merges. Product IDs (including coast_complexity_r6/r8), feature IDs, units,
spatial support, temporal meaning, provenance and QC remain distinct. Nearshore
Transitions is the bounded shoreline/deep-water bathymetry and connectivity
product; Coastal Bounds and other similarly named products remain separate.
The delivery writer applies physical-family metadata; the app normalizes both
current and verified startup catalogs, preserving saved feature selections.


### Spatial Support public projection (2026-10-20)

The ten graph/connector/hierarchy fields in `SPATIAL_SUPPORT_OMITTED_FIELDS`
are omitted from flat public Spatial Support delivery, including linked public
qualifier lists. Native H3 support artifacts retain their full validated schema:
parent/overlap/boundary fields support hierarchy validation; graph eligibility,
connection status and QC support graph construction and diagnostics; connector
target, distance and water-path fraction support routing and validation. Graph
consumers use native processed support paths. No native field or graph is deleted
or rebuilt. Other fields, including graph degree and water fractions, remain.
Exact scoped app filters also prevent legacy startup catalogs from restoring these
selectable variables. Run tests/test_spatial_support_delivery.py and the native
water-network and network-consumer contract tests, then the full suite.


### Anthropogenic presence selectors (2026-10-20)

**Superseding public policy:** the user explicitly requested unknown/null values
be filled False for these four delivered booleans only. True cells are unchanged.
False means no mapped positive evidence, including unknown filled False, not
confirmed absence. Original nullable evidence is retained in hidden
`*_SOURCE_NULLABLE` columns and native source context. Features, Relationships,
startup adapters and serialized public values use the same policy. The source
evidence semantics described below remain applicable internally.


Aquaculture, Artificial Reef, Disposal Site and Dredged Channel each expose one
nullable boolean. Aquaculture and reef retain existing mapped-positive evidence
values and identifiers. Disposal Site and Dredged Channel are true only where
existing mapped polygon area is positive and the linked area QC is
`positive_mapped_polygon_inventory`; otherwise they are null. These describe
mapped evidence, not activity. No absence is inferred from zero area or missing
evidence. Aquaculture evidence is qualified mapped point intersection, not
regulatory growing areas or polygon footprints. The current reef evidence is
all unknown. No false absence evidence exists in the original nullable source; public False fill is an explicit display policy.

The ten requested retired selectors and other measures/QC for these four groups
are picker-hidden metadata, not deleted source columns. Their original arrays,
geometry identifiers, source context and inspector qualifiers remain available
for processing. Exact family-scoped app adapters normalize verified startup and
current catalogs; old numeric area/distance fields are never relabeled boolean.
The public delivery writer applies `anthropogenic_presentation` idempotently.


Anthropogenic QC selector follow-up: comprehensive survey coverage established,
full H3 within source rectangle, generalized fallback, global inventory complete,
native land footprint unknown, network distance QC reason, observation period and
overwater QC are no longer selectable layers. All eight columns and their values
remain as internal/inspector context, including routing QC and unknown-coverage
semantics. This policy is scoped to Anthropogenic: duplicate display labels in
Coastal Environment, Estuary, Substrate, Coastal Bounds, Fluvial Connectivity and
Waterbody Morphometry are unchanged. The four presence booleans are unchanged.
