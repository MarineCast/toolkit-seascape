# Structural seascape variables (SV-01 through SV-07)

[Documentation index](README.md) · [scientific contracts](CONTRACTS.md) · [stage inputs](stage-inputs.md)

These are species-neutral physical or mapped-source products. A distance, candidate sill,
or mapped habitat area is not prey abundance, whale use, habitat quality, or evidence of
predictive value. All six implemented stages are **optional**; the ordinary demo and
default build do not require these regional inventories. The methods below are fixture
tested, but no new regional candidate, release, independent physical validation, or
OrcaCast consumer integration was run for this branch. Product IDs are registered in
`src/seascape/core/data/catalog.py`; materialized files appear only after a selected
stage succeeds. The checked-in catalog predates these candidate products.

## Build and read

In an owned workspace, edit `config/data/environment_seascape.yaml` after `seascape init`.
Supply reviewed local sources and bounded selections. Each stage reports its required
inputs through read-only preflight; it does not download them. For example:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-selected-outlets --dry-run --check-inputs --json
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-selected-outlets --candidate-root "$SEASCAPE_WORKSPACE/.seascape/candidates/selected-outlets"
```

Replace `seascape-selected-outlets` with `seascape-nearshore-transitions`,
`seascape-passage-sections`, `seascape-geographic-gateways`,
`seascape-coast-complexity`, or `seascape-mapped-habitat-mosaic`. Use a fresh
candidate root for each independent build. A completed schema-3 release can be read
through `seascape.products.resolve_product`; the three long-table facades
`read_released_outlets`, `read_released_gateways`, and `read_released_mosaic`
also validate explicit object/class selections. Their `pivot_selected_*` helpers
require selected IDs and reject duplicate object/cell keys. Join an external
outlet table on `OUTLET_ID` after reading the long table, for example:

```python
from seascape.hydrologic_connectivity.fluvial_connectivity.multiple_outlets import read_released_outlets
rows = read_released_outlets(["reviewed-outlet-id"], workspace="/path/to/released-workspace", resolution=8)
joined = rows.merge(external_outlet_table, on="OUTLET_ID", validate="many_to_one")
```

The external table belongs to its consumer; the toolkit does not calculate a
salmon-weighted or other ecological accessibility score. R8/R6 long tables must not
be merged directly into a one-row-per-H3 predictor matrix. R6 area and topology
summaries recompute on the **union of water-clipped R8 child supports**, not on a
geometric H3 R6 polygon. R6 network point distances use a water-valid R6
representative/attachment, not a child minimum. Existing bathymetry still uses its
own direct-pixel support. Source resolution is retained; resampling does not create
new bathymetric information.

| Addition | Registered principal products and key | Physical definitions and status |
| --- | --- | --- |
| SV-01 | `selected_outlet_inventory` (`OUTLET_ID`); `outlet_relationships_r8/r6` (`H3_INDEX`, `H3_RESOLUTION`, `OUTLET_ID`) | Every exact selected mouth receives a row. `WATER_NETWORK_DISTANCE_M` is minimum passable graph length plus declared source/target connectors; `EUCLIDEAN_DISTANCE_M` uses the same physical endpoints. `DETOUR_DISTANCE_M = network - Euclidean`; ratio is network / Euclidean except at coincident endpoints, where status/QC explains it. Distances are metres. Search-limited, unavailable attachment, and disconnected in the *available* graph have distinct statuses. |
| SV-02 | `shoreline_stations` (`STATION_ID`); `shoreline_transects` (`STATION_ID`, `DEPTH_THRESHOLD_M`); `nearshore_transitions_r8/r6` (`H3_INDEX`, `H3_RESOLUTION`, `DEPTH_THRESHOLD_M`) | For eligible nearshore support E = water-clipped cell ∩ buffered source shoreline, V = E ∩ valid bathymetry and B = V ∩ pixels with positive-down depth ≥ h, area(B) is `NEARSHORE_DEEP_WATER_AREA_M2`, area(B)/area(V) is `NEARSHORE_DEEP_WATER_FRAC_OF_VALID`, area(V)/area(E) is `NEARSHORE_BATHYMETRY_COVERAGE_FRAC`. Raster footprint intersections supply areas. `SHORE_TO_DEPTH_CONTOUR_WIDTH_M` is first sampled threshold crossing on a water-facing, contiguous transect; `CROSS_SHORE_DEPTH_GRADIENT` is depth change divided by the sampling interval. Empty E, nodata, land stop, ambiguous water side, and search limit retain separate statuses. `DISTANCE_TO_CONNECTED_DEEP_WATER_M` currently routes to a selected H3 cell with mapped deep area through the water graph; it does **not** certify a bathymetrically connected deep-water component or depth-constrained path. Component identification remains unfinished. |
| SV-03 | `passage_inventory` (`PASSAGE_ID`); `passage_cross_sections` (`SECTION_ID`); `sill_candidates` (`SILL_CANDIDATE_ID`); `h3_passage_associations_r8/r6` (`H3_INDEX`, `H3_RESOLUTION`, `PASSAGE_ID`) | A section normal to a reviewed centerline is clipped to each wet interval. `WET_WIDTH_M` sums wet lengths. `CROSS_SECTION_AREA_M2` integrates max(depth, 0) over complete valid wet intervals; partial valid integral has a separate field and complete area is null. `WIDTH_AT_DEPTH_THRESHOLD_M` sums intervals meeting depth ≥ h; `MAX_CONTIGUOUS_WIDTH_AT_DEPTH_THRESHOLD_M` is the longest run. `MAX_DEPTH_M` is positive down. Both banks and full bathymetry are required for a complete area. `SILL_CANDIDATE_DEPTH_M` is a **section-maximum proxy** at an interior shoal with deeper sections on both sides; it is not a validated controlling sill depth. Mapped/confirmed sill crests are not implemented. |
| SV-04 | `gateway_inventory` (`GATEWAY_ID`); `gateway_attachments` (`GATEWAY_ID`, `H3_RESOLUTION`, `GRAPH_H3_INDEX`); `gateway_route_diagnostics` (`ROUTE_ID`, `H3_RESOLUTION`); `gateway_relationships_r8/r6` (`H3_INDEX`, `H3_RESOLUTION`, `GATEWAY_ID`) | Network distance reaches reviewed gateway-geometry attachments, with connector length and graph status, not a gateway midpoint. Reviewed basin polygons can produce ambiguous membership; configured corridor axis position and lateral offset are metres and can be null. The route diagnostic removes declared crossing edges in a derived graph view; `ALTERNATE_ROUTE_LENGTH_AFTER_GATEWAY_REMOVAL_M` is a bounded alternate path length, not a count of routes or ecological importance. |
| SV-05 | `land_component_inventory` (`LAND_COMPONENT_ID`); `headland_candidates` (`HEADLAND_CANDIDATE_ID`); `coast_complexity_r8/r6` (`H3_INDEX`, `H3_RESOLUTION`) | Source coast length divided by water support area gives `SHORELINE_LENGTH_DENSITY_M_PER_KM2`; source segment arc/chord gives sinuosity at configured smoothing scales. Axial bearing uses length-weighted sin(2θ), cos(2θ), and concentration. Water-facing normal is separately probed. Headlands are curvature **candidates** at a declared smoothing/station scale. Islands are complete source land components before cell clipping; distinct IDs count once, with within-support area and eligible-area denominator. Source-boundary contacts carry truncation QC. These are cartographic-scale dependent estimates. |
| SV-06 | `normalized_mapped_habitat_inventory` (`RECORD_ID`); `mapped_habitat_support_r8/r6` (`H3_INDEX`, `H3_RESOLUTION`, `SUPPORT_TYPE`); `mapped_habitat_mosaic_r8/r6` (support key plus `HABITAT_TYPE`) | `MAPPED_AREA_M2` is the resolved polygon area intersecting eligible support; `MAPPED_FRACTION_OF_ELIGIBLE` divides by that support area. `SURVEYED_AREA_M2` comes only from complete survey footprints, never occupied polygons. `OBSERVATION_STATE` distinguishes presence, complete-footprint absence, and unknown. The same as-of resolver handles newer absence and overlap union. `compatible_union` geometrically unions class footprints only with compatible year support; subtype areas may overlap. `INTERSECTING_EVIDENCE_RECORD_IDS` lists intersecting evidence including superseded presence and absence, so it is not solely surviving-patch lineage. Marine and tidal-frame intertidal supports remain separate. Network distance and 5 km mapped-area fields are available for selected marine classes; intertidal network attachment remains unresolved. A missing regional provider does not imply absence. |
| SV-07 | No product | Outer-coast shelf width/position remains source blocked pending a reviewed shelf polygon/edge, datum and scope. A 200 m inland contour is not treated as a shelf break. |

## Source acquisition and review gate

Input paths in the packaged YAML are local configuration, not acquisition commands.
For SV-01, build the existing normalized HydroRIVERS mouth inventory and select exact
`FLUVIAL_MOUTH_ID` values. For SV-02, provide the existing source shoreline, water
geometry, GEBCO raster and their source manifests. Its raw negative elevation is
converted to positive-down depth only after masking land/nodata; record raster native
spacing, horizontal CRS, vertical datum and effective source scale. For SV-03, supply
a reviewed passage GeoParquet with stable IDs, bounded polygon, ordered centerline,
source/rights and depth datum. For SV-04, provide reviewed gateway geometry, valid
water-network attachments, and optional basin/corridor/route registries. For SV-05,
provide source coastline plus complete land components and source-context boundary.
For SV-06, review each provider's schema, native class semantics, rights, observation
date, available-at date, survey method, survey footprints and geometry support; then
use `VectorProviderContract` and `normalize_vector_provider` or supply equivalent
normalized GeoParquet. Intertidal support must be independently mapped in its tidal
frame. No provider-specific rights or regional coverage are asserted here.

The stage settings enforce small `max_cells`, `max_pairs`, `max_sections`,
`max_transects`, `max_records`, and radius-search bounds; inspect the dry-run and
configured outputs before execution. Run `PYTHONPATH=src python
scripts/check_structural_variables.py` for the 5-cell, 4-outlet, 2-gateway, 1-passage,
10×10-raster offline fixture. Its thresholds are software test controls, not
ecological recommendations. Missing source, partial coverage, graph disconnection,
search limit, source-context boundary censoring and confirmed zero are different
states. Check the specific status/QC columns before interpreting a numeric result.
