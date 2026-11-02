# Approved Seascape compact cores

> Historical review/migration reference. The normal writer now follows the
> [metric-only contract](metric-only-exports.md): no audit dependency, no diagnostic
> columns and no null-to-zero imputation. Existing delivered files remain unchanged.


Checked against local delivery schemas, Parquet footer null counts and targeted source formulas on **2026-10-25**. The user approved these twelve compact schemas on 2026-10-25; they are now implemented delivery policies. Approval does not establish modeling eligibility. The five already-reviewed static areas follow [reviewed delivery](reviewed-delivery.md).

Every core file retains `h3_index`, with the lower_snake_case metric names below. The required external audit retains the original names and native H3 support. Counts below include the H3 key. Existing R6/R8 support differs between families; join on H3 explicitly and never assume identical row sets. No new resolution or missing metric is synthesized.

These cores preserve native values and unknowns; boolean fields are stored as nullable int64 0/1. Anthropogenic retains its previously approved false-fill policy only for its four presence flags. A blanket zero-fill would change unreachable distances, unsupported composition and unobserved geometry into measurements. Move audit-only fields into required external support rather than discarding lineage. Useful alternative measurements are distinguished from unavailable placeholders.

| Family | Previous columns/file | Current core columns/file |
| --- | ---: | ---: |
| Anthropogenic | 57 | 6 |
| Coast Complexity | 19 | 10 |
| Coastal Bounds | 11 | 5 |
| Estuary | 25 | 2 |
| Fluvial Connectivity | 24 | 9 |
| Mapped Substrate Classes | 14 | 5 |
| Nearshore Transitions | 16 | 4 |
| Shoreline | 71–88 | 10–11 |
| Spatial Support | 17 | 4 |
| Substrate | 27 | 5 |
| Terrain | 60 | 9 |
| Waterbody Morphometry | 20 | 8 |

The largest reductions are diagnostics, unavailable placeholders and alternative representations. Some coverage/censoring measures remain deliberately: they materially change how a measurement should be interpreted.

## Anthropogenic

Keep the four already-selected presence flags and one useful coastal modification measure. Externally retain source-null flags, area/QC components, record totals and lineage. Fourteen distance/overwater measures are entirely null at both resolutions; exclude those placeholders from the compact file. Filled false means no mapped positive evidence, including unknown. It does not prove absence.

| Column | Description | Units |
| --- | --- | --- |
| `has_mapped_aquaculture` | Qualified mapped aquaculture evidence | 0/1 |
| `has_mapped_artificial_reef` | Mapped artificial reef evidence; ARSBC/WDFW/NOAA enrichment documented separately | 0/1 |
| `has_mapped_disposal_site` | Mapped disposal-site evidence | 0/1 |
| `has_mapped_dredged_channel` | Mapped dredged-channel evidence | 0/1 |
| `shoreline_armoring_fraction` | Source-qualified shoreline armoring fraction; preserve unknowns | fraction |

## Coast Complexity

Keep two physical sinuosity scales and paired axial encodings. Raw orientation degrees, total length and island area remain useful alternative representations in the audit; object IDs and censored-object lists are lineage. Do not assume this shoreline support is identical to the separate Shoreline product. Missing orientations stay unknown.

| Column | Description | Units |
| --- | --- | --- |
| `shoreline_density_m_per_km2` | Mapped shoreline length per support area | m/km² |
| `shoreline_orientation_sin_2theta` | Cyclic encoding of shoreline axial orientation | 1 |
| `shoreline_orientation_cos_2theta` | Paired cyclic encoding; retain with sine | 1 |
| `shoreline_orientation_concentration` | Agreement among segment axial orientations | 1 |
| `shoreline_sinuosity_500m` | Shoreline sinuosity at the declared 500 m scale | 1 |
| `shoreline_sinuosity_2000m` | Shoreline sinuosity at the declared 2,000 m scale | 1 |
| `island_count` | Mapped islands intersecting the source support; not abundance | count |
| `island_fraction` | Island area fraction on this product support | fraction |
| `distance_to_headland_candidate_m` | Distance to a geometry-derived headland candidate | m |

## Coastal Bounds

Enclosure is exactly 1 minus openness in the source formula and current delivered arrays, so keep one. Connector methods/distances, component IDs and network QC move to audit. Search limits, bearing configuration and open-water seed threshold remain required metadata.

| Column | Description | Units |
| --- | --- | --- |
| `distance_to_open_water_m` | Distance to configured open-water graph seeds | m |
| `ocean_openness_index` | Mean geometric fetch normalized by maximum search | 1 |
| `embayment_index` | Difference between maximum and mean normalized fetch | 1 |
| `open_water_aperture_deg` | Angular width of sufficiently open fetch bearings | degrees |

## Estuary

