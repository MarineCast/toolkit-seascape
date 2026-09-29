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
| SC-02 | `bathymetry/build.py` directly assigns pixels at each resolution; `pipeline.py` overwrote direct R6 counts and bands with R8-child sums while retaining direct R6 moments. | Canonical statistic family must use one declared sampling support; retain hierarchy-only parents as unavailable. | Removed the mixed-support overwrite; `direct_pixel_support_v2` candidate metadata declares the change. Controlled H3 boundary, one valid plus nodata pixel, band closure, hierarchy-only nulls, and missing-source regressions are in `test_bathymetry_contracts.py`. Historical releases retain old semantics. |
| SC-03 | `utils/habitat_surface.py`: clipping counted support cuts as habitat edges. | Habitat interfaces exclude artificial support cuts; patch identity is local to the reporting support, with truncation recorded. | Per-support geometry unions exclude boundary-coincident lines and set `TOPOLOGY_QC_REASON`; analytic and real H3 fixtures pass. Survey/AOI truncation beyond the reporting support still needs explicit metadata in SC-09. |
| SC-04 | `utils/habitat_aggregation.py`: parent patch counts/edges were sums of child values and the largest patch was the largest *child* fragment; empty fragmentation was zero. | Recompute union-scale topology; no-patch fragmentation is undefined with a reason. | R6 publication now unions selected child support geometry per parent and measures inventory geometry on that union. Without supplied parent geometry, topology remains null with `topology_not_computed` instead of inventing values. Empty fragmentation is null with `no_mapped_patch`. Analytic fixtures and the full suite pass. |
| SC-05 | `benthic_substrate/classification/build.py` closed modeled rock presence against source sediment percentages, encoded unsupported boulder/cobble/mixed as zero and fed an unjustified hardness index to reef suitability. | Preserve source-supported measurements separately, reject invalid percent inputs, and suppress unsupported derived quantities pending exact provider basis. | Rock is a modeled presence score, gravel/sand/mud are a separate sediment texture; only closed supported sediment shares get entropy. Unsupported classes, hard-substrate area fraction and hardness index are null with status, and reef suitability cannot recover them by reweighting. Producer regressions pass. Exact pinned December 2025 HUB Ocean product definitions were not accessible, so a joint areal closure and physical hardness calibration remain blocked, rather than fabricated. |
| SC-06 | `geomorphometry/build.py`: historical `PLAN_CURVATURE` used the surface-tangential denominator. | Distinguish horizontal plan from surface-tangential curvature, retain the latter under its own name, and version the meaning. | `PLAN_CURVATURE` now uses the horizontal contour denominator and `TANGENTIAL_CURVATURE` preserves the former expression; `geomorphometry_curvature_tpi_v2` manifest metadata and family documentation record equations/sign/scale. Analytic plane, parabola, dome, bowl, saddle, and rank-deficient tests pass. |
| SC-07 | `geomorphometry/build.py` excluded flat facets from VRM because their aspect is undefined; its standardized TPI returned zero for nonzero prominence divided by zero neighbor variance. Geomorphic terrain context had the same TPI case and was corrected in SC-01. | Flat facets retain vertical normals; nonzero prominence with zero neighbor variance is undefined. | Flat VRM and mixed flat/60-degree analytic tests pass. Ring TPI in metres remains +50 in the controlled case, Z is null with a QC reason, and downstream broad Z is also null. |
| SC-08 | Bathymetry contour distance queried nearest raster-edge crossing *points* and raised if no contour was present. | Segment distance, topology-preserving contours, and explicit unavailable status without dropping valid depth. | Marine-only marching squares produces interpolated segments, chooses ambiguous saddle pairings by center sign, and measures metric straight-line distance. A contour absent inside a valid crop yields null distance plus status while depth remains. Analytic line, circle, land/nodata, disconnected, and no-contour fixtures pass. Crop-edge censoring is documented; no regional accuracy claim is made. |
| SC-09 | Biogenic habitat processing previously treated positive canopy polygons as surveyed area, used an archive-wide latest year and could promote one absent child to whole-parent absence. | Separate survey opportunity, presence, absence, observation/publication time and as-of filtering. | Explicit complete-event footprints alone establish surveyed area and implicit absence; otherwise completeness is unknown. Latest local polygon evidence and source priority determine present/absent/unknown fractions; point/line evidence remains non-areal. R6 fractions aggregate by water area. Observation and known availability years are filtered before staging; unknown availability is flagged as retrospective. Synthetic producer regressions pass. |
| SC-10 | Source support through manifests/catalog/release/matrix: inspect sampling and uncertainty claims. | Effective source support and method identity survive R8/R6 and consumer export. | New candidate manifests carry method identity and source support. Release records, `ProductArtifact`, generated catalog fields and metric-matrix metadata retain those details when present; fixture tests cover resolution-specific records and missing uncertainty. The checked-in catalog describes older materializations and cannot be regenerated or represented as a new validated regional release without their source artifacts. Field definitions that remain producer-specific still require source-backed review; no independent validation is claimed. |

