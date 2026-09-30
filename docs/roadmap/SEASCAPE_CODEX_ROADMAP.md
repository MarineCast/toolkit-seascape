# Seascape: Quality and New-User Readiness Roadmap

**Repository:** `MarineCast/toolkit-seascape`\
**Prepared:** September 26, 2026\
**Reviewed baseline:** `f2400c13d509ad753d9168ed4e7a07d1ffcfc5a4`\
**Status:** Implementation specification. No roadmap tasks or acceptance tests have been executed as part of preparing this document.

## 1. Mission and definition of success

Improve the existing Seascape toolkit into a coherent, independently installable research package that a new Python/GIS user can operate without author assistance. Keep the existing scientific implementation and release architecture. Prioritize a working first result, reproducible installation, understandable failures, and evidence-backed product contracts over additional features.

A successful first experience is: install the package, run one bounded offline example, locate a real output table and figures, inspect validation and provenance, and understand the limits of the result. A successful advanced experience is: understand required sources, prepare a bounded real-data build, inspect its candidate, and consume an audited release without encoding internal mutable paths.

This milestone does not certify every product scientifically, establish full regional coverage, or make Seascape a production forecasting service. Do not collapse those claims into a single readiness label.

### Evidence already present at the reviewed baseline

Preserve and extend these assets instead of recreating them:

| Existing asset | Source of truth | Implication for this work |
| --- | --- | --- |
| Scoped agent instructions and scientific boundaries | `AGENTS.md` | Read applicable instructions before every task. |
| Candidate orchestration, declared stages, and dependency ordering | `src/seascape/workflow.py` | Extend the current planner; do not build a second workflow engine. |
| Immutable schema-3 release resolution | `src/seascape/products.py`, `docs/API.md` | Keep exact-resolution lookup, checksums, retained generations, and provenance. |
| Deterministic notebook calling the production bathymetry API | `notebooks/validation/01_TOOLKIT_VALIDATION.ipynb` | Extract shared demo orchestration; do not copy scientific calculations. The current notebook requires a checkout. |
| Linux Python 3.11/3.14 jobs, notebook execution, scoped static checks, dependency and secret audits | `.github/workflows/ci.yml` | Strengthen existing jobs. The current secondary wheel environment inherits system site packages. |
| Narrow Ruff baseline and four mypy/formatting target modules | `pyproject.toml` | Expand incrementally, with formatting separated from behavior changes. |
| Release-backed metric export that pins subsequent lookups to one release ID | `src/seascape/metric_matrix.py` | Preserve this behavior; test it rather than claiming it is missing. |
| H3 alignment, null/zero, and schema-3 export tests | `tests/test_metric_matrix.py` | Extend gaps; do not duplicate existing cases or remove legacy-mode tests. |
| Prior remediation and real-release statements | `docs/review-remediation.md`, `docs/metric-matrix.md` | Distinguish historical reported results from newly reproduced evidence. |

All paths above were inspected at the reviewed baseline, directly or during the preceding review. Proposed new paths below are suggestions, not assertions that those files already exist. Recheck the actual checkout before implementing.

## 2. Rules for the implementation agent

### Scope and scientific safeguards

1. Work only in `toolkit-seascape` unless the user explicitly expands the scope. Do not repair sibling toolkits or modify OrcaCast as a side effect.
2. Read root and applicable nested `AGENTS.md` files. Read MarineCast's shared `INFRASTRUCTURE.md` when changing shared boundaries, provenance contracts, or integration, as directed by the repository. If that document is unavailable, record the limitation; do not invent a standard.
3. Preserve horizontal CRS, projected units, vertical datum, depth sign, raster alignment, nodata masks, H3 support/resolution, source coverage, missingness, and join cardinality.
4. Do not change formulas, thresholds, schemas, or scientific defaults merely to make tests pass. A discovered scientific defect gets a focused regression test and a separately described fix. Flag intentional numerical changes for scientific review before release.
5. Do not weaken publication gates, silently substitute resolutions, impute nulls with zero, fabricate a completed release, or relabel synthetic inputs as an actual provider's survey.
6. Keep Seascape independently installable. Do not add sibling-path imports, checkout discovery as a runtime prerequisite, or an OrcaCast dependency.
7. Never write experimental output into existing canonical or retained-release directories. Do not delete release generations or perform automatic schema migrations.
8. Keep secrets, downloaded source datasets, large generated artifacts, local absolute paths, and graph caches out of tracked files. Preserve source rights and attribution.
9. Graphify is optional navigation tooling, not an acceptance prerequisite or a new runtime dependency. Follow existing repository guidance.

### Working-tree, Git, and authorization rules

Inspect status and the existing branch before editing. Preserve unrelated edits. Do not reset, clean, stash, rebase, or rewrite user work to obtain a tidy checkout. When isolation is needed, use a new worktree only after establishing which committed and uncommitted changes the task depends on.

Use `feature/seascape-<task-name>` branches, or the user's existing appropriate feature branch. Each numbered implementation task is a separate reviewable change. A local commit is not authorization to push, merge, tag, publish a package, alter repository settings, or redistribute data. Prepare those steps and report them as pending unless explicitly authorized.