This is a representative-point proximity product, not physical estuary boundary distance, salinity, tidal connectivity or an estuary membership flag. Four physical/connectivity/time placeholders have Arrow null type. The inventory count is a repeated constant of 292, not estuaries per cell. Move it, source IDs, projection/support flags and methods to audit. Consider hiding the family from default modeling until its point-proxy interpretation is accepted.

| Column | Description | Units |
| --- | --- | --- |
| `distance_to_mapped_estuary_point_m` | Proximity to qualified normalized mapped representative points | m |

## Fluvial Connectivity

Keep network distance and upstream size/branching. Direct distance, detour, segment counts and component mouth counts are useful optional alternatives, not rubbish; place them in the external support. Reachability and original network QC remain essential to interpreting null distances. Do not fill disconnected/null distances or upstream metrics with zero. Count columns are stored as double now; validate integer-valued nonnull data before any future integer conversion.

| Column | Description | Units |
| --- | --- | --- |
| `water_network_distance_to_river_mouth_m` | Distance along the qualified marine network | m |
| `connected_drainage_area_km2` | Connected upstream drainage area | km² |
| `connected_river_network_length_km` | Connected upstream network length | km |
| `connected_upstream_distance_km` | Connected upstream distance metric | km |
| `connected_strahler_order` | Connected river network order | order |
| `connected_headwater_count` | Connected source headwaters | count |
| `connected_tributary_junction_count` | Connected tributary junctions | count |
| `has_reachable_river_mouth` | Reachable under this graph and source context | 0/1 |

## Mapped Substrate Classes

Keep one representation of class composition and its coverage denominator. Areas, record counts, overlap diagnostics and QC move to audit. Fractions do not measure physical hardness; conflicts/unmapped cells stay null. In models with an intercept, all three fractions may be redundant; selecting the model encoding is downstream work.

| Column | Description | Units |
| --- | --- | --- |
| `mapped_hard_substrate_fraction` | Hard class conditional on usable mapped area | fraction of mapped area |
| `mapped_mixed_substrate_fraction` | Mixed class conditional on usable mapped area | fraction of mapped area |
| `mapped_soft_substrate_fraction` | Soft class conditional on usable mapped area | fraction of mapped area |
| `mapped_substrate_coverage_fraction` | Mapped source coverage of reporting-water support | fraction |

## Nearshore Transitions

The current depth threshold (100 m) and nearshore band width (1,000 m) are constants: retain them in metadata rather than repeating them. Area components, target IDs and QC move to audit. Keep coverage because low survey support changes the meaning of the deep-water fraction; missing/unreachable is not zero distance.

| Column | Description | Units |
| --- | --- | --- |
| `nearshore_deep_water_fraction` | Deep-water share of valid bathymetry in the nearshore band | fraction of valid area |
| `distance_to_connected_deep_water_m` | Distance to qualified connected deep-water target | m |
| `nearshore_bathymetry_coverage_fraction` | Valid bathymetry coverage of eligible nearshore support | fraction |

## Shoreline

Keep total length, seven physical class fractions, one coverage measure and the existing overall shore distance (R8 only). Class lengths and seven straight distances to class-specific shorelines are useful optional additions for absolute-length/offshore models; retain them in the audit, not the minimal core. Seven water-network class distances and physical-water-fraction fields are entirely null. Do not manufacture an R6 overall distance or infer exclusive classes: class overlap policy and fraction denominators stay explicit.

| Column | Description | Units |
| --- | --- | --- |
| `mapped_shoreline_length_m` | Total mapped shoreline length on this native support | m |
| `shoreline_classified_coverage_fraction` | Source-defined classified shoreline coverage | fraction |
| `rocky_shore_fraction` | Source-defined rocky shoreline class fraction | fraction |
| `sandy_shore_fraction` | Source-defined sandy shoreline class fraction | fraction |
| `gravel_shore_fraction` | Source-defined gravel shoreline class fraction | fraction |
| `cliff_shore_fraction` | Source-defined cliff shoreline class fraction | fraction |
| `bluff_shore_fraction` | Source-defined bluff shoreline class fraction | fraction |
| `deltaic_shore_fraction` | Source-defined deltaic shoreline class fraction | fraction |
| `estuarine_shore_fraction` | Source-defined estuarine shoreline class fraction | fraction |
| `distance_to_mapped_shoreline_m` | Existing mapped shoreline distance; R8 only | m |

## Spatial Support

Keep a small shared denominator/support table. H3 identity already encodes cell location/resolution; cell area can be calculated from H3, while land fraction is complementary to water fraction. Representative points, full/partial flags, graph degree, component IDs, connector details and mask/support versions remain audit or metadata. H3 centroids are not interchangeable with the existing representative points; dropping them from the core does not redefine those points.

