# Validated environments and static checks

## Tested platforms

The current package requires Python 3.14 (`>=3.14,<3.15`). Current CI is configured for Linux
x86_64 and macOS ARM64 on 3.14. Earlier 3.11 results below document historical revisions; 3.11 is no
longer a supported installation target.

The two ARM64 macOS jobs select `macos-15`; their explicit job names retain the
existing required `macos-14` check contexts. The runner label and recorded environment
identify the actual OS. This migration preserves the constrained dependency/native checks.

The [SS-09 implementation run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36327449869)
passed all nine jobs on `3022ace`, including the documented source-install quickstart on all three
consumer platforms. Prior [SS-08 implementation run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36324502530)
and [progress closure run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36324758385)
passed all nine jobs on `aace671` and `0d307de`, respectively. These are observed environments,
not a guarantee for all dependency lower bounds, OS versions or architectures.

| Environment | Executed evidence |
| --- | --- |
| Linux x86_64, Python 3.14 | Full offline suite and clean runtime-first wheel consumers; copied contracts/notebook |
| Linux x86_64, Python 3.11 (historical) | Earlier full offline suite and clean runtime-first wheel consumer; unsupported by current metadata |
| macOS ARM64, Python 3.14 | Clean runtime-first wheel consumer and constrained quality/native baseline |
| Local macOS 26.6.2 ARM64, CPython 3.14.6 | SS-09 full suite/clean consumer/source quickstart; GDAL 3.12.4, PROJ 9.8.1, GEOS 3.13.1 |
| Native Windows | Not supported for the existing POSIX publication locks; no Windows acceptance claimed |

The earlier macOS 14 runner required the Rasterio 1.5.1 wheel because 1.5.2
requires macOS 15 for its Python 3.14 ARM wheel. The migration to macOS 15 retains
`rasterio>=1.4,<1.5.2` and the recorded 1.5.1 baseline/native stack. Updating that
scientific dependency is separate work. The tagged `v0.1.0` metadata has no such limit.

In SS-09, Linux 3.11.16/3.14.7 each ran 368 tests with three absent-regional-artifact skips. All three
hosted consumer cases completed 16 expected-exit wheel steps and the documented source quickstart
(12 shell lines, 15 demo checks). Linux 3.11 used GDAL 3.10.3 / PROJ 9.5.1 / GEOS 3.13.1;
Linux/macOS 3.14.7 used GDAL 3.12.4 / PROJ 9.8.1 / GEOS 3.13.1. Real sources, regional scientific accuracy,
downstream integration and unfamiliar-human onboarding are separate, unrun gates.

## Reproducibility baseline

`quality-python314-macos-arm64.{txt,json}` is the current 2026-11-03
runtime/test/quality baseline, captured on CPython 3.14.0, macOS 27.0.1 ARM64,
GDAL 3.12.4, PROJ 9.8.1 and GEOS 3.13.1. The previous SS-07 baseline is preserved
as `quality-python314-macos-arm64-ss07.{txt,json}` with its original metadata.
The earlier `python314-macos-arm64.{txt,json}` remains historical runtime/test evidence.

