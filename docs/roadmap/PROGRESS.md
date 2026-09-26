# Seascape roadmap progress

Completed scope: SS-00 through SS-02; [specification](SEASCAPE_CODEX_ROADMAP.md).
SS-00 base/current commit: `f2400c13d509ad753d9168ed4e7a07d1ffcfc5a4` (no reset).
Initial state: clean `main`; remote `https://github.com/MarineCast/toolkit-seascape.git`.
Working branch: `feature/seascape-first-run-demo`. No remote mutations.

| Task | Status | Evidence / next gap |
| --- | --- | --- |
| SS-00 | passed | Baseline classified; notebook PASS (12 code cells, no errors) |
| SS-01 | passed | 21 regressions, runtime-only guarded wheel demo; full suite 241 passed / 3 skipped |
| SS-02 | passed | Portable copied notebook; 7 regressions; full suite 248 passed / 3 skipped |
| SS-03–SS-11 | not_run | SS-03 consumer-install CI is next; not started |

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
