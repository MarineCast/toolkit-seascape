# Seagrass mapped extent

The canonical producer, `seascape.biogenic_habitat.seagrass.build`, exposes only **Seagrass Extent (All Time)** (`SEAGRASS_EXTENT_ALL_TIME_M2`), presented in **Biogenic Habitats**. The annual generated feature and delivery were retired at the user's request; original survey geometry, observation years and source qualifications remain in the union and provenance. Status, methods, observed/modeled class, source periods, map dates, species resolution and computational geometry repairs remain internal support fields.

The producer geometrically unions eligible positive polygons and classified raster footprints before intersecting each full native H3 cell, independently at R6 and R8 in EPSG:6933 m². H3 edges are segmentized at 0.001° before projection. Coincident evidence and overlapping periods count once. Neither a sum nor a maximum of per-source cell areas replaces this union. Missing positive evidence remains null/unknown, with no claim of surveyed absence, current presence, completeness or pure canopy.

## Sources and temporal support

Reviewed 2026-10-20:

- [WA DNR Nearshore Habitat Inventory](https://dnr.wa.gov/aquatics/aquatic-science/nearshore-habitat-program/nearshore-habitat-inventory), agency public data: the [1995 Whatcom vegetation polygons](https://gis.dnr.wa.gov/site3/rest/services/Aquatics/AQ_Environment/MapServer/66) with `IVEG_CD=eel`, and [1996 Skagit vegetation polygons](https://gis.dnr.wa.gov/site3/rest/services/Aquatics/AQ_Environment/MapServer/60) with `GRID_CODE=5`. Other vegetation classes, including kelp, are excluded. Actual inventory survey years remain provenance in All Time; these are two different regional inventories, not consecutive whole-domain monitoring. Eelgrass species is unspecified in these class maps. Mapped class footprints are not a claim of 100% plant cover.
- [BC CRIMS Eelgrasses](https://catalogue.data.gov.bc.ca/dataset/eelgrasses-coastal-resource-information-management-system-crims), Open Government Licence – British Columbia: legacy mapped polygons, source methods/species attributes retained. Compilation began in 1979 with intermittent updates. `MAP_DATE` is preserved as a map date and does not establish an observation year. These polygons contribute to All Time; relative abundance/importance scores do not scale area and zero scores do not mean eelgrass absence.
- [Peng et al. (2026), Global 10-meter seagrass maps](https://doi.org/10.5281/zenodo.18612240), CC BY 4.0: retained compressed Sentinel-2 2019–2020 and 2023–2024 composites. Only binary positive class 1 pixel footprints contribute to All Time. Both periods and modeled status are explicit. They supply generic seagrass classification, not eelgrass species or field-confirmed observations. Neither endpoint is assigned an annual date; background/nodata 0 is not field absence. Depth, turbidity and clear-water detection limits remain material.

The original WA survey years remain source provenance. There is no annual output or time axis. Undated legacy evidence and multi-year composites contribute to All Time with their different temporal limitations retained. All Time spans available source history, not a fixed 20-year window. It is an evidence mosaic with heterogeneous methods, not a comparable time series or contemporaneous ecological state. Statistical monitoring sites, sampling frames and transects are not full mapped beds; shoreline lines and point observations supply no invented polygon area. No Kelp data are used.

## Build and validation

Acquisition is explicit through the family downloader. Builds read local configured sources. A retained audited inventory, independent R6/R8 full-cell support and JSON source context support replay without acquisition:

```bash
python -m seascape.biogenic_habitat.seagrass.build --inventory INVENTORY.parquet --full-cells 6=CELLS_R6.parquet --full-cells 8=CELLS_R8.parquet --source-context SOURCE_CONTEXT.json --output INTERNAL_PRODUCER_DIR
```

The producer transaction publishes `SEAGRASS_RES_6.parquet`, `SEAGRASS_RES_8.parquet`, the retained source inventory and the standard source/quality manifest. No annual table is produced. The flat delivery contains only `seagrass-r6-static.parquet` and `seagrass-r8-static.parquet` plus the shared catalog. The retired dynamic files have a scoped recoverable migration backup. Unique source data and unrelated products, especially Kelp's separate annual/all-history science, remain intact.

Raster ingestion reads bounded blocks directly from compressed ZIP members. Limits cover blocks, positive polygons, elapsed time, native cells and polygon/cell pairs. Exact archive hashes, original transforms, positive class 1 semantics and computational repairs remain recorded. Older native composite APIs remain explicit compatibility calculations; they are not current feature choices. Legacy composite fractions, network distances and survey confidence are unavailable from the all-history union and must not be inferred from it.

Synthetic tests verify overlap unions, date provenance, positive-only missingness, exclusions, static-only schema and transactional retirement of obsolete annual files. Regional acceptance checks that all retained All Time values and qualifiers remain unchanged, previous positives survive, each native resolution is independently supported and the live app has one scientific choice with no time axis. The family grouping never merges this numeric extent with Kelp or Bivalve.
