# Kelp source contract

- **Washington DNR annual floating-kelp inventories** (1989-2024, excluding
  unavailable survey years) are direct canopy observations. The roughly 85 MB
  archive is included by default and required for a production build. Only the
  latest annual layer contributes to `KELP_FRAC`, while dated layers contribute
  observation history. A generalized-only build requires an explicit override
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
potential kelp habitat as observed kelp. The DNR processing resolution changed
from approximately 20 m to approximately 4 m in 2010, so annual raw polygon area
is not assumed perfectly comparable across that break.