The failed [macOS snapshot](https://github.com/MarineCast/toolkit-seascape/actions/runs/41443432254)
contained exactly two newly required runtime packages absent from SS-07:
`ijson==3.6.0` and `psutil==7.2.2`. After including them, the audit identified
vulnerable older baseline pins. The current baseline updates only those affected
pins: Certifi 2026.10.18, Filelock 4.2.1, Msgpack 1.2.3 and Pillow 13.0.0.
All other SS-07 dependency versions and GDAL/PROJ/GEOS remain unchanged.
Ruff 0.16.9, mypy 2.3.1, pip-audit 2.10.1 and pip 26.2.1 remain in this baseline.
The quality extra still requires pip >=26.2; audits do not ignore vulnerable pins.

Both the extended constrained solve and a fresh unconstrained solve passed locally
on 2026-11-03: 766 tests, three expected absent-regional-artifact skips, lint,
formatting, configured types, `pip check` and strict closure audits with no known
vulnerabilities. The constrained dependency/native snapshot matched exactly.
This is tested compatibility on that platform, not proof for every declared lower
bound or OS. The macOS 15 hosted job independently checks and audits this baseline;
a configured job alone does not establish execution evidence.

To reproduce on a compatible Python 3.14 ARM64 macOS platform (use an explicit wheel path):

```sh
python3.14 -m venv /tmp/seascape-quality
/tmp/seascape-quality/bin/python -m pip install \
  -c docs/environments/quality-python314-macos-arm64.txt \
  '/absolute/path/toolkit_seascape-0.1.1-py3-none-any.whl[test,quality]'
/tmp/seascape-quality/bin/python -m pip check
/tmp/seascape-quality/bin/ruff check src tests scripts
/tmp/seascape-quality/bin/ruff format --check src tests scripts
/tmp/seascape-quality/bin/python -m mypy
/tmp/seascape-quality/bin/python -m pytest -q
/tmp/seascape-quality/bin/python scripts/environment_snapshot.py \
  --extra test --extra quality --output /tmp/seascape-quality-environment
/tmp/seascape-quality/bin/pip-audit --disable-pip --no-deps --strict \
  -r /tmp/seascape-quality-environment.txt
```

Run source checks from this checkout; run the existing installed-package/demo helpers from
outside it. The demo's runtime-only acceptance environment remains separate and has no
pytest/Jupyter packages. Constraints do not install dependencies or supply native libraries.
Compare snapshots before claiming reproduction: dependencies, extras, interpreter/minor version,
architecture and GDAL/PROJ/GEOS must match; OS/patch differences require separate recorded evidence.
Use a new venv and omit `-c` to exercise the unconstrained solve during release preparation.
Regenerate a baseline only after both solves and applicable checks pass; review version changes
and audit the new closure. Never force an obsolete vulnerable pin to make reproduction pass.

The snapshot defaults to runtime plus `test`; repeated `--extra` selects explicit project extras
and follows transitive extras/markers, failing for missing active distributions. Evidence stores
names/versions, platform/architecture and native versions. It omits executable/install paths,
direct package URLs and compiler build paths. Invalid version strings produce a sanitized error.
Review evidence before sharing; logs can contain private paths or rejected package locations.

Ruff checks all Python under `src/`, `tests/` and `scripts/`: syntax/control-flow baseline
`E9,F63,F7,F82`, unused imports/locals `F401,F841`, redefinitions/duplicate keys
`F811,F601,F602`, mutable defaults `B006`, and import order `I001`. Formatting uses the existing
defaults/Python 3.14 target. No new per-file exclusions or rule suppressions were added.

Mypy checks these **21 modules**, with annotated functions, checked bodies and unused-ignore warnings:

- `products.py`, `domain_parquets.py`, `legacy_products.py`, `core/geo/crs.py`, `core/artifacts/confinement.py`, `seafloor_physiography/depth.py`
- `demo.py`, `cli.py`, `_cli_diagnostics.py`, `preflight.py`
- `core/config/document.py`, `core/config/data.py`, `core/config/paths.py`, `metric_matrix.py`
- `historical.py`, `biogenic_habitat/seagrass/native.py`, `utils/geometry_quality.py`
- `spatial_support/coastal_policy.py`, `spatial_support/coastal_policy_build.py`
- `biogenic_habitat/kelp/native.py`
- `benthic_substrate/areal.py`

The project syntax/type target is Python 3.14. Existing skipped imports/missing external
stubs remain explicit limits; this is not strict typing of the whole scientific implementation.
The earlier NumPy-only stub override was removed with the 3.11 target; the exercised stubs are
now parsed against their supported Python version. No project-module errors are suppressed.
Preflight dictionaries now have concrete schema-1 types, without changing serialized reports or
exception behavior. Dynamic YAML and demo/export metadata stay open mappings at their boundaries.

CI retains tests, installed-wheel/notebook checks and security audits. Its quality matrix uses an
unconstrained Linux Python 3.14 solve and the constrained macOS Python 3.14 ARM64 baseline; the
constrained job compares the observed closure/native versions. Each saves and audits runtime,
test and quality dependencies. [Hosted run 36322829881](https://github.com/MarineCast/toolkit-seascape/actions/runs/36322829881)
passed all nine jobs on historical commit `6ddd5ca`, including then-supported Linux 3.11/3.14
consumers and macOS 3.14 ARM64.
Its constrained macOS quality job reproduced the dependency/native baseline on Python 3.14.7,
macOS 14.8.9; these differ from the recorded local interpreter patch/OS. See the progress record
for observed versions and exact acceptance limits. A configured matrix alone is not execution
evidence. Hosted Gitleaks history/tree gates passed; the untouched ignored Graphify hash finding
remains a failed broad local scan, not waived.
