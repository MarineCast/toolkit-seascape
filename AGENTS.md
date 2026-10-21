# toolkit-seascape agent guidance

## Scope and current state

Bathymetry, marine geomorphology, coastal geometry, and derived features.

The toolkit owns species-neutral product schemas, static feature eligibility and flat per-area Parquet
output contracts. Applications own prediction targets, temporal validation, predictive feature/scale
selection, model fitting and evaluation.

This repository contains the installable `seascape` package extracted from OrcaCast on 2026-09-15.
Read `docs/ARCHITECTURE.md` for ownership/import changes; `docs/CONTRACTS.md` for scientific
or product changes; README.md and docs/MIGRATION.md for setup or extraction-history questions.
Preserve unrelated changes and read deeper instructions before editing a subdirectory.

## Shared MarineCast context

For boundary, dependency, shared schema/provenance, or application-integration changes, read
[INFRASTRUCTURE.md](https://github.com/MarineCast/.github/blob/HEAD/INFRASTRUCTURE.md).
In the grouped workspace use `../../.github/INFRASTRUCTURE.md`; in a flat clone layout use
`../.github/INFRASTRUCTURE.md`, resolving from this checkout. Otherwise use the linked copy;
if unavailable, report the limitation without inventing a shared standard. Sibling instructions
are not inherited. Local implementation contracts remain authoritative; surface conflicts.

## Domain contracts

Preserve horizontal CRS, vertical datum, depth/elevation sign conventions, units, raster alignment,
and nodata masks. Define the spatial scale and neighborhood used by derived terrain metrics.
Keep land/water classification and missing coverage explicit. Geomorphology describes physical
features; species habitat suitability belongs in a downstream application.

## Implementation boundaries

- Keep this toolkit species-neutral and independently installable; do not require an OrcaCast
  checkout or import through sibling filesystem paths.
- Before adding a pipeline, define source rights, input/output grain, units, spatial and temporal
  support, missingness, provenance, and validation in the repository documentation.
- Add dependency declarations and runnable setup/validation commands with the implementation;
  do not copy viewshed's GDAL stack or commands unless this toolkit actually needs them.
- Prefer deterministic calculations and small synthetic/offline fixtures. Keep credentials,
  downloads, and large generated products out of tracked source.
- Keep unknown and unavailable values distinct from observed zero. Validate uniqueness and join
  cardinality rather than silently dropping conflicting records.

## Validation and completion

Use isolated Python 3.14: `python -m pip install -e '.[test]'`.
Start behavior validation with `python -m pytest -q tests/<relevant_test>.py`, then the required
suite below. Documentation-only edits need reference checks and `git diff --check`, not Python tests.
No local skills are needed yet; load only the task-specific documents routed above.


For documentation-only work, inspect `git status --short` and the diff, verify references, and run
`git diff --check` from this repository. Run `python -m pytest -q` from this checkout after installing `.[test]`.
Use `seascape build --dry-run` to inspect stage dependencies. Real acquisition and regional builds
are separate from offline tests; three materialized-product tests skip without regional data.
When adding executable behavior, add appropriate checks and document their exact commands here.
Report tests actually run, unverified source acquisition, and any unrun integration paths.

When changing user-visible workflows, product schemas, workspace behavior, or representative
processing APIs, check whether `notebooks/validation/01_TOOLKIT_VALIDATION.ipynb` must change. The
notebook exercises production APIs; do not duplicate scientific implementations in cells. Keep its
required path offline, deterministic, small, and CI-executable. Run it headlessly without modifying
the committed notebook:

```bash
jupyter nbconvert --to notebook --execute notebooks/validation/01_TOOLKIT_VALIDATION.ipynb --ExecutePreprocessor.timeout=120 --output seascape-toolkit-validation.ipynb --output-dir /tmp
```

## Offline demo checks

For planner/input-preflight changes, run `python -m pytest -q tests/test_preflight.py tests/test_workflow.py`
then the required full suite. `seascape --workspace /path/to/workspace build --only
seascape-geomorphometry --dry-run --check-inputs --json` inspects local prerequisites without writes,
hashes, downloads or producers. A ready report establishes only its stated inspection level;
missing/invalid/required-unverified checks fail. See [workflow limits](docs/WORKFLOWS.md).

For demo/CLI behavior, run `python -m pytest -q tests/test_demo.py`, then the required suite above.
For CLI diagnostics, also run `python -m pytest -q tests/test_cli_diagnostics.py tests/test_products.py`
to verify failure codes, stderr/JSON separation, family help forwarding and unchanged API exceptions.
`--debug` is a global option before the command; it never relaxes validation.
`seascape --workspace /path/to/fresh-workspace demo` performs synthetic software acceptance; it
never establishes a regional release. Keep artifacts in its owned `.seascape/demo` subtree.
After building/installing a wheel, copy `scripts/check_demo.py` outside the checkout and run it
with a clean runtime-only interpreter and `--workspace /path/to/fresh-workspace`. No test or
notebook extras may supply dependencies in that environment. See [demo guide](docs/demo.md).

For portable validation-notebook changes, run `python -m pytest -q tests/test_validation_notebook.py`
and the required suite. Copy the notebook and `scripts/check_validation_notebook.py` outside the
checkout; run the helper with an installed-wheel interpreter plus notebook extra, `--notebook`,
`--output`, `--forbid-root` and optionally `--workspace`. Keep its input directory notebook-only
and output separate. See [notebook guide](notebooks/README.md). Do not overwrite the committed
notebook with execution results or register a global kernel for acceptance.

For packaging/consumer acceptance changes, run `python -m pytest -q tests/test_consumer_acceptance.py`
then the required suite. Install `.[build]` in the build environment and use `python -m build`
to build the wheel from an sdist. Inspect both with `scripts/check_distribution.py`, then run
`scripts/check_consumer_install.py --wheel /transferred/wheel.whl --source /explicit/checkout
--forbid-root /checkout/group --output /fresh/outside/directory`. This creates an isolated consumer
and runs runtime checks before declared test/notebook extras. Output is refused if it already exists.
Read [development guide](docs/DEVELOPMENT.md) for the full commands and process-guard limitations.
Configured hosted jobs are not passed until their real run results exist.

## Documentation checks

For documentation/example changes, run `python scripts/check_docs.py` and
`python -m pytest -q tests/test_documentation.py`; executable-check changes also require the full
suite and review-hardening checks. After building an sdist, use `scripts/check_quickstart.py --sdist
/transferred/source.tar.gz --source /explicit/checkout --forbid-root /checkout/group --output
/fresh/outside/directory` to execute the marked source-install/demo/plan commands. Installation
may download declared dependencies; runtime uses the existing Python consumer guard and cannot
acquire sources. See [development](docs/DEVELOPMENT.md#documentation-and-first-result-acceptance).

## Codebase navigation

Use the existing local `graphify-out/graph.json` for structural questions; skip graph work for
obvious targeted edits. Prefer the smallest useful retrieval:

1. Known symbol: `explain` first, then follow only relevant callers/callees/imports/dependencies.
2. Use direct relationships before deeper traversal; broad `query` is for unknown ownership.
3. If results are large or truncated, narrow the symbol or relationship before increasing budget.
   `--budget` is not a guaranteed cap. Avoid unnecessary depth-2 neighborhoods.
4. Read the identified source/tests. They outrank schemas/contracts, architecture docs, then the
   graph. Use targeted `rg` when graph coverage or freshness is insufficient.

```bash
graphify explain "DomainBuildStage"
graphify affected "DomainBuildStage" --relation calls --depth 1
graphify query "<topic>" --context call --budget 1500
```

`affected` follows reverse edges (callers); `explain` shows immediate connections. Use ast-grep
for syntax patterns and `rg` for literal/config/prose/filename searches. Read architecture for
ownership/import changes, not every typo. Optional shared setup/examples:
[code navigation](https://github.com/MarineCast/.github/blob/HEAD/docs/code-navigation.md)
(local grouped workspace: `../../.github/docs/code-navigation.md`). No sibling checkout is required.

Graphify is optional developer tooling (`graphifyy==0.9.62`, isolated Python 3.10+), not a runtime
dependency. Create a missing graph or refresh after structural edits, from this checkout only:

```bash
graphify extract . --code-only --no-cluster
```

Do not rebuild merely for a question. Check intentional deletions before using `--force` to bypass
shrink protection. `.gitignore` and `.graphifyignore` apply; AST-only extraction does not index
prose semantically. Graphs/caches are disposable local-only files: never commit or publish them.
Any future sharing requires an explicit policy covering destination, revision, freshness and review.
Global skill defaults do not override repository scope or code-only extraction. Do not run
`graphify codex install` over maintained instructions or enable hooks/merge drivers implicitly.

## Review-hardening checks

For audit/promotion and passage-section changes, first run
`python -m pytest -q tests/test_completion_regressions.py tests/test_products.py
tests/domains/environment/seascape/test_release.py
tests/domains/environment/seascape/test_passage_sections.py`, then the full suite
and checks below. Audit schema 3 binds candidate bytes; fixture audit refreshes
are synthetic publisher tests, never regional certification. The validation
notebook remains a bathymetry client and does not exercise these release/passage gates.

The static San Juan snapshot renderer is `scripts/render_san_juan_snapshot.py`;
see `docs/examples/san-juan-bathymetry.md` for its explicit cached inputs and output.
It verifies retained identities and never downloads or recomputes scientific values.

Install `.[test,quality]`, then run `ruff check src tests scripts`, `python -m mypy`, and
`ruff format --check src tests scripts`. Use `ruff format src tests scripts` for formatting;
keep lint autofixes, import reordering and semantic edits in separate changes. The format gate
covers all Python in those paths with the existing Ruff defaults and Python 3.14 target;
there are no additional generated-code exclusions. Mypy checks the 21 interface modules listed
in `docs/environments/README.md`; skipped external imports remain documented there.
Run installed-wheel imports using `scripts/check_installed_package.py` from outside the checkout.
Capture the runtime/test/quality closure with `scripts/environment_snapshot.py --extra test
--extra quality --output /tmp/seascape-env`
and audit it with `pip-audit --disable-pip --no-deps --strict -r /tmp/seascape-env.txt`.
CI also runs Gitleaks over history and the working tree. Scope and platform limits are documented in
`docs/environments/README.md`; API/storage changes are documented in `docs/API.md`.

## Current data output workflow

For coastal-policy mask, native membership or reporting-mask changes, run
`python -m pytest -q tests/test_coastal_policy.py`, then the full suite, documentation,
notebook and quality checks above. Regional geometry validation remains separate from synthetic tests.

For common-denominator mapped substrate classes, run `python -m pytest -q
tests/test_areal_substrate.py`, then the full suite and quality/documentation checks above.
Mapped class fractions must not fill unavailable physical hardness fields.

For historical extraction, native positive-footprint and explicit geometry-QC changes, run
`python -m pytest -q tests/test_historical.py tests/test_geometry_quality.py
tests/test_native_seagrass.py tests/test_native_kelp.py tests/domains/environment/seascape/test_acquisition_identity.py`,
then the full suite, documentation, notebook and quality checks above. Historical source gaps
and unknown availability remain explicit; extraction does not approve pending regional inputs.

Normal builds write only flat `Data/Seascape/<area>-r<resolution>-static.parquet`, optional
`<area>-r<resolution>-dynamic.parquet` with a `date` column, and one small `catalog.json`.
No versioned filenames, release folders, retained generations or per-area sidecars.
The optional `research/` child is reserved for separately keyed object/long tables and is preserved
by flat area writes and historical output replacement. It is not another H3 product generation.
Keep definitions, units, source context and temporal precision embedded in Parquet.
Internal source caches and scratch computation are separate; successful default
builds remove scratch. Historical release APIs live in `seascape.legacy_products`
for explicit migration only and must not be reintroduced into normal builds.
For these changes run `python -m pytest -q tests/test_domain_parquets.py
tests/test_workflow.py tests/test_preflight.py`, then the required full suite,
documentation, notebook and quality checks above.

For shared-study selection and source-derived channel/outlet changes, run
`python -m pytest -q tests/test_study_selection.py tests/test_research_geometry.py
tests/test_native_nhd.py tests/domains/environment/seascape/test_gateways.py`, then the full,
quality, documentation, notebook and installed-wheel checks above. Native NHD archive network
flags, datum qualification and source-version conflicts must remain explicit. The portable
notebook also checks a packaged pending-study example; it does not certify regional inputs.

Flat-product publication control now lives outside the delivery parent at
`output.parent.parent/.marinecast-work/seascape/<destination-hash>`: stable lock,
transient staging and recovery journal. Do not recreate `.seascape-io` under Data.
Successful publication removes staged payloads/backups; default successful builds
already remove owned scratch. Supplied inputs and failed/explicit work roots are
not swept. See `docs/API.md` for the current storage contract.