Default to one selected task per execution after the baseline. Continue within that task through implementation, tests, and documentation; do not stop after merely proposing a plan. When blocked, record the exact blocker and complete independent work that remains in scope. Do not ask preference questions that can be resolved from source, tests, or existing conventions.

### Minimalism and dependency rules

Prefer existing helpers, validators, publishers, and configuration loaders. Do not add a general plugin system, orchestration framework, database, web application, dependency-injection framework, or shared cross-toolkit package for this milestone. A small internal module is acceptable when it removes duplication or makes a boundary independently testable.

Use existing dependencies where practical. New runtime dependencies require a concrete runtime need and a declaration in package metadata. Test, build, documentation, and notebook tooling belong in appropriate optional/development dependencies. Never install undeclared convenience packages in an acceptance environment to conceal a packaging failure.

### Evidence and completion rules

Report commands actually executed, exit status, pass/fail/skip counts, environment, and commit. Distinguish `passed`, `failed`, `blocked`, and `not_run`. Treat a configured CI job as unexecuted until a real run result exists. Do not describe HTML file creation as visual QA, a mocked provider as a live-source test, or a synthetic fixture as regional validation.

Store machine-specific logs under an ignored validation directory or CI artifacts. Keep one concise tracked progress document, proposed as `docs/roadmap/PROGRESS.md`, that records task status, decisions, and evidence references. Do not add a separate long prose audit for every small patch.

## 3. Execution sequence and checkpoints

| ID | Task | Depends on | Suggested change/branch suffix |
| --- | --- | --- | --- |
| SS-00 | Establish the actual baseline | None | `baseline` |
| SS-01 | Build a portable offline demo | SS-00 | `first-run-demo` |
| SS-02 | Make the notebook a portable thin client | SS-01 | `portable-notebook` |
| SS-03 | Add clean consumer-install acceptance | SS-01, SS-02 | `consumer-install-ci` |
| SS-04 | Add read-only prerequisite checks | SS-00; integrate after SS-03 | `preflight` |
| SS-05 | Improve CLI diagnostics and side-effect contracts | SS-01, SS-04 | `cli-diagnostics` |
| SS-06 | Apply repository-wide formatting only | SS-00; serialize after active code changes | `format-baseline` |
| SS-07 | Expand static checks and environment reproducibility | SS-06 | `quality-gates` |
| SS-08 | Close scientific, release, and export test gaps | SS-03, SS-05; recheck after SS-07 | `contract-acceptance` |
| SS-09 | Consolidate user and maintainer documentation | SS-01 through SS-08 | `onboarding-docs` |
| SS-10 | Prepare and execute an authorized bounded real-data pilot | SS-04, SS-08, SS-09; approved inputs/network scope | `real-data-pilot` |
| SS-11 | Complete release-candidate review and maintainer handoff | All software gates; evidence from SS-10 or explicit limitation | `release-readiness` |

Checkpoint A, after SS-03: a genuinely new installation produces and explains a useful offline result.\
Checkpoint B, after SS-08: execution behavior, scientific contracts, and consumer interfaces have stronger evidence.\
Checkpoint C, after SS-11: a reviewable release candidate has truthful documentation and explicit remaining limits.

Do not parallelize formatting with behavioral edits. Read-only review and documentation drafting may occur independently, but separate agents should not edit the same files or shared working tree. The table specifies review boundaries, not permission to auto-merge a chain of dependent pull requests.

## 4. Task specifications

### SS-00. Establish the actual baseline

**Objective:** Identify what is already implemented, what currently fails, and which claims have execution evidence before changing behavior.

**Read first:** `AGENTS.md`, `README.md`, `pyproject.toml`, `.github/workflows/ci.yml`, `docs/API.md`, `docs/CONTRACTS.md`, `docs/DEVELOPMENT.md`, `docs/review-remediation.md`, and the relevant source/tests. Use targeted reads; do not rebuild navigation graphs by default.

**Steps**

1. Record `git status --short`, current branch, `git rev-parse HEAD`, and the remote. Compare to the reviewed baseline without resetting the checkout to it.
2. Map the entry points for workspace initialization, bathymetry processing, planning, publication, product resolution, and matrix export. Record the exact current symbols and test locations.
3. Create an isolated development environment using the supported interpreter available locally. Record Python, OS, architecture, package versions, and native-library versions using the existing environment-snapshot helper where applicable.
4. Run the baseline test suite, current static checks, notebook, CLI help, and an external-workspace dry run. Respect the existing distinction between offline and materialized-product tests.
5. Inspect current CI results for the actual commit when available. Separate a dependency-download outage from a reproducible installation defect; neither is a pass.
6. Create the task status table in the progress document. Mark an already completed task as verified only with evidence from the current state; otherwise scope it to the remaining gap.

**Baseline commands, after confirming prerequisites and repository instructions**

