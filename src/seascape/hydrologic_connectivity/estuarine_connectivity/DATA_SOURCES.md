# Estuary-distance data sources

## Why locations replace polygons

The first version combined EPA CyAN estuary-system polygons in Washington with
much smaller PECP estuary polygons in British Columbia. EPA's Puget Sound and
Strait of Juan de Fuca polygons covered thousands of marine H3 cells, while the
B.C. polygons represented individual coastal estuaries. That produced an
artificial jurisdictional cutoff.

This version normalizes both jurisdictions to one point per mapped estuary and
emits straight-line and marine-connected distance to the nearest point. It does
not emit estuary membership, class, inlet position, exchange, channel degree, or
nearest-estuary identity as model covariates.

## British Columbia

- Dataset: [British Columbia Estuary Threats Assessment](https://databasin.org/datasets/bb12b20098cc47959e428e7408a03824/)
- Original polygon program: Pacific Estuary Conservation Program (PECP)
- Public derivative: 376 polygons, licensed CC BY 3.0 on the Data Basin page
- Normalization: one interior representative point per source polygon

The public layer is a PECP subset containing estuaries that could be linked to a
unique watershed. The broader BCMCA inventory describes 442 mapped estuaries,
but its raw feature data are restricted. Mapped absence is therefore not
evidence of physical estuary absence.

References:

- [BCMCA estuary layer and access status](https://bcmca.ca/data/eco_vascplants_estuaries/)
- [BCMCA metadata](https://bcmca.ca/datafiles/individualfiles/bcmca_eco_vascplants_estuaries_metadata.htm)
- [PECP estuary mapping metadata](https://www.cmnbc.ca/wp-content/uploads/2018/11/PECP-estuary-mapping-project_March-2007_meta.pdf)

## United States

- Dataset: [PMEP Estuary Points](https://www.pacificfishhabitat.org/data/estuary-points)
- Provider: Pacific Marine and Estuarine Fish Habitat Partnership
- Source inventory: 444 point locations across the contiguous U.S. West Coast
- Acquisition: public PMEP ArcGIS feature service, spatially filtered to the
  configured context bbox
- Normalization: source point retained without relocation

PMEP includes estuaries based on current or future potential to provide fish
habitat. It is a curated habitat inventory and may expand or contract; it is not
an exhaustive physical census.

## Processed contracts

`MAPPED_ESTUARIES.parquet` is a supporting point inventory containing:

- `ESTUARY_ID`
- `ESTUARY_NAME`
- `SOURCE_DATASET`
- `SOURCE_FEATURE_ID`
- `SOURCE_REGION`
- `LOCATION_METHOD`
- `WITHIN_MODEL_BBOX`
- `MARINE_GRAPH_H3_INDEX`
- `MARINE_GRAPH_SNAP_DISTANCE_M`
- `geometry`

`ESTUARINE_CONNECTIVITY_RES_8.parquet` contains exactly:

- `H3_INDEX`
- `DISTANCE_TO_ESTUARY_M`
- `WATER_NETWORK_DISTANCE_TO_ESTUARY_M`

The distance is straight-line Euclidean distance in metres from each H3 cell
center to the nearest normalized estuary point, calculated in `EPSG:32610`.
The source query retains a 75 km context around the model bbox so edge cells can
select nearby estuaries outside the prediction support.

`WATER_NETWORK_DISTANCE_TO_ESTUARY_M` is the shortest path over canonical,
water-passable H3 r8 edges. Every estuary point is normalized to a nearby water
entry point and then attached through a bounded connector that remains in the
canonical water mask. Unresolved source points and target cells retain explicit
QC reasons rather than receiving an across-land nearest-node attachment. The
inventory records each water-entry offset, access cell, connector length, water
path fraction, and QC result so this approximation is auditable.

Both values are static mapped-proximity covariates. They are not estuary
membership, distance to a tidal polygon boundary, inlet connectivity, tidal
exchange, flushing, salinity response, residence time, or plume extent.