| Column | Description | Units |
| --- | --- | --- |
| `water_area_m2` | Mapped water area on this product support | m² |
| `water_fraction` | Mapped water share of cell | fraction |
| `intersects_shoreline` | Intersection with configured shoreline | 0/1 |

## Substrate

Keep modeled rock score and three sediment components; retain modeling qualifiers and point-support scale. Neighbor weights/counts, entropy, fraction sum and methods move to audit. Physical hardness and joint rock-sediment fraction are entirely null. Do not label modeled components as measured physical hardness or combine them with mapped class fractions. This product is currently R6 only.

| Column | Description | Units |
| --- | --- | --- |
| `modeled_rock_presence_score` | Interpolated rock-presence score, not physical hardness | score |
| `modeled_gravel_fraction` | Modeled sediment composition | fraction |
| `modeled_sand_fraction` | Modeled sediment composition | fraction |
| `modeled_mud_fraction` | Modeled sediment composition | fraction |

## Terrain

The approved compact starter set contains eight metrics; retain all original scales/curvatures/relief variants as optional research fields in the audit. Ring 2 is an explicit simplicity choice, not validated as the best predictive scale or equivalent to a fixed metre radius. Native raster slope and H3 neighborhood slopes are different measurements. Preserve positive-down depth convention, raster masking and aspect validity. Do not recode missing slope/aspect as zero.

| Column | Description | Units |
| --- | --- | --- |
| `seafloor_slope_mean_deg` | Mean marine native-raster slope | degrees |
| `seafloor_northness` | Cosine of source aspect | 1 |
| `seafloor_eastness` | Sine of source aspect; keep paired with northness | 1 |
| `terrain_position_ring_2_z` | Terrain position at H3 ring 2 | standardized |
| `depth_std_ring_2_m` | Depth standard deviation at H3 ring 2 | m |
| `vector_ruggedness_ring_2` | Orientation-based ruggedness at H3 ring 2 | 1 |
| `positive_terrain_openness_deg` | Positive terrain openness on source scale | degrees |
| `negative_terrain_openness_deg` | Negative terrain openness on source scale | degrees |

## Waterbody Morphometry

Keep minimum/mean width, constriction, two candidate distances, local waterspace area and width censoring. Median/std width, perimeter, compactness and branch count are optional alternatives; component and connector fields are audit details. Retain censoring because search-limited widths are bounds, not exact cross-channel widths. Sills/passages remain geometric candidates, not navigational certification.

| Column | Description | Units |
| --- | --- | --- |
| `local_waterbody_min_width_m` | Minimum source directional waterbody width | m |
| `waterbody_mean_width_m` | Mean source directional waterbody width | m |
| `constriction_index` | Source geometric constriction index | 1 |
| `distance_to_constricted_passage_m` | Distance to geometry-derived constricted passage | m |
| `distance_to_sill_candidate_m` | Distance to geometry-derived sill candidate | m |
| `local_waterspace_area_km2` | Source local waterspace area on configured neighborhood | km² |
| `waterbody_width_censored_fraction` | Width directions reaching the configured search limit | fraction |

## Pending reviewed-family decisions

**Annual Kelp:** propose `h3_index`, `date`, `annual_kelp_extent_m2`, `has_mapped_kelp` (0/1). Keep survey-year precision and original annual nulls in required external support if a zero-fill delivery policy is later approved. This proposal has not changed the annual file.

**Freshwater:** the current approved edit removes only resolution. A possible further core is `h3_index`, `distance_to_river_mouth_m`, `mapped_river_mouth_pressure_5km`, `mapped_width_weighted_river_mouth_pressure_5km`; IDs and nearest-mouth width remain support/optional fields. The existing five non-key values are currently preserved. Freshwater is present in prepared Explorer catalogs; running-UI visibility was not independently checked in this assessment. Native R6 requires source-backed recalculation, not averaging R8 distances.

## Delivery and restoration

All twelve cores use `reviewed-core-static-v2`. Full original tables, optional alternative measurements, QC, source details, types and nulls remain in required external audits. `read_area` verifies bindings and returns the compact public schema; `restore_native` recovers the native table. The Explorer exposes only approved core metrics and retains original qualifiers in Details. Renamed public metrics have new feature IDs, so existing selections using retired field IDs may reset to a valid current field.

Normal exports validate native inputs before applying the core projection. Missing or ambiguous required source measures fail; measurements from a different native contract are not relabeled as modeled quantities. Native identity-only tables remain join inputs rather than creating empty metric products. Existing alternative native APIs remain separate from this reviewed delivery contract.

Machine-readable current field inventory and exact approved mappings are retained in the workspace Reports/seascape-review-2026-10-25 evidence directory. This review did not acquire fresh sources, compute regional geometry or evaluate model skill.
