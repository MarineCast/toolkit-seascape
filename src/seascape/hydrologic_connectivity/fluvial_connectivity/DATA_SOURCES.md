# Fluvial-connectivity data and feature contract

## Product objective

This module maps a consistent directed river network onto the resolution-8
marine H3 support. It answers four static questions:

1. how far a marine cell is from the nearest mapped river-network outlet when
   travel must remain on the marine water graph;
2. how large and hierarchical that outlet's connected upstream network is;
3. which mapped river basin and outlet sub-basin the cell is assigned to; and
4. whether land barriers force a detour or a graph discontinuity.

The finer mixed B.C./U.S. river-mouth inventory remains in
`freshwater_sources/`. This product intentionally uses one HydroRIVERS topology
for network metrics and does not splice jurisdictional networks with different
schemas or resolution.

## Source

[HydroRIVERS version 1](https://www.hydrosheds.org/products/hydrorivers) is a
global line network derived from HydroSHEDS at 15 arc-seconds. Reaches begin
where upstream catchment area reaches 10 km² or estimated long-term discharge
reaches 0.1 m³/s. Small streams below both thresholds are therefore absent.

The build uses fields defined in the
[HydroRIVERS technical documentation](https://data.hydrosheds.org/file/technical-documentation/HydroRIVERS_TechDoc_v10.pdf):

- `NEXT_DOWN` for the directed downstream link;
- `MAIN_RIV` for the most-downstream reach and complete connected basin;
- `DIST_DN_KM` and `DIST_UP_KM` for along-river distances;
- `ORD_STRA` for Strahler hierarchy;
- `UPLAND_SKM` for directly connected upstream drainage area; and
- `HYBAS_L12` for the containing HydroBASINS Pfafstetter level-12 sub-basin.

The complete 986,463-reach North American attribute table is used for basin
summaries. Geometry exports are clipped to the configured marine graph context.

## Marine-network distance and structural obstruction

The canonical H3 r8 marine-support product supplies graph nodes, land-barrier-
respecting edges, geodesic edge weights, and component lineage. Each exorheic
HydroRIVERS outlet is first normalized to a nearby water entry point and then
attached only through a bounded connector that remains in the canonical water
mask. Unresolved outlets remain in the mouth inventory with a QC reason. A
deterministic multi-source Dijkstra search assigns every reachable marine cell
to its nearest connected outlet.

For a marine cell and its assigned outlet:

- `WATER_NETWORK_DISTANCE_TO_FLUVIAL_MOUTH_M` is the shortest H3 water-graph
  path, including source and partial-coastal-cell connectors;
- `EUCLIDEAN_DISTANCE_TO_FLUVIAL_MOUTH_M` is straight-line projected distance;
- `FLUVIAL_PATH_DETOUR_M = max(0, network distance - Euclidean distance)`; and
- `FLUVIAL_PATH_DETOUR_RATIO` divides network distance by the larger of
  Euclidean distance and the median graph-edge length, then lower-bounds the
  result at 1. The resolution floor prevents unstable ratios for cells nearly
  coincident with an outlet.

`STRUCTURAL_DISCONTINUITY_FLAG`, `MARINE_NETWORK_COMPONENT_ID`, and the number
of mapped mouths in the component retain graph connectivity diagnostics. Land
is the obstruction source; time-varying tides and currents are not included.

## Tributary and hierarchy summaries

For each mapped outlet, all reaches sharing its `MAIN_RIV` are summarized into:

- connected upstream reach count;
- confluence count, defined as reaches with at least two direct upstream reaches;
- mapped headwater-reach count;
- outlet Strahler order;
- total connected upstream network length;
- maximum upstream network distance; and
- directly connected upstream drainage area.

These are mapped-network quantities subject to HydroRIVERS' extraction
threshold, not counts of every physical stream.

## Watershed-to-marine crosswalk

`WATERSHED_MARINE_CROSSWALK_RES_8.parquet` is a deterministic one-to-one
nearest-outlet crosswalk. Each marine H3 cell receives:

- the HydroRIVERS outlet ID;
- `MAIN_RIV` as the connected river-basin ID;
- the outlet reach's HydroBASINS level-12 sub-basin ID; and
- water-network distance and marine-component lineage.

This is an outlet-association crosswalk. It is not a polygon overlay of complete
watershed boundaries, and it intentionally does not duplicate a cell across
every river basin that could influence it.

## Barrier companion product

This base topology intentionally does not embed physical barrier records. The
sibling `fluvial_barriers/` package now supplies jurisdiction-specific dams,
culverts, waterfalls, tide gates, assessed passage status, source lineage, and
coverage flags using this package's segment, mouth, and marine-crosswalk
artifacts. Missing barrier records remain unknown rather than zero.

## Durable outputs

Processed products live under
`data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/fluvial_connectivity/`:

- `FLUVIAL_CONNECTIVITY_RES_8.parquet`: one feature row per marine H3 cell;
- `WATERSHED_MARINE_CROSSWALK_RES_8.parquet`: explicit nearest-outlet lineage;
- `FLUVIAL_NETWORK_SEGMENTS.parquet`: contextual network reaches with distance,
  hierarchy, and topology fields;
- `FLUVIAL_NETWORK_MOUTHS.parquet`: outlet points and complete-basin summaries;
- `fluvial_connectivity_manifest.json`: formulas, schemas, counts, distributions,
  source resolution, and barrier limitations.

Build and inspect with:

```bash
python -m seascape.hydrologic_connectivity.fluvial_connectivity.build
python -m seascape.hydrologic_connectivity.fluvial_connectivity.inspect
```

The inspector writes
`outputs/domains/environmental_layer/seascape/hydrologic_connectivity/fluvial_connectivity.html`.
Log transforms are used only for selected map color scales; stored covariates
remain raw.
