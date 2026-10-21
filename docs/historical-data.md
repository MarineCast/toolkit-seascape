# Historical Seascape data

The current [Seagrass dataset](seagrass.md) exposes only Seagrass Extent (All Time), the geometric union of all eligible source history with original survey dates retained as provenance. The native composite APIs documented below remain compatibility calculations; source intervals never become annual observations.

## Native annual positive footprints

The current delivered [Kelp dataset](kelp.md) uses all available history by
default and exposes Annual Kelp Extent plus Kelp Extent (All Time). The
native helper in this section describes the retained compatibility API; separate
`annual-kelp-footprints` and `mapped-kelp-mosaic` deliveries are superseded.

`seascape.biogenic_habitat.kelp.native.build_native_annual_footprints` consumes explicitly
source-identified annual positive polygon records, full native H3 geometry and the corresponding
static water clips. Inputs must retain source rights and observation years; raw inventories are
unchanged. Areas are geometric unions in EPSG:6933, independently intersected at each native
resolution. Full-H3 mapped extent and mapped extent inside the static water mask are distinct
quantities in m². They do not reconstruct historical water levels or current canopy.

The output grain is H3/resolution/survey year, with January 1 used only as a year label. Years
without source records are omitted and reported as missing. Cells without positive mapped
geometry retain null amounts and explicit `no_positive_mapped_evidence` status; neither survey
opportunity nor absence is inferred. Availability time remains unknown unless supplied by the
source context. Resource limits bound cells, records, cell-years and annual overlap pairs.
Synthetic overlap-union, missingness and distinct-native-resolution checks accompany this API;
regional source/topology review and serialized readback remain additional checks.

Historical extraction retains the requested modeling window separately from actual source
coverage. `seascape history` reads an explicit study JSON and existing flat area tables, preserves
their native H3 identities, metrics, units and scientific qualifications, and writes a separate
flat output directory. It never changes the input data or activates model predictors.

```sh
seascape history --study-config /path/to/study.json --input-dir /path/to/Data/Seascape --output-dir /path/to/history/Data/Seascape --report /path/to/history/coverage.json
```

The study's `time.start`, `time.end_exclusive` and UTC timezone define the request. JSON duplicate
keys, invalid dates, non-UTC requests and empty intervals fail. Production coastal-mask approval
is not inferred from this request: extraction preserves the source tables' existing support and
unresolved qualifications. This is a retrospective data extraction, not an independently validated
regional rebuild or an operational reconstruction of what was known on each historical date.

Annual records keep January 1 as the survey-year index. Selection uses overlap with the native
annual interval, so a partial-year request does not relabel an annual observation as daily data.
Explicit composite start/end interval columns similarly retain their full source period. Dynamic
tables with undocumented temporal precision are rejected. Missing years are reported, never
expanded into zero rows or forward filled. Static layers remain reference snapshots; no annual
observations or historical availability dates are manufactured. Unknown availability prevents a
claim of operational replay; `--require-known-availability` rejects such an extraction.

The report records source hashes, requested and actual time support, missing source years,
preserved spatial limitations, and static-reference versus dated roles. Output metadata embeds
the same request and per-area coverage. A successful extraction with gaps does not mean every
Seascape family, location or requested year is available.

## Sources for the current modeling period

Washington DNR's [annual kelp archive](https://dnr.wa.gov/aquatics/aquatic-science/nearshore-habitat-program/kelp-monitoring)
contains canopy observations through 2024. Its index polygons are not automatically complete
cell-year survey footprints. The processing change around 2010 and source-specific geometry
qualifications remain attached. The archive's advertised coverage does not establish 2025–2026
observations or complete spatial coverage of British Columbia and Washington.

The [global Sentinel-2 seagrass source](https://zenodo.org/records/18612240) supplies 2019–2020 and
2023–2024 modeled composites under CC BY 4.0. They are separate multi-year source periods,
not annual surveys, species-specific eelgrass, surveyed absence, or daily observations. Native
positive pixel-centre counts and full-H3 positive-footprint area remain different quantities.
Native footprint calculations retain EPSG:4326 source pixels, EPSG:6933 area, H3 vertex polygons
densified at 0.001 degree, explicit tile-rectangle support and zero/background/nodata limits.
No water-clipped, physical coverage or common-denominator hardness claim is added.

`seascape.biogenic_habitat.seagrass.native.combine_native_composites` converts explicit native
composite tables to dynamic interval records. It requires matching native support across periods,
preserves each source context, and rejects duplicate cell/period keys. It derives interval labels
only from the tables' explicit composite start/end years, without interpolation or daily expansion.

Downloads must retain source rights, URLs, retrieval times and hashes in source-cache manifests.
HTTP files are validated before replacing existing bytes; bounded sources can set `maximum_bytes`.
Archives remain compressed unless extraction is explicitly configured. No regional or historical
pull is evidence that provider coverage, source dates or scientific definitions are complete.
The packaged source configuration enables both retained seagrass composites for the canonical All Time union.
Acquisition remains an explicit step. The canonical habitat producer uses both composites only in All Time; verified WA inventory polygons also contribute to All Time, retaining their original survey years as provenance.

## Geometry and registry qualification

`seascape.utils.geometry_quality.audit_polygon_inventory` inspects keyed polygon evidence with
an explicit `reject`, `quarantine`, or `make_valid` policy. The default rejects invalid geometry.
An explicit repair retains record identity and original/result geometry hashes, records GEOS's
validity reason and discarded lower-dimensional components, and keeps a distinct repair state.
Make-valid is a computational topology repair, not a correction certified by the source provider.
Unusable results remain quarantined; raw source objects are never modified. Spatial coverage and
observed absence are not inferred from a repaired or omitted geometry.

Habitat and reef builds use this audit before spatial processing. Set the family's
`processing.invalid_geometry_policy` to `make_valid` or `quarantine` only for an explicit
processing decision; omitting it selects `reject`. Valid non-areal habitat observations retain
their non-areal support. Publication manifests retain the record-level audit and qualify
repaired or quarantined inventories as partial.

The optional outlet, passage, gateway, coast-complexity and mapped-habitat producers still require
their documented source-backed registries. Place-name IDs and reference points cannot substitute
for canonical mouth IDs, passage polygons/centrelines, reviewed graph attachments, complete island
components or tidal-frame survey support. Physical bottom hardness remains unavailable without a
justified common source denominator. Historical extraction does not waive these requirements.

The [major-location proposal](../config/registries/proposed-major-locations.json) records 30 river
outlets and 23 waterway locations across the planning area. Forty-five official name identities
are resolved; eight US waterway entries retain a named primary reference with an ID still pending.
All computational geometry, canonical outlet IDs and graph attachments are deliberately unset.
The proposal is not selected by any default build configuration.

## Validation

Run `python -m pytest -q tests/test_historical.py tests/test_geometry_quality.py
tests/test_native_seagrass.py tests/domains/environment/seascape/test_acquisition_identity.py`,
then the full suite and documented documentation, notebook and quality checks. Regional runs must
also check native row identity, temporal precision, source gaps and serialized output readback.

The source-closure study profile uses an explicit catalog under
`Data/Seascape`; the current canonical catalog also retains older-only areas with their original
provenance. Study definitions and registry files remain separate under `config/` and `Data/Study/`.
The historical exporter preserves a common reporting-mask identity only when all resolution
variants declare the same identity. Conflicting mask identities fail. Requested 2009–2026 support
does not backdate static maps or expand native annual/composite evidence into daily observations.
See [source closure](source-closure.md) for the current study results and remaining qualifications.
