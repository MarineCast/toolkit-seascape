# Reef source contract

This package keeps three concepts separate:

1. **Rocky reef** — `ROCKY_REEF_FRAC` is the dbSEABED modeled exposed-rock
   fraction from the cross-border substrate pipeline.
   `POTENTIAL_ROCKY_REEF_SUITABILITY` remains a separately named model that
   combines substrate hardness, slope, relief, ruggedness, and depth.
2. **Biogenic reef** — public WDFW oyster-bed polygons and B.C. ShoreZone oyster
   and mussel observations provide a generalized bivalve-bed proxy. Pacific
   oyster mapping may include cultivated or non-native beds, so this product is
   not structural-reef confirmation.
3. **Deep coral and sponge** — the relevant B.C. sponge-reef catalogue record is
   access-only. The current pipeline exports null values, confidence 0, and an
   explicit no-public-export status rather than pretending the habitat is
   absent.

The canonical user-facing Bivalve Extent (All-Time) now has a separate mapped-bed producer in `seascape.biogenic_habitat.bivalve`. This older reef proxy is retained for compatibility and must not be substituted for mapped-bed area. See `docs/bivalve.md` for admission/exclusion criteria.
