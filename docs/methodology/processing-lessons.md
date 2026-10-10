# Regional processing lessons

These findings come from bounded cached-source processing and independent review through
2026-10-07. They describe the established regional native R6/R8 support, not toolkit-wide
certification or complete source coverage. Keep scientific code pins, source hashes, resource
measurements and release manifests with each result. Publication status belongs to the publication
receipt; an offline test pass alone does not qualify a regional product.

## Scientific findings and next-run rules

| Finding | Evidence and consequence | Next-run rule |
| --- | --- | --- |
| Shoreline records repeat and classes overlap. | The source retained 27,009 repeated records. Physical lengths use geometric unions; classified and unclassified evidence can coexist. Nonexclusive class fractions can sum above one. | Preserve all source records, union physical lengths, and never remove nearby distinct lines or force exclusive classes. See [shoreline regressions](../../tests/domains/environment/seascape/test_shoreline_characterization.py). |
| Shellfish harvest regulation is not a physical aquaculture inventory. | All 434 WA Coastal Atlas harvest/water-quality polygons were excluded from physical area and presence. This restored 51 OSM aquaculture records previously suppressed by regulatory zones. The remaining 990 canonical physical records are points/centres; no qualified footprint polygons remain. | Keep regulatory classes separate. Aquaculture footprint fractions remain NULL; zero mapped polygon area is only an inventory diagnostic. Approved and Prohibited zones must both fail to establish physical presence. See [source notes](../../src/seascape/anthropogenic/DATA_SOURCES.md) and [regressions](../../tests/domains/environment/seascape/test_anthropogenic_contracts.py). |
| Terrain derivatives need deeper source support than the reported neighborhood. | A four-hop slope neighborhood needs five-hop depth support. An initial 14,275-neighborhood sample was followed by checks of all 6,428,019 relevant neighborhoods. Some primary outputs remain censored. | Preserve source-context and neighborhood QC. Native R8 terrain companions do not justify inventing R6 terrain values. |
| H3 membership does not imply complete hierarchy aggregation. | Reporting-cell census found 21 R8 parents outside the R6 reporting set and two R6 cells without reporting R8 children. Different products also use full-cell versus water-clipped support. | Recompute each native resolution using its declared support; never infer complete parent coverage from the reporting subset. |
| Reporting-clipped fallback annotations do not describe the full compute halo. | Reconstructing native fine-scale ENC/CanVec support corrected fallback annotations: 540 R6 and 1,875 R8 reporting flags changed. Old fallback touched 21 compute tiles; full compute support touched 37. | Qualify source priority over the actual compute support. Retain graph bounds and censoring; a finite graph does not establish global reachability. |
| Missing coverage is not observed absence. | Positive habitat polygons, OSM inventories and source point scores lack a complete survey opportunity denominator. Rock presence is not areal sediment texture or hard-bottom fraction. | Keep unknown values NULL. Distinguish mapped inventory zero from survey-qualified absence. Bottom hardness stays unsupported without joint areal rock/sediment support. |
| Time fields have different meanings. | OSM edit years are not physical construction dates. Acquisition/compilation dates do not date habitat observations. WA kelp annual layers cover 1989–2024 except unsurveyed 1993. | Preserve observation, edit, compilation and acquisition dates separately. No daily forward-fill, invented missing years, backdated modern observations or duplicate annual static files. |
| Native resolution and units are not accuracy claims. | GEBCO 15-arcsecond spacing is not uniform shallow-water accuracy. Elevation and positive-down depth retain their sign and vertical datum. Nine terrain field unit labels were corrected while all five scientific Parquet tables remained byte-identical. WA kelp native EPSG:2927 uses US survey feet. | Verify axis conversion, depth convention and datum before measuring. Treat metadata corrections separately from scientific value changes. |
| Projection and overlay precision need bounded qualification. | Eight native-valid water geometries became invalid after projection. Qualified repair changed area by at most 0.0064 m²; new vertices stayed within 6.69e-10 m of original boundaries. Kelp annual sources contain 1,885 touching/self-touching native rings; guarded topology normalization changed filled area by at most about 9e-9 m². | Preserve original source bytes and geometries. Record validity reasons, area change and vertex checks; reject material changes. Do not use unbounded whole-coast Hausdorff checks as the routine guard. |
| Large projected coordinates can affect overlay order. | A kelp sample differed by 0.000108 m² between union-then-clip and clip-then-union. Translating all inputs around the same cell centroid reduced the difference to 1.46e-11 m² under the original tolerance. | Use a shared local origin while preserving metre units and geometry. Do not relax tolerances, snap or resample merely to pass parity. |
| Source geometry may block only part of a family. | The WA generalized kelp persistence file contains 34 native-invalid records among 105. Annual bed polygons describe planimeter bed extent including small gaps, not pure canopy pixel area. Spatial map indices are statistical units, not qualified annual full-H3 survey footprints. | Keep generalized persistence spatial overlays blocked pending qualification, retain raw evidence, and continue separately qualified annual positive evidence. Preserve provider tabular summaries at their native unit/year grain. |
| Helpers need independent regional checks. | A shoreline tile-edge helper omitted 375.78 m of source line. Every one of the 88,243 R8 distances was checked: the omission had zero numeric effect, with the retained nearer shore at least 0.43469 m closer in the limiting comparison. | Fix the helper before reuse; the prior zero-impact check does not establish correctness in a different domain. |

## Performance and validation lessons

Measured single-worker regional runs used about 617 MiB RSS for terrain (229 seconds),
1.15 GiB for anthropogenic leaves (42 seconds), and 1,003 MiB for the aquaculture repair
(12 seconds). These are measurements for the retained source/domain combination, not generic
capacity guarantees. Coordinate memory before launch and check stage size during execution.

An initial scalar anthropogenic pilot suggested roughly two hours. Exact 10 km Cartesian water
subdivision reduced regional overlays to seconds without smoothing or changing the scientific
support. Its 3,116 parts closed source area to within 2.67e-5 m²; independent checks also used
20 km subdivision. Whole-water intersection and whole-coast Hausdorff attempts were too costly
and were stopped. Estimate from the final qualified algorithm, while retaining failed-run evidence.

The aquaculture repair checked all 90,864 native presence rows and all 474 OSM aquaculture
matching decisions independently; the other 46 metric columns were Arrow-equal to the previous
candidate. The source fix passed 700 tests with three expected materialized-data skips, plus the
required lint, formatting, typing and documentation checks. Initial failures exposed an older
installed wheel when source imports were not selected, and a packaged configuration copy that
had not been synchronized. Pin the runtime/import root and check both configuration copies.

## Evidence and current review boundaries

Published partial releases have checksummed provenance under these release-relative locations:

Resolve `releases/` and `publication-receipts/` references below from the intended `Data/seascape`
root. Resolve candidate `provenance/` references from that frozen candidate's root. Markdown
source/test links resolve within this repository; they do not require a private workspace path.

| Capability | Release/evidence location | Remaining boundary |
| --- | --- | --- |
| Native bathymetry and water support | `releases/seascape_native_bathymetry_20261006_v2/` | Source spacing, source extent, shallow-water accuracy and datum qualifications remain explicit. |
| Shoreline and depth-contour distance increment | `releases/seascape_distance_increment_20261006_v1/` | Crop uncertainty remains; repair the tile-edge helper before reuse. |
| Water graph and depth anomaly | `releases/seascape_watergraph_depth_anomaly_20261006_v1/provenance/` | Bounded traversal, full-compute fallback support and primary censoring remain explicit. |
| Physical shoreline | `releases/seascape_physical_shoreline_20261006_v2/provenance/` | Source mapping coverage and nonexclusive classes remain explicit. |
| Native R8 terrain | `releases/seascape_native_r8_terrain_20261006_v2/provenance/` | Native R8 companion scope, derivative support and corrected field units remain explicit. |
| Physical anthropogenic leaves | `releases/seascape_physical_anthropogenic_20261007_v2/provenance/` | Regulatory exclusions, point-only aquaculture evidence, unknown footprint fractions/dates and uncomputed network metrics remain explicit. |
| Annual mapped kelp bed evidence | `releases/seascape_annual_kelp_mapped_bed_evidence_20261007_v2/provenance/` | Actual survey years and three processing eras; positive bed extent rather than canopy/absence; current static water mask; generalized persistence remains blocked. |

