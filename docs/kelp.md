# Kelp extent

Kelp has one producer, `seascape.biogenic_habitat.kelp.build.build_kelp_habitat`,
and one delivered area, `kelp`. The Data Atlas exposes two scientific features:

| Feature | Field | Support |
| --- | --- | --- |
| Annual Kelp Extent | `ANNUAL_KELP_EXTENT_M2` | Mapped positive bed-extent polygon union in one recorded survey year, intersected with the full native H3 cell, m². |
| Kelp Extent (All Time) | `KELP_EXTENT_ALL_TIME_M2` | Spatial union of eligible mapped positive bed extents across all available history, intersected with the full native H3 cell, m². |

The static and dynamic Parquets are cadence variants of this one dataset, at R6
and R8. They replace the separate annual-footprint and mapped-kelp-mosaic areas.
Quality, source IDs, observation years, unknown-date contributions and geometry
repair flags remain in the tables and inspector; they are not additional picker
features. The normalized inventory and source audit are internal lineage.

## Calculation and interpretation

The extent calculation geometrically unions overlapping polygons before measuring
area in EPSG:6933. Duplicate sources and repeated annual observations cannot add
the same patch twice. R6 and R8 are independently calculated on their own full
native H3 geometry; no R8 upsampling or parent averaging is used.

Full-H3 extent deliberately preserves valid historical positives outside a newer
static water mask. It is not water-clipped area, water fraction, historical water
level, pure canopy area, habitat suitability, current presence, or a kelp/no-kelp
absence mask. Cells without mapped positive evidence have null extent and explicit
`no_positive_evidence_unknown_absence` status. A zero or missing source record is
not converted into a surveyed absence.

All available recorded years are used by default. The current dated source has
35 survey years, 1989–2024 excluding 1993. January 1 is only the survey-year label;
no daily expansion or forward fill is performed. 2025–2026 annual observations are
unavailable. Optional `start_year`/`end_year` bounds restrict known observation
years and exclude undated evidence by default. `include_undated=True` is an
explicit override; no unknown date is manufactured.

The default All Time product additionally includes explicitly flagged undated
legacy polygons. It must therefore be described as **1989–2024 dated evidence
plus undated legacy mapping**, not as a fully dated 1979–2024 observation series.
CRIMS compilation activity began in 1979; that is not an observation date for
each polygon. Catalogue update/retrieval dates never become survey years.

## Sources checked on 2026-10-20

| Source | Treatment and limits |
| --- | --- |
| [Washington DNR annual floating-kelp inventory](https://dnr.wa.gov/aquatics/aquatic-science/nearshore-habitat-program/kelp-monitoring) | Annual and All Time. Outer Washington coast, Strait of Juan de Fuca and mapped aquatic-reserve surveys. Bull and giant floating kelp bed extent, not complete statewide survey coverage. Processing differs between vector/CAD 1989–1992, approximately 20 m raster 1994–2009, and approximately 4 m raster 2010–2024; raw annual areas are not assumed perfectly comparable. |
| [B.C. CRIMS kelp beds](https://catalogue.data.gov.bc.ca/dataset/kelp-beds-coastal-resource-information-management-system-crims) | All Time only. Official legacy mapped kelp-bed polygons; no standardized observation-year field. The bounded current study-region query returned 10,707 valid polygons, with bull, giant, mixed and unspecified kelp classes and no eelgrass classification. The retained subset contained 1,961 of these geometries; 8,746 additional geometries broaden coverage around Vancouver Island. Open Government Licence – British Columbia. |
| [DNR floating-kelp persistence polygons](https://gis.dnr.wa.gov/site3/rest/services/Aquatics/AQ_Environment/MapServer/1) | All Time only where the published persistence category represents positive evidence. These generalized multi-year mapped polygons are not a precise annual observation or pure canopy boundary. Their binned proportion is not exposed as an exact ratio. All 105 retained records are included; 34 previously invalid polygons use the retained audited GEOS `make_valid` copy, with original/repaired geometry hashes and no source certification claim. |
| [DNR ShoreZone floating kelp](https://gis.dnr.wa.gov/site3/rest/services/Aquatics/AQ_Environment/MapServer/40) | Excluded from area calculation: 7,189 retained shoreline line records, including 725 positives, supply no measured bed width. No buffering invents polygon area. Raw observations and their provenance remain retained. |
| Statewide floating-kelp linear extent and current UAS/imagery work | The official DNR programme describes generalized 1 km shoreline-segment synthesis and recent imagery/UAS reports. Segment lengths and unclassified imagery are not compatible bed-area polygons. No unverified 2025 annual or new polygon product is inferred from those reports. |

The 2026-10-20 CRIMS pull was limited to the existing planning bounds
`[-129.7,45.9,-121.5,51.5]`, 20,000 records and 60 MB. Six pages returned
14,989,662 bytes. Actual reporting remains limited to the retained native study
cells; the query rectangle and source polygon bounds do not establish complete
Canadian or Washington survey coverage. Source pages, rights, URLs, hashes and
retrieval time are retained in the source-cache receipt. Unchanged raw sources
and the earlier geometry audit are reused.

The former R6 mosaic used unions of selected R8 children, which are not the same
geometry as native R6 cells. Two old derived R6 assignments therefore do not
carry forward as native-cell assignments: their eight underlying source records
have zero area in those full native cells and are retained in the correct
adjacent native R6 cells. The migration report records the exact keys and area
checks. All 692 positive prior R8 mosaic cells remain represented.

## Publication and compatibility

One family transaction publishes the internal static/dynamic tables, normalized
inventory and standard manifest together, removing stale generated family members
on rebuild. Final delivery uses `write_areas` with a scoped, recoverable retirement
of `annual-kelp-footprints` and `mapped-kelp-mosaic`. Only generated obsolete
products are retired; the migration retains a hash-verified rollback copy and
does not delete original source data. Unrelated area bytes and catalogue entries
must remain identical.

The historical `build_native_annual_footprints` function remains a compatibility
calculation API, not a second active producer or delivery dataset. Old retained
research scripts/releases are historical evidence, not the current build path.
Legacy benthic-composite Kelp fractions, persistence, network distances, richness
and survey coverage cannot be inferred from All Time extent. When that consumer
reads the new schema, unsupported Kelp derivatives and affected combined metrics
remain unavailable. The two new extent fields require downstream modeling review.

The regional acceptance checks compare all previous positive cell-year keys from
both prior products, require zero losses, verify All Time contains each annual
positive extent, validate exact Parquet readback, and retain native identity and
null semantics. The portable validation notebook remains the bathymetry API
exercise; this Kelp change is covered by focused offline and regional checks.
