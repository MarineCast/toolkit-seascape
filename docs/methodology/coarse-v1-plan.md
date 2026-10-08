# Coarse-first seascape v1 scope

The canonical backlog is [src/seascape/TODO.txt](../../src/seascape/TODO.txt). This document records the completed regional scope and later upgrades; it does not authorize acquisition or a new producer run.

## Published scope and acceptance

The reviewed static consolidation `seascape_consolidated_static_native_r6_r8_20261008_v5` contains 2,621 native R6 rows with 342 columns and 88,243 native R8 rows with 489 columns. R6 remains the default, with supported native R8 companions. Its manifest raw-content SHA-256 is `4018f5822575ab7f6e2a441eb389e22b67d78614141ab3a0295cbeba482b891b`. Each immutable release carries its field dictionary, source bindings, status/coverage qualifications, checksums and publication receipt. Prior releases remain unchanged.

The established regional bounding box is longitude −129.7 to −121.5 and latitude 45.9 to 51.5. A bounding box is not source coverage or water support. Exact existing reporting keys and native scientific methods are retained. No R5 water network, hierarchy aggregation, R6 terrain classification or R8 substrate upsampling is inferred. Static fields are versioned once, not repeated annually or daily. Observation years and model-composite vintages remain distinct.

| Scope | Delivered evidence | Limitations |
| --- | --- | --- |
| Existing static core | Prior bathymetry, graph, shoreline, anthropogenic, habitat and proximity fields retained exactly | Original source-relative and partial-support qualifications remain |
| Native R6 seagrass | Positive pixel-centre counts and projected positive-footprint overlap, complete available-source scan | Generic 2023–24 model composite, not species-specific eelgrass, surveyed coverage or absence; 34 partial source rectangles; R8 deferred |
| Direct native R6 substrate | Separate modeled rock score and gravel/sand/mud composition, point availability and conditional sediment entropy | Coarse 0.1° modeled surfaces; unknown observation dates; physical hardness, H3 areal coverage and joint rock/sediment fractions unavailable |
| Native R8 terrain form | Context-gated elevated/depressed/neutral slope proxies with explicit input/QC and NULL reasons | Heuristic, not calibrated geology/confidence; width, sill, constriction and native R6 classification unavailable |
| Mapped bivalve evidence | Existing source-scoped full-hex diagnostics and source provenance retained | Not structural reef fraction, habitat absence or survey completeness |
| Integrated ledger | Every field linked to native resolution, source/version, method, units/denominator, status/coverage and immutable release identity | Scoped completion does not certify the entire historical physical catalog |

The v5 join preserves all 301 prior R6 and 450 prior R8 fields exactly, including types, NULLs, row/column order and schema metadata. It adds 41 `SUBSTRATE_MODEL__` fields at R6 and 39 `TERRAIN_FORM__` fields at R8, including source release IDs. Existing dictionary entries, source bindings, sidecars and toolkit registry snapshots are preserved. These are reviewed release methods; this publication does not change the stock builder defaults or add the audit-only regional callers to the package.

## Seagrass method and qualification

Cached GlobalSeagrass2023_2024 evidence records Peng et al. 2026, DOI `10.5281/zenodo.18612240`, CC BY 4.0. The product is a generic positive-only shallow coastal model, not a field survey. Native pixels use an angular grid; nominal resolution does not establish constant pixel area.

All 20,610 blocks intersecting complete native R6 polygons were processed. The result contains 8,007,951 positive centres and 529,675,221.49 m² positive footprint overlap, with 285 nonzero and 2,336 zero-positive cells. Zero is not observed absence. Full-cell support is not water-clipped. The operator `native_positive_pixel_footprint_overlap_epsg6933_full_h3_lonlat_vertex_polygon_segmentized_0p001deg_v1` transforms native pixel footprints into EPSG:6933 and intersects them with H3 longitude/latitude vertex polygons segmentized at 0.001°. This is an explicit projected-edge approximation. Pixel-centre counts remain separate from footprint area.

Independent selection, boundary/seam tests and 32 cell-first references validate numerical processing. Shared GDAL/H3/GEOS/PROJ is an independence limit. Retained source evidence supplies the 2023–24 composite dates; a current provider metadata refresh remains unavailable. Native R8 needs its own support and cost qualification.

## Substrate method and qualification

Exact HUB Ocean dbSEABED products `[ver202512]` declare CC BY 4.0: rock dataset `e36187d8-c249-45ed-af53-47a06f52cf5d` and sediment dataset `5065080c-b9e7-4e08-b1f5-3a757007cade`. Official file-specific GeoTIFF metadata identifies gravel, sand and mud percentages; cache headers and raw hashes match. Product publication version is not observation year. Model-input observation dates remain unknown.

`direct_native_R6_representative_point_bilinear_percent_v1` samples existing source-relative water representative points inside their focal R6 cells. Pixel-centre bilinear weights exclude masked, nodata −99 and nonfinite neighbors; remaining weights are renormalized. Missing stays NULL, while valid zero stays zero. This is distinct from the stock builder's weighted R8 point aggregation and from H3 areal averaging.

