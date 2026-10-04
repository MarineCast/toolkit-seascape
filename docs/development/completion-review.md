# Codebase completion review — October 4, 2026

**The three reproduced defects below are now corrected.** Local software
regressions pass. Regional scientific acceptance, clean consumer acceptance and
hosted release verification remain separate gates; this is not a declaration that
all capabilities or regional products are complete.

Reviewed baseline: `fae2bab` (version 0.1.1), initially clean, on
`docs/seascape-banner-3x1`. Remediation is in the subsequent local working tree.
Source and tests were authoritative; graph locations were verified against source.
No products were promoted and no remote release was published.

## Corrections delivered

- Audit schema 3 records checksums for candidate products, manifests, catalog and
  governed metadata. Promotion requires literal boolean PASS and the same input
  inventory, rechecks under the writer lock, and verifies staged bytes. Old unbound
  audit reports must be regenerated. Existing retained release readers are unchanged.
- Threshold-width runs now split at shallow samples and missing intervals. The
  two 50 m deep intervals in the numerical example remain separate.
- Complete banks require wet-interval endpoints on the water boundary, away from
  the sampled section endpoints. Passage clipping alone leaves the section censored
  and its complete area null. The partial integral remains available.
- Passage outputs now identify method `passage_cross_section_shoal_candidate_v2`.
  Historical products are not silently relabeled; rebuild them to use the correction.
- The [San Juan atlas](../examples/san-juan-bathymetry.md) presents a fixed,
  source-backed R8/R6 bathymetry snapshot with PNG/PDF downloads and identities.
  It uses retained September 19 exploratory outputs, not a new regional release.

## Original findings — resolved

The descriptions and source line numbers below record the **pre-fix baseline**.
The correction and regression record above supersede their open status.

### Resolved P1 — Promotion does not bind its audit to the promoted bytes

Location: [`publish_candidate_release`](../../src/seascape/release.py), lines
590–648; audit creation is in `build_release_audit`, lines 434–462.

Promotion reads an audit JSON and tests only the truthiness of
`artifact_release_passed`. It then hashes the **current** candidate artifacts and
constructs a new release without rerunning the audit or comparing the candidate
to an audit-bound inventory. A candidate modified after auditing can therefore
be promoted as audited. Fresh release checksums prove which bytes were copied,
not that those bytes passed scientific validation.

Reproduction used the repository's minimal `_candidate_fixture` from
`tests/test_products.py`: leave its saved PASS report in place, replace the
bathymetry artifact with `b"changed-after-audit"`, call promotion, then call
`resolve_product`. Both calls succeed and the resolver returns those replacement
bytes. This is a publisher-boundary reproduction with synthetic bytes, not an
execution of a complete regional audit. The existing two-publication test also
changes artifact bytes while retaining that fixture's saved audit.

Required closure: bind the audit to all audited artifacts, family manifests and
governed configuration/catalog identities, require an actual boolean PASS, and
validate that binding under the publication transaction's concurrency contract.
Reject mutations without changing canonical or retained generations. Add
regressions for changed data, changed metadata, malformed PASS and unchanged
idempotent promotion. The ordinary orchestrator's upstream checks do not make the
direct publication boundary safe on their own.

### Resolved P2 — Deep intervals separated by a shallow gap are counted as contiguous

Location: [`measure_passage_section`](../../src/seascape/coastal_configuration/passage_sections.py),
lines 124–130.

The loop adds every positive threshold-width contribution to the current run.
Two adjacent sample intervals can each contain some deep water while their shared
sample is shallower than the threshold. That shallow gap should split the run,
but currently does not. This overstates
`MAX_CONTIGUOUS_WIDTH_AT_DEPTH_THRESHOLD_M` while total threshold width can remain
correct.

Reproduction: a 200 m wide wet section, samples at x = −100, 0, 100 m, depths
50, 0, 50 m, and threshold 25 m. Linear interpolation gives two separate 50 m
deep intervals. The function returns total width **100 m** (correct) and longest
contiguous width **100 m** (expected **50 m**).

Required closure: track threshold interval endpoints and continuity through each
sample, resetting across a below-threshold gap. Test alternating high/low depths,
threshold equality, nodata and islands. Preserve total width and area semantics.

### Resolved P2 — Passage-polygon clipping can masquerade as observed banks

Location: [`measure_passage_section`](../../src/seascape/coastal_configuration/passage_sections.py),
lines 88–99 and 131–145.

`bank_status` checks whether the full section endpoints fall outside the passage
polygon. It does not establish that both wet-interval ends are actual water/land
boundaries. A passage polygon can clip a much larger continuous water body and
still produce `BANK_STATUS=complete` and a nonnull complete cross-sectional area.
That conflicts with the documented requirement that both banks be observed.

Reproduction: passage rectangle x = [−100, 100], y = [0, 500]; centerline
(0, 0) → (0, 500); section centered at y = 250 with half-length 150 m; water
rectangle [−1000, 1000] on both axes; constant 50 m depth. Both section endpoints
remain in open water. The function nevertheless returns `complete` and
**10,000 m²** complete area. It should retain a censoring status and a null
complete area; the valid partial integral can remain separately available.

Required closure: distinguish source/passage extent boundaries from observed
shoreline banks, and test independently clipped passage and water polygons.

### Reproduce the two numerical cases

Run from an installed Python 3.14 environment. The comments show the corrected
results; automated acceptance assertions are in `tests/test_completion_regressions.py`.

