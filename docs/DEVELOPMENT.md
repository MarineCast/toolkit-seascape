# Development and validation

[Documentation index](README.md)

## Working in this repository

Read [AGENTS.md](../AGENTS.md), inspect `git status --short`, and preserve unrelated work. This is
an independent repository: run installation, tests and package builds here. Follow the
[architecture map](ARCHITECTURE.md) to put source-specific behavior with its owning family and
reusable behavior in toolkit helpers. Do not introduce application imports or sibling-path imports.

## Checks by change type

| Change | Appropriate checks |
| --- | --- |
| Documentation only | `python scripts/check_docs.py`; `mkdocs build --strict`; inspect diff; `git diff --check`; execute quickstart acceptance if examples change |
| Formatting only | `ruff format --check src tests scripts`, full offline suite and an AST comparison ignoring location metadata |
| Calculation or loader | Focused family tests, meaningful synthetic fixtures and applicable scientific contracts |
| CLI, configuration or package layout | Standalone-package tests, command help, build dry run and wheel installation |
| Publication or orchestration | Workflow/publication tests, dependency ordering and reuse/failure cases |
| Regional processing semantics | Materialized-product checks and candidate/canonical comparison with matching inputs |

From the checkout after installing `.[test]`:

```sh
python scripts/check_docs.py
python -m pytest -q
python -m pytest -q tests/test_standalone_package.py tests/test_workflow.py
seascape build --dry-run
git diff --check
```

## Documentation site

The site uses `mkdocs.yml`, Material for MkDocs, and Markdown under `docs/`. The
navigation starts with installation and a safe offline example, then links to the
generated historical field index, current method/source guides, and public API.
The historical catalog remains generated from checked-in configuration; do not
hand-edit its field block. `scripts/mkdocs_hooks.py` turns existing references from
`docs/` to repository source files into GitHub links for the hosted site. The
offline `check_docs.py` command still validates those local targets and headings.

```sh
python -m pip install -e '.[docs]'
mkdocs serve
mkdocs build --strict
python scripts/check_docs.py
```

The local server is at <http://127.0.0.1:8000/toolkit-seascape/>. CI builds strictly on pull
requests. After a push to `main`, `.github/workflows/docs.yml` uploads the
generated `site/` as a GitHub Pages artifact and deploys it. Repository Pages
settings must select **GitHub Actions** as the publishing source; an environment
or branch protection rule may also govern deployment. The generated site is ignored
by Git and no `gh-pages` branch is needed.