```bash
git status --short
git branch --show-current
git rev-parse HEAD
python -m pip install -e '.[test,quality,notebook]'
python -m pip check
python -m pytest -q
ruff check src tests scripts
python -m mypy
ruff format --check src/seascape/products.py src/seascape/core/geo/crs.py src/seascape/core/artifacts/confinement.py src/seascape/seafloor_physiography/depth.py
seascape --help
```

Use the existing headless notebook command with a new temporary output directory. Initialize a fresh temporary workspace before a CLI dry run; never reuse a real data workspace just to test configuration loading.

**Acceptance:** The baseline is recorded, unrelated changes are preserved, and all failures/skips are classified. No production behavior changes in this task. A failure may block dependent acceptance, but is not a reason to abandon independent documentation or test work.

### SS-01. Build a portable offline demo

**Objective:** Provide one safe command that proves the installed package can perform a real transformation, without a checkout, credentials, or source acquisition.

**Existing code to reuse:** notebook fixture setup, `seascape.seafloor_physiography.bathymetry.run_pipeline`, packaged configuration resources, and existing artifact helpers.

**Proposed files:** `src/seascape/demo.py`, focused additions to `src/seascape/cli.py`, and `tests/test_demo.py`. Use equivalent existing locations if the checkout already provides them.

**Proposed interface, not an existing command at the reviewed baseline**

```bash
seascape --workspace "$HOME/seascape-demo" demo
```

A small Python entry point such as `run_demo(workspace, *, overwrite=False)` should return a structured result with paths, validation summary, and execution metadata. Avoid making unrelated internal helpers public.

**Steps**

1. Move fixture preparation and orchestration out of notebook cells into reusable code. Keep actual bathymetry algorithms in their current production modules.
2. Use packaged resources, not repository-root discovery. Keep every demo input, config, output, and report inside a demo-owned subtree such as `<workspace>/.seascape/demo/`. Do not alter an existing workspace's ordinary configuration or canonical data.
3. Generate a tiny deterministic raster, H3 support, and bounded neighborhoods. Preserve the existing sign-conversion example and explicit nodata. Set provenance to an unmistakable synthetic/test source instead of inheriting a real provider identity from regional defaults.
4. Call the production bathymetry facade with acquisition disabled and all outputs confined to the demo subtree. Produce a real Parquet and family manifest, not a dummy success file.
5. Validate expected keys, nonempty support, declared resolution, selected independently known values, units/sign, nodata behavior, and required provenance. Reject empty outputs that would make boolean checks pass vacuously.
6. Write a machine-readable report and static input/output figures. Static figures must not require network tiles, a display server, or Jupyter. Runtime text must state that this is synthetic software acceptance, not a regional release.
7. Print the exact output/report paths and validation outcome. Keep output after completion so the user can inspect it.
8. Fail safely when demo-owned output already exists unless overwrite is explicitly requested. Even then, preserve unrelated files and never replace arbitrary directories based only on their name. Reuse current safe-writing primitives rather than creating a second publication system.

**Required tests:** normal run; arbitrary cwd; wheel-installed import; network attempts rejected during the tested computation; repeatability of values and keys; explicit nodata and zero behavior; input/output confinement; existing-output refusal; overwrite confined to known demo artifacts; failure does not leave a misleading PASS report; unrelated-file preservation; workspace environment restoration.

**Acceptance:** Runtime-only installation can produce and validate the demo without importing pytest or notebook packages. Expected values and keys repeat in the same environment. Do not require byte-identical manifests containing timestamps/run IDs or identical plotting bytes across platforms.

### SS-02. Make the validation notebook a portable thin client

**Objective:** Retain the explanatory notebook while removing its checkout dependency and duplicated orchestration.

**Files:** `notebooks/validation/01_TOOLKIT_VALIDATION.ipynb`, `notebooks/README.md`, and relevant documentation references.

**Steps**

1. Replace repository discovery with installed-package imports and the demo entry point. A copy of the notebook outside the repository must execute.
2. Let the notebook choose an explicitly displayed temporary or user-selected demo workspace. Delegate fixture generation, processing, and validation to SS-01.
3. Keep the useful explanation: environment, inputs, configuration, output grain, schema, values, figures, and validation limits. Do not turn it into a one-cell black box that hides what happened.
4. Correct statements that describe the Data Explorer as completed-release inspection when its actual role is live exploratory processing. Clearly separate synthetic acceptance, live exploration, and audited-release consumption.
5. Show each PASS/FAIL from real validation results. Do not equate successful imports or successful figure rendering with numerical correctness.
6. Execute headlessly to a separate output path. Keep committed source notebooks free of execution errors, machine-specific paths, large embedded outputs, and accidental edits from execution.
7. Verify any environment changes made in-process are restored when the reusable API finishes.

**Required tests:** headless execution from a directory containing only a copied notebook; correct environment/kernel; no checkout search; no source acquisition; no committed-notebook diff; generated reports marked synthetic.

**Acceptance:** The command-line demo and notebook use the same production and validation implementation. The notebook remains readable and useful to a newcomer, with the same explicit acceptance boundary.