Each of the four surfaces is available at 2,305 points, with 316 NULLs and 1,404 partial-neighbor samples. Rock is a modeled percentage-coverage score, including consolidated and biogenic/chemogenic hardgrounds; it is not measured lithic-rock hardness or H3 areal fraction. Gravel/sand/mud retain their separate sediment-composition basis. Entropy is emitted only when all three values are finite, have positive mass and sum approximately to one using absolute tolerance 0.001 and relative tolerance 0.00001. No forced closure or rock-complement denominator is introduced.

All 10,484 independent scalar raster samples, 2,621 composition checks and 128 frozen-pilot comparisons passed. Three rock values exceed mathematical one by 2.22e-16 due to floating-point accumulation; reviewed unrounded values are retained with 1e-12 numerical comparison tolerance. This is not a source percentage range violation. Physical hardness, areal substrate/survey coverage and a joint four-part composition remain unsupported.

## Terrain method and qualification

`native_R8_terrain_form_proxy_v1` requires finite positive-down depth, focal native marine support, native-raster slope in 0–90°, finite ring-four standardized terrain position, no position QC reason and complete four-hop context. Positive terrain position means neighboring mean depth minus focal depth: the bed is relatively elevated. All eligibility checks precede label thresholds.

Position ≥1 yields elevated and ≤−1 depressed terrain proxies. Otherwise slope ≥15° yields steep neutral, ≤5° low-slope neutral and the remainder intermediate neutral. Thresholds are heuristic; no geological confidence probability is assigned. The 88,243-row result has 70,872 eligible labels and 17,371 NULLs: 7,851 depth, 7,518 slope and 2,002 terrain-position unavailable. Source context flags remain explicit.

The first regional audit caller converted source nullable-string QC to Pandas NaN and incorrectly withheld eligible labels. Its scalar check repeated the representation conversion. Corrected Arrow-native batches preserve Python None; the reviewed operator and pilot remain unchanged. All rows passed an independent source-NULL scalar reference and exact source/QC comparisons. A dedicated conversion regression prevents the shared-error validation pattern. Failed attempts remain in local release provenance, outside version-controlled source.

## Bounded processing and publication

Cached sources were inspected before processing. Source acquisition, domain selection and resource estimates require explicit authorization. Regionally approved processing used one worker and at most 512 MiB RSS. Validation streams avoid overlapping whole-source, joined-output and readback copies. Persist peak RSS before checking a resource guard; do not retrospectively mark failed attempts compliant.

Static v5 required one streamed 78,392,987-byte candidate, with no complete working copy of the previous static tables. Every old and appended field was independently re-read and compared. The approved publication staging cap was 2.5 GiB, including workspace plus the single incoming copy. Established publication copies once to an incoming release directory, verifies hashes, atomically renames on the same filesystem and verifies readback again. Workspace evidence and all 18 prior releases remain intact. The manifest's candidate state remains a historical snapshot; a separate publication receipt records promotion.

## Ownership and later upgrades

Hydrology owns river topology, drainage, discharge and barriers. Seascape consumes qualified mouths/proximity with source IDs, clipped-query flags, confidence, tidal/estuary conventions and distributary treatment. Terminal flags alone and universal nearest-shore snapping do not establish mouths. The former HydroRIVERS topology pilot was canceled.

Later work includes fine coast/islands, higher-resolution habitat surveys, measured hardness, passage/sill methods and expanded coverage. Potential sources need exact rights, version, footprint and semantic qualification before acquisition:

- [DNR SVMP](https://dnr.wa.gov/aquatics/aquatic-science/nearshore-habitat-program/nearshore-habitat-eelgrass-monitoring): site opportunity is not mapped bed; trace presence may have zero area.
- [DFO NETForce](https://open.canada.ca/data/en/dataset/a733fb88-ddaf-47f8-95bb-e107630e8e62): preserve observed/model/bed distinctions and source-specific support.
- [PMEP CMECS substrate](https://www.pacificfishhabitat.org/data/data/nearshore-cmecs-substrate-habitat/): retain crosswalk methods/scales and quality; not measured hardness.
- [DFO Bottom Patches](https://open.canada.ca/data/en/dataset/6cda0f8d-110e-423d-8d7a-bf8a40eaa26e): separate observed and predicted support.
- [DFO sponge polygons](https://open.canada.ca/data/en/dataset/8ba7bced-b63f-462a-a8a1-7c7c8a7bcfa4): public-source lead, not an already ingested replacement for the configured access-only gate.
- [NOAA rocky HAPC](https://www.fisheries.noaa.gov/inport/item/79362): regulatory mapped extent, not hardness; consider only a qualified bounded subset rather than the approximately 10.9 GB package.

Retain [OSM attribution](https://www.openstreetmap.org/copyright) and the [mean high water springs coastline convention](https://wiki.openstreetmap.org/wiki/Tag:natural%3Dcoastline). Mapped infrastructure and ambiguous aquaculture tags do not establish licensed boundaries or surveyed habitat absence.
