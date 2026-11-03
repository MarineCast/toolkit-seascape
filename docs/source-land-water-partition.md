# Adopt a source land/water partition

`seascape.spatial_support.water_geometry.partition` reads an explicit checksummed
handoff and named WGS84 polygon layers. Water is the study rectangle minus land;
tile pieces retain union semantics, holes and islands. No dissolve, simplification,
new acquisition or point-island footprints are introduced. Complete outer coverage
from the retained global baseline and gap-free nonoverlap evidence are required.
Absence of finer local sources is not interpreted as water beyond that coverage.

`water_area` is independent of `reporting_water`. The latter is the engineering
coastal selector, with exact 12-nm eligibility still subject to boundary review.
Generalized source support, unknown native land footprints and policy-edge flags
must accompany regional H3 tables. Mapped water fractions are source geometry
quantities; physical water fractions and fine channel/island certainty can remain
unknown. Observation dates are not invented from source publication dates.

The reader checks geometry bytes, layer CRS, nonempty valid polygon types and
handoff topology evidence. It does not independently certify the source producer's
whole partition or source accuracy. Native R8 companions use the existing
hole-preserving overlap-aware H3 census on simple source-piece bounding boxes,
then actual polygon positive-area intersections on separate reporting pieces.
This preserves thin slivers, excludes touch-only cells and retains union membership
across tiles; no area threshold or simplification is applied. R6 reporting membership
comes from the pinned handoff. No R5 water network is introduced.

An optional module CLI adopts the handoff or writes exclusive native membership:

```bash
python -m seascape.spatial_support.water_geometry.partition --handoff /explicit/partition-handoff.json
python -m seascape.spatial_support.water_geometry.partition --handoff /explicit/partition-handoff.json --native-r8-output /explicit/new-membership.r8.txt
```

These commands create no app and publish no final release. Scientific bathymetry
continues to use full-H3 native pixel centers; polygon support selects H3 membership
rather than redefining native depth samples. Selected depth statistics, quantiles
and bands can be delivered first. Graph-dependent local anomalies, contour/context
metrics, native geomorphometry and other source-dependent families remain explicitly
unfinished until their own inputs and methods are checked. A selected first release
must not be labelled the complete Seascape toolkit.

Validation: `python -m pytest -q tests/test_source_partition.py`, then the repository
full suite and quality/docs checks. No network call is required. The optional source
adoption CLI does not enter the deterministic required notebook path.