### SS-03. Add clean consumer-install acceptance

**Objective:** Detect undeclared dependencies, missing package resources, and accidental source-tree access.

**Files:** `.github/workflows/ci.yml`, `scripts/check_installed_package.py`, proposed acceptance helper/tests, and package metadata only where justified.

**Steps**

1. Build a wheel in a build environment and transfer it to a separate consumer environment. Do not inherit site packages, use editable installs, or use `--no-deps` for the final consumer install.
2. Install only the wheel and its declared runtime dependencies first. Run `pip check`, installed-module checks, CLI help, workspace initialization, dry run, and the SS-01 demo before installing pytest/Jupyter/quality extras.
3. Run from outside the checkout. Clear source-path overrides and verify the import location. Copy the existing checker outside the repository if needed; preserve its block on OrcaCast imports.
4. Install the appropriate declared test/notebook extras in a separate acceptance layer and execute relevant external tests and the copied notebook. Do not let those extras supply missing runtime dependencies unnoticed.
5. Add a Linux job for the existing supported Python endpoints and at least one macOS job for a specifically selected supported interpreter/architecture. Record the actual runner platform instead of inferring it from a generic label.
6. Block external network access for the offline execution stage, after dependency installation, with a test/runner mechanism that covers the invoked process. At minimum explicitly test that demo code fails on attempted outbound access; distinguish that from an operating-system-level network denial.
7. Upload concise reports and environment snapshots on failure and success as appropriate. Preserve the existing quality/security jobs.
8. Build and inspect an sdist before final release, ensuring resources survive a wheel built from that sdist. Put any new standard build tooling in development dependencies.

**Acceptance tests:** missing runtime dependency fails; absent packaged config fails; an import from `src/` fails; a required notebook file is not needed by the runtime demo; consumer output contains valid products; no sibling repository access; Linux and actual macOS run results exist.

**Important distinction:** A Linux container cannot establish macOS acceptance. When remote jobs cannot be run from the agent's environment, the workflow change may be complete, but macOS validation remains `not_run` until the real job passes.

### SS-04. Add read-only prerequisite checks to the existing planner

**Objective:** Explain what is missing before users start a potentially expensive build.

**Files:** `src/seascape/cli.py`, the current planner in `src/seascape/workflow.py`, narrowly scoped configuration/input-validation helpers, and proposed `tests/test_preflight.py`.

**Proposed additive command**

```bash
seascape --workspace "$HOME/seascape-workspace" build \
  --only seascape-geomorphometry --dry-run --check-inputs
```

Add `--json` to this build-planning interface for machine-readable output if consistent with the CLI design. Existing plain `build --dry-run` must retain its documented behavior. Do not invent a second stage registry.

**Steps**

1. Resolve configuration, stage selection, dependency expansion, workspace, and candidate/output paths through existing code. Share a plan object/helper only when needed to avoid divergence.
2. Distinguish external prerequisites from intermediates produced by selected upstream stages. Do not report every absent downstream output as a missing source.
3. Check selected-stage prerequisites only. Missing data for unrelated families must not block a scoped plan.
4. Validate inexpensive required properties using existing validators: config shape, resolved paths, readability, relevant metadata, spatial support declarations, and any contract that can be checked without execution.
5. State which checks were performed. Path/header validation does not imply checksum or scientific validation. Do not hash an enormous source dataset silently as part of a lightweight plan.
6. Report statuses such as `ready`, `missing_external`, `generated_by_plan`, `invalid`, `unverified`, and `not_applicable`, with a required/optional flag and corrective action.
7. Include workspace, selected config, expanded stages, source paths, output destinations, publication intent, and limitations in the report. Avoid secret values or credential-bearing URLs.
8. Make the operation read-only: no source download, producer execution, output cleanup, candidate creation, or mutation of existing products. Avoid calling a validator that writes while claiming read-only behavior.
9. Return failure when a required prerequisite is missing/invalid or cannot be checked at the declared level. Optional limitations remain visible without masquerading as complete verification.

**Required tests:** valid plan; absent external raster; generated intermediates; missing unrelated-family input; bad config; invalid unit/sign declaration; workspace precedence; environment restoration; unsupported stage; unreadable source; no network; filesystem unchanged; JSON stdout remains parseable.

**Acceptance:** The preflight plan and actual execution use the same dependency and path resolution. A passing report means the documented preflight checks passed, not that a build or release audit has already succeeded.

### SS-05. Improve CLI diagnostics and document side effects

**Objective:** Make common failures actionable while preserving detailed debugging information and Python API behavior.

**Files:** CLI and family dispatch boundaries, existing workflow results, `docs/API.md`, `docs/WORKFLOWS.md`, and focused CLI tests.

**Steps**

