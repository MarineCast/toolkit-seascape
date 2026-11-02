# Full-study Seascape final bounded production report — 2026-10-29

Latest packaged acceptance: [1 November installed producer closeout](installed-producer-closeout.md).
It records fresh terrain/substrate runs, metric-only exports and quantified precision results.
Earlier task-directory evidence may no longer be available; retained source/candidate paths
and the new evidence root are distinguished in that report.


Follow-up resolved: the [intact-part correction](nearshore-intact-closeout.md) now passes full-area nearshore comparison at both resolutions. All 15 fields and null masks match within unchanged tolerances for 81,380 R8 and 2,424 R6 cells. Three R6 cells lack retained support. The earlier clipped candidate is retained as rejected evidence. Terrain's 18 exceedances remain unresolved.

## Measured outcomes

**Coastal bounds is complete.** All 81,380 R8 rows and all nine comparable delivered fields match at the original tolerance, with identical null masks and no missing study keys. The approved 900-second ceiling was not hit. Cold full-graph rays took 452.6 seconds for 176,364 graph nodes, plus 0.2 seconds for 1,078 unrepresented target centers. The first producer attempt ran 464.50 seconds at 1,104,560,128 bytes peak sampled RSS and stopped only at a water-manifest relocation check after all calculations. The cache was retained.

Water-geometry manifest paths needed the same strict relocation treatment as water-network paths. Every original artifact hash was verified before rebinding. A symlink was insufficient because config resolution canonicalizes it. The final candidate uses a checksum-identical 2,109,395-byte local water-input copy, an adjacent manifest with absolute retained-source artifact/source bindings and a selected-input binding to that copy. Original provenance and hashes are preserved in a relocation receipt; checksum-mismatch rejection is tested. No verification was disabled. Successful cached finalization took 12.11 seconds, peak RSS 1,020,690,432 bytes. One intermediate symlink attempt also consumed 12.08 seconds; all its files remain preserved. Final output: `coastal-bounds-exact-ray-cache-bound-input/metrics-r8-study.parquet` under the candidate root.

**Waterbody completed.** All 81,380 R8 rows and all 18 comparable fields match exactly, including null masks, with no missing study keys. The cached run took 26.21 seconds and peaked at 1,172,504,576 bytes RSS (1.09 GiB). Output: `waterbody-morphometry-exact-ray-cache-bound-input/metrics-r8-study.parquet`. Existing zero-candidate sill lineage remains part of the retained producer/configuration; exact parity does not independently validate that scientific selection policy.

**Nearshore full attempt:** return code 0, elapsed 112.83 seconds, peak sampled RSS 2,051,031,040 bytes; stop reason None. Three real-source reference patches (44 cells, three positive components) had exact areas, geometry symmetric differences, shoreline filters and component records/IDs. NEARSHORE_TRANSITIONS_RES_8.parquet: 81380 rows; 0 missing study keys; 15 comparable fields; 4 fields with discrepancies. NEARSHORE_TRANSITIONS_RES_6.parquet: 2424 rows; 3 missing study keys; 15 comparable fields; 5 fields with discrepancies.

**Terrain differences are quantified, not waived.** Original acceptance remains atol=1e-6 plus rtol=1e-9, evaluated in each field's unit. Eighteen field/cell comparisons in 12 of 81,380 cells exceed it; null masks all match. Detailed records include actual values and each tolerance:

| Field | Exceedances | Max absolute difference | Max relative difference |
|---|---:|---:|---:|
| ASPECT | 2 | 1.6608446e-5 degrees | 5.5241e-8 |
| ASPECT_CIRCULAR_MEAN_RING_1 | 5 | 2.2598580e-5 degrees | 1.5451e-7 |
| ASPECT_CIRCULAR_MEAN_RING_2 | 5 | 2.3796696e-6 degrees | 1.5108e-8 |
| NEIGHBORHOOD_ROUGHNESS_RING_2_M | 5 | 1.0976581e-5 m | 4.4024e-5 |
| NEIGHBORHOOD_ROUGHNESS_RING_4_M | 1 | 5.5735317e-6 m | 9.4166e-6 |

The worst aspect cell has slope 1.1180e-6 degrees: its direction is sensitive because the fitted gradient is almost flat. Every affected roughness fit has only four points, with column-scaled condition numbers 4.33e5–9.57e7, indicating nearly collinear support and substantial amplification of floating-point changes. Broader current-code reference recomputation exactly matches all candidate fields at the 12 affected cells, excluding chunk pruning as the cause. The original manifest does not capture the numerical-library/geometry runtime, so its exact historical floating-point difference cannot be reconstructed. Conditioning identifies the mechanism of sensitivity, not a proved single library-version culprit. No tolerance relaxation or automatic scientific QC/null-policy change was applied. A condition-aware numerical QC decision remains separate from historical production parity.

## All 17 delivered families