The [observed platform table](environments/README.md#tested-platforms) records actual CI evidence.
The [CI workflow](../.github/workflows/ci.yml) defines Python 3.14 jobs. A configured job
is not evidence it ran. The offline suite includes tests that skip without regional materialized
products; report skips separately from passed checks. Do not infer live provider availability,
map rendering, a full regional rebuild or application compatibility from unit tests.

Formatting uses the existing Ruff defaults and Python 3.14 target in `pyproject.toml`. Contributor
and CI format checks cover all Python under `src/`, `tests/` and `scripts/`, with no additional
generated-code exclusions:

```sh
ruff format src tests scripts
ruff format --check src tests scripts
```

Keep formatter changes separate from lint autofixes, import reordering, API/type changes and
scientific edits. For a broad formatting change, compare parsed ASTs before/after with location
metadata ignored, investigate any difference, and run the full suite. Source-byte changes alter
package code identity and can invalidate recorded resume state; retain those existing checks.

## Clean consumer acceptance

The `consumer-install` CI job targets Linux Python 3.14 (x86_64) and macOS Python 3.14
(arm64, `macos-15`). It asserts the observed interpreter/system/architecture and saves native
library versions. Runner labels follow the [GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners);
the saved environment, rather than the label alone, identifies what actually ran. The first
[hosted acceptance run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36322829881)
passed all three consumer cases on commit `6ddd5ca`; see [progress](roadmap/PROGRESS.md) for versions
and limits. Other revisions/platforms remain unverified until executed; local macOS evidence
does not establish Linux or hosted acceptance.

Use a build environment with the declared `build` extra. Python build's default command builds
an sdist and then a wheel from that sdist. Set `DIST_DIR` and `CONSUMER_DIR` to new paths outside
the checkout/group being forbidden; the absolute paths below are placeholders.

```sh
DIST_DIR="$(mktemp -d)"
CONSUMER_DIR="$(mktemp -d)/consumer"
python -m pip install '.[build]'
python -m build --outdir "$DIST_DIR"
python scripts/check_distribution.py --sdist "$DIST_DIR"/*.tar.gz \
  --wheel "$DIST_DIR"/*.whl --output "$DIST_DIR/distribution-report.json"
python scripts/check_consumer_install.py --wheel "$DIST_DIR"/*.whl \
  --source /absolute/path/to/toolkit-seascape --forbid-root /absolute/path/to/checkout-group \
  --output "$CONSUMER_DIR"
```

The controller copies only acceptance files from the explicit source location, creates a fresh
venv without inherited/user packages, clears source/workspace overrides and installs the wheel
normally with declared runtime dependencies. Before extras, it runs `pip check`, every installed
module with OrcaCast blocked, required packaged resources, CLI help/init/dry run and the synthetic
demo. No notebook file, pytest or Jupyter is present in that phase. Then it installs the same wheel's
declared test/notebook extras, runs copied product/review/demo/matrix tests and the copied-only notebook
with an interpreter-pinned temporary kernel. Production calculations/validation are reused.

Negative probes require an import-denied runtime dependency and a source import to fail, remove
and restore one known config only in the throwaway installation, and inject an outbound attempt
into the demo's pipeline call. The latter must leave a FAIL report. Import denial simulates an
absent runtime module; it is not a live-provider test. Existing source or consumer output is never
cleaned or overwritten. Demo artifacts stay in their owned `.seascape/demo` subtrees.

Dependency installation permits network access. The invoked Python runtime/test processes then
reject socket/DNS activity, child processes and checkout/group reads. The notebook kernel uses
its existing guard, allowing Jupyter loopback. Guard rejection is tested explicitly. This is Python
process evidence, not an OS firewall or protection against native-extension networking.

`report.json` records each exact argv/cwd, expected and actual exit, status, duration and log.
`runtime-environment.json` and `extras-environment.json` inventory their separate layers without
requiring pytest for a runtime snapshot. Failure preserves logs and a FAIL report; CI uploads these,
distribution checks/hashes, executed notebook and synthetic demo outputs on success or failure.
It does not upload the venv, acquire real sources or publish a package.

Focused regression command: `python -m pytest -q tests/test_consumer_acceptance.py`.

## Documentation and first-result acceptance

`python scripts/check_docs.py` checks local links and heading fragments, fenced CLI command/stage
names, the checked-in catalog's generated reference block and byte-identical packaged configuration
templates. External URL availability is deliberately outside this offline check. It compares the
[stage-input reference](stage-inputs.md) with the existing planner/preflight metadata from temporary
templates; it runs no producers and generates no authoritative product catalog.

After deliberately changing stage declarations, review `python scripts/check_docs.py --write-stage-reference`
and its diff. Catalog/eligibility/product-document generation still requires materialized products.

Using the distributions built above, execute all three marked first-result blocks verbatim:

```sh
QUICKSTART_DIR="$(mktemp -d)/quickstart"
python scripts/check_quickstart.py --sdist "$DIST_DIR"/*.tar.gz \
  --source "$PWD" --forbid-root "$(dirname "$PWD")" --output "$QUICKSTART_DIR"
```

This transfers an sdist to a disposable directory, runs the README's isolated developer source
install, then runs its demo and the workflow's init/stages/dry-run outside both source trees. The
CLI runner rejects Python checkout reads, socket activity and child processes, and verifies a
normal installed package with no pytest/Jupyter. Installation may contact dependency indexes;
runtime uses the existing consumer guard, with the same native-network limitation described
above. Reports retain the exact blocks, traced shell commands and logs. Existing output is refused
and failure preserves evidence.
CI executes this on each consumer platform and uploads its report/log/demo artifacts.

`python -m pytest -q tests/test_documentation.py` tests link/anchor/template/command drift and executes
the API's freeze-and-read example through the real publisher/resolver using a small publication
fixture. That fixture is software boundary evidence, not a full regional scientific release audit.

Before proposing a release, review the full offline/quality/consumer/notebook results, source rights,
real-data limitations and progress record. Preserve retained releases; remote publishing and the
bounded real-data pilot require their own authorization. Release-candidate review remains SS-11.

## Scientific changes

Preserve row identity, units, CRS, vertical datum, resolution, source coverage and missingness.
Test boundary cases such as disconnected graphs, duplicate keys, absent source coverage and
non-finite values. Document intentional formula or schema changes and their downstream impact.
The [contracts](CONTRACTS.md) and family source guides are the detailed reference.

To compare already-built candidate and canonical products:

```sh
python -m seascape.maintenance.validate_seascape_rebuild --canonical-root /path/to/seascape-workspace --candidate-root /path/to/seascape-workspace/.seascape/candidate --output /path/to/comparison.json
```

The comparator reads matching catalog paths and checks schemas, identity, missingness, numeric
values and categorical distributions. It does not build either side. Review its report together
with provenance and configuration differences before concluding that two regional builds agree.

## Generated metadata and documentation

The workflow runs catalog, static eligibility and documentation stages after product construction. Maintainers
can also inspect their interfaces directly:

```sh
python -m seascape.maintenance.update_seascape_feature_catalog --help
python -m seascape.governance.feature_eligibility --help
python -m seascape.maintenance.update_seascape_docs --help
```

Catalog generation requires materialized products. Do not regenerate it against an incomplete
workspace and describe the result as a validated release. The product index contains a generated
block; update that block through the generator rather than editing field rows by hand.

After changing editable configuration templates, copy `config/common.yaml` and `config/data/*.yaml`
into `src/seascape/resources/config/`. Generated catalog, eligibility, and product-index artifacts
are intentionally absent from packaged init resources. The standalone-package tests check the
editable copies. Repository guides in `docs/` are not copied by `seascape init`.

## Adding a family or product

1. Define the source rights, output grain, spatial support, units, missingness and provenance.
2. Implement acquisition/validation and builders in the owning family with offline fixtures.
3. Register applicable dataset identities and dependencies in `core/data/catalog.py`.
4. Add workflow stages and declared outputs/manifests to `workflow.py`.
5. Update CLI family selectors when exposing download or inspection commands.
6. Update the catalog generator's product definitions, release requirements, configuration and
   packaged templates as needed; keep identifiers and source module paths consistent.
7. Update the product/source guides and run checks for the affected behavior.

Record what was actually executed, what required missing data, and what remains unverified.
