# Hydrologic connectivity

## Purpose and non-goals

This family represents freshwater-to-marine entry points, river topology, mapped physical
barriers and passage evidence, and mapped estuary proximity. It does not infer missing barriers,
site-specific passage status, plume dynamics, salinity, or estuary membership.

## Sources, dependencies, and resolutions

HydroRIVERS supplies the common river topology; authoritative B.C./Washington inventories supply
barrier and passage records; PECP/PMEP supply mapped estuaries. Leaf `DATA_SOURCES.md` files are the
authority for provenance and licences. Freshwater, fluvial connectivity, and estuarine distance
are R8; fluvial barriers publish R8 and feature-aware R6 products.

## Commands

```bash
python -m seascape.hydrologic_connectivity.freshwater_sources.build
python -m seascape.hydrologic_connectivity.fluvial_connectivity.build
python -m seascape.hydrologic_connectivity.fluvial_barriers.build
python -m seascape.hydrologic_connectivity.estuarine_connectivity.build
```

## Artifacts and publication

Inventories, normalized networks, mouths, crosswalks, feature/confidence tables, and manifests
live beneath the matching processed leaf directory. Multi-output builders stage complete sets;
the manifest is written last and strict checksums reject interrupted promotion.

## Missingness, QC, and R8 to R6 aggregation

Straight distance and water-network distance are distinct. A graph attachment is not proof of
reachability. Missing barrier records are never zero barriers; passage state is retained only when
the source explicitly assesses it. R6 barrier counts and evidence are aggregated by their owning
rules, with null/unmapped states preserved.

## Inspection and validation

Inspectors show source locations, connectors, components, and feature surfaces through shared
presentation routing. Validation covers river topology, mouth attachment bounds, finite Dijkstra
results, component-aware reachability, passage ontology, R8 to R6 support, and checksums.