```python
from shapely.geometry import LineString, box
from seascape.coastal_configuration.passage_sections import measure_passage_section

passage = box(-100, 0, 100, 500)

def section(water, depth_at):
    return measure_passage_section(
        "fixture", passage, LineString([(0, 0), (0, 500)]), water, depth_at,
        along_axis_m=250, half_length_m=150, sample_step_m=100,
        depth_threshold_m=25, tangent_scale_m=50,
    )

split = section(passage, lambda x, y: abs(x) / 2)
print(split.width_at_depth_threshold_m)                 # 100; correct
print(split.max_contiguous_width_at_depth_threshold_m) # 50; separate deep intervals
clipped = section(box(-1000, -1000, 1000, 1000), lambda x, y: 50)
print(clipped.bank_status, clipped.cross_section_area_m2)
# bank_censored None; partial integral remains available
```

## Dead code candidates

An AST reference scan over `src`, `tests`, `scripts` and notebook helpers was
followed by repository text searches and selected Graphify checks. No internal
callers were found for the candidates below. This establishes removal candidates,
not proof that no external consumer imports them. Nothing was deleted.

| Candidate | Evidence and recommendation |
| --- | --- |
| [`water_network.validation.is_finite_or_null`](../../src/seascape/spatial_support/water_network/validation.py) | Definition only in repository search; Graphify shows no caller. First removal candidate. |
| [`h3_geometry.build.prepare_water_geometry`](../../src/seascape/spatial_support/h3_geometry/build.py) | Definition only; Graphify shows helper dependencies but no caller. Current clipping uses a different path. Remove after checking downstream imports. |
| [`utils.spatial.prepare_water_land_context`](../../src/seascape/utils/spatial.py) | Definition and utility README description only; no code caller. Remove with its documentation if no external contract is retained. |
| [`core.data.contracts.CollectionRequest`](../../src/seascape/core/data/contracts.py) | No internal construction or import found. Inherited generic acquisition request includes a `days=15` field. Candidate for trimming the extracted scaffolding after API review. |

Keep the compatibility alias `load_yaml_config` until its deprecation policy is
explicit. Likewise, do not infer that release readers, `read_seascape_geoparquet`,
`build_full_counting_universes`, exported geometry utilities, or `validate_table`
are dead just because internal call counts are zero: they can serve external
Python clients. CLI dispatch and exported names also make raw reference counts
insufficient evidence for automatic deletion.

## What “complete” should mean

For a bounded **software-complete public preview**, the three findings are closed
with regression evidence. Finish clean runtime-only consumer and notebook acceptance,
the unfamiliar-user exercise, history secret scanning and hosted CI on the final
revision. Review external usage before removing public dead-code candidates.
The v0.1.0 preparation checklist is now explicitly historical; current version 0.1.1
gates need their own evidence.

For **regional scientific acceptance**, the
[capability coverage register](../capability-coverage.md) still identifies
unmaterialized method changes, reviewed-registry gaps and unavailable providers.
Rebuild and audit a bounded source-backed candidate using the corrected methods,
check rights, datum, temporal/coverage support and missingness, and independently
review results. Generic producer fixtures do not close those source gates.
Scope out explicitly blocked capabilities rather than declaring their data ready.

OrcaCast integration and hosted release state were not inspected in this review.
The toolkit's documented consumer implementation is not fresh evidence that an
application output or regional release has been validated.

## Remediation validation — October 4, 2026

Executed on macOS ARM64 with CPython 3.14.6. Disposable review and wheel venvs
inherited scientific dependencies; they are **not** clean runtime-only consumer
installations. The wheel import probe ran outside the checkout and imported the
installed wheel with OrcaCast blocked.

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 491 passed, 3 skipped; all skips require absent regional artifacts |
| New completion regression module | 22 passed, including stale audit, malformed PASS, lock/staging mutations and passage geometry/threshold cases |
| `ruff check src tests scripts` | Passed |
| `ruff format --check src tests scripts` | Passed; 266 files |
| `python -m mypy` | Passed; configured 12 modules |
| `python -m build --no-isolation` | Built sdist, then wheel from sdist, version 0.1.1 |
| `scripts/check_distribution.py` | Passed; nine required files, five resources, Python 3.14 metadata |
| Outside-checkout `scripts/check_installed_package.py` | 177 installed modules imported with OrcaCast blocked |
| Runtime/test/quality dependency snapshot and `pip-audit --disable-pip --no-deps --strict` | No known vulnerabilities in the updated disposable closure; see environment note below |
| `python scripts/check_docs.py` | Passed; 61 documents, 254 local links, 32 workflow stages; external URLs not exhaustively checked |
| `python -m mkdocs build --strict` | Passed |
| San Juan renderer | Verified retained product, upstream and geometry identities; exported PNG, PDF and identity JSON |
| Local MkDocs browser inspection | Atlas checked at desktop and 390 px mobile widths; full-resolution links available |
| `git diff --check` | Passed |

The initial dependency audit found five advisory entries across inherited
`pip==26.1.2` and `urllib3==2.7.0`. Updating only the disposable review environment
to pip 26.2.1 and urllib3 2.8.0 cleared that audit. Package dependency ranges and the
user's original environment were not changed; older installed environments still
need updates and their own audit. The full suite was rerun after this
validation-environment update: 491 passed and 3 skipped in 40.40 seconds.

The earlier synthetic [worked example](../examples/read-bathymetry.md) also passed
its exact shell blocks in a fresh workspace: 15 demo checks, 153 rows, 33 columns,
135 available depths and 18 null depths. The atlas is a separate real-data snapshot;
neither example establishes current regional scientific acceptance.

Not rerun: live acquisition, full regional build/release, independent scientific
validation, downstream integration, clean consumer/notebook acceptance, history
secret scan or hosted CI. Local passing tests do not remove those boundaries.