1. Define the intended presentation for missing config, missing source, invalid scientific config, existing output, incomplete dependency, checksum mismatch, and failed publication. Do not catch every `ValueError` or `Exception` globally and disguise programming defects as user mistakes.
2. Translate only identifiable expected failures at CLI boundaries. Preserve useful exception chaining and nonzero exit codes. Keep Python API exceptions intact unless a separately documented compatibility change is required.
3. Use the pattern: operation, reason, relevant nonsecret path/setting, corrective action, and a brief guide pointer. Never recommend bypassing validation or overwriting trusted output to clear a failure.
4. Keep help forwarding and exit behavior working for family commands. Add a debug path only if needed; document its exact position in the CLI and test it.
5. Send human diagnostics to stderr when a command emits machine-readable stdout. Keep JSON output free of progress text and traceback fragments.
6. Document all user-facing operations in a small table: input prerequisites, network behavior, outputs, overwrite/resume behavior, and whether they construct a candidate, publish a family, or promote a whole release.
7. Document residual hazards honestly. Do not describe direct family APIs as isolated candidate builds when they write configured outputs.

**Acceptance:** Common first-run mistakes yield a useful message and failure status. Unexpected errors remain diagnosable. Existing scripts and public producer/consumer contracts continue to work, with any deliberate change explicitly recorded.

### SS-06. Apply repository-wide formatting only

**Objective:** Remove uneven code presentation without hiding semantic changes in a large diff.

**Files:** Python under `src/`, `tests/`, and `scripts/`; formatting configuration and CI; a short related note in `AGENTS.md` if needed.

**Steps**

1. Use the existing formatter and document its target paths. Exclude generated code only with a concrete reason.
2. Apply formatting without lint autofixes, import reordering, symbol renaming, type changes, directory moves, or algorithm edits.
3. Check that source behavior is unchanged using the full suite and, where practical, AST comparisons that ignore location metadata. Investigate differences rather than assuming a formatter proves semantic equivalence.
4. Make formatting enforcement cover the same paths in CI and contributor instructions.
5. Keep this change isolated from other active source edits to reduce merge-conflict noise.

**Acceptance:** `ruff format --check src tests scripts` succeeds and tests show no introduced regression. The diff is recognizably formatting-only. Import cleanup and lint corrections belong in SS-07, not this change.

### SS-07. Expand static checks and environment reproducibility

**Objective:** Prevent routine defects and make supported installations repeatable without pretending legacy code is fully strictly typed.

**Files:** `pyproject.toml`, `.github/workflows/ci.yml`, current environment snapshot tooling, `docs/environments/README.md`, and selected interface modules.

**Steps**

1. Expand Ruff gradually to useful correctness, unused-name, and import checks after reviewing compatibility with the codebase. Avoid blanket rule bundles that trigger a mass behavior rewrite.
2. Keep exceptions narrow and justified. Do not add file-wide suppressions or weaken a check merely to obtain green CI.
3. Expand type checks around the demo/result interface, CLI dispatch, preflight inputs/results, configuration boundaries, and metric export. Keep current product/CRS/confinement/depth targets.
4. Establish concrete parameter, return, and exception contracts. Do not rename public APIs solely for type-checker convenience.
5. Use the existing environment snapshot to record Python, platform/architecture, Python dependencies, and native GDAL/PROJ/GEOS versions when available. Redact local credential-bearing package URLs and private paths before publishing evidence.
6. Add a documented, tested reproducibility baseline using constraints or an equivalent standard approach appropriate to the platforms exercised. Keep reasonable library dependency ranges in package metadata; do not freeze every transitive dependency there.
7. Exercise both the reproducible baseline and an unconstrained supported dependency solve periodically or during release preparation. Clearly distinguish tested compatibility from a broad lower-bound declaration.
8. Retain dependency and secret audits. Do not disable audits, add broad ignores, or downgrade vulnerable packages without an explicit reviewed rationale.

**Acceptance:** The expanded gates pass, installed environments are recorded reproducibly, and docs state exactly which modules/platforms were checked. Full strict typing of every scientific routine is not required to finish this milestone.

### SS-08. Close scientific, release, and export test gaps

**Objective:** Demonstrate the contracts users rely on, using small independently interpretable tests and real public interfaces.

**Existing anchors:** `tests/test_products.py`, `tests/test_review_regressions.py`, `tests/test_workflow.py`, `tests/test_metric_matrix.py`, publication tests discovered in SS-00, and family scientific tests.

**Steps**

