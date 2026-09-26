# Seascape roadmap progress

Scope: SS-00 and SS-01 only; [specification](SEASCAPE_CODEX_ROADMAP.md).
Base/current commit: `f2400c13d509ad753d9168ed4e7a07d1ffcfc5a4` (no reset).
Initial state: clean `main`; remote `https://github.com/MarineCast/toolkit-seascape.git`.
Working branch: `feature/seascape-first-run-demo`. No remote mutations.

| Task | Status | Evidence / next gap |
| --- | --- | --- |
| SS-00 | passed | Baseline classified; notebook PASS (12 code cells, no errors) |
| SS-01 | not_run | Portable demo absent at baseline |
| SS-02–SS-11 | not_run | Outside this session; SS-02 is next |

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