| Family | Current full-study result | Remaining scope / blocker |
|---|---|---|
| Bivalve | R6/R8 produced; shared native fields/nulls match | Newly included study keys explicit; retained normalized source start |
| Seagrass | R6/R8 produced; native fields/nulls match | Provider acquisition/classification not rerun |
| Kelp | Static both grids match; 35 annual years / 2,933,245 shared rows match | Experimental annual scientific review; outside-study historical rows excluded |
| Coast Complexity | R8 complete and R6 2,424; compared fields/nulls match | Three requested R6 keys absent from retained support |
| Freshwater | R8 complete; five fields/nulls match within tolerance | Mouth-inventory downstream workflow only |
| Mapped Substrate Classes | Explicit historical-operation R6/R8 candidates exactly match | Current defaults unchanged; future-release coordinate policy separate |
| Coastal Bounds | R8 complete; all nine comparable fields/nulls match | No remaining full-study comparison blocker for delivered fields |
| Terrain | R8 complete; 53/58 comparable fields pass; all nulls match | 18 exceedances in five fields / 12 cells; conditioning/numerical QC documented above |
| Bathymetry | R8 complete for 24 verified fields | R6 and isobath-distance fields pending |
| Waterbody Morphometry | R8 81,380 produced; all 18 compared fields/nulls exactly match | Retained sill-selection lineage reproduced; scientific policy unchanged |
| Nearshore Transitions | Corrected full R8 and 2,424 R6 produced; all 15 fields/nulls pass | Three unsupported R6 keys; intact-part candidate remains separate from delivery |
| Spatial Support | Prior bounded partial replay | Full geometry/graph producer coverage pending |
| Fluvial Connectivity | Prior bounded downstream replay | Full network-distance candidate pending; raw HydroRIVERS binding unresolved |
| Shoreline | Prior bounded WA/BC real-source replay | Complete classified BC inventory absent; source-scoped candidate pending |
| Anthropogenic | Prior bounded positive real examples | Complete inventory, original mask and positive reef unresolved |
| Substrate (modeled R6) | Prior bounded real raster production | Full current-support candidate pending; point-support vintage differences explicit |
| Estuary | Prior bounded qualified US point replay | Complete qualified cross-border inventory unavailable |

## Reproducibility and validation

All candidate outputs remain under `.seascape/work/full-study-reproduction-20261029`; no delivered file or catalog was promoted/replaced. The 17-family table reports remaining stages honestly: this is not complete upstream regeneration for all Seascape products. Unknown source coverage is not observed zero. The three missing R6 physical-support cells require a separately validated support regeneration; the historical normalized inventories and retained water graph are still prerequisites.

Execution scripts and detailed JSON evidence are in `/Users/tylerstevenson/Documents/Codex/2026-10-29/task-6/full-study`. `harness-sha256.json` records their identities. Installed wheel is `repair-dist/toolkit_seascape-0.1.1-py3-none-any.whl`, SHA256 `a28da1082dfed8c9cc0f3d1f649b108aa3df1776e9db09e9e2cc241c0dd7f201`. Candidates use that installed package. Candidate-only optimized wrappers inject verified geometry/cache operations; these are not packaged defaults and are not a portable one-command release workflow. Fresh output paths are mandatory; successful candidate directories refuse overwrite.

Commands, from this task directory, with an authorized fresh candidate path configured in each supervisor:

```bash
repair-venv/bin/python full-study/run_waterbody_final.py
repair-venv/bin/python full-study/run_nearshore_tiled.py
```

The supervisors enforce 600-second wall time, 2 GiB sampled RSS, 2 GiB candidate staging and 20 GiB free-space reserve. Coastal cold-ray production had a separately approved 900-second ceiling. Exact cached identities include ordered cells, coordinates, water WKB, range and implementation; identity checks were not bypassed. Original relocation manifests, hashes and receipts remain beside candidate inputs. Historical mapped-substrate operation is an explicit option, not a default CRS change.

Fresh final validation: 690 pytest tests passed, three expected materialized-data skips, two Pandas deprecation warnings; Ruff lint and formatting passed (330 files); mypy passed (21 modules); docs check passed (72 documents, 333 local links); strict MkDocs build passed; git diff --check passed. The installed-package check imported 211 modules with OrcaCast blocked. Full pytest uses the installed repair-wheel environment; newer concurrent source edits are not thereby certified as shipped wheel contents. Initial quality-check attempts could not write repository caches; reruns with no-cache / writable temporary cache passed. External documentation URLs and source acquisition were not retested.

The isolated installed-wheel notebook passed: 15 production checks, 22 notebook checks, two embedded figures, no external network or acquisition attempts. The first sandbox attempt could not allocate a local loopback port; the owned helper was stopped and an authorized scoped rerun passed. Evidence: `final-notebook-retry.log`.

No new acquisitions, denied-endpoint retries, commits, pushes or Data Explorer restart. Remaining manual inputs: qualified full BC/cross-border estuary inventory; complete classified BC shoreline; complete anthropogenic physical inventories and a positive reef example; historical anthropogenic water mask for exact old fraction parity. Existing source subsets do support bounded new-source calculations, but cannot certify full geographic coverage. Original terrain numerical runtime is absent; strict numerical parity remains unresolved as quantified above. Annual kelp scientific review remains separate from computational reproduction.

## Earlier nearshore discrepancies — resolved by intact-part correction

At R8, eligible and valid bathymetry area each exceed tolerance in 38 cells (max 212.0174 m²); deep-water area in 8 cells (max 211.9119 m²); deep-water fraction in 7 cells (max 8.02237e-5). At R6, eligible and valid area each differ in 25 cells (max 239.9851 m²); deep area in 7 cells (max 211.9119 m²), deep fraction in 6 cells (max 7.88464e-6), bathymetry coverage fraction in one cell (max 1.70400e-6). All 15 compared fields have identical null masks at both resolutions. The 44-cell reference fixtures establish local parity, not whole-region equivalence. The follow-up isolated clipping-before-buffering as the cause. The corrected full candidate passes unchanged tolerances; delivery has not been replaced.