## Bounded additions and first use

Sixteen-bearing geometric fetch export records metres, search limit, censoring and source status.
The optional GEBCO TID adapter validates declared release and exact raster grid alignment, counts
categorical codes on the depth pixel support, and publishes depth/TID together. Deterministic
fixtures pass; no regional TID source has been acquired or materialized. The
[capability matrix](capability-coverage.md) records implementation versus data/contract blocks.

Preflight and producers now use explicit selected jurisdictions. A B.C.-only water-geometry
candidate consumes the existing Canadian region and territorial-zone layers; B.C.-only habitat
selection disables Washington inventories. The default cross-border configuration remains intact.
The [real-data recipe](real-data-recipe.md) specifies a bounded candidate command and source
requirements, but was not executed: a fresh, permitted and reviewed GEBCO crop and canonical
water-support inputs are not present. The [new-user checklist](new-user-checklist.md) is ready;
no unfamiliar-user trial occurred. No source was acquired, no canonical product or retained release
was changed, and no independent scientific validation has been performed in this branch.

## Validation on the implementation branch

All commands below used `/tmp/seascape-roadmap-dev/bin/python` (3.14.6) in this checkout unless
the command names its own executable. `python -m pytest -q`: exit 0, 444 passed, 3 skipped,
110 warnings; the three skips require materialized regional artifacts. The first full-suite run
after the TID change exited 1 (one demo-provider provenance failure); correcting the inherited
GEBCO datum/evidence claims made the rerun pass. `python -m pytest -q
tests/domains/environment/seascape/test_gebco_tid.py tests/test_preflight.py
tests/test_water_geometry_provenance.py tests/test_consumer_acceptance.py`: exit 0, 92 passed.
`ruff check src tests scripts`, `ruff format --check src tests scripts`, `python -m mypy`,
`python scripts/check_docs.py`, `python -m pytest -q tests/test_documentation.py`, and
`python -m pip check`: exit 0; docs checked 46 documents, 198 local links and 26 stages,
but not external URLs. The notebook's first sandboxed `jupyter nbconvert --to notebook --execute
notebooks/validation/01_TOOLKIT_VALIDATION.ipynb --ExecutePreprocessor.timeout=120
--output seascape-toolkit-validation-hardening.ipynb --output-dir /private/tmp` exited 1 because
loopback socket bind was denied. Repeating the same command with local-kernel permission exited 0;
the executed notebook has 25 cells and no error outputs.

`python -m build --outdir /private/tmp/seascape-hardening-dist-20260929` exited 1 because sandboxed
isolated build dependency installation could not resolve PyPI. Repeating the isolated build with
network permission and `--outdir /private/tmp/seascape-hardening-isolated-dist-20260929` exited 0;
the sdist and wheel passed `scripts/check_distribution.py` (9 required files, 5 packaged resources).
The non-isolated fallback build also exited 0, but the later isolated build is the final package
evidence.
The first sandboxed clean-consumer and quickstart runs exited 1 at dependency installation because
PyPI DNS was unavailable. With network permission the quickstart checker passed all install/demo/
plan blocks and 15 demo checks outside the checkout. The first network-enabled consumer run
exited 1 at the installed-module check because its registry-count assertion still expected 75;
the TID registration increased it to 77. The assertion was corrected to require both TID IDs;
the final isolated-build wheel passed `scripts/check_consumer_install.py`: installed-runtime import,
resources, CLI, demo and negative probes passed; after extras, 179 copied tests and the copied
validation notebook passed. The matching isolated-build sdist passed
`scripts/check_quickstart.py`: install/demo/plan blocks and 15 demo checks. Both ran outside the
checkout and recorded reports under `/private/tmp/seascape-hardening-isolated-consumer-20260929/`
and `/private/tmp/seascape-hardening-isolated-quickstart-20260929/`. The direct local command
`seascape --workspace /private/tmp/seascape-hardening-demo-20260929 demo` exited 0 with
`Synthetic software acceptance: PASS` and kept its Parquet, manifest, report and two figures in
the demo-owned subtree. None of these package checks is a regional build, a source acquisition,
or a scientific accuracy assessment.
