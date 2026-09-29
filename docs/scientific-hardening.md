# Scientific hardening evidence register

This register tracks the implementation requested in the scientific-hardening task. It starts from
`53a4c07841944e5bfb40ff1b00cc32980131503b` on the independent
`feature/seascape-scientific-hardening` branch. The reviewed `fcd0a83` commit is historical context;
all findings are rechecked against current producers. This is an implementation record, not a
claim of independent scientific validation or a completed regional release.

## Baseline (before changes)

Interpreter: `/tmp/seascape-roadmap-dev/bin/python`, Python 3.14.6. All commands ran from this
checkout unless noted. `python -m pytest -q`: exit 0, 410 passed, 3 skipped, 101 warnings;
three skips require materialized regional artifacts. `python scripts/check_docs.py`: exit 0,
42 documents, 183 local links, 26 stages; external URLs were not checked.
`python -m pytest -q tests/test_documentation.py`: exit 0, 16 passed.
`ruff check src tests scripts`, `ruff format --check src tests scripts`, `python -m mypy`, and
`python -m pip check`: exit 0. The offline CLI demo ran in a fresh `/private/tmp` workspace,
exited 0 with `Synthetic software acceptance: PASS (not a regional release)` and emitted a
Parquet table, manifest, report and two PNGs inside its owned `.seascape/demo` tree.
An initial malformed shell invocation of the demo exited 1 before launching the CLI; the corrected
command above was executed successfully. No distribution or clean-consumer baseline run yet.

## Issue status

| Issue | Current producer / finding | Required contract and downstream effect | Status |
| --- | --- | --- | --- |
| SC-01 | `geomorphic_units/build.py`: `_rise` and `_fall` converted missing inputs to positive flat/narrow/near evidence; `_select_labels` used `argmax` on unsupported rows. | Missing required evidence keeps a class ineligible; all-ineligible rows have an explicit reason. Post-mapping support describes the final label. Changed labels/support require a new candidate and method identity. | Corrected in `geomorphic_evidence_v2`; five focused tests and the full suite (414 passed, 3 artifact-dependent skips) passed after this fix. This is software acceptance, not independent validation. |
| SC-02 | `bathymetry/build.py` directly assigns pixels at each resolution; `pipeline.py` overwrote direct R6 counts and bands with R8-child sums while retaining direct R6 moments. | Canonical statistic family must use one declared sampling support; retain hierarchy-only parents as unavailable. | Direct support correction in progress; controlled H3 boundary fixture passes. |
| SC-03 | `utils/habitat_surface.py`: inspect clipped edge and patch semantics. | Habitat interfaces must exclude artificial support cuts; patch identity and truncation must be declared. | Not yet resolved. |
| SC-04 | `utils/habitat_aggregation.py`: inspect parent topology and empty fragmentation. | Recompute union-scale topology; no-patch fragmentation is undefined with a reason. | Not yet resolved. |
| SC-05 | `benthic_substrate/classification/build.py` and dependent hardness/reef products: inspect unsupported classes and composition basis. | Preserve source-supported parts and unknown states; verify primary dbSEABED measurement definitions before joint closure. | Not yet resolved; provider definitions to verify. |
| SC-06 | `geomorphometry/build.py`: inspect plan/tangential/profile/general curvature definitions. | Analytic fixtures and primary method references; version changed meanings. | Not yet resolved. |
| SC-07 | `geomorphometry/build.py` and geomorphic terrain context: inspect flat normals and zero-variance TPI. | Flat facets retain vertical normals; nonzero prominence with zero neighbor variance is undefined. | Not yet resolved. |
| SC-08 | Bathymetry contour distance: inspect crossing-point geometry. | Segment distance, topology-preserving contours, and explicit unavailable status without dropping valid depth. | Not yet resolved. |
| SC-09 | Biogenic habitat observation processing: inspect footprints, time and partial parent coverage. | Separate survey opportunity, presence, absence, publication time and as-of filtering. | Not yet resolved. |
| SC-10 | Source support through manifests/catalog/release/matrix: inspect sampling and uncertainty claims. | Effective source support and method identity survive R8/R6 and consumer export. | Not yet resolved. |

Later phases include directional fetch, a categorical GEBCO TID adapter, a truthful capability
matrix, conditional source preflight, a bounded real-data recipe and installed-wheel validation.
No source was acquired, no canonical product or retained release was changed, and no user trial
or independent scientific validation has been performed in this branch.