The repaired anthropogenic release `seascape.physical-anthropogenic-leaves.20261007.v2`
passed independent narrow review and was published atomically without recomputation. Its 37-file manifest SHA-256 is
`ed2df99962b9bfa7490cf1577f80850d2ba02c3d868e34cfdff97f5f7a7403f2`;
scientific code is pinned to `5634dc93e9f06ee414d091bd17c07fb3b8e0b330`.
Its `provenance/` retains the repair and independent validation; the publication receipt is
`publication-receipts/seascape_physical_anthropogenic_20261007_v2.json`.
All five prior releases passed checksum preservation checks. Later documentation edits do not
replace the scientific code pin or mutate the release.

The kelp pilot independently validated 50 R6 and 150 R8 cells across 35 actual survey years:
7,000 cell-year rows, 3,949 mapped-positive intersections and 200 static date envelopes. Raw-source
checks covered 210 scalar area samples and 105 original native geometries; all-row missingness,
date and uniqueness checks passed. The run used 31.5 seconds, 664 MiB RSS and 13.2 MiB staging,
with no acquisition. Its manifest SHA-256 is
`254d90531d0de4f6b1613bf66556002fad747a09f6de7bf9e6d12c6ce7eeec1b`.

The actual annual source bounds are approximately 124.825°W–122.633°W, 47.662°N–48.900°N,
narrower than the full regional reporting domain. Conservative bounding rectangles identify 423 R6
and 14,712 R8 candidates; these counts are not surveyed coverage. An unfiltered scalar extrapolation
exceeded one hour. Exact source-to-cell STRtree intersections reduced actual nonempty joins to
17,632 cell-years, and streaming Arrow row groups avoided millions of Python dictionaries. The
authorized regional run took 56.1 seconds, 767 MiB RSS and approximately 60.7 MiB final staging,
well below the approved caps. This speedup retained exact geometry, local-origin measurements,
duplicate unions and the original tolerances. Estimate resource demand from the qualified sparse
join algorithm rather than extrapolating empty-cell scalar work.

The regional candidate contains 3,180,240 annual cell-year rows, 90,864 static observation-date
envelopes and all 34,095 original annual source records. Independent validation checked every
cell-year invariant and date envelope, all original native geometries/properties and normalized
WGS84 geometries, 7,000 pilot numeric comparisons, and 700 raw-source scalar area samples.
The independent checker took 9.3 seconds and 1,035 MiB RSS. Maximum sampled area difference was
5.23e-7 m² under the original tolerance. All raw source and GDB component hashes passed readback.

External review found one processing-history annotation defect: 363,456 rows for 1989–1992
were labelled as 20 m raster processing. Provider metadata instead specifies vector/CAD in
1989–1992, unsurveyed 1993, approximately 20 m raster in 1994–2009, and approximately 4 m
raster in 2010–2024. The repair clarifies all three era strings while preserving the other 16
annual columns exactly and all five unaffected Parquet artifacts byte-for-byte. No geometry or
area was recomputed. The local era fix is pinned to `cf712b188045683df8976bc41674e041ce5983b6`;
the original numerical code identity remains separate. Ten era regressions and the full suite
of 710 tests passed, with three expected skips and the required quality/documentation checks.

Corrected release `seascape.annual-kelp-mapped-bed-evidence.20261007.v2` passed narrow external
review and was published atomically without numerical recomputation. Its 35-file manifest SHA-256 is
`9bf67f2d19161f04ef593f1035ac257e87cc12c1348f4eb9af222dbf26c3e8ea`.
The publication receipt is `publication-receipts/seascape_annual_kelp_mapped_bed_evidence_20261007_v2.json`;
all six earlier releases passed preservation checks. Portable evidence locations inside the release are `provenance/EXECUTION_ACTUALS.json`,
`provenance/INDEPENDENT_VALIDATION.json`, `provenance/METRIC_DEFINITIONS.md`, and
`provenance/SOURCE_HASHES_RIGHTS_COVERAGE.json`, `provenance/PROCESSING_ERA_REPAIR.json`, and
`provenance/PROCESSING_ERA_INDEPENDENT_PARITY.json`. Source topology and original native WKB remain
auditable. Outside the annual source extent, surveyed absence stays unknown. No complete
kelp-family claim, qualified H3 absence, generalized persistence overlay, daily forward-fill or
network distance is established. Provider statistics remain at their native unit/year grain.

## Next coastal mechanisms: inspection findings, not regional results

The implemented [exposure builder](../../src/seascape/coastal_configuration/exposure_and_enclosure/build.py)
and [waterbody builder](../../src/seascape/coastal_configuration/waterbody_morphometry/build.py)
are native R8 only. Their defaults request a 60 km graph buffer, 112 km fetch-mask buffer and
122 km land guard. The current qualified water partition covers the study rectangle and the
retained graph has a five-ring compute halo; these are not equivalent contexts. The cached global
Natural Earth baseline is available as a separately labelled generalized source, not an automatic
fine-source extension. No regional coastal run is qualified by default builder availability.

The [ray sampler](../../src/seascape/spatial_support/water_network/geometry.py) checks water
coverage every 100 m on each WGS84 geodesic bearing, returning the last covered sample before
the first uncovered sample. Thin barriers can be missed, and a clipped source rectangle can be
mistaken for shore unless its first exit is classified explicitly. Despite the builder descriptions,
the ray calculation uses the water geometry, while the prepared land mask is not passed to it.
Preserve the sampled method and source-edge uncertainty; do not silently substitute an exact
intersection result or describe these distances as wind/wave exposure.

Local water-space area sums full H3 cell areas over an eight-hop passable graph neighborhood.
Its perimeter counts missing internal graph adjacencies using the average R8 hexagon edge length.
These are graph footprint proxies, not clipped physical water area or mapped shoreline perimeter.
Five-hop constriction depends on surrounding sampled widths. Open-water, narrows and algorithmic
sill distances also require qualified seed opportunity and graph closure. Current default manifests
hardcode complete source coverage, which does not describe this mixed-source bounded domain.

The authorized 128-cell R8 diagnostic pilot completed in 38.1 seconds at 1,132 MiB peak RSS,
with roughly 115 KiB initial output. Separate independent validation took 22.1 seconds at
1,033 MiB RSS. The final review bundle is about 175 KiB; total added staging stayed below
1 MiB, with zero acquisition. No full builder or broad halo build was invoked.

All 2,048 target rays and their origin/cap/source-edge classifications passed independent checks.
There were 94 source-extent exits, 577 configured-limit censored rays and 16 origin-not-water
rays from one unmapped H3 centre. A synthetic 10 m barrier between sample stations was skipped.
Among 254 numeric one-kilometre continuous references plus two invalid-origin cases on
one-metre-densified geodesics, three real rays
skipped mapped land intervals of 5.92, 8.26 and 21.36 m. Gap midpoints were independently verified
against the retained native land layer. For example, cell `8812981ad9fffff` eastward sampled
fetch was 1,000 m, while the first continuous mapped-land exit was 252.03 m. This is evidence
about mapped geometry, not physical survey accuracy. Sampling error is not bounded by 100 m
when a barrier falls wholly between stations.

Independent validation also checked 254 five/eight-hop graph neighborhoods and 127 graph-footprint
area/perimeter/frontier-branch calculations. Eight-hop local source-census and connector checks
qualified 81 target closures within the retained source-relative graph. These graph footprint
proxies are defensible under their declared meaning; they remain distinct from physical water
area and shoreline perimeter. All primary fetch, network, sill, physical-area/perimeter and
constriction products remain NULL or uncertified. The 127 sampled constriction diagnostics are
not observed nonconstriction or publication-ready primary values.

The candidate-facing diagnostic source contract explicitly records partial coverage and inherits
the bound upstream mixed ENC/CanVec/Natural Earth attribution and rights. Five offline contract
regressions prevent unqualified complete coverage or a generic provider replacement. The default
full builders remain unqualified and were not used to construct this diagnostic bundle.

