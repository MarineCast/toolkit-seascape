> This earlier milestone is superseded by the [source-closure study](source-closure.md).
> Its counts and pending items describe the previous source mask.

# Regional coastal-policy completion

The coastal-policy builder implements an explicitly supplied coastal reach and independently
identified inland marine water bodies. It does not select the reporting domain by an acquisition
rectangle or territorial boundary. Inputs retain source IDs, versions, rights and cartographic
scale. GSHHG 2.3.7 full-resolution level-1 land/ocean boundaries are a source candidate under
LGPL; their historical cartography does not establish present-day intertidal or bathymetric datum.
Source completeness and scientific acceptance are separate from successful software execution.

## Geometry and support

`seascape.spatial_support.coastal_policy` accepts WGS84 source coast lines, a marine-water
polygon, typed inland-water polygons and their complete source context. All geometries must be
valid, finite, regional and source identified. Inland types are explicit strait, sound, bay,
inlet, estuary or marine channel. An enclosing rectangle is never accepted as an inland-water
selection. Raw inventories are immutable.

The offshore corridor starts from a local azimuthal-equidistant construction, then corrects its
boundary vertices using WGS84 ellipsoidal forward/inverse geodesics to the nearest source coast.
Boundary edges are at most 250 m. The configured numerical envelope is at most 0–10 m beyond the requested
22,224 m distance (5 m by default), with a half-tolerance construction margin. Every corrected vertex and edge
midpoint is checked; an out-of-envelope construction fails. Source-context truncation also fails.
The final mask is the union of this corridor and the explicitly typed inland geometries,
intersected with source marine water. The geodesic envelope qualifies the constructed corridor,
not the positional accuracy or tidal datum of the source shoreline.
Constructed-buffer self-intersections may receive a recorded make-valid operation; the raw source
does not change and the final distance envelope is checked again. H3 intersections use exact
spatial tiles to keep detailed regional coastline processing bounded.

H3 candidates use overlap enumeration and retain only positive-area intersections with the
materialized mask. No centre-only or minimum-fraction filter substitutes for membership. Area
uses intersections in common EPSG:6933 geometry, with full H3 vertex polygons densified at
0.001 degree and the polygonal-edge approximation recorded. Shared projected clipping keeps
the full-cell and water-area denominator consistent along source-tile seams.
Native full/water GeoParquets retain that EPSG:6933 geometry, avoiding a lossy inverse-projection
round trip of touching slivers. The mask and source registries remain EPSG:4326. Non-areal
intersection remnants do not contribute to positive-area membership.
Native R6/R8 memberships remain distinct; contextual graphs may extend beyond reporting support.
A mask build never certifies source observation coverage, historical water levels, physical bottom
hardness or downstream predictor eligibility.

`water_network.reporting_mask_path` selects this materialized reporting geometry independently of
the larger canonical water context. R8 reporting membership uses positive-area mask intersection;
R6 structural support preserves the exact R8-parent hierarchy, including explicitly flagged dry
geometric parents. These structural parent supports are distinct from direct native R6 mask
membership. Legacy configurations without the path retain their existing rectangular selection.
The reporting-mask checksum is bound in the canonical-network manifest.
Reporting membership selects canonical cell keys. Canonical source-water cell geometries are
not clipped again to the reporting mask; each producer retains its declared cell/raster
denominator. Direct native mask-water intersections used by the annual footprint and mapped-class
APIs remain separate support, even where R8 identities match.

## Regional execution

Build configured source registries with
`python -m seascape.spatial_support.coastal_policy_build --config /path/to/config.yaml`.
The `coastal_policy` section requires `coastline_path`, `marine_water_path`, `inland_water_path`
and `source_context_path`; optional bounds include `max_cells`, `max_vertices`, `resolutions`,
`offshore_distance_m`, `numerical_tolerance_m` and `graph_context_buffer_m`. `output_dir` must
be inside the workspace and separate from inputs. The producer atomically writes the mask,
wider marine context, native full/water membership files and a checksum-bound provenance manifest.
It does not automatically activate a study registry or run the legacy territorial-water builder.

Regional optional stages require bounded plans rather than simply increasing fixture limits.
Batches must keep full neighborhood context and globally consistent deep-component/network
identities. R6 child-union summaries require all eligible children together. Batch-local distance
minima or disconnected components cannot be advertised as regional results.

Nearshore processing bounds reporting cells, context cells, virtual raster pixels and stations
separately. Components are labeled once across canonical context, and cell queries use local
raster windows. Routes can reach contextual deep targets outside the reporting subset. R6 areas
are recomputed from complete selected R8 unions. Coast calculations use indexed local fragments
and one traversal of source-line distances for stations and sinuosity; complete source land
components are retained separately from the working land-side context clip. `shoreline_path` can
explicitly select a source geometry inventory for either optional producer.

Mosaic R8 radius sums reuse the canonical 5 km operator; R6 builds one bounded shared operator
per selected support and reuses it across classes. These amounts remain mapped area within the
selected support, with context censoring explicit. The tidal support registry requires source ID,
version, rights, known `TIDAL_FRAME` and `VERTICAL_DATUM`, and `INDEPENDENT_TIDAL_SUPPORT=true`;
unknown datums and habitat footprints substituted for independently mapped tidal support fail.

Named locations retain gazetteer identities separately from computational geometry. Source-backed
mouth IDs, passage geometry/centrelines, depth datum and gateway crossing attachments must be
bound and validated before execution. Missing or unresolved objects remain explicit. Complete
land components are retained before H3 clipping, including source-boundary censoring.