1. Map each critical contract to existing test names. Mark present evidence, missing evidence, and new failures separately. Avoid duplicating tests or counting test quantity as quality.
2. Add explicit expected-value assertions to the demo. Derive expectations from the documented algorithm and simple analytic/hand-checkable inputs, not by calling the implementation twice or blessing current output blindly.
3. Cover a constant field, a controlled gradient, nodata edges, true zero, unavailable values, and invalid inputs where relevant. Validate nonempty supports so all-null/all-empty results cannot pass.
4. Preserve row-order invariance, unique keys, exact resolution, support equality/cardinality, depth sign, projected units, and finite-value policy. Add boundary cases only where coverage is absent or a failure is reproduced.
5. Exercise a tiny production transformation and family validation end to end. Separately exercise a test-only canonical release through the actual publication/resolution pathway where existing fixtures support it. Do not weaken the real release gate to make a one-family demo look like a complete release.
6. Retain existing synthetic release-reader tests. Handcrafted test manifests are appropriate for isolated parser cases, but do not use them as the sole evidence that production publication works.
7. Verify publication A, publication B, historical resolution of A, exact resolution rejection, tampered checksums, unsafe paths, config-change resume invalidation, and interrupted-promotion recovery using existing fixtures/helpers.
8. Extend matrix checks for shuffled input rows, duplicate/null/wrong-resolution keys, support mismatch, retained null versus zero, QC/evidence columns, source units, source types, and collision-free names.
9. Add a controlled release-switch test: after export chooses release A, publishing B must not cause the exported table or metadata to mix generations. The implementation already pins later lookups; this test protects that contract.
10. Test failed exports, existing destinations, input/output aliasing, and overwrite behavior. Ensure a failure does not replace the previously valid destination. Treat explicit legacy output as structurally checked, never as a schema-3 release.
11. Record numeric tolerances with scientific reasoning. Separate same-environment deterministic equality from cross-platform floating-point tolerances and from runtime metadata differences.

**Acceptance:** Critical numerical, metadata, provenance, publication, and consumer contracts have named executable evidence. No new broad skips, forced PASS flags, silent coercions, or unsupported scientific claims are used to reach green.

### SS-09. Consolidate documentation around three user journeys

**Objective:** Make current use clear without accumulating another layer of repetitive architecture prose.

**Files:** `README.md`, `docs/README.md`, `docs/WORKFLOWS.md`, `docs/CONFIGURATION.md`, `docs/API.md`, `docs/DEVELOPMENT.md`, `docs/products.md`, `docs/metric-matrix.md`, notebook guide, and concise contribution/release notes as needed.

**Steps**

1. Make the README explain purpose, audience, and the first output before migration history. Show one representative result generated by the demo, clearly labeled synthetic.
2. Provide an exact installation path from obtaining the source to an isolated environment and first result. Use the tested release artifact or verified source-install method; do not imply that an unpublished package is on PyPI.
3. Separate three routes: offline synthetic demo, bounded real-data processing, and consumption of an audited release. Do not suggest they prove the same thing.
4. Make commands executable as written with one clearly defined workspace variable. Label placeholders explicitly and show required configuration edits rather than saying only “adjust settings.”
5. Show output paths, a small table/schema example, units/sign conventions, QC interpretation, and expected success/failure behavior. Preserve the distinction between unavailable and observed zero.
6. Add a supported-environment table grounded in actual CI evidence. Keep native Windows explicitly outside the current POSIX publication scope unless separately implemented and tested.
7. Give advanced users a stage-to-required-source reference generated from existing metadata where feasible. Document provider rights, bounds, resolution, output size/performance evidence, and limitations in the owning guides instead of duplicating them.
8. Add a consumer example that freezes a release ID, resolves exact products, and reads their outputs. Align matrix documentation with tested field and provenance behavior.
9. Clearly label old migration/remediation documents as dated evidence. Correct stale current-use claims without rewriting history or representing past tests as recent execution.
10. Check relative links, headings, command names, generated documentation, and packaged-template consistency in CI. Keep offline link/file checks separate from optional external-URL availability checks.
11. Follow existing catalog-generation rules. Do not regenerate authoritative product documentation against an empty workspace and label it a release catalog.

**Acceptance:** A reader can follow the first-result guide without learning OrcaCast history or reading producer source. Every supported quickstart command is exercised automatically, and longer workflows have explicit prerequisite/validation boundaries.

### SS-10. Prepare a bounded real-data pilot and measured operating envelope

**Objective:** Produce reproducible evidence for one useful real-data path without silently launching a regional rebuild or redistributing restricted inputs.

**Authorization:** Use locally available inputs when appropriate and safe. Live acquisition requires explicit source, spatial extent, date/release, workspace, and resource limits approved by the user. Prepare the runbook and leave execution `blocked` if those are unavailable; do not ask the agent to run unbounded defaults.

**Files:** A compact example configuration/runbook in the existing examples or documentation convention; a validation evidence summary. Large artifacts remain external/ignored.

**Steps**

1. Inspect the existing San Juan explorer and reported release evidence before choosing the pilot. Reuse a suitable bounded recipe instead of inventing another region and masking method.
2. Select a modest bathymetry/spatial-support path with clearly available source rights and versions. Document any exploratory mask as exploratory; do not promote it to canonical territorial-water support by implication.
3. Record source identity/checksum, source and product resolutions, CRS/datum/sign, config fingerprint, code identity, environment, storage destination, and planned limits. A small AOI is not proof of a small download; inspect provider acquisition behavior first.
4. Run preflight. Stop before an operation that exceeds the approved acquisition/disk/runtime scope or requires a source not yet authorized.
5. Execute in a fresh workspace with publication off unless a separate disposable test workspace and explicit publication scope are approved. Preserve previous datasets and snapshots.
6. Validate output keys, support/coverage, units, missingness, QC, manifests, and source identity. For version comparisons, compare only like-for-like source/configuration inputs or explain intentional differences.
7. Measure elapsed time, input/output bytes, and peak memory with a documented method. Include child-process resource use or state its exclusion. Repeat before reporting stability; avoid unsupported promises about regional scaling.
8. Render and actually inspect output maps. Check extent, orientation, sign/legend, nodata display, coastlines, and obvious artifacts. Record visual QA separately from file generation.
9. Provide a small reproducibility record with exact commands and environment. Separate restricted source data from redistributable examples.
10. Update current documentation with measured evidence and limitations. Describe a limited pilot as a limited pilot, not certification of all product families.

