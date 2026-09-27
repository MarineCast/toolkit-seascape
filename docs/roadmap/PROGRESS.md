# Seascape roadmap progress

Implemented scope: SS-00 through SS-08; SS-03 hosted acceptance passed.
[Specification](SEASCAPE_CODEX_ROADMAP.md).
SS-00 base/current commit: `f2400c13d509ad753d9168ed4e7a07d1ffcfc5a4` (no reset).
Initial state: clean `main`; remote `https://github.com/MarineCast/toolkit-seascape.git`.
Working branch: `feature/seascape-repository-organization-updates`. Feature-branch pushes authorized
on September 27; no merge, tag or package publication. Earlier entries retain their dated evidence.
Current next action: SS-09. Stop before documentation consolidation in this SS-08 execution.

| Task | Status | Evidence / next gap |
| --- | --- | --- |
| SS-00 | passed | Baseline classified; notebook PASS (12 code cells, no errors) |
| SS-01 | passed | 21 regressions, runtime-only guarded wheel demo; full suite 241 passed / 3 skipped |
| SS-02 | passed | Portable copied notebook; 7 regressions; full suite 248 passed / 3 skipped |
| SS-03 | passed | All three hosted consumer cases passed; run 36322829881, tested commit 6ddd5ca |
| SS-04 | passed | Read-only input preflight; 34 new regressions; guarded runtime-only wheel acceptance |
| SS-05 | passed | CLI-only guidance/debug, side-effect contracts, 29 regressions; runtime-only wheel acceptance |
| SS-06 | passed | Ruff baseline; 209 ASTs unchanged; full suite 322 passed / 3 skipped |
| SS-07 | passed | Local expanded lint/type gates; fresh constrained/range solves and audits; broad ignored-cache secret scan failed |
| SS-08 | passed | Analytic/matrix/publication evidence; local and hosted 352 passed / 3 skipped; run 36324502530, 9/9 jobs |
| SS-09–SS-11 | not_run | SS-09 is next; no documentation consolidation or real-data pilot performed |

## SS-00 baseline

Current source matches the reviewed baseline. Entry points (source/tests are authoritative):

| Operation | Symbols | Existing tests |
| --- | --- | --- |
| Init / CLI | `cli.initialize_workspace`, `cli.main` | `test_standalone_package.py` |
| Bathymetry | `bathymetry.load_bathymetry_config`, `run_pipeline`, `build_bathymetry_parquet` | `test_bathymetry_contracts.py`, validation notebook |
| Planning | `workflow.selected_stages`, `run_domain_layer_build` | `test_workflow.py` |
| Publication | `publication.TransactionalSeascapePublisher`, `publication.SeascapeReleasePublisher` | `test_publication.py`, `test_release.py`, `test_review_regressions.py` |
| Resolution | `products.list_products`, `list_resolutions`, `resolve_product` | `test_products.py`, `test_review_regressions.py` |
| Matrix | `metric_matrix.build_metric_matrix` | `test_metric_matrix.py` |

Isolated development venv: `/tmp/seascape-roadmap-dev`, no inherited site packages.
Python 3.14.6, macOS 26.6.2 ARM64; GDAL 3.12.4, PROJ 9.8.1, GEOS 3.13.1.
Exact commands/exit codes and dependency/native versions: `/tmp/seascape-roadmap-evidence/baseline-commands.json`
and `baseline-environment.{json,txt}`. Logs are local machine evidence, not committed artifacts.

- `python -m pip install -e '.[test,quality,notebook]'`: initial sandbox run exit 1 (PyPI DNS,
  not a demonstrated dependency defect); network-enabled retry exit 0. Install logs under `/tmp`.
- `python -m pip check`: exit 0.
- `python -m pytest -q`: exit 0, **220 passed / 0 failed / 3 skipped**. Two feature-catalog tests
  and one network-consumer test require absent regional artifacts. Ten upstream/deprecation warnings.
- `ruff check src tests scripts`, `python -m mypy`, current four-module `ruff format --check`: exit 0 each.
- `seascape --help`: exit 0.
- `seascape --workspace /tmp/seascape-roadmap-evidence/baseline-workspace init` and
  `seascape --workspace /tmp/seascape-roadmap-evidence/baseline-workspace build --dry-run`: exit 0 each;
  fresh workspace, 26 stages, no acquisition/publication.
- `python scripts/environment_snapshot.py --output /tmp/seascape-roadmap-evidence/baseline-environment`: exit 0.
- Notebook: initial run exit 1 (sandbox loopback bind denied); local-socket retry exit 1
  (venv CLI missing from PATH); corrected PATH/local-socket retry exit 0, 12 executed code cells, PASS marker and zero errors.
  Output `seascape-toolkit-validation.ipynb` under the evidence directory. Committed notebook untouched.
- GitHub connector `fetch_commit_workflow_runs` for this exact commit returned an empty list;
  hosted CI has no available execution evidence. Historical remediation counts are dated evidence.

No production behavior changed during SS-00. No unrelated edits existed to preserve. Live acquisition,
regional rebuild, consumer integration and remote release checks remain outside scope.

## SS-01 portable demo — passed

Implementation and local acceptance complete. Base: `0d6963b284e51184292cbf591abeeac977cca445`;
this record's containing implementation commit is the SS-01 handoff. Final Git identity is also
saved in `/tmp/seascape-roadmap-evidence/final-git-state.json` and reported in the task handoff.

- Added `demo.run_demo(workspace, *, overwrite=False)` / `DemoResult` and `seascape demo`.
  The 48×48 notebook recipe feeds the existing `bathymetry.run_pipeline` with download/map off.
  Packaged configuration, transactional family publication, checksums and atomic writers are reused.
- All paths belong to `.seascape/demo`; ordinary configs/canonical products/releases are preserved.
  Ownership/symlink/path-type/transaction checks and a POSIX lock guard reruns. Only known files
  are replaced; previous PASS is invalidated before computation, including metadata failures.
- Reserved provider `SYNTHETIC` records fixture licensing/warnings and requires acquisition and
  interactive maps disabled. Existing real-provider metadata defaults are regression-tested.
  No scientific formulas, thresholds, default regional configs, schemas or release gates changed.
- 14 executed checks cover actual nonempty output, exact H3 r8 support, 2016 eligible pixels,
  5 m constant depth, observed zero statistics/fractions, null nodata/outside/sea-level support,
  finite values, sign/CRS, provenance, family/source/upstream checksums and returned paths.
- **21 focused tests passed / 0 failed / 0 skipped**; full suite **241 passed / 0 failed / 3 skipped**
  (same absent regional artifacts as SS-00). Full run: 31 dependency/deprecation warnings.
- Runtime-only wheel acceptance: 14/14 checks, 0 network attempts, pytest/Jupyter absent and their
  imports forbidden. Installed package imported from consumer `site-packages`, arbitrary cwd `/tmp`,
  source overrides cleared. Audit guard verifies outbound rejection and demo filesystem confinement;
  two Matplotlib font-discovery child attempts were denied, with successful bundled-font fallback.
  This is Python process evidence, not an OS-level firewall or a sandbox for native extensions.
- Both static PNGs were opened and visually inspected: extent/orientation, synthetic titles,
  meter/sign labels and grey unavailable cells. Figures generated without basemap/display server.
- Final existing notebook: 12 executed code cells, PASS marker, zero errors. Notebook/config/resource
  diffs remain empty. Portable thin-client conversion is SS-02 and was not started.

Commands ran from the owning checkout with `/tmp/seascape-roadmap-dev/bin` on PATH unless indicated.
Machine logs and exact baseline/final static commands: `/tmp/seascape-roadmap-evidence/`.

