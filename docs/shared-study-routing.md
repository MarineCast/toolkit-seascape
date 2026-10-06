# Shared study producer routing and remaining work

The selected-study production gate remains. Two explicit, bounded scientific routes are now
implemented in `seascape.study_routes`: bathymetry and native R8 geomorphometry. They run existing
scientific methods over verified compute memberships before selecting reporting rows. They do
not invoke downloads or regional release promotion. The synthetic CLI orchestration below now
runs them through common family manifests and a retained, byte-bound software generation.
Standalone producers retain their existing interfaces and methods.

## Mandatory delivery core

A qualified coastal plus inland mask, exact R6 reporting registry, scientifically required R8/R6
compute water support, and source/native coverage evidence are mandatory dependencies for any
selected-study metrics. At least the supported static bathymetry table is the baseline deliverable
in this implementation sequence; this is not authorization to certify a real domain. Additional
families may be delivered only at supported grains and with qualified sources and statuses.
Every delivered family needs versioned tables, actual coverage/provenance, independent native
checks and immutable external checksums. A catalog listing is not a demand to populate every field.
The historical 522-field catalog must not force unqualified optional capabilities into the result.

The current complete workflow catalog/release graph assumes many optional families exist.
Before a partial real release, implement an explicit selected-capability manifest and audit the
actual delivered dependency closure. Do not silently skip required inputs, fabricate empty complete
products, reuse the old rectangle's release, or relax audit schema 3.

## Per-family routing inventory