**Acceptance:** There is either a reproduced bounded real-data run with reviewable evidence, or an explicit blocked runbook with the missing input/permission listed. The latter does not satisfy the real-data gate, but need not prevent an honestly labeled offline research prerelease.

### SS-11. Final release-candidate review and maintainer handoff

**Objective:** Assemble a tested candidate and distinguish agent-completable work from release-owner actions.

**Steps**

1. Re-run the acceptance gates on the exact release-candidate commit. Confirm a clean intended diff and that no local source datasets, caches, credentials, or personal paths entered tracked files.
2. Build the wheel and sdist in a clean environment, then install the resulting wheel in clean Linux/macOS consumer environments. Verify package metadata and required resources from the built artifacts, not just the checkout.
3. Run the offline demo, copied notebook, full offline suite, critical publication/export acceptance, formatting, linting, targeted typing, template/doc consistency, dependency audit, and secret scan. Report every skip.
4. Ask a genuinely unfamiliar user to follow the guide and locate/interpret outputs. Codex can run an automated fresh-user simulation, but must not label that human usability evidence. Keep this maintainer/user check explicit.
5. Prepare release notes that separate new capabilities, fixed defects, compatibility changes, known limits, test evidence, and unrun real-data paths. Propose a version under the repository's policy rather than assigning one arbitrarily.
6. Prepare a short maintainer checklist for required status checks/rulesets, merge policy, tagged release, and release assets. Inspect effective rulesets and current check names before proposing administrative changes. The historical branch-protection response is not proof of all effective rules.
7. Do not merge, push tags, publish to a registry, alter GitHub settings, or upload data without explicit authorization. If authorized later, release the tested artifact or rebuild from the same immutable commit with equivalent verification.
8. Leave the progress document with final status, exact evidence, remaining risks, and the next task. Do not write “production ready” when the evidence establishes only research-package acceptance.

**Acceptance:** The owner receives a reviewable release candidate, a clear go/no-go checklist, and no hidden claims. Administrative and live-data blockers remain visible rather than being marked complete by the agent.

## 5. Cross-cutting acceptance matrix

Use this matrix to review the final candidate. An existing test can satisfy a row; creating a new file is not inherently required.

| Contract | Required evidence |
| --- | --- |
| Package independence | Wheel import outside checkout; OrcaCast imports blocked; no sibling path access. |
| Runtime dependencies | Runtime-only consumer install runs the demo before installing development extras. |
| Portable notebook | Copied notebook executes outside source tree in its intended environment. |
| Offline execution | No outbound activity under the documented test/runner guard. |
| Safe demo workspace | No mutation of ordinary configuration, canonical data, retained releases, or unrelated files. |
| Truthful demo provenance | Synthetic source metadata and explicit nonregional/nonrelease label. |
| Deterministic calculation | Repeatable keys and values with justified tolerances; metadata timestamps excluded. |
| Nonvacuous validation | Empty support/all-null unexpected output is rejected. |
| Scientific semantics | Sign, units, CRS, nodata, resolution, and coverage assertions. |
| Planning correctness | Same dependency resolution as execution; generated intermediates distinguished from external inputs. |
| Read-only preflight | Filesystem and network assertions; no producer or publication call. |
| Useful errors | Actionable expected failures, nonzero exit, valid JSON when requested, preserved debug path. |
| Release immutability | Publish A/B, resolve A later, verify hashes and safe path confinement. |
| Recovery and resume | Injected failures and changed configuration invalidate unsafe reuse or recover safely. |
| Export correctness | Key alignment, null/zero/QC/units, exact support, single release identity, failure-safe destination. |
| Supported environments | Actual Linux/macOS consumer job results, with interpreter and architecture recorded. |
| Code presentation | Formatting gate across intended source/test/script paths. |
| Static/security checks | Defined lint/type scope; current dependency and secret audit results. |
| Documentation accuracy | Tested first-run commands, resource/template/link consistency, dated historical evidence. |
| Real-data claims | Bounded source/config/environment record; numerical and visual QA separately identified. |
| Human usability | Observed unfamiliar-user trial, or honestly marked pending. |

No arbitrary global coverage percentage is a substitute for these contracts. No manual PASS flags or skipped core checks are acceptable substitutes for execution.

## 6. Per-task handoff format

At the end of every selected task, report:

