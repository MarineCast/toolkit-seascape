# Scientific replay matrix — 2026-10-29

For subsequent whole-study candidates, measured resources, discrepancies and outstanding stages, see the [full-study production report](full-study-reproduction.md). The table below records the earlier bounded evidence.

**All seventeen families now have at least one bounded scientific producer replay.**
This is field-specific evidence, not complete regional or historical reproduction.
Thirteen families use the retained-input replays below; four previously blocked
families now have [new-source candidate runs](real-data-production.md) through
recovered installed operators. All 27 static files also passed the separate compact
projection check. Wider coverage, upstream stages and some source bindings remain open.

The [initial review and maps](reproducibility-review.md) documents the earlier audit.
Public sources were subsequently reacquired for the four repaired pathways;
no delivered dataset or catalog was replaced.

## Family-by-family findings

Paths below are relative to `Toolkits/toolkit-seascape` unless prefixed `Data/`.
`W` means `.seascape/work/source-closure-20261016`, and `P` means
`W/workspace/data/processed/domain/environmental_layer/seascape`. The retained
configuration is `W/workspace/config/data/environment_seascape.yaml`. It is a
historical configured workspace, not a claim that packaged defaults find these
sources automatically. Existing inputs must remain in place or be explicitly rebound.

| Delivered family | Status and current evidence | Retained prerequisites, remaining limit / next step |
| --- | --- | --- |
| Bathymetry | **Source replay verified, partial fields:** 40 R8 cells; 24 depth, quantile, band-count/fraction and local-anomaly fields matched exactly. | `.seascape/cache/regional/bathymetry/GEBCO_2026_COASTAL_CONTEXT.tif`; canonical water neighborhoods under `P/spatial_support/water_network`. Full two-ring neighbor halo retained for local anomaly. Isobath distances and R6 not replayed. |
| Terrain | **Source replay verified, partial fields:** 32 sampled R8 cells with native slope output; mean and Q90 slope matched exactly. | Same GEBCO raster and current `_native_raster_slope_summary`. No slope samples existed in eight other selected cells; not counted as verified outputs. Other plane/neighborhood/ruggedness/openness fields still need their complete halo replay. |
| Bivalve | **Source replay verified, bounded:** 40 R6 cells; native area and null masks matched exactly. | `.seascape/work/biogenic-recovery-20261020/source-inventory.parquet` and `source-context.json`; full native H3 geometry. R8 and complete field/provenance parity not tested. |
| Seagrass | **Source replay verified, bounded:** 20 R6 + 20 R8 cells, ten positive and ten unknown per grid; all 13 non-key native fields matched, including source/date/method/QC qualifiers. | `.seascape/work/seagrass-consolidation-20261020/all-time-producer/SEAGRASS_SOURCE_INVENTORY.parquet`; native source context from bound audit. This starts from retained normalized source geometry, not rerun Sentinel raster classification or provider collection. |
| Kelp | **Source replay verified, bounded:** annual 20 R6 + 20 R8 cells × 35 years = 1,400 rows; all eight non-key fields matched. Static 30 cells/grid (20 positive, ten unknown) matched native area exactly. | Annual uses `.seascape/work/history-2009-2026/kelp-audited-inventory.parquet`. Static replaces its old BC subset with six retained `BC_CRIMS_KELP_BEDS_*.geojson` pages under `.seascape/cache/kelp-consolidation-20261020`, normalized through package `_records`. Static record-ID/count qualifier parity is not asserted. Annual scientific/user review remains pending despite computational parity. |
| Mapped Substrate Classes | **Source replay verified, bounded:** ten covered cells at each R6/R8; all 12 native measurement/QC fields matched exactly. | `W/DFO_BOTTOM_PATCHES_REGIONAL_SOURCE.parquet`, projected geometry audit and `P/spatial_support/water_geometry/H3_COASTAL_WATER_RES_{res}.parquet`. Current `build_areal_class_fractions` uses original classes and EPSG:6933. Unknown/uncovered cells were not selected in this replay. Raw DFO archives remain in `.seascape/cache/regional/bottom-patches`; normalization was not rerun from archives. |
| Freshwater | **Source replay verified, bounded downstream stage:** 40 R8 rows; all five native fields matched within floating-point tolerance. | `Data/Seascape/research/freshwater-mouth-inventory.parquet`, configured decay/width reference and current `_build_h3_features`. Max distance error 2.60e-9 m; pressure error ≤5.33e-12. Raw flowline-to-mouth selection/width inference was not replayed. |
| Nearshore Transitions | **Source replay verified, partial fields:** 20 R8 cells; five eligible/valid/deep-area, deep-fraction and coverage fields matched (max area error 1.75e-10 m²). | Configured water, `W/SOURCE_COASTLINE.parquet`, GEBCO depth raster and full R8 geometry. Current `nearshore_depth_areas` with original nearest-neighbor WarpedVRT, threshold and band width. Connected-deep-water distance, full component labeling and R6 aggregation not replayed. |
| Coast Complexity | **Source replay verified, partial fields:** 20 R8 cells; seven length/density, axial orientation and island fields matched exactly. | `W/SOURCE_COASTLINE.parquet`, `W/land-component-registry.parquet`, `W/source-context.parquet`, configured water and native geometry; current `_coast_chunks` / `summarize_coast`. Sinuosity, headland generation/distance and R6 not replayed. |
| Spatial Support | **Source replay verified, partial fields:** 20 R8 cells; water area, fraction and shoreline-intersection flag matched (max area error 2.39e-5 m²; fraction 3.26e-11). | Current `water_network.build._build_geometry_and_base_support` from `P/spatial_support/water_geometry/COASTAL_CONTEXT_WATER.parquet`, retained config and explicit cells. Graph edges, connectors and neighborhood construction not replayed. A preliminary coastal-policy membership calculation was the wrong producer and differed by up to 3.46 m²; it was rejected rather than relaxing tolerances. |
| Coastal Bounds | **Source replay verified, partial fields:** 20 R8 cells; openness, embayment and angular aperture matched exactly. | Configured water/land geometry and retained marine-support representative points; current directional-fetch and output functions. Open-water network distance still requires the full-context open-seed computation, not a cropped graph. |
| Waterbody Morphometry | **Source replay verified, partial fields:** 20 R8 cells; local minimum width, mean width and censored fraction matched exactly. | Configured water/land geometry and retained representative points; current directional shore-distance/width functions. Constriction, local water-space and distances to narrows/sill candidates still require full graph context. |
| Fluvial Connectivity | **Source replay verified, downstream network stage:** 40 R8 distances matched exactly. | `P/hydrologic_connectivity/fluvial_connectivity/FLUVIAL_NETWORK_MOUTHS.parquet`, retained water geometry and checksum-validated complete 176,364-node graph. Current source attachment kept 1,784 mouths and correctly excluded 59 without valid connectors, then production shortest paths and target connectors reproduced the samples. Raw HydroRIVERS-to-mouth topology, basin attributes and unreachable target cases were not replayed. The configured original HydroRIVERS shapefile under `Modeling/OrcaCast/data/seascape/raw/...` is absent; original source-network closure needs a corrected retained-source binding. |
| Shoreline | **Real-source replay verified, bounded WA fields:** 16 R6 + 40 R8 cells, 20 numeric measurement/diagnostic fields and null masks matched. | Reacquired NOAA NWFSC 2018 source; recovered unique-line-union operator. A further 16 BC R8 cells match from a complete bounded ShoreZone extract; separate shoreline-distance fields remain untested. |
| Anthropogenic | **Real-source production verified, partial:** 16 R6 + 40 R8 cells. Armoring fractions and native null masks match; one positive R6 dredged-channel area matches. | New complete bounded DNR extract and NOAA channels; current water mask differs from historical support, changing area fractions. BC follow-up verifies 12 positive aquaculture and 12 disposal cases per grid and all four public flags across 48 cells. Positive reef, complete inventory and historical water-mask parity remain open. Ecology services returned HTTP 403; OSM returned HTTP 406. |
| Substrate (modeled R6) | **Real-source replay verified at historical sample points:** 16 R6 cells; all four raster fields and independent scalar reads match exactly. | Reacquired dbSEABED ver202512 rasters. Historical coordinates survive in the native audit. Using newer retained support coordinates changes sediment fractions; upstream historical support is not reproduced. |
| Estuary | **Real-source replay verified, bounded US points:** 40 R8 distances match exactly. | Reacquired 103 PMEP points in a declared bounding box and recovered finite-inventory representative-point operator. BC polygon qualification/normalization and full inventory closure remain untested. |

