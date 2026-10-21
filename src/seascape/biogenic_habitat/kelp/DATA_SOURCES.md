# Kelp source contract

The current producer emits one Kelp dataset with **Annual Kelp Extent** and
**Kelp Extent (All Time)**, in full-native-H3 m². Read the
[current calculation, source eligibility, date and coverage contract](../../../../docs/kelp.md).
The older KELP_FRAC/proximity/persistence/confidence family and separate annual
footprint delivery are superseded; the legacy calculation helper remains readable.

- Washington DNR's dated mapped-bed observations supply annual and All Time
  extent, using all available survey years by default. Missing positive evidence
  is unknown, never surveyed absence. The current retained annual inventory spans
  1989–2024 excluding 1993; 2025–2026 observations are unavailable.
- B.C. CRIMS polygons and positive Washington persistence polygons supply
  source-qualified All Time geometry only. Unknown observation dates remain
  explicit and are excluded by default from an explicitly year-bounded request.
  CRIMS is a legacy compilation collected from 1979 onwards, not a standardized
  annual survey series. Generalized persistence polygons are not exact canopy.
- The retained audit repairs all 34 previously invalid persistence records with
  GEOS make_valid, preserving original/result hashes. This is computational
  repair, not provider certification, completeness, or surveyed absence.
- ShoreZone floating-kelp lines have no measured bed width and contribute no
  invented polygon area. They remain retained source evidence. Eelgrass,
  generic seagrass, modeled potential habitat and no-record zeros are excluded.

Unions prevent double counting across sources and years. Current water masks do
not erase historical positive bed evidence; neither current presence nor a
historical water-level surface is reconstructed. Processing-era changes in 1994
and 2010 limit comparisons of raw annual mapped areas. Source rights, retrieval
vintage, exact date qualifications and the scoped 2026-10-20 CRIMS acquisition
are documented in the canonical contract and embedded provenance.