```text
Task: SS-XX / title
Status: passed | failed | blocked | not_run
Base commit and current commit:
Branch:
Files changed:
Behavior/API changes:
Scientific behavior changed: no | yes (explain)
Commands executed and exit codes:
Test counts: passed / failed / skipped, with skip reasons
Environment and evidence paths:
Known risks or blocked external checks:
Unrelated work preserved:
Next recommended task:
Remote changes performed: none, unless explicitly authorized and listed
```

For a partially complete task, distinguish implementation completion from acceptance completion. A written macOS workflow with no executed job is not a validated macOS installation. A source-downloader test using mocked responses is not a live-provider check.

## 7. Launch prompt for Codex

Use this with the roadmap attached or saved in the repository. Keeping the roadmap as a separate document avoids turning `AGENTS.md` into a long one-off project plan.

```text
Implement the Seascape quality and new-user readiness roadmap in
SEASCAPE_CODEX_ROADMAP.md (attached, or at
 docs/roadmap/SEASCAPE_CODEX_ROADMAP.md in this checkout).

Work only in MarineCast/toolkit-seascape. First read applicable AGENTS.md
instructions, inspect git status and the current branch/commit, and verify
the roadmap against the actual source. The roadmap's reviewed commit is
context, not an instruction to reset or overwrite newer work.

For this session, complete SS-00, then implement SS-01. Do not stop after
planning. Reuse the existing production bathymetry API, artifact helpers,
packaged resources, and notebook fixture logic. Do not duplicate scientific
calculations or weaken release/scientific validation.

Preserve unrelated changes, existing configurations, canonical products,
and retained releases. Keep all demo artifacts in the demo-owned workspace.
The demo must work from an installed wheel without a repository checkout,
credentials, source downloads, pytest, or Jupyter. Label synthetic provenance
explicitly and add the required regression/acceptance tests.

Use an appropriate feature/seascape-* branch or preserve an existing suitable
feature branch. Keep changes reviewable. Do not push, merge, tag, publish,
change GitHub settings, acquire real datasets, or modify sibling repositories.

Run applicable checks, update the concise progress record, and report exact
commands, results, skips, blockers, changed files, and scientific/API impact.
Do not claim a test passed unless it ran. If something is blocked, complete
independent work within SS-00/SS-01 and state the blocker precisely.

Finish with the roadmap's per-task handoff. Stop before SS-02.
```

### Continuation prompt

```text
Continue the Seascape roadmap. Read the roadmap, current progress record,
applicable AGENTS.md instructions, and the actual working tree. Select the
next incomplete task whose prerequisites are satisfied. Reverify earlier
assumptions that its implementation depends on. Implement that one task,
run its acceptance checks, update progress, and report using the handoff
format. Preserve the roadmap's scope, scientific, data-safety, and remote-
authorization boundaries. Do not redo verified work or claim blocked checks
passed. Stop after the selected task and identify the next task.
```

## 8. Deferred work and release-owner decisions

Do not add new product families, scientific formulas, a GUI, new workflow frameworks, Windows-native publication, automatic release cleanup, or broad cross-toolkit integration during this milestone. Consider those only after the first-result and consumer-install gates hold.

Live downloads and real-source redistribution, scientific behavior changes, repository rules, merge/tag/package publishing, and the human usability trial require an explicit owner decision or evidence that the decision has already been made. These are not reasons to stall unrelated safe implementation; they are boundaries that should appear clearly in the handoff.

## 9. Review evidence index

The following repository sources ground the initial plan. They are not a claim that the proposed tasks already exist or that acceptance has been rerun. Re-open them at the actual implementation commit.

- `AGENTS.md`: local scope, scientific safeguards, validation commands, shared-infrastructure navigation.
- `src/seascape/cli.py`: existing CLI and family dispatch.
- `src/seascape/workflow.py`: `DomainBuildContext`, `DomainBuildStage`, `StageResult`, stage runners and orchestration.
- `src/seascape/products.py` and `docs/API.md`: supported facades, side effects, exact-resolution and retained-release contracts.
- `src/seascape/metric_matrix.py` and `tests/test_metric_matrix.py`: release-pinned export, key alignment, metadata, legacy boundary.
- `notebooks/validation/01_TOOLKIT_VALIDATION.ipynb`: checkout discovery, synthetic input, production bathymetry execution and broad assertions.
- `notebooks/README.md`: distinction between offline acceptance and live exploratory processing.
- `.github/workflows/ci.yml`: existing installation, notebook, quality, security, and inherited-site-package wheel jobs.
- `scripts/check_installed_package.py`: installed import-location check and blocked application imports.
- `pyproject.toml`: dependency declarations, extras, narrow lint rules, selected type-check targets.
- `docs/WORKFLOWS.md`, `docs/CONFIGURATION.md`, `docs/DEVELOPMENT.md`, `docs/CONTRACTS.md`: execution and documentation contracts.
- `docs/review-remediation.md`: historical corrections and their dated evidence.
- `docs/metric-matrix.md`: export contract and reported local audited-release evidence; verify the underlying run before treating it as reproduced.

The roadmap's execution sequence, proposed modules/flags, acceptance matrix, and task boundaries are recommendations tailored to these sources, not newly verified runtime results.