| Family and implementation | Remaining exact producer route | Source or contract prerequisite / delivery scope |
| --- | --- | --- |
| Water geometry (`spatial_support/water_geometry/build.py`) | Replace territorial-water reporting selection with the owner's qualified mask; retain separately sourced context geometry and waterbody types; bind mask/source manifests. | Mandatory support. US line closure has 381 unmatched interior endpoints; qualified coastal/inland topology and mask encoding/hash manifest are unavailable. |
| H3 geometry (`spatial_support/h3_geometry/build.py`) | Materialize exact listed reporting cells and distinct full/clipped compute geometries without `model_area` envelope clipping or simplification changing membership. | Mandatory support. Registry IDs must come from the qualified mask, not seven-cell pilot or bbox centers. |
| Water network (`spatial_support/water_network/build.py`) | Build R8 water-passable context and exact R6 parent support, preserve components/connectors/paths, and expose direct-overlap reporting sets independently of compute hierarchy. Pin edges and neighborhoods to mask/config/context. | Mandatory for graph-derived metrics. Real water geometry and producer-specific halo completeness pending; no R5 water network. |
| Bathymetry (`seafloor_physiography/bathymetry/build.py`, `pipeline.py`) | Explicit route implemented: pinned raster/graph snapshots, compute-first native pixel statistics/anomalies/contours, reporting-last trim, per-row sample/extent status and embedded provenance. Still wire cached pipeline/export/CLI and common manifest/audit to qualified support. | Baseline static family. Source crop/version/datum/rights and graph closure must be qualified for the new support before real use. TID companion is conditional and needs separately pinned aligned categorical raster; it is not routed by the new API. |
| Geomorphometry (`seafloor_physiography/geomorphometry/build.py`) | Explicit existing R8 native slope and graph-scale terrain route implemented; require matching compute bathymetry provenance. Still wire pipeline/publisher and source stencil completeness. | Conditional derived family. Preserve native R8 grain; any R6 export must use a supported family-specific reduction, not an invented direct or hierarchy equivalence. |
| Shoreline characterization (`coastal_configuration/shoreline_characterization/build.py`) | Route exact reporting support; normalize pinned BC/WA class observations with vintage/rights; retain context shore segments and graph-source reach; trim outputs after distance calculations. | Conditional metrics; geometry and cross-border shoreline classification coverage need qualification. Modern classifications cannot be backdated. |
| Shoreline proximity (`coastal_configuration/shoreline_proximity/build.py`) | Replace model-area loader with exact reporting set; keep source segments and 60 km network context outside reporting; pin distance graph and per-source availability. | Conditional metrics; qualified context shoreline/graph and complete requested reach needed. |
| Exposure/enclosure (`coastal_configuration/exposure_and_enclosure/build.py`) | Route target cells separately from native/fetch geometry and 60 km coastal network; preserve existing fetch-ray support and edge statuses; select reporting after computation. | Conditional metrics; 50 km fetch/native source support must be assessed independently; an H3 file is not complete ray water geometry. |
| Waterbody morphometry (`coastal_configuration/waterbody_morphometry/build.py`) | Bind qualified component geometry, graph context and compute bathymetry; compute per component/neighborhood before selecting reporting cells. | Conditional metrics; component/type and coastal/inland topology decisions unresolved. |
| Geomorphic units (`seafloor_physiography/geomorphic_units/build.py`) | Bind compute terrain plus waterbody context; preserve broad graph neighborhoods and existing physical classification before reporting selection. | Conditional derived family; cannot run on reporting-trimmed terrain or unqualified waterbody inputs. |
| Freshwater sources (`hydrologic_connectivity/freshwater_sources/build.py`) | Keep native drainage/catchment inventory in 250 km context and BC/US source contexts of 50/25 km; separate inventory extent from reporting targets. | Conditional metrics; qualify cross-border river/catchment source footprints, vintage and rights. Larger context cannot be replaced by the coastal mask. |
| Fluvial connectivity (`hydrologic_connectivity/fluvial_connectivity/build.py`) | Map qualified outlets to context water graph, compute reachable paths/components before exact reporting trim; bind upstream freshwater inventory. | Conditional metrics; outlets, river topology and water-passable graph prerequisites pending. |
| Selected outlets (`hydrologic_connectivity/fluvial_connectivity/selected_outlets_build.py`) | Bind outlet selection to complete context graph and reporting membership; retain exact deterministic source/tie identity. | Conditional companion, not mandatory for baseline bathymetry. |
| Fluvial barriers (`hydrologic_connectivity/fluvial_barriers/build.py`) | Keep barrier native network inventory outside reporting; compute source topology/paths and availability before water reporting selection. | Conditional metrics; cross-border barrier source completeness/rights and routing graph need qualification. |
| Estuarine connectivity (`hydrologic_connectivity/estuarine_connectivity/build.py`) | Preserve 75 km catchment/source context, qualified estuary types, outlets and graph; select reporting only after source connectivity calculations. | Conditional metrics; native catchments/estuaries and source-period coverage pending. |
| Nearshore transitions (`coastal_configuration/nearshore_build.py`) | Route exact reporting cells but retain compute depth, class shoreline and transition support; provenance must bind both upstream families. | Conditional derived family; depth and class-shoreline support qualification prerequisite. |
| Passage sections (`coastal_configuration/passage_build.py`) | Bind candidate water geometry and compute depth to cross-section construction, retain endpoints and native source context, select reporting links last. | Conditional physical family; topology/section validity and audit schema 3 identities remain mandatory. |
| Geographic gateways (`coastal_configuration/gateway_build.py`) | Bind gateway geometry/network source support and exact reporting references; preserve ownership/component and path validation. | Conditional physical family; qualified component topology needed. |
| Coast complexity (`coastal_configuration/coast_complexity_build.py`) | Retain full context shore segments for existing radius/neighborhood calculations, then trim reporting rows; pin class shore lineage. | Conditional metrics; no simplification or envelope substitution may alter shoreline scale. |
| Mapped habitat mosaic (`biogenic_habitat/mosaic_build.py`) | Route exact targets and qualified mapped geometry on native source extent, preserve 5 km water-network neighborhood area and source vintages; qualify static snapshot semantics. | Optional source-dependent capability. Explicit mapped-source rights and actual observation coverage required; unsupported areas remain unknown. |
| Substrate classification (`benthic_substrate/classification/build.py`) | Keep native dbSEABED grid sampling semantics, per-source validity and graph distance support; trim exact reporting rows and bind raw grid versions/rights. | Optional modeled evidence. Cached global 0.1-degree surfaces do not establish mapped survey coverage or native precision. |
| Bottom hardness (`benthic_substrate/bottom_hardness/build.py`) | Route supported substrate companion rows/coverage if requested; retain current null hardness outputs and method/QC status. | Deferred unsupported numeric index: current method explicitly lacks a verified joint rock/sediment areal denominator. Do not revive historical non-null hardness or fabricate composition fractions. |
| Seagrass (`biogenic_habitat/seagrass/build.py`) | Bind qualified mapped/modeled source geometry, source period and context water graph; compute supported grains before reporting trim. | Optional; coverage/rights/vintage and observed-versus-modeled distinction must be qualified. |
| Kelp (`biogenic_habitat/kelp/build.py`) | Bind qualified source period, mapped support and habitat-distance graph; retain temporal source semantics before reporting selection. | Optional; no annual static duplication or backdating modern polygons. |
| Reef (`biogenic_habitat/reef/build.py`) | Route exact reporting with native/model substrate and terrain context; preserve evidence type and invalid/unavailable upstream statuses. | Optional derived evidence; depends on qualified terrain/substrate, not a newly invented physical hardness index. |
| Benthic composite (`biogenic_habitat/composite/build.py`) | Join only explicitly selected, grain-compatible qualified habitat companions with one-to-one keys and actual missingness. | Optional aggregate; do not require every optional habitat source or turn unknown into zero. |
| Anthropogenic (`anthropogenic/build.py`) | Retain native structures/evidence extent and source observation dates; route water graph and reporting targets separately before R8/R6 export. | Optional source-dependent evidence; source rights/cross-border coverage and modern dates must be qualified. |
| Catalog/eligibility/docs/audit/release (`workflow.py`, publication modules) | Bind delivered capability set and dependency closure to config, masks, source/halo manifests, versioned output hashes and schema-3 audit; publish only validated selected static products. | Mandatory delivery evidence, currently blocked on actual qualified support. Do not broaden the scope to all catalog fields or relax release gates. |