Diagnostic bundle `seascape.coastal-mechanisms-diagnostic.20261007.v1` has 19 checksummed files;
manifest SHA-256 is `0c414b8a49ecab7fa29cc45b099c4d3e12017ec60318ba826dbe7da1de6d7d91`.
Evidence locations within that bundle are `SYNTHETIC_THIN_BARRIER_CHECKS.json`,
`SHORT_RANGE_CONTINUOUS_GEOMETRY_REFERENCES_R8.parquet`, `INDEPENDENT_VALIDATION.json`,
`GRAPH_NEIGHBORHOOD_SOURCE_CERTIFICATES.json`, `SOURCE_CONTRACT.json` and `RECOMMENDATION.json`.
These references resolve from the diagnostic bundle root, which is separate from published releases.

The separately versioned continuous first-exit diagnostic subsequently completed on the same
128 R8 targets. It intersects a WGS84 geodesic polyline with native mapped water and the registered
source extent, preserving the legacy sampled values alongside it. Source-edge exits and configured
caps are censored bounds; origin-not-water distances are NULL. Thirteen narrow-barrier, domain-edge,
censoring and context-binding regressions passed. No default toolkit method was substituted.

All 2,048 full rays passed independent intersection/difference comparisons. The 254 numeric short
one-metre-densified references differed by at most 0.000414 m; two further cases check invalid
origins. Sixteen full-ray ten-metre-densified
references by at most 0.000150 m. These checks share GEOS/Geod and qualify numerical geometry
agreement, not survey accuracy. Legacy sampling exceeded continuous first exit by more than
100 m on 112 rays; the maximum was 48,624 m. Continuous results include 91 source-edge exits,
572 configured caps and 16 origin-not-water rays. Only 31 targets have mapped endpoints on all
eight opposed axes; 104 have every ray within registered source context.

The main diagnostic took 155.0 seconds at 685 MiB RSS. Independent artifact readback and a
64-ray producer benchmark took 15.2 seconds at 811 MiB RSS. The benchmark covers eight stress
cases, not a representative regional sample. Its mean 0.03079 seconds per ray extrapolates to
8.2 minutes for 1,000 targets and 12.1 hours for 88,243 targets; adding dual geometry comparisons
extrapolates to 18.3 minutes and 27.0 hours respectively. New context, graph work and review are
excluded. The regional run remains held. Added diagnostic staging stayed below 1 MiB with zero
acquisition. A proposed read-only context preflight has an unmeasured engineering budget of
2–10 minutes, 32 MiB staging and 1,536 MiB RSS; it has not started.

Diagnostic v2 has 19 checksummed files and manifest SHA-256
`48d911b5b101dd1c538b1b191371e13f18e4cd3bbb4ab8f6c5b606a4d582b517`.
Its bundle-root evidence is `CONTINUOUS_FIRST_EXIT_V2_WITH_LEGACY_R8.parquet`,
`LOCAL_CONTINUOUS_GEOMETRY_DIAGNOSTICS_R8.parquet`,
`FEASIBILITY_AND_INDEPENDENT_READBACK.json`, `METHOD_DEFINITIONS.md` and
`RECOMMENDATION_AND_MINIMUM_CONTEXT_PLAN.json`. The bundle binds the exact executed method
snapshot and an AST-equivalent comment clarification. All primary physical fetch, width and
network products remain unqualified. Full fetch beyond the current rectangle
requires separately adopted geometry extent/rights/priority coverage; cached global Natural Earth
can support an explicitly generalized comparison, not fine coastline or small-island accuracy.
Global network distances need qualified seed opportunity and traversal context. Their broad halo
cost is unmeasured and requires a separate source/member-count preflight. No R6 coastal metric,
physical hardness, missing source footprint or reviewed passage registry is inferred.

The bounded performance preflight tested two exact polygon-piece STRtree chunk variants and an
unchanged native-boundary index. All 4,096 chunk checks passed within 1.69e-9 m of the frozen
continuous reference. One-kilometre chunks took 123.4 seconds; five-kilometre chunks took 27.6
seconds. Smaller chunks can cost more through repeated geometry operations.

Indexing 31,659 fragments of at most 64 original boundary edges retained all 1,436,639 native
coordinates. Exact ray/boundary events partition the identical geodesic polyline; prepared water
and registered-extent midpoint checks identify its first uncovered interval. All 2,048 statuses
and distances matched the reference exactly. Five synthetic regressions cover thin barriers,
crop edges, caps, invalid origins, tangencies, boundary travel and internal seams. Setup took
14.0 seconds and rays 1.05 seconds, with 755 MiB peak RSS. A naive stress-sample regional
extrapolation is 12.1 minutes, excluding validation, context and review. No regional run or default
method change occurred. A representative distribution preflight remains the next performance gate.

Rectangular centroid counts size the proposed context, not marine support or certified geodesic
buffers: R8 counts are 861,579 for the approximate 60 km graph rectangle, 1,120,563 for the
112 km water rectangle and 1,174,152 for the 122 km land guard. The current graph has only
139,661 raw candidates. Broader graph cost remains unmeasured; seed opportunity, connector
closure and mapped geometry registration are separate artifacts. Global Natural Earth is cached,
but detailed ENC/CanVec source bounds do not span these wider rectangles. Existing nonarea land
records do not establish island footprints. New fine-source transfer bytes cannot be bounded
honestly until missing coverage polygons and native source members are selected.

Freshwater sources offer a cheaper independent scoped increment. Cached BC FWA and US NHD were
queried around the old domain, not the expanded reporting rectangle; their filters and query
extents must survive into missingness flags. HydroRIVERS is already extracted. The freshwater
builder loads the 322 MB BC GeoJSON before clipping, so a bounded implementation needs windowed
or streaming reads. Configured two-metre mouth widths are defaults, not observations. Mapped-mouth
straight distance and unweighted pressure do not require fetch or global marine network closure;
full physical nearest-mouth and upstream connectivity claims remain gated. A proposed 128-target
pilot is an unmeasured 5–15 minute, 16–64 MiB staging, 1,536 MiB RSS, zero-acquisition task; it
has not started.

The performance/source-context review bundle has 16 checksummed files; manifest SHA-256 is
`5bfdbe5ccfb9919d4395b7e05e9e5f0caa3eb4956c439eef4a4eb693cb0bfe99`.
Bundle-root evidence is `BOUNDARY_INDEX_PARITY.parquet`, `BENCHMARK_PARITY.parquet`,
`SOURCE_CONTEXT.json`, `coastal-boundary-index-preflight-tests.log` and
`IMPLEMENTATION_AND_SOURCE_CONTEXT_PLAN.json`. Zero acquisition and no halo build occurred.

The subsequent 1,000-target indexed pilot covered all 201 spatial/source-flag strata, including
the prior 128 stress cases and 872 additional deterministic targets. Every one of 16,000 rays
matched the continuous reference exactly; 512 difference-based checks agreed. Separate readback
verified every row's grain, censoring, primary NULLs and source bindings, plus exact preservation
of the prior 2,048 values/statuses/origins. There are 453 source-edge rays, 4,264 caps and 64
invalid-origin rays from four targets. The purposeful selection remains distinct from a random
population sample. Producer ray time was 8.13 seconds; reference ray time was 435.6 seconds.
Total pilot time was 480.7 seconds at 850 MiB RSS. A current-mask regional producer extrapolation
is 12.0 minutes; all-ray reference comparison would require about 10.7 hours. A proposed regional
diagnostic needs prespecified stratified independent QA and all-row contracts, with an unmeasured
engineering budget of 15–45 minutes and 64–128 MiB staging. No regional run is cleared or started.

That review bundle has 16 checksummed files and manifest SHA-256
`fc53c113daf3709b56503652b2f82016fd4561b6a58f1b0a4c3b41a62cd735d0`.
Bundle-root evidence is `CONTINUOUS_FIRST_EXIT_1000_TARGET_DIAGNOSTIC_R8.parquet`,
`TARGET_SELECTION_R8.parquet`, `EXECUTION_AND_PARITY.json` and `INDEPENDENT_READBACK.json`.

The 128-target freshwater pilot subsequently retained 7,323 algorithmic native endpoint candidates:
6,107 BC FWA, 506 supported US NHD and 710 HydroRIVERS. These are inferred mapped candidates,
not observed physical marine mouths. Of the BC candidates, 6,016 have zero downstream measure;
91 have nonzero minima in the retained cache, which cannot establish true terminals beyond its
query context. The NHD mask excludes 11 Coastline and three CanalDitch records. ArtificialPath
is a source representation, not evidence of a physically artificial channel. HydroRIVERS sources
within 5 km of detailed candidates are retained separately as 997 suppressed records.

