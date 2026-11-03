# Nearshore intact-part correction closeout — 2026-10-29

The candidate-only runner now preserves intact original shoreline parts before buffering, caches up to 32 buffered parts and clips buffered polygons to tiles. Cutting or re-unioning the source lines before buffering is avoided. The full-context frame is released after component construction, when it is no longer used. Packaged defaults, physical thresholds and delivered data remain unchanged.

Worst-case preflight retained all 177,739 context geometries and exercised 13,724 cells intersecting the 12 most complex source parts (largest: 64,590 vertices), plus all 38 failing cells. It passed in 59.82 seconds at 1,342,898,176 bytes peak RSS (1.25 GiB). An initial repeated-buffer implementation passed regression but hit its 120-second preflight limit at 1.63 GiB; its evidence is retained. Caching complete-part buffers removed repeated work without clipping source geometry.

Full nearshore stage: return code 0; elapsed 214.60 seconds; peak sampled RSS 2,040,037,376 bytes (1.900 GiB); stop reason None. Guard samples every 0.25 seconds; sampled RSS is not a guarantee against shorter peaks. Limits remained 600 seconds, 2 GiB RSS, 2 GiB candidate staging and 20 GiB free space.

Comparison summary: 81,380 rows, 0 unsupported study keys, 15 compared fields; 2,424 rows, 3 unsupported study keys, 15 compared fields

Fields with unresolved discrepancies: {}.

Candidate root: `/Users/tylerstevenson/Documents/Code_Repos/MarineCast/Toolkits/toolkit-seascape/.seascape/work/full-study-reproduction-20261029/nearshore-transitions-intact-parts-validated`. Detailed comparisons and source/config identity are in its `manifest.json`; `candidate-optimization.json` pins generated runner/helper identities. The original clipped candidate is retained separately and must not be promoted. Three missing R6 cells are absent from retained physical support; do not fabricate values for them.

Regression tests: `repair-venv/bin/python -m pytest -q -p no:cacheprovider full-study/test_nearshore_intact.py` passed all three real-source tests: worst-cell historical parity, explicit reproduction of the rejected clipping error, and symmetric-difference equivalence to independently buffered complete parts. Memory preflight additionally checks all 38 historical area failures. Final installed-environment suite passed 690 tests, three expected materialized-data skips and two Pandas deprecation warnings. Installed import validation passed 211 modules with OrcaCast blocked. The installed wheel remains unchanged; this certifies the existing wheel plus explicitly recorded candidate-only helpers, not a new packaged release.

Reproduction entry point: `repair-venv/bin/python full-study/run_nearshore_intact.py`, after selecting a fresh separate candidate path; existing outputs refuse overwrite. All scripts and JSON evidence are in `/Users/tylerstevenson/Documents/Codex/2026-10-29/task-6/full-study`. No downloads, original-data replacements, app restart, commits or publication.