## Explicit scientific route interface

`route_bathymetry` and `route_geomorphometry` take an already verified study support, scientific
configuration and `PinnedInput` records. Inputs are config-relative paths under resolved Data root;
the same bounded byte snapshot is hashed and parsed. Input metadata requires source version,
observation period, rights and evidence type. Graph metadata additionally binds config hash, mask
hash, resolution-specific compute-membership hash and maximum graph hops. The existing graph
validator checks context keys, self rows, pair uniqueness, hop bounds and finite distances; it
does not independently establish native edge passability or graph completeness.

Native raster headers are checked before pixel decoding; Parquet row counts are checked before
table decoding. Defaults are 16 MiB per input and 1,000,000 pixels/rows. These are per-input checks,
not a certified regional peak-memory budget. Existing native slope stencil/header rules remain.
The raster's affine-transformed footprint, native CRS, nodata, dimensions and pixel support are
recorded separately from reporting geometry. No native pixels are clipped to the study mask:
the existing full-H3-cell marine pixel-center statistic grain is preserved; the mask selects rows.

`RoutedProduct` retains compute context and exact reporting tables separately. Reporting rows
include explicit H3 resolution, native sample status and native extent status. No valid marine pixels
means null statistics/counts, not measured zero; valid flat native slope remains observed zero.
`write_reporting` and `write_compute` write separate static Parquet artifacts with embedded route
provenance and refuse overwrite. Downstream geomorphometry refuses reporting-only depth inputs,
wrong study/mask/resolution and inconsistent route identity. These are software artifacts, not
publication: metadata explicitly says `production_ready=false` and `release_eligible=false`.

Actual source rights/coverage, coastal selection and native halo completeness require qualified
owner manifests. The real mask manifest/hash policy and per-producer native source formats remain
the precise contract prerequisite for pipeline/CLI routing. No global execution flag was added.

## Resource caveat

H3 overlap enumeration uses a heuristic envelope-area preflight and a soft candidate-count check
after enumeration. A thin strip can allocate 89 cells with a 20-cell limit before failing. It is not
a strict allocation bound and cannot justify regional scaling or lifting the memory hold. Native
byte/pixel/row checks above do not change that limitation; a defensible regional enumeration budget
or incremental implementation is still required before a broad run.

## Executable core software pipeline

The exact CLI path is:

```sh
seascape --workspace /explicit/fixture-workspace --study-config /fixture/config/study.v1.json \
  study-core-fixture --input-manifest /fixture/config/core-inputs.json
```

`seascape.study_core.run_core_fixture` is the orchestration entrypoint. It consumes a provisional
adjacent input manifest, explicitly labeled `synthetic_software_acceptance`, with pinned config
identity, mask path, compute memberships, native raster/graphs and explicit scientific settings.
The required capability closure is `bathymetry_r6` plus `bathymetry_native_r8`. The sole currently
supported optional capability is `geomorphometry_native_r8`; every other family, including
unsupported numeric hardness and TID, is explicitly excluded in `capabilities.json`. The fixture
layout is config plus `../Data`; this local proof format is not the owner-approved real-source
qualification contract and does not modify root study-v1.

The pipeline performs config validation, exact reporting and compute membership verification,
retained source/mask/graph/config snapshots, native scientific computation, reporting selection,
common family manifest schema 3.0.0 validation, and an audit schema 3 exact-byte inventory. Package
revision/dirty/source-tree identity is retained and checked for changes during computation. The
audit checks reporting keys/resolution/finite values, native missingness and depth-band identities,
embedded route identities, source/upstream checksums and all selected capability manifests.

Successful candidates move to
`.seascape/study-core-fixtures/releases/<release_id>/` beneath the explicit workspace. Source
snapshots are copied, so later edits to original fixture inputs do not change retained products.
Generations are never overwritten. `verify_core_fixture_release` revalidates retained input and
output bytes, scientific table and common manifest contracts, and the bound software audit after
relocation. Unknown optional families are not fabricated to satisfy a whole-catalog release.

The audit and release metadata contain `software_release_passed=true`, but
`artifact_release_passed=false`, `regional_release_eligible=false` and `production_ready=false`.
This deliberately cannot satisfy `publish_candidate_release`, which requires a literal regional
artifact PASS. The software generation is outside the regional resolver's `.seascape/releases`
namespace. No new regional execution/publish flag exists, and the original full regional audit and
publication paths are unchanged. It is an executable end-to-end software proof, not real support
qualification or final processed regional data.

The concrete adjacent native-support contract proposal remains at the task's
`native-support-contract-proposal.json` for parent/config-owner review. Actual mask encoding/hash,
qualification evidence and native halo/source formats remain pending agreement. Their absence
blocks real pipeline/publication adoption rather than being filled with invented qualification.