Both native endpoints remain available for point-placement review; no line clip or snap creates
an outlet. The existing 1,500 m marine-water proximity rule and a conservative source-edge guard
define the diagnostic selection. The edge-exclusion table contains only the first 1,000 exclusions;
complete pass counters and unchanged bound raw caches preserve the broader evidence. Straight
distance and the sum of 5 km exponential proximity kernels describe this retained candidate
inventory. They are not discharge, actual nutrient pressure, true river density or water-network
connectivity. Widths are NULL; configured 2 m assumptions occupy separate fields.

All 128 independent scalar nearest-distance and summed-kernel checks passed. All 7,323 native
endpoint placements, source geometries, BC route minima, supported US taxonomy and HydroRIVERS
precedence checks passed. The 255 scalar coast/endpoint checks agreed exactly. However, the valid
native water union becomes invalid after EPSG:32610 projection: the first self-intersection is
at [445965.216998321, 5549899.14158011], inverse longitude/latitude
[-123.75552412735877, 50.098889890207666], only 2.52e-18 degrees from the valid native boundary.
Retained endpoint membership disagrees on zero native/projected cases. Numerical parity does not
clear projected topology. No repair was applied; projection-dependent mouth qualification and
regional processing remain on hold. Explicit row flags were added with exact Arrow equality of
every pre-existing column, preserving the numerical pilot and pre-annotation evidence.

Freshwater processing took 30.2 seconds at 949 MiB RSS; independent validation took 23.6 seconds
at 749 MiB. Target arithmetic alone extrapolates to 6.4 seconds for 88,243 targets, excluding
source setup and QA. A scoped regional engineering estimate remains 10–40 minutes and 64–192 MiB
after projection, terminal-context and source-contract gates. Streaming pressure chunks must
bound memory; raw snapshot dates remain distinct from unknown observation dates.

The freshwater review bundle has 28 checksummed files and manifest SHA-256
`716404f464ada4f6be1e691f0f6fb73baeb7c8f6c5de1eb2149026870310c349`.
Bundle-root evidence is `RETAINED_NATIVE_MAPPED_MOUTH_INVENTORY.parquet`,
`FRESHWATER_GEOMETRIC_PROXIMITY_128_NATIVE_R8.parquet`, `INDEPENDENT_VALIDATION.json`,
`ADDITIONAL_NATIVE_GEOMETRY_VALIDATION.json` and `QUALIFICATION_ANNOTATION_AND_PARITY.json`.
Both pilots used zero acquisition, preserved the published releases and made no default toolkit
method change. Each stayed within 15 minutes, 64 MiB added staging and 1,536 MiB RSS.

Freshwater v2 resolves the distance-specific projection gate by separating valid native membership
from the unchanged metric boundary. An attempted polygon `make_valid` structure normalization was
rejected: reported area changed by 0.0121765 m², exceeding the fixed 0.01 m² guard, and 176 original
vertices disappeared. A common centroid translation did not remove that discrepancy. The guard
was not weakened and the polygon normalization was not accepted.

The accepted distance representation retains every transformed source boundary coordinate exactly,
with zero added/removed unique vertices or displacement, in valid LineString fragments. Water
membership comes from the valid native WGS84 polygon; metre distances use those unchanged
EPSG:32610 boundary segments. The invalid projected polygon interior and filled area are not used.
Among 169,430 source endpoints, one HydroRIVERS first endpoint changes membership: source ID
70286061 at [-122.93958333333359, 49.083333333332625] is covered natively but not by the invalid
projected polygon, 0.11505 m from its metric boundary. All 7,232 retained common inventory points,
native line geometries and selected coast distances are unchanged. This distinguishes source
membership from projected straight-edge representation, rather than pretending every difference
is floating-point epsilon.

The 91 BC nonzero retained route minima are now excluded from qualified metric inventory and
preserved separately as uncertain endpoint candidates. Recomputing HydroRIVERS precedence restores
three records. The corrected inventory contains 7,235 provider-terminal candidates: 6,016 BC FWA,
506 US NHD and 713 HydroRIVERS. Provider terminal markers and a mapped-water proximity rule do not
establish observed physical marine outlets. Four representation regressions, seven terminal-scope
regressions, independent scalar metric checks and all native endpoint/source geometry checks pass.
Corrected processing took 39.4 seconds at 833 MiB RSS; independent validation took 26.0 seconds
at 975 MiB. The original pilot and rejected projected geometry remain retained.

The useful partial scope is native-R8 distance to the nearest qualified retained provider-terminal
candidate, its identity, unweighted 5 km geometric proximity, and source/date/coverage/assumption
flags. Complete physical outlets outside cached query footprints, observed discharge/current
runoff/nutrient loads, and widths of line-only channels without areal evidence are source gaps.
Widths from existing river polygons and network closures are deferred computation/qualification,
not blanket missing-source claims. Projected filled-area uses remain method-limited. No R6
freshwater producer is invented. The scoped regional proposal remains 10–40 minutes and 64–192 MiB,
subject to this corrected pilot's review; no freshwater regional run has started.

The corrected freshwater bundle has 39 checksummed files; manifest SHA-256 is
`5ff1fe3b53ddf297eb666dbdf5dd11b3bb9ecf54851672d0cfa6acfa68fc894c`.
Bundle-root evidence includes `DISTANCE_REPRESENTATION_NORMALIZATION.json`,
`NORMALIZATION_GUARD_FAILURE_CHARACTERIZATION.json`, `BEFORE_AFTER_INVENTORY_SCOPE.json`,
`LOCATED_US_HYDRO_MEMBERSHIP_CHANGE.json`, `INDEPENDENT_VALIDATION.json` and
`QUALIFIED_PARTIAL_SCOPE_AND_REMAINING_GATES.json`.

Independent review cleared the indexed coastal method for a regional current-mask product after
execution preconditions. The frozen regional origin census identifies 892 connector origins outside
their focal H3 cells and 186 invalid origin prechecks. Actual origin coordinates, source H3 and
proxy labels are explicit; off-cell measurements cannot populate focal in-cell fields. Focal
fallback/island/policy flags do not certify the whole ray. The regional runner streams bounded
128-target row groups, with no exhaustive per-ray JSONL, all 16,000 pilot regression anchors and
640 frozen difference/reference QA rays spanning all 201 strata, every origin method and validity
class, and known caps/edges/high-complexity cases. Any source, QA, row-contract or resource failure
stops processing. The authorized run is now complete and frozen for independent byte review; Data publication remains gated.


The first regional attempt stopped after 512 targets when a missing source-H3 identifier appeared
as floating NaN in an Arrow string column. The failed stage remains retained and unpublished.
A separate v2 serializer converts missing identifiers to NULL, preserves valid H3 strings and
rejects invalid nonmissing values; five regressions pass. It changes no coordinates, origins,
scientific method or QA. The independent reader uses explicit object arrays to preserve NULL
without pandas type re-inference. These are serialization/readback corrections only.

The v2 regional producer completed 88,243 native R8 targets and 1,411,888 rays in 702.83 seconds,
with 840,122,368 bytes peak RSS and 44,467,383 bytes of stage output. It downloaded nothing.
All 16,000 pilot anchors and 640 frozen reference/difference checks across 201 strata matched
exactly. Streamed independent readback checked every ray, every summary, origin metadata,
source/code hashes, censoring and NULL rules in 2.98 seconds with 577,798,144 bytes peak RSS.
There are 1,038,432 mapped-boundary exits, 355,403 configured-limit caps, 15,077 source-edge exits,
2,960 unmapped-water-origin rays and 16 outside-extent-origin rays. The latter two represent
185 plus one invalid origins. All 892 off-cell proxies have focal fields NULL.

The mean capped connected-run bound and minimum of eight opposed-run sums are discrete,
origin-defined current-mask statistics. Source-edge or invalid rays suppress their summaries;
configured caps remain explicitly flagged. These statistics do not establish physical fetch,
physical waterbody width or minimum channel constriction. Full physical primary fields remain
NULL and whole-ray fine-source accuracy remains false. Default R6 methods are unchanged and
no R6 coastal product or R5 water network is fabricated.

