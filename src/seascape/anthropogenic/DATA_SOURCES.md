# Anthropogenic seascape sources

This pipeline is coverage-first and cross-border. OpenStreetMap/OpenSeaMap is the
common BC-Washington backbone; government inventories replace or supplement it
where systematic geometry is public. The source inventory retains every record,
while `IS_CANONICAL` and `DUPLICATE_OF_RECORD_ID` prevent overlapping volunteered
records from being counted twice.

## Configured sources

- OpenStreetMap/OpenSeaMap: seawalls, breakwaters, groynes/jetties, causeways,
  piers, ferry terminals, marinas, ports, dredged areas, dumping grounds,
  aquaculture, and artificial reefs. ODbL 1.0; attribution required.
- Washington DNR ShoreZone shoreline modification: systematic armoring
  percentages and pier/dock counts.
- British Columbia ShoreZone shore-unit classifications: systematic shoreline
  denominator and mapped man-made form codes.
- NOAA Coastal Maintained Channels: authoritative Washington maintained-channel
  polygons derived from NOAA ENC and USACE sources.
- Washington Ecology Coastal Atlas: ocean-disposal sites and commercial
  shellfish polygons.
- Environment and Climate Change Canada: active disposal-at-sea sites.
- Fisheries and Oceans Canada: current BC shellfish and marine-finfish licence
  coordinates.

## Interpretation constraints

- Distances are to the nearest **mapped** feature on the canonical marine graph;
  they do not assert inventory completeness.
- Armoring fraction uses only systematic ShoreZone shoreline denominators. OSM
  shoreline features may seed distance but never contribute to the denominator.
- Piers, docks, floats, dolphins, and wharves share the `pier` family because the
  source ontologies do not distinguish them consistently across the border.
- Artificial-reef and aquaculture non-detections are null unless explicit source
  coverage supports absence. Always use the confidence table alongside features.
- The products are ecological/modeling covariates and are not suitable for marine
  navigation or regulatory determinations.
