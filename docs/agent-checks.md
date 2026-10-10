# Conditional agent checks

All commands and inline paths are relative to the checkout root. Load only the section matching
the task. Behavior changes require focused tests followed by `python -m pytest -q`; apply all
matching conditional gates below. Do not rerun the full suite separately for each matching row.
Documentation/example edits require references, `git diff --check`, `python scripts/check_docs.py`
and `python -m pytest -q tests/test_documentation.py`; prose-only changes do not require the full
package suite. Executable-check changes also require the full suite and review-hardening checks.
No offline check proves acquisition, a regional release, platform acceptance or hosted CI success.

## Validation notebook

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
then the full package suite. `seascape --workspace /path/to/workspace build --only
seascape-geomorphometry --dry-run --check-inputs --json` inspects local prerequisites without writes,
hashes, downloads or producers. A ready report establishes only its stated inspection level;
missing/invalid/required-unverified checks fail. See [workflow limits](WORKFLOWS.md).

For demo/CLI behavior, run `python -m pytest -q tests/test_demo.py`, then the full package suite.
For CLI diagnostics, also run `python -m pytest -q tests/test_cli_diagnostics.py tests/test_products.py`
to verify failure codes, stderr/JSON separation, family help forwarding and unchanged API exceptions.
`--debug` is a global option before the command; it never relaxes validation.
`seascape --workspace /path/to/fresh-workspace demo` performs synthetic software acceptance; it
never establishes a regional release. Keep artifacts in its owned `.seascape/demo` subtree.
After building/installing a wheel, copy `scripts/check_demo.py` outside the checkout and run it
with a clean runtime-only interpreter and `--workspace /path/to/fresh-workspace`. No test or
notebook extras may supply dependencies in that environment. See [demo guide](demo.md).

For portable validation-notebook changes, run `python -m pytest -q tests/test_validation_notebook.py`
and the full package suite. Copy the notebook and `scripts/check_validation_notebook.py` outside the
checkout; run the helper with an installed-wheel interpreter plus notebook extra, `--notebook`,
`--output`, `--forbid-root` and optionally `--workspace`. Keep its input directory notebook-only
and output separate. See [notebook guide](../notebooks/README.md). Do not overwrite the committed
notebook with execution results or register a global kernel for acceptance.

For packaging/consumer acceptance changes, run `python -m pytest -q tests/test_consumer_acceptance.py`
then the full package suite. Install `.[build]` in the build environment and use `python -m build`
to build the wheel from an sdist. Inspect both with `scripts/check_distribution.py`, then run
`scripts/check_consumer_install.py --wheel /transferred/wheel.whl --source /explicit/checkout
--forbid-root /checkout/group --output /fresh/outside/directory`. This creates an isolated consumer
and runs runtime checks before declared test/notebook extras. Output is refused if it already exists.
Read [development guide](DEVELOPMENT.md) for the full commands and process-guard limitations.
Configured hosted jobs are not passed until their real run results exist.

## Documentation checks

For every documentation/example edit (including prose-only edits), run `python scripts/check_docs.py` and
`python -m pytest -q tests/test_documentation.py`; executable-check changes also require the full
suite and review-hardening checks. After building an sdist, use `scripts/check_quickstart.py --sdist
/transferred/source.tar.gz --source /explicit/checkout --forbid-root /checkout/group --output
/fresh/outside/directory` to execute the marked source-install/demo/plan commands. Installation
may download declared dependencies; runtime uses the existing Python consumer guard and cannot
acquire sources. See [development](DEVELOPMENT.md#documentation-and-first-result-acceptance).


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
there are no additional generated-code exclusions. Mypy checks the 12 interface modules listed
in `docs/environments/README.md`; skipped external imports remain documented there.
Run installed-wheel imports using `scripts/check_installed_package.py` from outside the checkout.
Capture the runtime/test/quality closure with `scripts/environment_snapshot.py --extra test
--extra quality --output /tmp/seascape-env`
and audit it with `pip-audit --disable-pip --no-deps --strict -r /tmp/seascape-env.txt`.
CI also runs Gitleaks over history and the working tree. Scope and platform limits are documented in
`docs/environments/README.md`; API/storage changes are documented in `docs/API.md`.

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
dependency. Build or refresh only when explicitly requested, after structural edits settle, from this checkout only:

```bash
graphify extract . --code-only --no-cluster
```

Do not rebuild merely for a question. Check intentional deletions before using `--force` to bypass
shrink protection. `.gitignore` and `.graphifyignore` apply; AST-only extraction does not index
prose semantically. Graphs/caches are disposable local-only files: never commit or publish them.
Any future sharing requires an explicit policy covering destination, revision, freshness and review.
Global skill defaults do not override repository scope or code-only extraction. Do not run
`graphify codex install` over maintained instructions or enable hooks/merge drivers implicitly.