The frozen `coastal-regional-currentmask-review-20261007-v2` bundle has 33 checksummed files;
manifest SHA-256 is `d6a656f48ef7840491b730cc19bbd4de681e8e3559ec02ee864e4b07daf46e84`.
Bundle-root `QUALIFIED_PARTIAL_SCOPE_METRIC_DEFINITIONS_SCHEMA3.json` defines all metrics and
coverage limits; `TABLE_INVENTORY_AND_SCHEMAS.json`, `EXECUTION_AND_QA.json`,
`INDEPENDENT_ALL_ROW_READBACK.json` and `RUNNER_BINDINGS.json` record evidence. The source
rectangle remains [-129.7,45.9,-121.5,51.5] with mixed native/fallback detail and unresolved island
footprints. Certified broader geometry/network context and physical accuracy remain absent.
Independent frozen-byte review and parent publication authorization are still required.

The regional freshwater operator is authorized only for the fixed, corrected 7,235-provider-terminal
inventory. Freeze source/inventory hashes, all 88,243 native R8 H3 centres and their projected
EPSG:32610 coordinates, native-water membership, cached-query bbox flags, output schema and
stratified scalar QA before execution. Preserve every original 128 pilot anchor. Stream no more
than 512 targets per batch; compute the unweighted exponential sum over every retained record
with a 5 km e-folding scale and no hard cutoff. Do not move land centres or use the rejected
projected filled-water polygon. Nearest identities must belong to the frozen inventory and have
tie-equivalent distance. All source-period, physical-mouth-width/distance, discharge/nutrient and
full-regional-coverage claims stay unknown or false. Input rights remain their existing provider
lineage; no new redistribution claim follows. A 40-minute/192-MiB/1.5-GiB/zero-acquisition,
one-worker execution cap applies; final bytes require independent review before publication.


Independent regional byte review cleared the coastal v2 current-mask increment. The exact
33-file candidate was atomically published as
`seascape_coastal_currentmask_origin_defined_native_r8_20261007_v2` on 2026-10-07.
All published files and all seven previous releases passed checksum readback unchanged.
Manifest `d6a656f48ef7840491b730cc19bbd4de681e8e3559ec02ee864e4b07daf46e84` is the
unchanged prepublication snapshot; its false publication field is superseded operationally by
the separate publication receipt. This does not qualify full physical fetch or channel width.

The freshwater v3 regional producer reused the cleared 7,235-point inventory and completed
88,243 centres in 5.37 seconds with 335,708,160 bytes peak RSS and 6,159,904 bytes of stage.
The frozen QA contains 864 scalar targets across 376 combined source/query/water strata and
all 128 original pilot anchors. All pass; maximum nearest error is 7.28e-12 m and kernel error
1.43e-14. Independent all-row hypot recalculation checked every metric, nearest-ID tie distance,
centre projection, native-water membership, query-bbox flags, physical/date NULLs and hashes;
256 new nonproducer scalar checks span 187 source strata. Validation took 19.15 seconds with
985,235,456 bytes peak RSS; maximum all-row kernel error is 2.85e-14. There was no acquisition.

The 10,986 land or unmapped centres remain unmoved geometric centres. Of all centres, 34,377
lie outside both cached detailed-source query bboxes; finite-inventory values still exist there,
but do not imply complete river-mouth coverage. Nearest distances range 2.99 m to 73.07 km.
The dimensionless unweighted operator remains inventory-sensitive and has no runoff, flow or
nutrient meaning. Physical width/distance/discharge fields and observation periods remain NULL;
full regional freshwater qualification remains false. The only preparation correction converted
numpy integer counts to JSON-native integers before freeze; failed preparation files remain
retained and scientific values unchanged. Six bounded-kernel regressions pass.

The `freshwater-regional-provider-terminal-review-20261007-v3` candidate has 39 checksummed
files, 23,959,565 bytes and manifest SHA-256
`3d1a64045c63005d127333f565ce164ea48a7a38b56c7f78aeb90bc4065f062c`. Bundle-root
`QUALIFIED_PARTIAL_SCOPE_METRIC_DEFINITIONS_SCHEMA3.json`, `REGIONAL_METRIC_CENSUS.json`,
`EXECUTION_AND_QA.json`, `INDEPENDENT_ALL_ROW_VALIDATION.json` and
`TABLE_INVENTORY_AND_SCHEMAS.json` define scope and evidence. No freshwater Data publication
has occurred; independent regional frozen-byte review remains required.

Freshwater v3 subsequently passed independent regional byte review and was atomically published
as `seascape_freshwater_provider_terminal_proximity_native_r8_20261007_v3`, unchanged manifest
`3d1a64045c63005d127333f565ce164ea48a7a38b56c7f78aeb90bc4065f062c`. All 39 files and all
eight previous releases passed readback. Its publication receipt supersedes the unchanged
candidate's prepublication flag operationally; no scientific recomputation or new rights claim
occurred. Nine immutable partial releases now cover ten scoped family increments, with seventeen
historical catalog families lacking a published increment. No catalog family is represented as
fully complete merely because a diagnostic or partial increment is available.

The end-of-batch metadata review corrects an earlier overstatement about reef sources: all 50
Washington oyster records are polygons; the 501 BC bivalve records are 325 polygons and 176
multipolygons. Mapped-bivalve extents are therefore cache-feasible after species/geometry/union
qualification. They do not establish structural reefs, rocky reef, coral/sponge coverage or
surveyed absence. Metadata counts are not a completed reef product.

A static consumption bundle requires explicit release-path/manifest bindings: the current toolkit
DatasetRegistry still uses canonical processed-path templates, while these increments live under
new immutable release directories. Six selected tables can join at the 2,621-key native R6 support;
ten selected tables can join at the 88,243-key native R8 support after filtering the mixed-resolution
kelp date envelope. The R8 count includes the new freshwater operator; the earlier eight-release
snapshot had nine selected R8 tables. Preserve namespace and per-family QC/observation fields,
resolve base placeholders against qualified later increments explicitly, and exclude within-compute
terrain diagnostics from eligible features. Annual kelp and bearing-level coastal rays remain
separate dated/directional grains. R8-only metrics do not become invented R6 aggregates.

Retained-source metadata identifies 127 BC estuary polygons and 194 US native estuary points
(5,306,157 bytes relevant GeoJSON). A coherent next proposal is their normalized location inventory
and partial native R8 planar nearest proximity, using the established BC interior-point and US
unchanged-point definitions. The older 75 km query rectangle covers only part of the expanded
current domain; BC unique-watershed estuary subset and PMEP potential-habitat inventory are not
complete physical censuses. Full marine network context/attachments, tidal exchange and salinity
remain separate gates. Only planning and source metadata inspection were performed; no new
estuary, habitat, geomorphic or network producer was launched. The readiness JSON/CSV distinguishes
ordinary bounded implementation from source access, missing physical observations and actual
user-selected outlet/source decisions.

The approved static consolidation is now frozen for independent join/schema/lineage review.
Native R6 has 2,621 rows and 252 columns; native R8 has 88,243 rows and 392 columns. Every
non-key source field is namespaced without numerical transformation, and explicit preferred
aliases select reviewed contours and graph anomalies while retaining the original placeholders.
The 640-entry field dictionary binds fields to original source/hash/manifest, row quality,
coverage and date columns; source release IDs remain per component. Exact builtin registry
specification rows are archived without mutation, with a separate pinned consumption registry.
Annual kelp and directional rays remain existing checksummed sidecar references, not copied.

The producer took 3.53 seconds with 1,354,989,568 bytes peak RSS. This exceeded the initial memory
estimate but stayed under the approved 1.5 GiB cap. Independent every-field readback used one
source component at a time, checked original values/types/NULLs, native row order and keys,
preferred aliases, registry specifications, source/sidecar hashes and all nine original releases.
It took 2.13 seconds with 1,136,607,232 bytes peak RSS. Five exact-join/cardinality/type/NULL tests
pass. The initial receipt preparation assumed one receipt hash key; older bathymetry/distance
receipts use `manifest_raw_sha256` and bathymetry's receipt remains at its original retained
location. Both receipt forms are bound exactly; failed preparation logs and empty failed stages
remain retained. This correction changed no input or scientific value.