Missing-path findings establish that the recorded bindings are broken, not that
unique source files were deleted everywhere. The follow-up recovered producer code
from Git and reacquired selected public sources; it did not recover deleted releases.
Embedded provenance cannot replace missing source bytes or full inventory qualification.

## Execute the bounded replays

Install the current checkout with Python 3.14 and declared runtime dependencies.
The replay harness uses installed package production functions; it does not
reimplement scientific formulas. Some functions are private and version-bound;
these are maintainer audit examples rather than stable public APIs.

```sh
python scripts/replay_retained_seascape.py \
  --workspace /absolute/path/to/MarineCast \
  --output /absolute/path/to/owned-review-output --group habitats
```

Run groups **sequentially**: `habitats`, `kelp_static`, `physical`, `geometry`,
`support`, `rays`, `network`. The existing `review_delivered_seascape.py` runs the initial
bivalve replay and gallery. Each group writes small JSON comparison results only,
except the initial example's sample Parquet/maps. The harness refuses output below
`Data/`. Inputs are read in place; production publication functions are not called.

The `geometry` group retains whole source geometries intersecting the sampled
support (plus the complete nearshore band). The first whole-coast dissolution
attempt was stopped for runtime; filtering source candidates before union avoids
that overhead without clipping scientific cell support or changing local values.
The support sample passes explicit cells into the actual marine-support producer.
Network distance fields are not validated by the local geometry checks.

Most numeric comparisons use `rtol=1e-10, atol=1e-6`, with null masks/key alignment
checked. Geometry summaries use `rtol=1e-9, atol=1e-6`. Read the per-group script
for exact selected keys and comparisons; sampled results do not prove all regions,
source processing eras or null mechanisms. January 1 annual-Kelp dates were
compared as cell/year keys and retain survey-year-label meaning.

## Evidence and checks

* [Habitat comparisons](assets/review-20261029/habitat-replays.json)
* [Kelp static comparisons](assets/review-20261029/kelp-static-replays.json)
* [Raster, mapped substrate and freshwater comparisons](assets/review-20261029/physical-replays.json)
* [Nearshore and coast comparisons](assets/review-20261029/geometry-replays.json)
* [Marine support comparison](assets/review-20261029/support-replay.json)
* [Directional geometry comparisons](assets/review-20261029/ray-replays.json)
* [Fluvial network comparison](assets/review-20261029/network-replay.json)
* [Retained input hashes](assets/review-20261029/replay-inputs.json)

Installed source hashes and runtime versions remain in the initial review's
environment record. The follow-up production guide records bounded acquisition and
new installed-package checks. Upstream river-network and regional graph reconstruction,
full historical acceptance and independent scientific validation remain incomplete. No publication or dataset promotion is implied.
