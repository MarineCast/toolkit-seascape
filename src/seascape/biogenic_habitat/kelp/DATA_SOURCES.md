# Kelp source contract

- **Washington DNR annual floating-kelp inventories** (1989-2024, excluding
  unavailable survey years) are direct canopy observations. The roughly 85 MB
  archive is included by default and required for a production build. Annual
  polygons are positive canopy observations, not their survey footprints.
  The latest applicable positive or explicit negative evidence is selected by
  location and as-of year; an archive-wide latest year does not erase older
  observations where no later survey evidence applies. `KELP_FRAC` is mapped
  last-known presence, not a contemporaneous complete canopy census. A
  generalized-only build requires an explicit override
  and records the incomplete source state in its manifest.
- **Washington DNR persistence polygons and ShoreZone** provide generalized
  spatial coverage and mapped presence/absence. The five-category proportion
  layer is retained as the midpoint of its published 0.2-wide class
  (`0.1, 0.3, 0.5, 0.7, 0.9`) and labeled
  `mapped_binned_proportion_midpoint`; it is not presented as an exact surveyed
  annual ratio.
- **B.C. CRIMS kelp beds** are legacy compiled polygons. They contribute mapped
  area and proximity with confidence 2, but missing coast is not treated as an
  observed absence.

Floating canopy is not all kelp habitat. This product never relabels modeled
potential kelp habitat as observed kelp. DNR processing was vector/CAD in
1989–1992; 1993 was not surveyed. Raster processing used approximately 20 m cells
in 1994–2009 and approximately 4 m cells in 2010–2024. These processing labels
are not physical accuracy claims. Annual raw polygon area is not assumed
perfectly comparable across these methodological breaks. The current source
normalizers do not register separate complete survey-footprint geometries or
availability dates; survey completeness therefore remains unknown and a
historical as-of export is retrospective rather than an operational replay.
