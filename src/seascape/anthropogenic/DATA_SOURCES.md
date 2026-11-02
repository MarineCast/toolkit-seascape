# Anthropogenic seascape sources

This pipeline is coverage-first and cross-border. OpenStreetMap/OpenSeaMap is the
common BC-Washington backbone; government inventories replace or supplement it
where systematic geometry is public. The source inventory retains every record,
while `IS_CANONICAL` and `DUPLICATE_OF_RECORD_ID` prevent overlapping volunteered
records from being counted twice.

## Configured sources

The default OSM acquisition uses regional Geofabrik PBF extracts for BC,
Washington and Oregon, filtered by native `osmium-tool` with referenced objects
retained. Checksums, source URLs and extraction settings remain in the raw
download receipt. Nodes retain their locations; ways and relations use their
complete object bounding-box centers, preserving point/center evidence rather
than claiming mapped area. Selection requires the object bounds to intersect the
configured source extent. Incomplete references fail acquisition. The configured
extract coverage is regional; other study extents require suitable extracts.
The optional Overpass route remains available and rejects timeout responses even
when they contain partial elements. See [source recovery](../../../docs/source-rebuild-recovery.md).

- OpenStreetMap/OpenSeaMap: seawalls, breakwaters, groynes/jetties, causeways,
  piers, ferry terminals, marinas, ports, dredged areas, dumping grounds,
  aquaculture, and artificial reefs. ODbL 1.0; attribution required.
- Washington DNR ShoreZone shoreline modification: systematic armoring
  percentages and pier/dock counts.
- British Columbia ShoreZone shore-unit classifications: systematic shoreline
  denominator and mapped man-made form codes.
- NOAA Coastal Maintained Channels: authoritative Washington maintained-channel
  polygons derived from NOAA ENC and USACE sources.
- Washington Ecology Coastal Atlas: ocean-disposal sites. Layer 314 shellfish
  harvest/water-quality classifications are retained as regulatory source
  evidence; Approved/Conditional/Restricted/Prohibited/Unclassified polygons
  are excluded from physical aquaculture area, presence, and deduplication
  authority. They are not cultivation installations or farm footprints.
- Environment and Climate Change Canada: active disposal-at-sea sites.
- Fisheries and Oceans Canada: current BC shellfish and marine-finfish licence
  coordinates.

## Interpretation constraints

Artificial reef enrichment additionally uses the eight BC sites in ARSBC's 2016
brochure, seven WDFW 2025 published fishing-reef locations, and ten explicitly
classified NOAA Puget Sound ESI 2006 reef points. The reconciled normalized
inventory preserves all 25 records and selects 18 site locations. WDFW coordinates
take precedence for shared sites; NOAA's WDFW 2005 lineage is not independent
confirmation. See [source qualifications, conflict handling and native support](../../../docs/artificial-reefs.md).

- Distances are to the nearest **mapped** feature on the canonical marine graph;
  they do not assert inventory completeness.
- Armoring fraction uses only systematic ShoreZone shoreline denominators. OSM
  shoreline features may seed distance but never contribute to the denominator.
  The 2026-11-01 combination rule takes the maximum available dataset estimate
  for each cell: 0% and 100% combine to 100%; missing contributes no estimate.
  Unique line locations are length-weighted within each dataset, with coincident
  estimates taking the maximum locally. R6 combines lengths within each dataset
  before selecting its maximum. All-missing armoring remains null.
- Piers, docks, floats, dolphins, and wharves share the `pier` family because the
  source ontologies do not distinguish them consistently across the border.
- Artificial-reef and aquaculture non-detections are null unless explicit source
  coverage supports absence. Native confidence/qualification remains internal;
  final metric-only outputs retain source context as embedded metadata.
- The products are ecological/modeling covariates and are not suitable for marine
  navigation or regulatory determinations.
