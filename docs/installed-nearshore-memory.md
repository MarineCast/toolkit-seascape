# Installed nearshore memory fix — 2026-10-30

Latest packaged acceptance: [1 November installed producer closeout](installed-producer-closeout.md).
It records fresh terrain/substrate runs, metric-only exports and quantified precision results.
Earlier task-directory evidence may no longer be available; retained source/candidate paths
and the new evidence root are distinguished in that report.


Cause isolated: `COASTAL_REPORTING_MASK` is buffered by 7,000 m solely to test station membership. This regional MultiPolygon buffer pushed setup above 2 GiB; input reads completed below 700 MiB.

Package source now uses an STRtree over intact polygon parts, caches at most eight complete-part buffers, and tests station coverage without constructing the regional buffer union. The source geometries and distances are unchanged. A 3,375-point fixture compares station decisions with the original dissolved buffer. Twelve geometry regressions pass; all 17 earlier affected tests passed before the added membership test. Lint, formatting and diff checks pass.

Setup diagnostic reached its intentional pre-computation endpoint in 17.35 s at 943,570,944 bytes peak RSS, with no memory guard trigger. The diagnostic's exit code 1 is its intentional `DIAGNOSTIC_COMPLETE_BEFORE_COMPUTE` exception, not a production failure.

Full installed candidate is running under the original 2 GiB/600 s guard in `nearshore-transitions-installed-interest-bounded`, separate from delivery. Supervisor: `integration/run_installed_interest.py`; status will be `nearshore-installed-interest-status.json` under the full-study candidate root. No success claimed before comparison finishes.

Remaining scope is unchanged: terrain centering and precision regressions, portable identity-bound bindings, historical CRS selection, bounded terrain/substrate production, supported reporting of three missing R6 cells, command-level replay and final docs/maps. No original delivery replaced.

## Full installed attempt outcome

The regional attempt did not complete: its supervisor stopped it after 168.54 seconds at 2,177,548,288 bytes RSS (2.028 GiB), 30,064,640 bytes above the unchanged guard. The initial setup allocation is resolved, but a later allocation remains. No finished candidate or full-area parity is claimed. Later-stage allocation profiling is required before another run; the limit was not increased. Status: `nearshore-installed-interest-status.json` under the existing full-study candidate root.

Fresh validation: 702 source tests passed with three expected skips; 12 geometry tests pass, including station-buffer membership; lint/format and all 21 type-check modules pass; installed imports and guarded validation notebook pass. Documentation check passes for 76 documents. Existing delivery remains unchanged. Terrain corrections, bindings, historical CRS configuration, bounded terrain/substrate paths and final command-level acceptance remain outstanding.

## Resolved installed full-study acceptance — 2026-10-30

The later spike occurred during station buffering, after area geometry work. The package now releases no-longer-used detailed supports, checks exact polygon coverage/distance before allocating buffered parts, and caps GDAL block caching at 64 MiB. The cache cap changes resource use, not raster values or resampling. Intact source geometry and scientific thresholds remain unchanged.

The installed producer completed in **242.21 s**, peak sampled RSS **2,133,819,392 bytes (1.987 GiB)**, below the unchanged 2 GiB ceiling. Headroom is small; keep the guard on future runs. All 15 comparable fields and null masks pass at 81,380 R8 and 2,424 R6 cells. Three R6 cells still lack retained support. The 65,991 station rows, 65,991 transect rows and 823 deep components match retained products, including keys and all compared columns. Detailed evidence: task `integration/cache-comparisons.json`; candidate directory `nearshore-transitions-installed-bounded-cache`; resource receipt `nearshore-cache-status.json` under the full-study root. No review-script scientific replacement was used; observational wrappers only logged stage RSS.

Mean-depth centering is also integrated in terrain source, preserving the same least-squares plane and aspect cutoff. Independent Decimal regressions pass; on the two affected real cells the source aspect errors against the 60-digit reference are 5.07e-11 and 3.58e-11 degrees. This terrain change is not yet in the wheel used for the nearshore acceptance, and full terrain historical parity remains unverified. Do not mark its 18 previous exceedances resolved merely from the two direct-aspect checks.

Current source validation: **705 tests passed, three expected skips**, lint/format and all 21 type modules pass. The nearshore acceptance concerns native internal products, not the final public export schema.

### New final-export contract

Final static exports must contain only `h3_index` and scientific metrics; dynamic exports only `date`, `h3_index` and scientific metrics. Preserve missing metric nulls. Coverage, audit, status and provenance columns are excluded from final delivery. Optional diagnostics and source-identity validation remain separate. New metric production must not require historical coverage/audit output files. Necessary source geometry/support inputs must be identified separately from those avoidable historical outputs.

That export/dependency change is authorized but not yet implemented in the existing compact-delivery path, which still requires legacy external audits in some cases. Remaining work also includes portable hash-bound bindings, explicit historical CRS selection, bounded terrain/substrate paths, supported reporting of the three missing R6 cells, a wheel including terrain centering, final command-level replay and documentation/maps. Existing delivery is untouched.