The `static-consolidation-20261007-v1/release-candidate` has 47 checksummed files, 69,233,814 bytes
and manifest `7bf4f4efeb690ab7e8839bbc4f46993c135c462a0e9ea0f9d855f269a9f66b98`.
Its `CONSUMPTION_GUIDE.txt`, `FIELD_DICTIONARY.json`,
`CONSOLIDATED_CONSUMPTION_REGISTRY.json`, `ARCHIVED_RELEASE_PROVENANCE.json` and
`INDEPENDENT_EVERY_FIELD_READBACK.json` explain use and verification. Modeling eligibility and
physical source completeness are not inferred from assembly or a non-null value. The combined
candidate is unpublished pending independent review. The estuary pilot remains unstarted, with
proposal bounds 128 targets, 1–5 minutes, 16–32 MiB staging, 1.5 GiB RSS and zero acquisition.

Independent join/schema/lineage review cleared the exact combined candidate. It was atomically
published on 2026-10-07 as `seascape_consolidated_static_native_r6_r8_20261007_v1`, preserving
manifest `7bf4f4efeb690ab7e8839bbc4f46993c135c462a0e9ea0f9d855f269a9f66b98` and all 47
checksummed files. Final published-root readback again checked all 602 source fields, 22 aliases,
105 registry specifications, native order/types/NULLs, source status and all nine previous releases.
It took 2.11 seconds with 1,151,254,528 bytes peak RSS. Relative output-table and provenance
archive paths resolve from the published root. Sidecar absolute pins remain unchanged; equivalent
relative paths from the published root were checked against their original hashes. The original
legacy receipt's workspace-relative path is preserved, while its exact archived provenance copy
resolves independently from the published root. Frozen prepublication flags remain unchanged;
the separate publication receipt is the operational publication truth. This is the final coherent
checkpoint for this batch: no estuary or other producer has started.

A subsequent authorized estuary pilot retained all 127 BC source polygons and 194 US source points.
Preflight found 29 BC native polygons invalid, with the same 29 invalid after EPSG:32610 projection.
They remain original, unrepaired, explicitly excluded evidence. The qualified operator uses 98 valid
BC polygons normalized to an interior representative point in EPSG:32610, inverse-checked inside
the original native polygon, and all 194 unchanged US native points. No source geometry is clipped
or repaired. This deliberately partial method differs from the stock toolkit BC repair-and-context-
clip normalization; it is not claimed as stock-product parity or a complete 127-polygon normalization.

All 321 original WKB/property/validity checks and independent normalization checks pass; all 128
native H3-centre scalar nearest distances/IDs, tie distances, query-bbox flags and physical/date
NULLs pass. Maximum distance error is 1.46e-11 m. Producer execution took 0.638 seconds with
347,930,624 bytes peak RSS; independent validation took 0.499 seconds with 225,394,688 bytes peak
RSS. The two source representations remain distinguishable, with original cache dates separate
from unknown observation periods. Point proximity does not establish physical estuary extent,
complete estuary coverage, water-network connectivity, salinity, tidal exchange or plume behavior.

The frozen `estuary-128-review-20261007-v1` has 16 checksummed files, 4,318,777 bytes and manifest
`41103964b8872759020d89f2744104bdc9ff9ab590343faa8f2e1b4a6179d97f`.
Total retained pilot plus review is 8,605,752 bytes, below the approved 32 MiB cap. The regional
proposal reuses this 292-point inventory for 88,243 native R8 centres, with 2–10 minutes estimated
compute, 16–32 MiB estimated additional staging, a 48 MiB proposed staging cap, 1.5 GiB RSS cap,
512-target batches and zero acquisition. Method/scope review of the 29 exclusions must precede
expansion; regional execution and estuary publication have not started. All ten published releases
remain preserved. Source expansion, geometry repair and marine graph/seed closure are separate
unqualified work, not implied by this bounded point operator.

After independent pilot scope clearance, the fixed 292-point operator ran over all 88,243 native
R8 centres in batches of at most 512. Producer execution took 4.694 seconds with 267,730,944 bytes
peak RSS. Independent all-row validation took 4.773 seconds with 379,404,288 bytes peak RSS:
all native keys, H3 centres, projected coordinates, nearest distances, actual selected point/source
methods, query flags and physical/date NULLs passed. All 128 pilot anchors and the frozen 640
scalar checks across 364 strata passed; 256 fresh nonproducer scalar checks also passed. Maximum
distance error was 2.91e-11 m. Five tie regressions accept any retained point realizing the minimum;
there is no unspecified canonical point-ID tie-break claim. No actual regional target had multiple
retained points tied within the 1e-7 m validation tolerance.

The source coverage remains partial: 27,986 centres fall outside the original cache query rectangle,
and 10,986 centres are land or unmapped. Native centres remain unmoved. All 321 source records and
29 invalid unrepaired BC exclusions are preserved. Representative-point proximity does not qualify
physical boundary distance, estuary membership, network connectivity, salinity or tidal exchange.
Observation periods remain unknown rather than inheriting the modern cache retrieval date.

The regional review bundle `estuary-regional-review-20261007-v2` has 33 checksummed files,
23,828,221 bytes and manifest
`3b839937cebe92cc0120aa8925c5bd48874f67b412367669b6ac71ae6ab5f9a9`.
Plan, stage and review together retain 43,383,953 bytes, below the approved 48 MiB cap. Total task
staging remains below 2 GiB. No source acquisition occurred. Independent frozen-byte review is
pending before Data publication; all ten prior releases, including consolidated static v1, remain
unchanged. A later separately versioned consolidation must be reviewed after estuary publication.

Independent regional review subsequently cleared the exact estuary manifest. Its 33 checksummed
files were atomically published as
`seascape_mapped_estuary_representative_point_proximity_native_r8_20261007_v2` on 2026-10-07.
Published checksum readback passed; every prior release remained unchanged. The immutable
prepublication manifest still records `Data_publication=false`; the separate publication receipt
records actual publication. Do not mutate the cleared manifest to update that historical snapshot.

A separately versioned consolidated static v2 appends the 23 estuary non-key source fields plus
its immutable release ID at native R8 only. R6 is byte-identical to v1. Independent streaming
readback verifies all 392 existing R8 fields, including values, Arrow field types, NULLs, schema
metadata and native row order, without recomputing any scientific values. Every original dictionary
entry is unchanged; 24 estuary entries link source hashes, definitions, coverage and unknown dates.
The R8 table has 416 columns; sidecar grains, absolute paths and equivalent Data-relative paths
are qualified, and all eleven published releases remain unchanged. Streaming 4,096-row groups
reduces producer peak RSS to 525,942,784 bytes versus the earlier whole-table join. Producer and
independent validator took 3.021 and 1.864 seconds; validator peak RSS was 624,115,712 bytes.

The v2 candidate is frozen in place, avoiding a second large review copy: 45 checksummed files,
71,835,813 bytes, manifest
`94006351aa59052ea4ee42172c32816dce952f40d446c495d2f1928a03560205`.
It awaits narrow independent join review before publication. About 24 MiB remain under the retained
2 GiB task cap; no cleanup is authorized. The next cheapest leaf is correctly named mapped oyster
and bivalve polygon extent evidence from 551 retained polygons, not structural reef habitat.
Only metadata/preflight and a proposed 128-centre, 8 MiB pilot are planned; no new producer started.
Larger regional work needs a new bounded staging plan. Seagrass tile/window inspection and fluvial
topology remain implementation dependencies; missing hardness/structural reef evidence, unresolved
dbSEABED terms and access-only sources remain real source/access gates.

Narrow independent v2 join review cleared the exact 45-file manifest. Static v2 was atomically
published as `seascape_consolidated_static_native_r6_r8_20261007_v2`; all eleven prior releases,
including v1, remain unchanged. Published every-field readback passed in 1.444 seconds with
638,287,872 bytes peak RSS. Relocated relative static paths, pinned sources, sidecars and archived
provenance resolve with matching hashes. Twelve immutable releases now pass complete checksum
readback. The combined default and companion are the v2 `metrics/SEASCAPE_STATIC_NATIVE_R6.parquet`
and `metrics/SEASCAPE_STATIC_NATIVE_R8.parquet`; partial coverage and source-specific limits remain.