Freshwater ArcGIS acquisition binds each extract to its URL, query, fields, envelope, tiling and
SHA-256 receipt. Reuse requires that identity and those bytes; legacy unbound extracts require
explicit reacquisition. ID inventories must be complete, and every returned batch must match the
requested IDs exactly. Acquisition refuses more than 4,096 tiles or 500,000 features per source.
These limits bound local work and do not establish observational completeness outside the query.

Habitat providers require native class, date, rights, geometry and coverage review. Intertidal
support is independently sourced in its tidal frame. Observed/modeled, mapped presence, survey
opportunity and absence remain separate. Physical hardness requires an areal source definition;
a probability of rock occurrence is not an areal hard-bottom fraction.

## Areal substrate classes

`seascape.benthic_substrate.areal.build_areal_class_fractions` measures source polygon classes
on explicit native H3 water support. Per-class geometric unions share the union of mapped source
polygons as their denominator. Coverage relative to reporting water is separate. Outside mapped
coverage, amounts and fractions remain null. Conflicting class overlaps retain amounts but withhold
fractions and carry explicit QC. Duplicate same-class coverage is counted once.

The DFO Bottom Patches 1.0 source defines hard, mixed and soft modeled substrate classes, with
observations and extrapolation. These are conditional mapped-class fractions. They do not supply a
calibrated physical hardness index, exposed-rock fraction or uniform tidal datum. Physical hardness
fields remain unavailable. See the [DFO source record](https://open.canada.ca/data/en/dataset/6cda0f8d-110e-423d-8d7a-bf8a40eaa26e)
and [methods](https://waves-vagues.dfo-mpo.gc.ca/Library/41056164.pdf). Original region, depth ribbon,
class, confidence and source keys remain in the retained source inventory; class fractions do not
turn observation-guided modeled polygons into direct areal observations or annual history.

## Local regional run: 16 October 2026

The isolated local workspace is `.seascape/work/regional-completion-20261016/workspace`.
Its reporting mask and native H3 inventories passed geographic controls, land-exclusion,
area-partition and geodesic-envelope checks. Native memberships contain 462 R5, 2,411 R6,
13,397 R7 and 81,004 R8 cells. Structural R6 has 2,431 R8 parents; it is a different support
from native R6 and must not be substituted in joins. The enclosing shared study registry
has not been activated by this toolkit run.

The canonical graph, expanded GEBCO bathymetry, R8 geomorphometry and fluvial connectivity,
coast complexity and nearshore transitions completed on this support. Coast complexity retained
31,653 headland candidates and complete source land components. Nearshore used 823 shared
contextual deep-water components, with R6 summaries computed from complete R8 child unions.
The conservative canonical H3 candidate enumeration also retains wet cells containing small
land holes that experimental polygon-overlap enumeration omitted.

All 53 proposed major locations have official gazetteer name identities. The separate
`config/registries/selected_outlets.proposed.v1.json` retains 30 proposed modeled-basin bindings,
including disagreements and source-scale limits. Of these, 26 IDs occur in the current coastal
outlet inventory and have R8/R6 relationship products. Gold, Nitinat, Fraser and Klinaklini
candidate terminals lie beyond the configured coastal tolerance; their bindings remain unavailable.
No small neighboring creek substitutes for those rivers. Delta branches and physical mouth
locations remain unqualified. The 23 named waterway locations still require reviewed physical
passage/gateway geometries, centrelines, depth datum and crossing attachments; name-reference
points are insufficient.

The local flat candidate has ten areas and 18 resolution-specific Parquets plus `catalog.json`.
It includes the available structural families, annual kelp positive footprints, native seagrass
composites, a marine floating-kelp mosaic and conditional mapped substrate classes. All tables
passed native-identity, missingness and public-reader readback checks. The separate historical
extract is `.seascape/work/regional-completion-20261016/modeling-period/Data/Seascape`, with
`modeling-period/coverage.json` recording the requested 2009–2026 interval. Kelp has source-year
evidence for 2009–2024; seagrass retains 2019–2020 and 2023–2024 composites. Static references
are not backdated, unavailable years are not filled, and historical operational availability
remains unknown. These source periods do not establish complete spatial survey coverage.

The three DFO Bottom Patches archives yielded 346,972 regional source polygons. Explicit audits
repaired 537 invalid source geometries in copied inventories; raw archives remain unchanged.
Their mapped union covers about 16.34% of reporting-water area. Cross-class overlap conflicts
withhold fractions in 534 R8 and 230 native R6 cells. These products do not complete physical
hardness or the habitat mosaic: the other habitat providers, independent tidal frame and calibrated
hardness definition remain missing. Expanded BC freshwater extracts succeeded; the live US NHD
requests timed out and are recorded as unresolved. Marine Regions boundary redistribution rights
also need resolution before sharing the assembled geometry.

The main `MarineCast/Data/Seascape` catalog and all 21 existing Parquets remain byte-identical
to the start of this run. The candidate is local and partial; it has not been promoted into the
shared study, integrated into the Explorer UI, published or certified as a complete modeling input.

## Validation

Run `python -m pytest -q tests/test_coastal_policy.py`, then the repository suite, quality,
documentation and validation-notebook checks. A regional run additionally checks geographic
control points, the geodesic boundary envelope, land exclusion, context completeness, exact H3
membership, source fingerprints, area bounds and serialized output readback. Only an explicitly
validated mask and membership registry may update the study's pending spatial status.
