# Fluvial-marine structural barriers

This package combines authoritative B.C. and Washington inventories for dams,
culverts, waterfalls and other natural barriers, tide gates, and assessed fish
passage. `download.py` preserves the source snapshots and checksums;
`build.py` retains source rows, canonicalizes overlaps, attaches features to the
existing fluvial topology, and maps affected river mouths onto the canonical
marine H3 graph; `inspect.py` writes R8 or R6 interactive maps.

## Sources

- B.C. PSCIS assessments: assessed stream crossings and explicit barrier status.
  The catalogue labels these records **Access Only**; keep the raw snapshot local
  unless its redistribution terms are independently confirmed.
- B.C. Provincial Obstacles: mapped waterfalls, cascades, culverts, dams, and
  other fish obstacles under the Open Government Licence - B.C.
- B.C. public dam inventory and Flood Protection Works appurtenances. Only
  floodboxes and outlet points with an explicit gate type become tide gates;
  generic fence gates are excluded.
- Washington WDFW Fish Passage and Diversion Screening Inventory: statewide
  assessed sites, feature types, barrier status, and percent passable.
- Washington WDFW Coastal Tidal Restrictions 2025: only records explicitly
  stating a tide/flood gate is present become tide-gate records.
- USGS national waterfalls and rapids: CC0 physical features linked to NHD;
  clearly identified rapids are excluded from the waterfall class.

## Interpretation limits

These inventories are broad but not exhaustive. A missing source record is
therefore **unmapped**, not a confirmed absence and never a zero barrier count.
Passage classes are populated only from assessed PSCIS/WDFW fields; physical-only
inventories remain `NOT_ASSESSED`.

The current cross-border river attachment uses HydroRIVERS v10 because it is the
common topology already materialized by the fluvial-connectivity pipeline. Its
small-stream detail is coarser than B.C. FWA or U.S. NHDPlus HR, so attached
along-river distances are explicitly labeled as an operational fallback. The
marine leg is calculated on the canonical land-barrier-respecting H3 R8 graph.