Producers stop at this checkpoint. Task staging has approximately 24 MiB remaining under 2 GiB;
no staging, cache or release was deleted. The future budget proposal prefers a 2.25 GiB staging cap
(256 MiB extra) while preserving evidence. An alternative, requiring explicit approval and a restore
map, is removing only the redundant local v1/v2 candidate copies after verifying their identical
immutable published bundles. Both options are proposals only. Missing physical sources and rights
gates remain distinct from an ordinary staging/resource decision.

The user subsequently approved a 2.25 GiB total staging cap for a bounded cached bivalve batch,
preserving existing files. Source taxonomy inspection corrected a material earlier inventory
assumption: the 501 BC records are mixed-species habitat observation polygons, only 74 of which
name bivalves (50 Mytilus trossulus, 24 Crassostrea gigas). The other 427 include kelp, eelgrass,
barnacles and other classes and remain preserved but excluded from the bivalve operator. WA has
50 generalized oyster-bed records with presence Yes and explicit WDFW Fish Program layer names;
one native and projected invalid polygon, OBJECTID 951, remains unrepaired and excluded. The
qualified inventory has 123 records: 49 valid WA beds and 74 BC taxon-associated observations.
The BC bivalve records share 43 geometries. Keep every record; use unique geometric union for area.

WA mapped oyster-bed extent and BC bivalve-associated habitat observation polygon extent are
separate source concepts. A BC observation polygon does not establish the exact bivalve canopy
or bed footprint. Pacific oyster mapping may include cultivated or non-native beds; neither source
establishes an aquaculture footprint, harvest regulation classification or structural reef. Strict
taxonomy tests reject Approved/Prohibited, unknown harvest layers and nonbivalve species.

The 128-centre native R8 pilot preserves all 551 original WKBs and provider attributes. It computes
EPSG:32610 full-H3 intersection unions, class unions, record overlap excess, WA/BC overlap and
native-centre distance to the retained polygon inventory. Full-hex ratios are mapped-polygon
diagnostics, not physical habitat fractions. Query footprint is not survey completeness; geometry
can extend beyond the query rectangle. All 41 zero intersections are not observed absence, and
87 positive intersections establish retained mapped evidence only. Physical bed/canopy area,
water-denominator/fraction, current presence, network distance, farm inference, structural reef
and observation year remain NULL. The 2026-07-25 cache date is not an observation year.

All 551 independent source identity/taxonomy/geometry checks and 128 independent per-record
intersection-union, class/overlap and minimum-distance checks passed. Maximum area difference
was 7.56e-8 square metres and distance difference 3.64e-12 metres. Five taxonomy/union regressions
passed. Producer took 6.322 seconds with 295,960,576 bytes peak RSS; validator took 0.960 seconds
with 357,941,248 bytes peak RSS. Shared GEOS/PROJ/provider dependencies limit independence;
this is not independent habitat groundtruth or a complete survey census.

The in-place frozen pilot has 20 checksummed files, 1,235,146 bytes, manifest
`ea3dd7761d85aecc79694fa962c8bc35f41709795c7c3b4b19d2c31d85dd327a`.
It uses less than the approved 8 MiB pilot cap, with zero acquisition and no cleanup. All twelve
published releases remain unchanged. Scope review precedes a proposed 1,024 R8 plus 128 R6
timing/method gate capped at 120 seconds and 8 MiB. Preliminary direct-native regional estimates
are 4–20 minutes and 16–40 MiB, proposed hard caps 20 minutes/48 MiB/1.5 GiB RSS, batches 512,
zero acquisition. These are provisional; numeric/setup/I/O timing must precede broad launch.
R6 would use direct native polygons, with water-membership unknown unless separately supported;
no R8 aggregate or R5 network is invented. Regional processing and publication have not started.

Independent pilot scope review cleared the timing gate only and corrected wording: the 427
excluded BC records are records without an explicitly selected bivalve taxon/class, including
25 `-none-` records. Do not assert that all 427 are nonbivalves. Filtering and preserved flags did
not change; original frozen pilot field names remain historical schema labels.

The approved 1,024 R8 plus 128 direct R6 timing gate uses a STRtree for candidate intersections
and nearest retained polygon. Geometric unions still count overlapping/repeated geometry once;
record sums remain separate evidence. Five indexed-operator regressions cover duplicate union,
partial class overlap, zero intersection with finite distance, boundary contact and equal-nearest
polygons. All 1,152 targets independently pass per-record union/class/overlap/distance checks;
area and distance differences are zero. All 128 original pilot anchors retain full-field parity
within declared floating tolerances. R6 directly uses its native H3 polygon and keeps centre-water
membership NULL, rather than inventing it from R8 or representative-point membership.

Producer took 1.037 seconds with 221,511,680 bytes peak RSS; independent all-target checker took
1.545 seconds with 209,698,816 bytes peak RSS. Setup was 0.510 seconds, R6 numeric time was
0.103 seconds for 128 targets, R8 numeric time was 0.377 seconds for 1,024 targets, and output I/O
was 0.009 seconds. Numeric times include periodic batch guards. Combined compute is 2.582 seconds,
well below 120 seconds; no acquisition or cleanup occurred. Shared GEOS/PROJ/provider dependencies
remain an independence limit, not new physical habitat groundtruth.

The in-place frozen timing gate has 18 checksummed files, 206,352 bytes and manifest
`651a17f6c1f2f89d382cf7b94ba948d40fe5fe923121bab9b8540b04107f218d`.
Original pilot 20-file checksums and all twelve published releases remain unchanged. The measured
linear regional numeric baseline is 34.59 seconds and independent all-row checker baseline is
121.87 seconds for 2,621 R6 plus 88,243 R8 native targets. A bounded regional proposal estimates
3–8 minutes and 12–32 MiB added staging, hard caps 600 seconds/48 MiB/1.5 GiB RSS, one worker,
batches at most 512 and zero acquisition. Safety margins cover setup/I/O/source-edge/candidate mix;
the clustered timing sample is not a runtime guarantee. About 278 MiB remain under the approved
2.25 GiB task cap. Review/approval precedes regional launch; no full run or publication has started.

The regional mapped-bivalve batch was subsequently authorized with the measured 600-second,
48 MiB, 1.5 GiB RSS, one-worker and 512-target-batch limits. The producer completed once:
2,621 direct native R6 and 88,243 native R8 rows in 17.967 seconds, peak RSS 265,486,336 bytes.
All 1,152 timing anchors passed. Positive retained mapped-polygon intersections occur in 128 R6
and 1,266 R8 targets; the other 2,493 R6 and 86,977 R8 targets retain explicit not-observed-absence
status. Centres outside the old cache query rectangle number 1,367 R6 and 44,201 R8. These counts
describe retained mapping and retrieval scope, not physical habitat presence or survey completeness.

A connection loss interrupted the first validator before any result was produced. On reconnect
session 52697 was no longer registered and only startup warnings remained; the producer files
were preserved and not recomputed. The identical validator then completed against those bytes,
with the original log retained separately from the resumed log. Earlier interrupted runtime is
unknown and is not presented as a completed check. All 90,864 rows independently pass per-record
union/class area, overlap, minimum-distance, native support, coverage/status and NULL checks.
Area and distance differences are zero; all 1,152 timing and 128 original pilot anchors pass.
Completed validation took 91.720 seconds with 495,927,296 bytes peak RSS; confirmed producer
plus completed checker totals 109.688 seconds, below the approved 600-second limit.

The regional candidate is frozen in place with 34 checksummed files, 7,427,567 bytes and manifest
`9c574ab32d72cdee94f3f7e962eb238bc8cc568382a5cf94d1084e48a2baaf36`.
It preserves all 551 native records and provider attributes, the 123 qualified records, unrepaired
WA 951 exclusion and 427 records without an explicitly selected bivalve taxon/class, including
25 `-none-` records. It adds 640 independent nonanchor sample checks covering all 384 eligible
source/geographic strata; every regional row was checked regardless of sampling. The dictionary
links each output field to native/qualified evidence, exact table hashes and scope/quality definitions.
R6 centre-water membership and all unavailable physical/date/network/reef/farm quantities stay
NULL. BC observation polygons remain distinct from WA mapped beds; no source repair, canopy
or absence inference, annual repetition or modern backdating occurred.