| Command / evidence | Exit / result |
| --- | --- |
| `python -m pytest -q tests/test_demo.py` (`demo-tests-final.log`) | 0; 21 passed |
| `python -m pytest -q` (`final-tests.log`) | 0; 241 passed, 3 regional skips |
| `ruff check src tests scripts`; `python -m mypy` | 0 each; typing retains existing four-module scope |
| Current four-module format gate plus `src/seascape/demo.py`, `src/seascape/cli.py`, `tests/test_demo.py`, `scripts/check_demo.py` | 0; 8 formatted files; full command in `final-commands.json` |
| `python -m pip check` (development and runtime consumer) | 0 each |
| `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/seascape-roadmap-evidence/wheels` | First failed (exit code not captured): setuptools absent in venv; declared build requirements installed; final exit 0 |
| `python -m pip install 'setuptools>=80' wheel` (development venv) | 0; declared build prerequisites |
| Consumer `python -m pip install /tmp/seascape-roadmap-evidence/wheels/toolkit_seascape-0.1.0-py3-none-any.whl` | First exit 1: wheel not yet built; final fresh runtime/dependency install exit 0, no inherited packages |
| Consumer `python -m pip install --no-deps --force-reinstall /tmp/seascape-roadmap-evidence/wheels/toolkit_seascape-0.1.0-py3-none-any.whl` | 0; final wheel refresh after runtime dependencies were already installed normally |
| From `/tmp`: `env -u PYTHONPATH -u SEASCAPE_WORKSPACE -u SEASCAPE_CANDIDATE_ROOT /tmp/seascape-roadmap-consumer/bin/python /tmp/seascape-roadmap-evidence/check_demo.py --workspace /private/tmp/seascape-roadmap-evidence/consumer-demo-confined2` | 0; 14/14, confinement and outbound guard; `consumer-demo-confined2.log` |
| Copied `check_installed_package.py`, consumer Python from `/tmp`, PYTHONPATH cleared | 0; 161 modules imported with OrcaCast blocked; `consumer-imports.log` |
| Consumer `seascape --help` | 0; `consumer-help.log` |
| Consumer `seascape --workspace /private/tmp/seascape-roadmap-evidence/consumer-demo-confined2 demo` | 1 expected; existing output refused, PASS report retained |
| `jupyter nbconvert --to notebook --execute notebooks/validation/01_TOOLKIT_VALIDATION.ipynb --ExecutePreprocessor.timeout=120 --output seascape-toolkit-validation-final.ipynb --output-dir /tmp/seascape-roadmap-evidence` | 0 with local kernel sockets and development venv PATH; `final-notebook.log` |
| `pip-audit --disable-pip --no-deps --strict -r /tmp/seascape-roadmap-evidence/baseline-environment.txt` | 0; no known vulnerabilities; `dependency-audit.log` |
| `gitleaks git . --redact --no-banner --log-opts="--all"` | 0; no leaks in history |
| `gitleaks dir . --redact --no-banner` | 1; pre-existing ignored `graphify-out/cache/stat-index.json`, generic-api-key false positive on a 64-character file hash under `hashes["docs/api.md"]` |
| `gitleaks dir /tmp/seascape-roadmap-evidence/review-files --redact --no-banner` | 0; copied tracked + nonignored files; cache preserved, no ignore added |
| Local Markdown references in 6 changed guides; `git diff --check` | 0; links exist and diff clean |
| `git diff --exit-code -- notebooks config src/seascape/resources` | 0; no notebook/template edits |

