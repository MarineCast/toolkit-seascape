# River-mouth data plan

## Narrow product objective

The current product contains only:

1. river-system linework for provenance and inspection;
2. marine river-mouth points with mapped mouth width where a river polygon exists;
3. distance from every modeled water H3 cell to its nearest river mouth, plus the
   nearest mouth identifier and mapped width;
4. unweighted and square-root-width-weighted mapped river-mouth pressure.

Discharge, runoff, plume extent, salinity response, precipitation, permanence,
stream order, drainage area, watershed class, hard-radius source counts,
glaciers, and springs are intentionally outside this build.

## Selected sources

| Source | Role | Limitation |
| --- | --- | --- |
| [B.C. Freshwater Atlas Stream Network](https://catalogue.data.gov.bc.ca/dataset/freshwater-atlas-stream-network) | Detailed B.C. river/stream linework and terminal segments used to locate mouths | The line layer has no physical channel width. |
| [B.C. Freshwater Atlas Rivers](https://delivery.maps.gov.bc.ca/arcgis/rest/services/whse/bcgw_pub_whse_basemapping/MapServer/17) | Authoritative river polygons used to measure B.C. mouth width | Only rivers represented as polygons receive measured width; narrow line-only streams receive the configured 2 m fallback. |
| [USGS NHD small-scale flowlines](https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/4) | Operational U.S. terminal-flowline coverage used to locate mouths | This service is coarser than NHDPlus HR and may omit small coastal streams. HydroRIVERS supplies the broader U.S. system overlay, and the mouth source is labeled `US_NHD_SMALL_SCALE` in every output. |
| [USGS NHDPlus HR NHDArea](https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/8) | High-resolution U.S. `StreamRiver` polygons used only to measure width | NHD represents wide-river areal extent separately from the flowline. A spatial association is required because the operational flowline service is small-scale. |
| [HydroRIVERS v1.0](https://www.hydrosheds.org/products/hydrorivers) | Cross-border river-system coverage and terminal-mouth fallback | HydroRIVERS omits small streams and is not used to estimate width. Detailed jurisdictional mouths take precedence within the configured match distance. |

ArcGIS sources are queried in bounded tiles over source-specific buffered model
extents. HydroRIVERS is downloaded as its published North American archive. Raw
snapshots and a checksum manifest live under
`data/raw/environment/seascape/hydrologic_connectivity/freshwater_sources/`.

## Mouth and width rules

1. A mouth is the endpoint of a terminal or most-downstream route segment that is
   closest to, and within the configured tolerance of, canonical marine water.
2. Detailed B.C. and U.S. mouth locations take precedence over a nearby
   HydroRIVERS terminal point.
3. Width is the median of perpendicular cross-sections at configured distances
   upstream from the mouth along the terminal line.
4. A cross-section is accepted only when it intersects an official mapped river
   polygon close to the terminal line. Width is never inferred from stream order
   or drainage area.
5. When no mapped polygon supports a physical measurement, `MOUTH_WIDTH_M` uses
   the configured 2 m line-only stream fallback. These rows use
   `MOUTH_WIDTH_SOURCE_DATASET=CONFIGURED_DEFAULT` and
   `MOUTH_WIDTH_METHOD=configured_default_line_only_width`.
6. `MOUTH_WIDTH_SOURCE_DATASET` and `MOUTH_WIDTH_METHOD` distinguish measured
   widths from configured defaults in every row.

## Mapped river-mouth pressure

For H3 cell `i` and mapped mouth `j`, the unweighted score is
`sum(exp(-distance_ij / 5000 m))`. The experimental width-weighted score is
`sum(sqrt(mouth_width_j / 2 m) * exp(-distance_ij / 5000 m))`. The build sums
all mapped mouths without a hard cutoff and stores the raw scores without
standardizing or log-transforming them.

The 5 km value is an e-folding distance, not a claimed plume boundary. These
covariates describe effective proximity to the current mapped mouth inventory.
They are not discharge, salinity response, plume extent, or complete physical
river density. B.C. and U.S. mouth sources have different spatial resolution,
so both fields retain the `MAPPED_` prefix.

## Durable outputs

All processed products live under
`data/processed/domain/environmental_layer/seascape/hydrologic_connectivity/freshwater_sources/`:

- `RIVER_MOUTHS.parquet`: marine mouth points with measured or configured-default
  mouth width;
- `RIVER_SYSTEMS.parquet`: normalized river/stream linework;
- `RIVER_MOUTH_FEATURES_RES_8.parquet`: `H3_INDEX`, nearest-mouth distance and
  identity, nearest mouth width, and both 5 km mapped-pressure scores;
- `river_mouths_manifest.json`: counts, schema, and output paths.

The inspector exports
`outputs/domains/environmental_layer/seascape/hydrologic_connectivity/freshwater_sources.html`
with distance and pressure surfaces, width-scaled mouth markers, and the
river-system overlay. Pressure colors use `log1p` for display only; tooltips show
raw scores.