All twelve published releases, including consolidated static v2, and both prior bivalve pilot/timing
bundles pass unchanged checksum readback. Zero acquisition, cleanup or other producer occurred.
About 270 MiB remain under the 2.25 GiB task cap; candidate staging remains below 48 MiB.
No publication has occurred. External frozen-byte review is the remaining gate.

Independent regional review subsequently cleared the exact bivalve manifest. Its 34-file bundle
was atomically published as
`seascape_generalized_mapped_bivalve_polygon_evidence_native_r6_r8_20261007_v1`.
Published hashes, all-row numeric proof values, status/NULL checks and 70 field lineage references
passed relocated readback. All twelve previous releases, including consolidated static v2, stayed
unchanged. This remains partial generalized mapping evidence, with separate BC observation and
WA bed semantics; publication does not qualify physical species footprint, coverage or absence.

Before any static v3 copies, a transient staging estimate recorded 85–105 MiB additional allocated
space, with a 128 MiB hard bound. Current task staging plus the hard bound was 2.111 GiB, below
the approved 2.25 GiB limit. Streaming outputs directly to one candidate and freezing in place
avoids a duplicate large review copy. No prior staging/cache/release was removed. The resulting
allocated task delta is about 84.6 MiB and leaves approximately 185 MiB headroom.

Static v3 adds the 33 non-key bivalve source fields and immutable release ID at both native scales:
2,621 R6 rows with 286 columns and 88,243 R8 rows with 450 columns. Independent full-field
readback verifies all 252 existing R6 and 416 existing R8 columns preserve exact decoded values,
types, NULLs, schema metadata and row order. All 664 prior dictionary entries are unchanged; 68
new entries bind original source fields, class distinctions, portable scope/lineage paths and row
qualifiers. R6 centre-water membership and unavailable physical/date/network/reef/farm quantities
remain NULL. Sidecars retain annual/bearing grain and are referenced, not copied or flattened.
No scientific values were recomputed and no original preferred alias was changed.

Producer took 3.000 seconds with 497,156,096 bytes peak RSS; independent readback took 1.630
seconds with 638,025,728 bytes peak RSS. The in-place v3 candidate has 50 checksummed files,
75,596,437 bytes and manifest
`99ae96b8490b8cb74f18544ae510db07243d7404fd23b5f775160bd6a936b0e7`.
All thirteen published releases remain unchanged. The separate candidate is frozen for narrow
independent join review and has not been published. Zero acquisition, cleanup, pushes, merges or
unrelated producers occurred; narrow review is the remaining gate.

Independent narrow review then cleared the exact static v3 manifest and all 50 checksums. The
unchanged candidate was atomically published as `seascape_consolidated_static_native_r6_r8_20261007_v3`.
Published all-field readback passed in 1.625 seconds with 648,167,424 bytes peak RSS. All 252 prior
R6 and 416 prior R8 fields and the source-native bivalve additions remain exact. All 23 relocated
static/source/sidecar references resolve with matching hashes; archived provenance and dictionary
links pass. Thirteen prior releases stayed unchanged; all fourteen published releases now pass
complete checksum readback. The user-consumption default is the v3 native R6 table (2,621 rows,
286 columns) and finer companion is native R8 (88,243 rows, 450 columns), with its guide/dictionary.
Publication keeps all partial source and physical/date/network limits in force.

Producers stop at this checkpoint, with approximately 185 MiB left under the 2.25 GiB task cap.
The catalog still has zero fully fulfilled physical families: twelve have published scoped partial
increments, eight need bounded implementation/dependency work, five remain source-limited and
two hardness families lack qualified physical source support. Nine supplemental capabilities are
tracked separately. A concrete next cached-source proposal is HydroRIVERS topology preflight:
986,463 DBF records and HYRIV_ID/NEXT_DOWN/MAIN_RIV/HYBAS_L12 are confirmed in the retained
101,606,171-byte DBF, with 151,192,524-byte SHP and 7,891,804-byte SHX read in place. Stream
attributes, verify identity/terms, IDs/downstream references/cycles/terminal and basin closure, then
retain at most 1,024 reaches for an independently checked pilot. NEXT_DOWN zero must not be
invented as a marine mouth. Preliminary estimate is 3–8 minutes and 8–24 MiB added staging, with
a proposed 32 MiB stage cap, one worker/1.5 GiB RSS/zero acquisition. This is planning only; no
new topology processing, acquisition, cleanup, push, merge or other producer was launched.

## Coarse seagrass source and integration lessons (2026-10-08)

Compare checksum algorithms before declaring an integrity failure: repository `checksum_path` hashes UTF-8 basename plus complete file bytes, while `shasum` hashes bytes alone. The cached seagrass archive matched its original repository checksum, configured raw-content MD5, size and acquisition identity; the initial cross-algorithm comparison was invalid. Preserve both explicitly named digests and the original receipt. No cache repair or expected-hash replacement was needed. Live provider metadata refresh remained unavailable; cached CC BY 4.0/source identity qualifications were retained rather than described as fresh verification.

A footprint-only scan is insufficient. The 32-block sample's northwest blocks were all zero, yet the full selected regional scan found northwest positives. Source zero is nodata/background, not surveyed absence. Exact full native R6 support selected 20,610 blocks instead of 72,366 bbox blocks while preserving cell edges beyond the nominal domain. Independent per-cell enumeration matched all memberships. Three disjoint source tile rectangles avoid duplicate pixel area; 34 cells remain rectangle-partial even when every available block completes.

The bounded pixel-footprint operator processes one native block at a time, separately reporting H3 centre counts and EPSG:6933 footprint-overlap area on full cells. It avoids giant polygonization, water clipping, extraction and nominal 100 m² assumptions. Geographic H3 vertex edges segmentized at 0.001° are an explicitly named numerical approximation, not exact spherical-boundary certification. Full execution took 130 seconds and 243.5 MiB peak RSS; an independent cell-first reference matched 32 whole-cell counts with maximum area discrepancy 0.000105 m². These checks share H3/GDAL/GEOS/PROJ and do not supply physical ground truth. Completed-block receipts prevent an interrupted cell from receiving a completed zero.

The exact regional model-evidence release is published separately. Static integration preserves all previous fields and byte-identical R8, adding native R6 fields only; source-composite 2023–24 columns describe model vintage, not annual/current observations. Arrow string versus large_string can make strict key-array equality fail despite identical values: align by exact unique key values and retain original key types. Preserve the stopped-attempt evidence. Native R8 remains deferred until its own source-support/method cost is qualified; never infer it by upsampling R6. The static-v4 candidate remains pending narrow final join review.

The earlier HydroRIVERS proposal above is superseded and canceled. River topology, drainage, discharge and barriers belong to Hydrology; seascape consumes qualified mouth/proximity evidence only.

Static-v4 independent join clearance has now been completed and the exact candidate is published locally. All 15 previous releases pass full checksum readback; coarse R6 positive-model seagrass is delivered independently of later family gaps. Native R8 and observed-source upgrades remain later work. Bounded substrate preflight found that its older receipt uses raw-byte SHA-256, unlike newer filename-prefixed receipts: identify the checksum convention per evidence version. Current/legacy cached locations are distinct but byte-identical. Source headers show global 0.1° modeled grids with unspecified unit tags/rights; grid compatibility alone does not establish joint composition, measured hardness, physical area, survey coverage or publication permission. No substrate producer or source acquisition ran.


## Preserve source NULLs and bound validation allocations (2026-10-08)

A nullable Arrow large-string QC column can become Pandas StringDtype with NaN missing values. Scientific eligibility written for Python None then treats those NaNs as QC reasons. A scalar check that consumes the same converted values can agree with the wrong classification. Preserve Arrow-native None in source batches, and run the independent scalar reference against source-NULL semantics. Include a regression that reproduces this representation conversion; do not alter scientific thresholds to compensate.

Validation can exceed producer memory by retaining original source tables, joined output, serialized readback and successive full-table set_index/loc/reset_index copies. Stream aligned batches and check every key, strict uniqueness, every input/QC field and scalar label/status. Persist process peak RSS before a guard can raise. Keep failed attempts and their claims as historical evidence, add a distinct diagnosis and corrected candidate, and never retrospectively report the failed generation as compliant. For the corrected terrain candidate, 1,024-row batches peaked at 209.1 MiB; no full-table joins or regional key sets were materialized.
