# Bivalve mapped-bed extent

The canonical `seascape.biogenic_habitat.bivalve` producer emits only **Bivalve Extent (All-Time)** (`BIVALVE_EXTENT_ALL_TIME_M2`), a static square-metre union on each full native H3 grid. Its scientific identity remains Bivalve; the intended presentation family is **Biogenic Habitats** alongside the two Kelp products and Seagrass All Time. This presentation does not merge their measurements or temporal meanings.

## Source admission and limitations

The 2026-10-20 bounded acquisition retained all 1,183 [BC CRIMS clam-bed records](https://catalogue.data.gov.bc.ca/dataset/clam-beds-coastal-resource-information-management-system-crims), 50 previously audited WA WDFW oyster-bed records, and 39 current [WDFW PHS public polygons](https://geodataservices.wdfw.wa.gov/arcgis/rest/services/PHSOnTheWeb/PHSOnTheWebPublic/MapServer/3) explicitly classified as Oyster Beds, Presence, AS MAPPED, and original polygons. The configured older WA service was unavailable. The BC licence is Open Government Licence - British Columbia; WA attribution and public agency terms are retained in source context.

CRIMS is legacy generalized distribution mapping, assembled across study regions since 1979 and intermittently updated. Neither catalogue modification times, MAP_DATE, compilation dates nor source dates are observation years. Admitted records remain undated. Source species abbreviations remain verbatim, not guessed taxonomic identifications. This is mapped bed extent, not organism canopy, structural reef confirmation, present-day occupancy or exhaustive WA/Canadian coverage.

The full WA response and earlier inventories remain retained. The 632 current taxonomic presence polygons lack verified bed-boundary semantics and are excluded; ShoreZone observation-unit polygons also are not admitted as measured beds. These conservative exclusions can reduce earlier proxy coverage and must not be described as loss of habitat. DFO geoduck biological samples, dive observations and gridded fishing activity do not establish bed footprints. Growing/harvest/closure areas, aquaculture plans and leases, potential habitat, points, lines and sample area estimates are excluded. No buffers or zero/absence values are invented.

## Calculation and replay

Eligible polygons are audited separately with recorded GEOS make_valid repairs. Their geometric union is intersected independently with full native R6/R8 cells in EPSG:6933; H3 edges are densified at 0.001 degrees before projection. Overlapping records count once. Existing native delivery support is retained; evidence beyond that support does not imply absence. Unknown cells are null. Every positive cell retains source datasets, methods, verbatim species, date qualifications, repair flags and intersecting record counts.

`build_bivalve_extents` accepts an audited GeoDataFrame, explicit full native cells and source context containing rights. It enforces unique identities, valid geometry, native cell keys, and bounds on records/cells/intersection pairs. `build_bivalve_habitat` publishes only the bivalve area through the existing flat writer; no downloads occur implicitly. Stage into a dedicated candidate output and validate before promoting into delivery. Retire obsolete generated fields only with a scoped rollback; retain all original evidence.

```bash
python -m seascape.biogenic_habitat.bivalve.build --inventory INVENTORY.parquet --source-context SOURCE_CONTEXT.json --full-cells 6=CELLS_R6.parquet --full-cells 8=CELLS_R8.parquet --output CANDIDATE
python -m pytest -q tests/test_bivalve_extents.py tests/test_seagrass_extents.py tests/test_kelp_extents.py
```

The existing reef APIs remain compatibility calculations, not the canonical Bivalve extent producer. Their rocky-reef and coral/sponge products are separate and were not changed. See the scoped recovery report for current promotion/live-check status; a staged candidate is not a delivered release.