Earlier consumer guard trials failed on metadata's `platform.platform()` subprocess and font
probing (RuntimeError did not permit Matplotlib's expected fallback), then descriptor-relative
publisher cleanup was incorrectly interpreted relative to cwd. Final code removes metadata's
subprocess, records RUNNING before metadata, denies children with PermissionError, and tracks
file-descriptor bases in the acceptance helper. Final guarded execution passed; failures were not
counted as passes. Wheel/environment evidence: `wheel-build-final.log`, `consumer-environment.json`,
`consumer-demo-confined2/.seascape/demo/report.json` and its figures beneath the evidence directory.

Files: `src/seascape/demo.py`, `src/seascape/cli.py`, bathymetry `pipeline.py`, `tests/test_demo.py`,
`scripts/check_demo.py`, `AGENTS.md`, `README.md`, `docs/{API,README,demo}.md`, this progress record.
No new runtime dependencies. No unrelated initial edits existed; existing configuration, retained
products, sibling repositories and local graph cache were preserved. No remote changes performed.

Known limits: local macOS ARM64 Python 3.14.6 evidence only; no available hosted CI result for baseline,
no Linux/other-interpreter acceptance, no live providers/regional rebuild/downstream integration,
no human newcomer trial. Process-global environment selection is not thread-safe; separate-process
writers are guarded. All these external checks remain unrun, not software acceptance blockers.
The SS-01 handoff recommended SS-02; its subsequent implementation is recorded below.

## SS-02 portable notebook — passed

Base: `4017612214878ce181bde69c909b3c718142d74a`; clean initial working tree on the existing
`feature/seascape-first-run-demo` branch. This record's containing commit is the SS-02 handoff;
exact final Git identity is in `/tmp/seascape-ss02-evidence/final-git-state.json`.
SS-01 prerequisites were reverified against current `run_demo`, CLI delegation, packaged resources,
production bathymetry and tests. Its unchanged runtime wheel was reused, not rebuilt or relabeled:
SHA-256 `503b38e2972ff61be2a2a307e77dba319df7fbdffdb33582e683372fab8b1682`.
No baseline reset, live exploration or runtime-only acceptance redo.

- Replaced checkout discovery and fixture/orchestration cells with installed `run_demo`.
  Twelve readable code cells inspect environment, selected workspace, generated configuration,
  input raster/support, output grain/schema/control values, the API's two figures, actual checks
  and synthetic provenance. Default temporary products persist after kernel shutdown; optional
  `SEASCAPE_DEMO_WORKSPACE` selects a workspace. Explicit overwrite remains false by default.
- Added truthful presentation gates for empty/failed checks, report disagreement and environment
  restoration. Corrected Data Explorer claims: its actual helper performs live San Juan bathymetry
  exploration with an exploratory water mask, not completed-release inspection/certification.
- Added copied-notebook acceptance with a temporary interpreter-pinned kernel, no global kernel
  registration, checkout-read rejection, outbound Python socket/DNS rejection and provider denial.
  Guard self-test rejects outbound access; loopback remains allowed. This is process evidence,
  not an OS firewall or native-extension network sandbox.
- Both default and chosen-workspace guarded runs passed **14 production / 15 notebook checks**,
  displayed **2 PNGs**, retained synthetic reports after kernel shutdown, restored all four inspected
  environment variables (including sentinel overrides), and recorded **0 acquisition / 0 outbound
  attempts**. The consumer has notebook extras but still no pytest; imports resolve in its isolated
  wheel `site-packages`. Each input directory contains only its copied notebook.
- Plain `nbconvert` also passed: **12 executed code cells, 0 errors, 2 PNGs**, actual PASS marker,
  explicit interpreter/import paths. Source is unexecuted, contains no machine paths/embedded
  outputs, and stayed byte-identical through execution. Final source SHA-256:
  `f618fc5df6bc2d68eeda842e6e22f135da80827dde85b1adac1382a1b3c545b3`.

Exact command lines, cwd, exit codes and logs: `/tmp/seascape-ss02-evidence/commands.json`.
Development interpreter `/tmp/seascape-roadmap-dev/bin/python`; consumer
`/tmp/seascape-roadmap-consumer/bin/python`. Python 3.14.6, macOS 26.6.2 ARM64;
GDAL 3.12.4 / PROJ 9.8.1 / GEOS 3.13.1. Environment inventories:
`development-environment.{json,txt}`, `consumer-environment.json` under that evidence directory.

| Command / evidence | Exit / result |
| --- | --- |
| Consumer `python -m pip install 'toolkit-seascape[notebook] @ file:///private/tmp/seascape-roadmap-evidence/wheels/toolkit_seascape-0.1.0-py3-none-any.whl'` | 0; declared optional extra, no runtime install redo |
| Development `python -m pytest -q tests/test_validation_notebook.py` | 0; 7 passed, 0 failed/skipped; `focused-tests-final.log` |
| Development `python -m pytest -q` | 0; 248 passed, 0 failed, 3 skipped; `full-tests-final.log`; 31 dependency/deprecation warnings |
| Consumer copied `check_validation_notebook.py`, chosen workspace + four sentinel overrides | 0; `selected-verified-executed.{ipynb,json}`, `selected-verified-notebook.log` |
| Consumer copied helper, default temporary workspace + four environment variables unset | 0; `default-verified-executed.{ipynb,json}`, `default-verified-notebook.log` |
| Consumer `python -m jupyter nbconvert --to notebook --execute 01_TOOLKIT_VALIDATION.ipynb --ExecutePreprocessor.timeout=120 --ExecutePreprocessor.kernel_name=seascape-ss02 --output plain-verified-executed.ipynb --output-dir /tmp/seascape-ss02-evidence` | 0; cwd `plain-verified-copy`, explicit local kernel/PATH/JUPYTER_PATH; `plain-verified-notebook.log` |
| `ruff check src tests scripts`; current four-module format gate + two new Python files; `python -m mypy` | 0 each; existing typing scope preserved; `ruff-check.log`, `ruff-format.log`, `mypy.log` |
| Consumer `python -m pip check` | 0; `consumer-pip-check.log` |
| Existing environment snapshot helper: consumer / development | 1 / 0; helper requires absent consumer pytest; consumer versions captured separately without installing pytest |
| Evidence source/reference inspection; `git diff --check`; production/config/dependency/CI/live-notebook diff guard | 0 each; 22 local links, unchanged copied bytes and isolated execution verified |

The three skips are two feature-catalog tests and one network-consumer test requiring absent
materialized regional artifacts. Earlier notebook executions passed before final review exposed
Pandas truncation of the import path. Plain-text paths were added and all final executions rerun.
Two evidence-inspection trials failed on raw JSON stream-list handling and that path truncation;
the normalized final inspection passed. These inspection failures were not counted as passes.
Jupyter's local TCP transport warning is retained in logs; no external connections were authorized.

Files: `AGENTS.md`, `README.md`, `docs/demo.md`, `notebooks/README.md`,
`notebooks/validation/01_TOOLKIT_VALIDATION.ipynb`, `scripts/check_validation_notebook.py`,
`tests/test_validation_notebook.py`, this progress record. No production API, formula, units/sign,
missingness, schema, dependency declaration, default configuration or scientific/release gate change.
No unrelated initial edits existed. Production source, canonical products/retained releases,
other notebooks, graph cache and sibling repositories were preserved; all demo artifacts remain
in demo-owned subtrees. Remote changes: **none**.

No implementation/acceptance blocker remains. Linux, other interpreters, hosted consumer CI,
live providers, regional scientific validity, downstream integration and a human newcomer trial
remain **not_run**. Security/dependency audits already recorded in SS-01 were not rerun for this
notebook-only task. Next: **SS-03 — clean consumer-install acceptance**. Stop before SS-03.

## SS-03 clean consumer-install acceptance — blocked on hosted execution

Implementation complete; local acceptance passed. Full task acceptance remains blocked by the
unexecuted hosted matrix. Base: `c1cab8b44990f9e86d4a4bac26d88bddab0eb30a`, clean tree on
`feature/seascape-first-run-demo`. This record's containing commit is the implementation handoff;
final Git identity is in `/tmp/seascape-ss03-evidence/final-git-state.json`.
Reverified SS-01/SS-02 APIs, resource loading, notebook source/hash and existing wheel/CI helpers.
The inherited-site-package CI wheel check was still present; no prior task or baseline was reset.

- Replaced that check with Linux Python 3.11/3.14 x86_64 and macOS Python 3.14 arm64 (`macos-14`)
  consumer jobs. They build an isolated sdist, build the wheel from that sdist, inspect critical
  files/all packaged resources, then install normally into a fresh venv with no inherited/user
  site packages. Added only the declared optional build tools; runtime requirements unchanged.
- Runtime layer runs dependency checks, 161 installed-module imports with OrcaCast blocked,
  packaged-resource checks, the actual installed console script's help/init/26-stage dry run,
  and the existing guarded demo before pytest/Jupyter or the notebook file is present.
- Four expected nonzero probes passed: import-denied Rasterio (simulated dependency absence),
  attempted source import rejected, actual installed config removal/restoration rejected by the
  resource checker, and injected outbound demo activity rejected with a retained **FAIL** report.
  Source config and ordinary/canonical/release directories are not used for these probes.
- Only after runtime PASS, installed declared test/notebook extras; **55 copied tests passed**
  (0 failed/skipped, 25 warnings) and the notebook-only copy passed **14 production / 15 notebook
  checks**, 2 figures, no acquisition/outbound attempts, restored environment and retained artifacts.
  Its source hash remains `f618fc5df6bc2d68eeda842e6e22f135da80827dde85b1adac1382a1b3c545b3`.
- Python process guards self-test denied network/checkout access and deny child escapes. Jupyter
  uses the existing loopback-aware kernel guard. This is not an OS/native-extension firewall.
  CI asserts observed interpreter/system/architecture and uploads concise evidence on failure
  or success, including hidden demo files, without uploading the consumer venv.
  Existing notebook/security jobs and quality checks are retained; format targets add only this patch.

Local environment: macOS **26.6.2**, Darwin **25.6.0**, arm64, Python **3.14.6**;
GDAL **3.12.4**, PROJ **9.8.1**, GEOS **3.13.1**. Separate runtime/extras inventories and exact
consumer argv/cwd/expected/actual exits: `acceptance-verified/{runtime-environment.json,
extras-environment.json,report.json}` under `/tmp/seascape-ss03-evidence/`.
Host commands/exits: `commands.json`; archive hashes/resource evidence: `distribution-report.json`.

| Executed command / evidence | Exit / result |
| --- | --- |
| Development `python -m pip install 'build>=1.2'` | 0; newly declared build tool; existing setuptools/wheel already present |
| `python -m build --outdir /tmp/seascape-ss03-evidence/distributions` | 0; isolated sdist then wheel from sdist; `distribution-build.log` |
| `python scripts/check_distribution.py --sdist …tar.gz --wheel …whl --output …/distribution-report.json` | 0; 9 required files and all 5 packaged resources preserved |
| `python -m pytest -q tests/test_consumer_acceptance.py` | 0; **11 passed / 0 failed / 0 skipped**; `focused-tests-verified.log` |
| `python -m pytest -q` | 0; **259 passed / 0 failed / 3 skipped**; 31 warnings; `full-tests-verified.log` |
| `python scripts/check_consumer_install.py --wheel …whl --source <checkout> --forbid-root <MarineCast> --output …/acceptance-verified` | 0; all 16 steps met expected exits; `consumer-run-verified.log`, consumer `report.json` |
| `ruff check src tests scripts`; existing four-module + seven changed Python-file format gate; `python -m mypy` | 0 each; existing four-module typing scope retained |
| Final YAML parse / all shell steps `bash -n`, guide reference checks, security/quality preservation, copied-file/hash checks, `git diff --check` | 0; evidence `review-check.json`, `source-reference-ci-check.json` |

The same two feature-catalog tests and one network-consumer test skip for absent materialized
regional artifacts. Earlier consumer runs exited **1**: first the helper incorrectly used
`python -m seascape.cli` (no module entry point), then its outbound probe patched an unbound
pipeline alias. Init-file and expected-denial assertions caught both. Corrected console dispatch
and bound-call injection have regressions; fresh final acceptance passed. Earlier failures remain
in `acceptance/` and `acceptance-final/`; they were not relabeled or counted as complete passes.

Files: `.github/workflows/ci.yml`, `AGENTS.md`, `pyproject.toml`, `docs/{DEVELOPMENT,demo}.md`,
`notebooks/README.md`, `scripts/{check_installed_package,check_demo,check_distribution,
check_consumer_install,check_consumer_failures,consumer_guard}.py`,
`tests/test_consumer_acceptance.py`, this progress record. Scientific/public API behavior changed:
**no**; formulas, missingness, schemas, release gates, production source, configurations, notebook
source, canonical products/retained releases and siblings preserved. No unrelated initial edits.
No live acquisition, remote mutation, release publication or history rewrite.

Hosted Linux 3.11/3.14 and macOS-14 3.14 arm64 jobs: **not_run**. No local Linux/container runtime
or Python 3.11 was available; new hosted jobs cannot execute without an authorized remote update.
Local macOS-26 evidence does not establish the hosted macOS-14 job. Security/dependency audits
were not rerun; their existing CI gates remain unchanged. Regional/live/downstream/human checks
remain outside scope. Next: **SS-04 — read-only prerequisite checks**, with SS-03 hosted acceptance
still pending before integration. Stop before SS-04. Remote changes: **none**.


## SS-04 read-only prerequisite checks — passed

Base: `368ee1b2400415a298dd742f4d6cad3fe4990af8`; the containing implementation commit is this
handoff (exact final identity also in `/tmp/seascape-ss04-evidence/final-git-state.json`).
Clean initial tree; retained `feature/seascape-first-run-demo`. SS-00 prerequisites reverified
against current CLI, stage registry, family loaders, candidate rebasing and scientific contracts.
SS-03 implementation is present; its hosted acceptance remains blocked, not relabeled passed.

- Added `build --dry-run --check-inputs [--json]`; flags require `--dry-run`. Plain dry-run stays
  unchanged. JSON-only planning explicitly reports inspection `not_run`; checked failures emit
  parseable JSON and exit 1. Report schema 1 includes workspace/config/candidate, stage expansion,
  configured/default destinations, publication intent, checks, required/optional status and actions.
- Execution and preflight share `plan_domain_layer_build` and candidate configuration rendering.
  Existing family loaders inspect a context-local copy in memory; common/workspace overrides are
  restored. No second stage registry, data hashes, acquisition, builder, cleanup or candidate writes.
  Exact upstream output paths are `generated_by_plan`; absent external inputs remain distinct.
- Existing CRS/unit/sign/H3/scale validation is reused. Native raster header checks were factored
  out of the slope function and reused without reading pixels; formulas, thresholds, masks,
  defaults, schemas and release validation remain unchanged. Header inspection accepts local TIFF
  signatures/GTiff only, disables GDAL auxiliary writes and rejects disguised remote VRT sources.
- Readability is not schema/coverage validation. Vector/Parquet headers, source values, datum,
  checksum/reuse identity, directory/archive usability and release approval remain unverified.
  Required skip reuse, kelp annual-layer usability and reef partial-inventory usability fail as
  `unverified`; optional limits cannot turn them into PASS. All 26 packaged stages report their
  selected prerequisites without execution. Configured fluvial barrier dependencies are included.
- **43 focused passed / 0 failed / 0 skipped** (34 new plus 9 existing workflow tests); final full
  suite **293 passed / 0 failed / 3 skipped**, 65 dependency/deprecation warnings. Same two
  feature-catalog and one network-consumer tests skip for absent materialized regional artifacts.
- Final wheel built from its sdist, required resources compared, then force-reinstalled into the
  fresh runtime-only consumer (initial normal wheel install resolved all declared dependencies;
  no inherited site packages). Guarded imports: 162 modules, OrcaCast/source access blocked.
  Ready/missing cases passed with pytest/Jupyter absent and imports blocked, Python outbound/child
  guards active, zero Python write attempts, identical workspace bytes and environment after
  each call. Installed console help/negative JSON case also ran. This is Python guard evidence,
  not an OS/native firewall. Fixtures explicitly label synthetic path/header acceptance only.
- Validation notebook/demo/configuration resources are unchanged; this additive planning command
  needs no thin-client notebook change. Their existing production regressions ran in the full suite;
  copied-notebook/headless/SS-03 matrix acceptance was not redone. No real data or release created.

Commands below ran in the owning checkout, with `/tmp/seascape-roadmap-dev/bin` as the development
interpreter/tool prefix. Evidence root `E=/tmp/seascape-ss04-evidence`; `C=$E/consumer/bin/python`.
These prefixes abbreviate absolute paths only. Final static argv/exit records are in
`static-commands.json`; installed-console argv/cwd/expected/actual exits in `consumer-commands-final.json`.

| Command | Exit / evidence |
| --- | --- |
| `python -m pytest -q tests/test_preflight.py tests/test_workflow.py` | 0; `focused-tests-final.log`, 43 passed |
| `python -m pytest -q` | 0; `full-tests-final.log`, 293 passed / 3 skipped |
| `ruff check src tests scripts` | 0 |
| `python -m mypy` | 0; existing 4-module scope |
| `ruff format --check src/seascape/products.py src/seascape/core/geo/crs.py src/seascape/core/artifacts/confinement.py src/seascape/seafloor_physiography/depth.py src/seascape/preflight.py src/seascape/cli.py src/seascape/core/config/data.py tests/test_preflight.py` | 0; 8 files |
| `python scripts/environment_snapshot.py --output /tmp/seascape-ss04-evidence/environment` | 0; `environment.{json,txt}` |
| `pip-audit --disable-pip --no-deps --strict -r /tmp/seascape-ss04-evidence/environment.txt` | 0; no known vulnerabilities; `dependency-audit.log` |
| `gitleaks git . --redact --no-banner --log-opts=--all` | 0; 13 base commits; `gitleaks-history.log` |
| `gitleaks dir . --redact --no-banner` | **1**; ignored local cache finding, below |
| `gitleaks dir . --redact --no-banner --report-format json --report-path /tmp/seascape-ss04-evidence/gitleaks-tree-report.json` | **1**; redacted diagnostic |
| `gitleaks dir /tmp/seascape-ss04-evidence/tracked-scan --redact --no-banner` | 0; current tracked source plus the two new task files, copied read-only; `gitleaks-tracked.log` |
| `python -m build --no-isolation --outdir /tmp/seascape-ss04-evidence/distributions-final` | 0; sdist then wheel from sdist using installed declared build tools; `build-final.log` |
| `python scripts/check_distribution.py --wheel /tmp/seascape-ss04-evidence/distributions-final/toolkit_seascape-0.1.0-py3-none-any.whl --sdist /tmp/seascape-ss04-evidence/distributions-final/toolkit_seascape-0.1.0.tar.gz --output /tmp/seascape-ss04-evidence/distribution-final.json` | 0; 9 required files, 5 resources |
| `python -m venv /tmp/seascape-ss04-evidence/consumer` then `$C -m pip install /tmp/seascape-ss04-evidence/distributions/toolkit_seascape-0.1.0-py3-none-any.whl` | 0; fresh consumer, `install.log` |
| `$C -m pip install --force-reinstall --no-deps /tmp/seascape-ss04-evidence/distributions-final/toolkit_seascape-0.1.0-py3-none-any.whl` | 0; final wheel, `install-final.log` |
| `$C -m pip check` | 0; `pip-check-final.log` |
| `$C $E/consumer_guard.py --forbid-root /Users/tylerstevenson/Documents/Code_Repos/MarineCast --script $E/check_installed_package.py -- --snapshot $E/consumer-environment-final.json` | 0; `imports-final.log`, 162 imports |
| `$C $E/consumer_guard.py --forbid-root /Users/tylerstevenson/Documents/Code_Repos/MarineCast --script $E/preflight_acceptance_final.py` | 0; `consumer-preflight-final.log`, ready/missing reports |
| `$C $E/consumer_guard.py --forbid-root /Users/tylerstevenson/Documents/Code_Repos/MarineCast --script $E/consumer/bin/seascape -- --workspace $E/workspace-final build --only seascape-geomorphometry --dry-run --check-inputs --json` | 1 **expected**; missing raster, parseable JSON, `console-missing.log` |
| `$C $E/consumer_guard.py --forbid-root /Users/tylerstevenson/Documents/Code_Repos/MarineCast --script $E/consumer/bin/seascape -- build --help` | 0; both flags exposed, `console-help.log` |
| `git diff --check` | 0 |

Consumer commands clear `PYTHONPATH`/`PYTHONHOME` and set `PYTHONDONTWRITEBYTECODE=1`; scripts
are copied outside the checkout. Python 3.14.6, macOS 26.6.2 arm64; GDAL 3.12.4, PROJ 9.8.1,
GEOS 3.13.1. Final wheel SHA-256 `f68ef744a9adea081280205cd4393ec4cd411a3390889b6e9ce688a99cc96867`;
sdist `0f32cbf1ecc871acb81747eeddf40731b07f32293b647c6e5db3d0a36fa802f8`.
An earlier focused run exited 1 (one assertion counted the newly added destination-access check
as a source input: 41 passed / 1 failed); corrected assertion scopes source inputs. Initial archive
helper invocation omitted required `--output` (exit 2); corrected inspection passed. Earlier
34/42-test runs and initial wheel acceptance passed, but final counts/artifact above supersede them.

Broad directory secret scan is **failed**, not passed: one `generic-api-key` finding at ignored
`graphify-out/cache/stat-index.json:1`, a 64-hex documentation hash under
`docs/API.md -> hashes -> docs/api.md`. This pre-existing developer cache is unmodified. The
tracked-source scan passed; no security gate or ignore/allowlist was weakened. Its redacted report
is local evidence, not a published artifact. Hosted Linux/macOS SS-03 checks remain **not_run**
because remote updates are not authorized. Regional/live/downstream/human acceptance is not_run.

Changed files: `AGENTS.md`, `docs/{API,WORKFLOWS}.md`, `src/seascape/{cli,workflow,preflight}.py`,
`src/seascape/core/config/data.py`, `src/seascape/seafloor_physiography/geomorphometry/build.py`,
`tests/test_preflight.py`, this progress record. Scientific behavior changed: **no**. Additive CLI
planning/report behavior; existing producer/consumer signatures and numerical behavior preserved.
No unrelated tracked edits existed; configurations, canonical products, retained releases,
notebook source, ignored cache and sibling repositories preserved. Next: **SS-05**, CLI diagnostics
and side-effect contracts. Stop before SS-05. Remote changes: **none**.

## SS-05 CLI diagnostics and operation effects

**passed** (local implementation/acceptance). Base `7ebdb999d80ecce934169a4cb1b52de107be245b`;
current commit is the SS-05 commit containing this record. Preserved
`feature/seascape-first-run-demo`. SS-01/SS-04 prerequisites were satisfied; source reinspection
confirmed family forwarding/restoration, existing config validators, stage re-raise behavior,
candidate runners disabling acquisition, immutable release checks and transaction recovery.

Identified CLI failures now report operation/stage, reason, nonsecret path/setting, corrective
action and guide on stderr, with exit 1. Translation uses known validation sites/resource failure
types; unlisted calculation/programming failures still raise. Global `--debug` **before** the
command exposes original chained tracebacks. Family help (0), parser errors (2), nonzero family
returns, workspace/argv restoration and Python exception types/causes remain intact. An internal
workflow callback changes only CLI stage-failure presentation; normal API re-raise/results are
unchanged. JSON preflight schema/stdout are unchanged; failure guidance is additive stderr.
The workflow guide now lists prerequisites, network/write/replacement/reuse behavior and
candidate/family/whole-release effects, including direct-family and inspection hazards.

Final verification below ran in the owning checkout unless the command uses the copied helpers
under `E` (those ran from `E`, outside the checkout). Exact command prefixes:

```sh
D=/tmp/seascape-roadmap-dev/bin
R=/tmp/seascape-ss04-evidence/consumer/bin
E=/tmp/seascape-ss05-evidence
F=/Users/tylerstevenson/Documents/Code_Repos/MarineCast
$D/python -m pytest -q tests/test_cli_diagnostics.py tests/test_products.py tests/test_demo.py tests/test_preflight.py tests/test_workflow.py
$D/python -m pytest -q
$D/ruff check src tests scripts
$D/python -m mypy
$D/ruff format --check src/seascape/products.py src/seascape/core/geo/crs.py src/seascape/core/artifacts/confinement.py src/seascape/seafloor_physiography/depth.py src/seascape/cli.py src/seascape/_cli_diagnostics.py tests/test_cli_diagnostics.py
$D/python -m build --no-isolation --outdir $E/distributions-final
$D/python scripts/check_distribution.py --sdist $E/distributions-final/toolkit_seascape-0.1.0.tar.gz --wheel $E/distributions-final/toolkit_seascape-0.1.0-py3-none-any.whl --output $E/distribution-final.json
$R/python -m pip install --force-reinstall --no-deps $E/distributions-final/toolkit_seascape-0.1.0-py3-none-any.whl
$R/python -m pip check
$R/python $E/consumer_guard.py --forbid-root $F --script $E/check_installed_package.py -- --snapshot $E/installed-final.json
$R/python $E/consumer_guard.py --forbid-root $F --script $E/cli_acceptance_final.py
$R/python $E/check_demo.py --workspace $E/demo-workspace-final --forbid-root $F
$D/python scripts/environment_snapshot.py --output $E/environment
$D/pip-audit --disable-pip --no-deps --strict -r $E/environment.txt
git diff --check
gitleaks dir $E/tracked-scan --redact --no-banner
gitleaks git . --redact --no-banner --log-opts=--all
```

All final commands above exited **0**. Focused **103 passed / 0 failed / 0 skipped**; full
**322 passed / 0 failed / 3 skipped**, 65 warnings. Skips: two feature-catalog and one
network-consumer test require absent materialized regional artifacts. Added **29 regressions**.
Lint, four-module mypy and seven-file format checks passed; no repository-wide formatting.
Build used provisioned declared build tools, producing wheel from sdist. Distribution inspection
passed (9 required files, 5 resources). Final wheel SHA-256
`e7b947f0cf62ccc7b538c1e4e061ef097d22d8dd877e94f806977058e4d841e4`;
sdist `e356f47837efff0e52869f56fc21eee692348c34e50dd9f4bc1b9aed13aeb307`.

Runtime-only acceptance reused the isolated SS-04 consumer **after force-reinstalling this wheel**;
no inherited site packages, pytest or Jupyter supplied dependencies. Guarded imports: **163 modules**.
Copied CLI helper: **13 cases** with exit/JSON/diagnostic/restoration/output-preservation checks.
Copied demo: **14 production acceptance checks**, synthetic provenance, demo-owned artifacts only.
Python checkout/outbound/child guards passed; these are not an OS/native-extension firewall claim.
Console wrapper commands using `$R/python $E/consumer_guard.py --forbid-root $F --script
$R/seascape --` also ran: `--help` exit **0**; `--workspace $E/cli-workspace --debug inspect
bathymetry --config missing.yaml` exit **1**; `--workspace $E/cli-workspace build --only
seascape-bathymetry --dry-run --check-inputs --json` exit **1**. Failure exits were expected;
JSON parsed and debug stderr contained the original traceback with empty stdout.

Evidence: `/tmp/seascape-ss05-evidence/` (`commands.json`, final test/build/import/demo logs, CLI cases, distribution,
installed/environment snapshots, audit/security logs; initial intermediate logs also retained).
Python 3.14.6/macOS ARM64; GDAL 3.12.4, PROJ 9.8.1, GEOS 3.13.1. Audit exit **0**, no known
vulnerabilities. Initial focused runs exited **1** (4 failed/83 passed, then 1 failed/99 passed):
test API calls needed the selected workspace for relative includes and the original `CRSError`
type for an invalid CRS. Corrected tests passed. Intermediate focused/full checks also passed
(102/321 respectively); final review added a publication-path refusal regression and revalidated
the final source/wheel. One read-only inspection shell typo (`/ tmp`) exited **126**, no mutation.

Broad `gitleaks dir . --redact --no-banner --report-format json --report-path
/tmp/seascape-ss05-evidence/gitleaks-tree.json` exited **1**: the same ignored, untouched
`graphify-out/cache/stat-index.json:1` `generic-api-key` finding, a 64-hex documentation cache
hash at `docs/API.md -> hashes -> docs/api.md`. Broad scan **failed**, not waived/passed.
Tracked-source and local-history scans passed; no ignore/allowlist/gate weakened. Debug/provider
tracebacks can contain sensitive detail. Unlisted validation failures remain diagnosable tracebacks.
Hosted SS-03 Linux/macOS checks remain **not_run**, remote updates unauthorized. Live acquisition,
regional rebuilds, downstream integration and human release acceptance are **not_run**. Notebook
was assessed: it still calls unchanged `run_demo`; hash unchanged, no edit or redundant headless run.

Changed: `AGENTS.md`, `docs/{API,WORKFLOWS}.md`, this record,
`src/seascape/{cli,workflow,_cli_diagnostics}.py`, `tests/{test_cli_diagnostics,test_products}.py`.
Scientific behavior changed: **no**; formulas, defaults, product/release schemas, Python exception
contracts and scientific/release gates retained. No unrelated tracked changes existed. Existing
configurations, canonical/retained products, notebook, ignored cache and siblings preserved.
Next: **SS-06**, repository-wide formatting only. Stop before SS-06. Remote changes: **none**.

## SS-06 formatting baseline

**passed** (local implementation/acceptance). Base `818df353a418ee3ec963466228c6589851599e72`;
current commit is the SS-06 commit containing this record. Clean starting tree; preserved
`feature/seascape-first-run-demo`. SS-00 prerequisite complete; source edits were serialized.
Rechecked existing Ruff configuration, CI gates, source-byte code identity and prior acceptance
limits. Used Ruff **0.16.9**, existing defaults/Python 3.11 target, without additional exclusions.

Formatted **124 Python files** under `src/`, `tests/`, `scripts/`; no lint autofixes, import
reordering, symbol/type changes, moves or algorithm edits. All **209 Python ASTs** match exactly
after ignoring location metadata (including `TypeIgnore.lineno`), retaining type comments and
string/docstring values. All **56 protected file hashes** match, including configuration, resources,
schemas and notebook. All 209 files also parse with Python 3.14's `feature_version=(3,11)`;
this is syntax evidence, not execution on Python 3.11. CI and contributor instructions now enforce
`ruff format --check src tests scripts`. A structural YAML comparison confirms the CI format
command is the only workflow change; other test/scientific/security/consumer gates are retained.

Exact verification commands (owning checkout, except copied helpers run from `E`):

```sh
D=/tmp/seascape-roadmap-dev/bin
R=/tmp/seascape-ss04-evidence/consumer/bin
E=/tmp/seascape-ss06-evidence
F=/Users/tylerstevenson/Documents/Code_Repos/MarineCast
$D/ruff format src tests scripts
$D/python $E/verify_format.py
$D/ruff format --check src tests scripts
$D/ruff check src tests scripts
$D/python -m mypy
$D/python -m pytest -q
$D/python -m build --no-isolation --outdir $E/distributions
$D/python scripts/check_distribution.py --sdist $E/distributions/toolkit_seascape-0.1.0.tar.gz --wheel $E/distributions/toolkit_seascape-0.1.0-py3-none-any.whl --output $E/distribution.json
$R/python -m pip install --force-reinstall --no-deps $E/distributions/toolkit_seascape-0.1.0-py3-none-any.whl
$R/python -m pip check
$R/python $E/consumer_guard.py --forbid-root $F --script $E/check_installed_package.py -- --snapshot $E/installed.json
$R/python $E/check_demo.py --workspace $E/demo-workspace --forbid-root $F
$D/python scripts/environment_snapshot.py --output $E/environment
$D/pip-audit --disable-pip --no-deps --strict -r $E/environment.txt
gitleaks dir $E/tracked-scan --redact --no-banner
gitleaks git . --redact --no-banner --log-opts=--all
git diff --check
```

Commands above exited **0**. Full suite: **322 passed / 0 failed / 3 skipped**, 65 warnings.
Two feature-catalog and one network-consumer test skip because materialized regional artifacts
are absent. No new tests or changed assertions; test ASTs are identical. Full format check:
230 files already formatted (209 tracked Python files); existing four-module mypy and bug lint
passed. Initial `ruff format --check src tests scripts` exited **1**, reporting 124 files needing
formatting; corrected by the formatter. One inspection command ended with a stray `/ tmp`
(exit **126**, read-only typo); expected absent old evidence-path probes were not acceptance.

Wheel built from sdist and inspected (9 required files, 5 resources). SHA-256: wheel
`cc60508ccc2c7db7115cba67b38b7cf90dc86bcd391cb89f1b50b2a1b259bb21`, sdist
`5f55b80dbbf99be8a74084d2fe61976f34196eade487688e13d496b3165d42e4`.
Reused isolated runtime-only SS-04 consumer after force-reinstalling this wheel; no inherited
packages, pytest or Jupyter dependencies. Guarded **163 module imports** and **14 demo checks**
passed; synthetic artifacts only in `E/demo-workspace/.seascape/demo`. Guards establish Python
checkout/outbound/child-process denial, not an OS/native firewall. Dependency audit found no known
vulnerabilities. Python 3.14.6/macOS ARM64; GDAL 3.12.4, PROJ 9.8.1, GEOS 3.13.1.

Evidence: `/tmp/seascape-ss06-evidence/` (command ledger, before/after ASTs, `verification-final.json`,
protected hashes, scope/CI verification, changed-file inventory and test/build/runtime/security logs).
Broad `gitleaks dir . --redact --no-banner --report-format json --report-path
/tmp/seascape-ss06-evidence/gitleaks-tree.json` exited **1** on the same untouched ignored
`graphify-out/cache/stat-index.json:1` documentation-hash finding. Broad scan **failed**; tracked
source/history passed. No cache deletion, allowlist or weakened gate. Hosted SS-03 Linux/macOS
checks remain **not_run** (remote updates unauthorized). Notebook assessed: unchanged file and
production API ASTs; no edit or repeated headless run. Live acquisition, regional rebuilds,
downstream integration and human release acceptance remain **not_run**.

Changed files: 124 Python files (complete inventory in evidence), `.github/workflows/ci.yml`,
`AGENTS.md`, `docs/DEVELOPMENT.md`, `docs/environments/README.md`, this progress record.
Behavior/API/scientific changes: **none**. Source bytes/code identity change, so existing resume
state may invalidate; validation is preserved. Ruff remains range-declared; version reproducibility
and broader lint/typing belong to SS-07. No unrelated tracked changes existed. Existing configs,
canonical products, retained releases, notebook, ignored cache and siblings preserved.
Next: **SS-07**, static checks and environment reproducibility. Stop before SS-07.
Remote changes: **none**.

## SS-07 static checks and reproducibility

**passed** (local SS-07 implementation/static/reproducibility acceptance; broad tree secret scan
still **failed**). Base `7f2832e086e5dda513ebf5bd207a56d38fa0dbd5`; current commit is the SS-07
commit containing this record. Clean starting tree; retained `feature/seascape-first-run-demo`.
Reverified SS-06, current package/CI gates, public interfaces and snapshot traversal against source.

Added narrow Ruff `F401,F841,F811,F601,F602,B006,I001` rules, preserving prior rules and formatting.
Corrected 52 import-order findings and two unused test imports; no exclusions/suppressions added.
Mypy now checks 12 documented interface modules, retaining product/CRS/confinement/depth targets.
Added demo fixture and preflight schema-1 types, generator/resource-copy annotations, and separate
CLI result locals. Existing exception, serialized report, scientific/product/release contracts stay
unchanged. Only external NumPy stubs are skipped explicitly: installed stubs contain Python 3.12+
syntax incompatible with the retained 3.11 type target. Existing imported-code/missing-stub limits
remain documented; scientific array internals are not claimed strictly typed.

Extended the existing snapshot's explicit extras/marker traversal, including transitive extras,
cycles and missing-active-distribution failure. It records versions/native/platform evidence,
omitting package URLs, executable/install/compiler paths; invalid versions raise a sanitized error.
Six new regressions cover closure, extras, cycles, markers, privacy and failure. Added separate
runtime/test/quality constraints/JSON; retained historical evidence and runtime metadata ranges.
CI quality now exercises Linux 3.11 unconstrained and macOS ARM64 3.14 constrained installs, compares
baseline closure/native versions, and audits both quality closures. Other CI jobs/settings are
structurally unchanged. The expanded audit found bootstrap pip 26.1.2 affected by
`PYSEC-2026-3721` (two advisory rows, one package). Added **quality-only** `pip>=26.2`, upgraded to
26.2.1, rebuilt and exercised two new isolated installs; final audits have no known vulnerabilities.
No vulnerability exclusions, vulnerable downgrades or new runtime dependencies.

Exact final acceptance commands, in this checkout unless noted:

```sh
D=/tmp/seascape-roadmap-dev/bin
R=/tmp/seascape-ss04-evidence/consumer/bin
E=/tmp/seascape-ss07-evidence
F=/Users/tylerstevenson/Documents/Code_Repos/MarineCast
$D/python scripts/environment_snapshot.py --extra test --extra quality --output docs/environments/quality-python314-macos-arm64
$D/python -m build --no-isolation --outdir $E/final-distributions
$D/python -m venv $E/baseline
$D/python -m venv $E/range
$E/baseline/bin/python -m pip install --cache-dir $E/pip-cache --retries 1 -c docs/environments/quality-python314-macos-arm64.txt "$E/final-distributions/toolkit_seascape-0.1.0-py3-none-any.whl[test,quality]"
$E/range/bin/python -m pip install --cache-dir $E/pip-cache-unconstrained --retries 1 "$E/final-distributions/toolkit_seascape-0.1.0-py3-none-any.whl[test,quality]"
# Each command below ran in both baseline and range; actual argv/exits are in *-commands.json.
for V in "$E/baseline/bin" "$E/range/bin"; do
  "$V/python" -m pip check
  "$V/ruff" check src tests scripts
  "$V/ruff" format --check src tests scripts
  "$V/python" -m mypy
  "$V/python" -m pytest -q
  "$V/python" scripts/environment_snapshot.py --extra test --extra quality --output "$E/$(basename "$(dirname "$V")")-environment"
  "$V/pip-audit" --disable-pip --no-deps --strict -r "$E/$(basename "$(dirname "$V")")-environment.txt"
done
$D/python scripts/check_distribution.py --sdist $E/final-distributions/toolkit_seascape-0.1.0.tar.gz --wheel $E/final-distributions/toolkit_seascape-0.1.0-py3-none-any.whl --output $E/final-distribution.json
$R/python -m pip install --no-cache-dir --force-reinstall --no-deps $E/final-distributions/toolkit_seascape-0.1.0-py3-none-any.whl
$R/python -m pip check
# Copied helpers below ran from E, outside checkout; source/overrides cleared by the helpers.
$R/python $E/consumer_guard.py --forbid-root $F --script $E/check_installed_package.py -- --snapshot $E/final-installed.json
$R/python $E/check_demo.py --workspace $E/final-demo-workspace --forbid-root $F
gitleaks dir $E/tracked-scan --redact --no-banner
gitleaks git . --redact --no-banner --log-opts=--all
git diff --check
```

Final commands above exited **0**. Each final installed-wheel suite: **328 passed / 0 failed /
3 skipped**, 65 warnings (baseline 96.44s; range 101.27s). Two feature-catalog and one network test
require absent regional artifacts. Initial development full suite also 328/0/3; focused suite
**103/0/0**. Static checks: 231 formatted files; 12 typed modules. Both isolated environments use
CPython 3.14.6, macOS 26.6.2 ARM64, GDAL 3.12.4, PROJ 9.8.1, GEOS 3.13.1, Ruff 0.16.9,
mypy 2.3.1, pip-audit 2.10.1 and pip 26.2.1. Exact constrained snapshot matches the tracked baseline;
range solve differs only in platformdirs **4.12.0 vs 4.11.15**. No inherited site packages.
Quality environments intentionally include pytest; separate reused runtime-only consumer has
no pytest/Jupyter packages. Guarded **163 imports** and **14 demo checks** pass on the final wheel;
no network attempts, two denied font-discovery child attempts. Synthetic artifacts stay in
`E/final-demo-workspace/.seascape/demo`. Guards are Python-level denial, not a native/OS firewall.

Final sdist SHA-256 `79b0a3951d131ac3f071588ec7d8390d6c678ce583eb27b01eebd4e121fca67b`;
wheel `ac3c4a2959b34acfa66e4b8d867e812dd5dd1f241558f61ae02760afcdbc6b21`.
Distribution inspection passed (9 required files, 5 resources). Reviewed 45 import-only changed
Python ASTs with imports removed; other source changes are annotations/types and CLI local names.
14 protected config/resource/notebook files match HEAD; tracked Python parses with 3.11 syntax
(which is not execution on 3.11). Notebook assessed: unchanged notebook/public runtime behavior;
no edit or repeated Jupyter run. Source-byte/resume identities may change; validators retained.

Failures retained in evidence: exploratory unused/import lint exit **1** (54 findings), initial
expanded mypy exit **2** (NumPy stub syntax), then exit **1** (five CLI result-type errors), corrected;
first constrained install exit **1** (sandbox PyPI DNS; network-enabled retry passed); initial
closure-equality probe exit **1** (expected unconstrained platformdirs drift, corrected comparison).
Initial pre-security constrained/range audits exited **1**, then final fresh fixed installs/audits
passed. One helper-copy/import batch ran from the wrong cwd and exited **2** (missing copied helper);
corrected owning-cwd copy and outside-cwd acceptance passed. A patch-tool invocation was rejected
for duplicate operations on one file before any edit; corrected. These are not passed checks.

`gitleaks dir . --redact --no-banner --report-format json --report-path
/tmp/seascape-ss07-evidence/gitleaks-tree.json` exited **1**: the same untouched ignored
`graphify-out/cache/stat-index.json:1` generic-api-key documentation-hash finding. Broad scan
**failed**; tracked-tree/history scans passed. No cache deletion/allowlist/gate weakening. Hosted
Linux/macOS acceptance and new quality matrix remain **not_run**: remote changes unauthorized.
Live data, regional builds, downstream integration and human usability/release trials **not_run**.

Changed files: 59 files; complete inventory in `E/changed-files.txt`. Functional/type/tooling
changes: `pyproject.toml`, CI, `scripts/environment_snapshot.py`, `src/seascape/{cli,demo,preflight}.py`,
`core/config/data.py`, new `tests/test_environment_snapshot.py`, new quality constraints/JSON,
`AGENTS.md`, `README.md`, environment guide and this progress record. Remaining Python changes are
import cleanup only. Evidence: `/tmp/seascape-ss07-evidence/` (final per-environment command JSON/logs,
solve/native snapshots/difference, full/audit/build/distribution/runtime/security/scope evidence).
Behavior/API: stronger static contracts and reproducible development tooling; snapshot gains
explicit extras and sanitized evidence; runtime Python APIs, CLI outputs and report schemas retained.
Scientific behavior changed: **no**. No unrelated starting edits existed; configs, packaged
resources, canonical/retained products, notebook, ignored cache and siblings preserved.
Next: **SS-08**, pending hosted SS-03 prerequisite; stop before SS-08. Remote changes: **none**.

## SS-03 acceptance closure recheck — blocked

Selected the earliest incomplete task with satisfied prerequisites: **SS-03** (SS-01/SS-02 passed).
Base `721a7199436ece870cceea17b3b2e312378e24ac`; current commit is this documentation handoff.
Clean starting tree; retained `feature/seascape-first-run-demo`. Read current instructions,
roadmap/progress, consumer CI, `check_consumer_install.py` and its regression tests. Runtime-first
installation, copied outside-checkout helpers, negative probes, declared test/notebook layer,
three Linux/macOS interpreter/architecture cases and scientific/security gates remain implemented.
No independent unfinished local implementation was identified; verified work was not repeated.

Read-only GitHub checks at **2026-09-27 13:19 UTC**:

- `github_fetch_commit` for current `721a7199436ece870cceea17b3b2e312378e24ac` and SS-03
  `368ee1b2400415a298dd742f4d6cad3fe4990af8`: HTTP **422**, "No commit found for SHA" for both.
- `github_search_branches(owner=MarineCast, repo_name=toolkit-seascape,
  query=feature/seascape-first-run-demo)`: successful read, no matching branches.
- Direct GET `https://api.github.com/repos/MarineCast/toolkit-seascape/actions/runs?head_sha=721a7199436ece870cceea17b3b2e312378e24ac&per_page=100`
  and the same endpoint with `head_sha=368ee1b2400415a298dd742f4d6cad3fe4990af8`:
  both successful reads, **total_count=0**. These queries include all trigger types;
  an empty pull-request-only wrapper was not used to infer absence of other runs.
- GET `https://api.github.com/repos/MarineCast/toolkit-seascape/branches/main`:
  successful read, remote main remains `f2400c13d509ad753d9168ed4e7a07d1ffcfc5a4`.

Precise blocker: the consumer workflow changes are local; the required hosted Linux 3.11/3.14
x86_64 and macOS 3.14 ARM64 execution/results do not exist for these commits. Executing them
requires an explicitly authorized remote update followed by inspection of real job results.
Current scope forbids push/remote mutations; no dispatch, rerun, PR, settings change or remote
update was performed. SS-08 depends on SS-03; SS-09 onward likewise remain ineligible. Local
macOS success and configured jobs do not satisfy the missing hosted evidence.

Commands: `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git remote -v`,
`git log -10 --oneline`, `git branch -vv`, reference/diff checks and `git diff --check`: exit **0**.
`command -v docker`, `command -v podman`, `command -v python3.11`: exit **1** each (not on PATH).
`/tmp/seascape-roadmap-dev/bin/python -c 'import platform; print(platform.python_version(), platform.system(), platform.machine())'`:
exit **0**, Python **3.14.6 / Darwin / arm64**. Hosted acceptance **not_run**; pytest/build/demo/
notebook/audits **not_run this recheck**, preserving previously verified evidence rather than
claiming fresh passes. Tests this turn: **not_run**, no new pass/fail/skip counts.

Changed: this progress record only. Behavior/API/scientific changes: **none**. No unrelated
starting changes; production source, CI, tests, configs, resources, notebooks, products/releases,
ignored caches and sibling repositories preserved. Evidence: `/tmp/seascape-ss03-recheck-evidence/`.
Next: finish **SS-03 hosted acceptance**, then **SS-08**; stop before SS-08. Remote changes: **none**.

## SS-03 hosted acceptance closure — passed

User explicitly authorized the feature-branch push to test SS-03 and publish the local code
changes to Git. Preserved all earlier commits on `feature/seascape-repository-organization-updates`.
Base/tested commit **`6ddd5ca7d4ce25b229bf0dd50bbd3e3708afc7f8`**; current commit is this documentation
handoff. Clean starting tree. No new production, CI, configuration, test or scientific changes.
This result supersedes the earlier blocked SS-03 entries without relabeling those historical runs.

[Run 36322829881](https://github.com/MarineCast/toolkit-seascape/actions/runs/36322829881), triggered by
push on September 27, completed **success**: **9/9 jobs**. Inspected job conclusions and decoded
logs; consumer environment JSON and expected-exit results are printed in those logs. All three
consumer jobs built/inspected an sdist and its wheel, passed **16/16 consumer steps**, verified
**163 installed modules**, and asserted the observed interpreter/system/architecture:

| Actual consumer | GDAL / PROJ / GEOS | Job ID |
| --- | --- | --- |
| Ubuntu 24.04.5, Linux x86_64, Python 3.11.16 | 3.10.3 / 9.5.1 / 3.13.1 | 108629839889 |
| Ubuntu 24.04.5, Linux x86_64, Python 3.14.7 | 3.12.4 / 9.8.1 / 3.13.1 | 108629839917 |
| macOS 14.8.9, Darwin arm64, Python 3.14.7 | 3.12.4 / 9.8.1 / 3.13.1 | 108629839834 |

Each consumer installed the wheel with dependencies in a fresh, non-inherited runtime environment;
pip/import/resource/help/init/dry-run/demo checks passed before test/notebook extras. Four expected
negative probes per case exited **1** with required markers (missing Rasterio, source import,
missing packaged resource, attempted outbound activity); these are successful rejection tests,
not concealed failures. Runtime demo, copied external tests and copied notebook steps exited **0**.
Python process guards do not claim OS/native isolation or regional scientific validity.

Both Linux full-suite jobs: **328 passed / 0 failed / 3 skipped**, 65 warnings each. Skips remain
two feature-catalog and one network-consumer test requiring absent materialized regional products.
The separate notebook job passed. Both quality jobs passed lint, 231-file format checks,
12-module mypy, dependency checks and advisory audits (no known vulnerabilities). The constrained
macOS job compared dependency/native versions successfully; interpreter patch/OS differences
from the local baseline are recorded above. Hosted Gitleaks history and broad fresh-checkout
scans passed. Earlier local ignored-cache findings remain historical failed scans, not waived.

Exact commands/actions: `git push --set-upstream origin feature/seascape-repository-organization-updates`
(exit **0**); `git rev-parse HEAD origin/feature/seascape-repository-organization-updates`
(exit **0**, matching SHA). Read-only GitHub run/jobs/logs/artifacts requests succeeded. Executed
CI commands are retained verbatim in `.github/workflows/ci.yml` and the downloaded decoded job logs.
Documentation reference checks, `git diff --check`, commit and documentation push exited **0**.
No additional local pytest/build/notebook execution was needed for this documentation-only closure.

Five non-expired Actions artifacts exist: three consumer bundles and two scientific-environment
snapshots. Recorded IDs/digests/expiry in `/tmp/seascape-ss03-hosted-evidence/run-36322829881.json`;
decoded logs are `job-<id>.log` there. Artifact ZIP contents were not downloaded: nested copied-test
counts and figure visual QA are not newly claimed. Reports/logs/distributions remain available in
Actions artifacts. Native versions and all 16 expected-exit results were verified from job logs.

Changed: this record, `docs/environments/README.md`, `docs/DEVELOPMENT.md`. Behavior/API/scientific
changes: **none**. No unrelated starting edits; source, CI, tests, configs, resources, notebooks,
canonical/retained products, ignored caches and siblings preserved. Remote changes: authorized
feature-branch pushes only; no PR, merge, tag, settings change, package publication or dataset
acquisition. Live/regional/downstream/human release acceptance remain **not_run**.
Next: **SS-08**, now eligible; stop before SS-08.

## SS-08 scientific, publication and export acceptance — passed

Base `e3e831bfc63ef5578838308b2e82322d26d74dac`; current commit is the SS-08 commit containing
this record. Branch `feature/seascape-repository-organization-updates`; initial tree clean.
Rechecked roadmap, progress, root/owner AGENTS, contracts, source and named tests. Read-only
GitHub lookup reconfirmed prerequisite run `36323147359` succeeded on the base commit.
SS-03/SS-05 and the SS-07 static boundary are satisfied; no prior implementation repeated.

Contract map: **P** = present at base, **N** = missing evidence added/extended here. All names
below executed in the focused/full suite; test quantity is not a scientific certification.

| Contract | Named evidence | Classification |
| --- | --- | --- |
| Production transformation, family/checksum validation, constant field, nodata/unavailable, observed zero, nonempty support, sign/CRS, explicit synthetic provenance | `test_normal_run_nonempty_expected_values_and_provenance`, `test_empty_or_all_null_output_cannot_pass`, `test_arbitrary_cwd_environment_restoration_and_confinement` | P; first test extended N for gradient |
| Analytic gradient and finite-value rejection | `test_demo_rejects_corrupted_gradient_values`, `test_demo_finite_policy_rejects_infinity` | N |
| Keyed row invariance, identical support/cardinality, unique/non-null exact-resolution keys | `test_composite_is_invariant_to_each_input_order`, `test_composite_rejects_incompatible_identity`; matrix `test_matrix_rejects_duplicate_h3_keys`, `test_matrix_rejects_invalid_identity_without_replacing_output`, `test_matrix_row_order_invariance_and_collision_free_field_names` | P composite/duplicate; N matrix boundaries |
| Depth sign/missingness, metric projected axes, Q90; flat/coastal nodata and controlled plane slope | `test_depth_values_reject_contradiction_and_preserve_missingness`, `test_scientific_configuration_rejects_nonmetric_crs`, `test_terrain_rejects_unsupported_depth_sign_before_io`, `test_q90_schema_rejects_other_quantiles`, `test_native_slope_masks_land_nodata_and_preserves_flat_edges`, `test_native_slope_matches_north_south_plane_including_edges` | P |
| Actual publication A/B, retained historical A, manifest-last ordering, interrupted recovery/rollback | `test_two_publications_retain_prior_product_and_manifest_bytes`, `test_generation_is_rolled_back_when_canonical_promotion_fails`, `test_release_publisher_promotes_manifest_last`, `test_snapshot_recovers_interrupted_release_before_read`, `test_release_rolls_back_failure_at_each_promotion` | P |
| Exact resolution, tampering, unsafe paths, invalid release IDs | `test_missing_product_and_resolution_fail_without_fallback`, `test_checksum_mismatch_and_incomplete_release_fail`, `test_historical_release_id_is_validated`, `test_product_resolver_rejects_paths_outside_generation`, `test_matrix_rejects_unsafe_catalog_paths` | P parser checks; N unsafe product/catalog cases |
| Resume invalidation after included config, package identity and file-backed source changes | `test_resume_invalidates_when_included_domain_config_changes`, `test_resume_invalidates_when_package_code_identity_changes`, `test_resume_invalidates_when_file_backed_source_changes` | P |
| Export freezes A while actual publisher installs B; table, catalog and checksum metadata cannot mix | `test_matrix_pins_real_publication_during_release_switch` | N, existing pinning passed unchanged |
| Null/zero, QC/evidence, units, original types, field names, explicit legacy limits | `test_matrix_aligns_by_h3_and_preserves_zero_null_and_qc`, `test_matrix_row_order_invariance_and_collision_free_field_names` | P values/metadata; N shuffled/collision boundaries |
| Empty support, failed write/replace, existing destinations, aliases/overwrite and retained generations | `test_matrix_rejects_empty_support_without_resolution_column`, `test_matrix_failed_write_preserves_valid_destination`, `test_matrix_output_cannot_replace_input`, release-switch test; `test_existing_export_is_preserved` | N except existing CLI refusal P |

**Reproduced failures and fix:** initial matrix run: **3 failed / 17 passed**, exit 1. Empty tables
without a resolution column were accepted; overwrite could replace the input catalog or canonical
release manifest. Export now rejects empty support and those aliases, and cannot write into any
retained generation. Python signatures, output schema, physical values and exception types remain
unchanged; these invalid inputs now raise `ValueError`. Initial collection exit 2 was a test fixture
import error, fixed by making copied tests a package and reusing the existing publisher fixture.
Initial focused exit 1 (108 passed / 2 failed / 16 fixture errors) exposed an arithmetic mistake in
the new analytic expectation; corrected the row sum from 452 to 453, without changing calculations.

Demo adds `gradient` to report controls and one real check (15 total), using the original raster,
production bathymetry API, packaged config and family validator. The 18 interior pixels have
`sum(row)=453`, `sum(column)=426`; `d=5+(145*c+80*r)/47` gives mean `5680/47`, min `5280/47`,
max `6085/47`, range `805/47` meters. Absolute 3e-5 m accounts for float32 fixture rounding;
constant depth retains 1e-6 m and band partitions 1e-12, no relative tolerance. Existing slope
plane assertions retain NumPy's tolerance for double-precision angular-to-meter arithmetic.
Same-environment keyed tables repeat exactly; timestamps/run IDs/plotting bytes are not compared.
The notebook remains a thin client; only its explanation changed. **Scientific behavior changed: no.**
Publisher tests reuse a test-only pre-audited fixture; they exercise publication/resolution, not
a full regional audit. The one-family demo is never promoted or labeled a complete release.

Executed commands/results (all from this checkout; exact expanded argv, exit codes and logs in
`/tmp/seascape-ss08-evidence/commands.json`; consumer subcommands in `acceptance/report.json`):

| Command | Result |
| --- | --- |
| `/tmp/seascape-roadmap-dev/bin/python -m pytest -q` | exit 0, **352 passed / 0 failed / 3 skipped**, 69 warnings |
| Focused `python -m pytest -q` over demo/matrix/products/review/workflow/consumer/publication/release/bathymetry contracts | exit 0, **126 passed**, 29 warnings; exact file list in `focused-final.json` |
| `ruff check src tests scripts`; `ruff format --check src tests scripts`; `python -m mypy` | exit 0 each; 232 formatted files, 12 checked interface modules |
| `python -m pip check` | exit 0; no broken requirements |
| `python -m build --no-isolation --outdir /tmp/seascape-ss08-evidence/distributions` | exit 0; wheel built from sdist, declared provisioned build tools |
| `python scripts/check_distribution.py --sdist … --wheel … --output …` | exit 0, 9 required files / 5 resources survive; full args in `distribution.json` |
| `python scripts/check_consumer_install.py --wheel … --source … --forbid-root … --output …` | exit 0, **16/16** expected-exit steps; fresh isolated runtime first, then declared extras |
| Copied guarded pytest; copied headless notebook | exit 0 each; **83 passed / 0 skipped**, 29 warnings; notebook **15 production / 16 total checks**, 2 embedded figures, no outbound/acquisition attempts |
| `python scripts/environment_snapshot.py --extra test --extra quality --output /tmp/seascape-ss08-evidence/environment` | exit 0, Python/native/dependency closure recorded |
| `pip-audit --disable-pip --no-deps --strict -r /tmp/seascape-ss08-evidence/environment.txt` | exit 0, no known vulnerabilities; no ignore/downgrade |
| `gitleaks dir /tmp/seascape-ss08-evidence/tracked-review --redact --no-banner`; `git diff --check` | exit 0 each; tracked/new source scan only, ignored cache preserved |

Environment: fresh consumer and development CPython **3.14.6**, macOS **26.6.2 ARM64**;
GDAL **3.12.4**, PROJ **9.8.1**, GEOS **3.13.1**. Source/OrcaCast reads, outbound Python activity
and child processes denied during consumer execution; installations permit declared dependency
downloads and notebook loopback traffic. No OS firewall claim. Wheel SHA-256 and distribution
checks are in `distribution-report.json`; portable execution/logs/notebook in `acceptance/`.

The three skips remain the two feature-catalog checks and one network-consumer check requiring
absent regional artifacts. No new skips. Prior broad ignored-cache Gitleaks finding is not waived
or relabeled passed; that scan was not repeated. Real acquisition, regional equality/accuracy,
downstream integration, visual figure QA and human onboarding trials **not_run**.
Hosted [run 36324502530](https://github.com/MarineCast/toolkit-seascape/actions/runs/36324502530)
passed **9/9 jobs** on implementation commit `aace671d74c565b4f141805dbe66505fb055f239`:
Linux Python 3.11 and 3.14 each **352 passed / 3 skipped**, 69 warnings; all three clean consumer
cases (Linux 3.11/3.14, macOS ARM64 3.14) **16/16 expected-exit steps**; notebook, both quality
jobs and history/tree secret scans passed. Decoded job logs and exact tested SHA are in
`/tmp/seascape-ss08-evidence/hosted/`. Hosted copied-test counts/artifact interiors were not
downloaded or inspected; their executed steps passed. This progress-only closure changes no code.
Initial unrelated tracked changes: none; configs, canonical/retained products, caches and sibling
repositories preserved. Files: demo/matrix APIs, consumer helper, three contract test files plus
test-package marker, demo/matrix guides, notebook explanation and this record.
Remote actions: normal authorized feature push of implementation and this progress closure;
no merge, tag, package publication, settings or dataset changes. Next: **SS-09**; stop before it.
