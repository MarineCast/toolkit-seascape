# Validated environments and static checks

## Tested platforms

The [SS-08 implementation run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36324502530)
and [progress closure run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36324758385)
passed all nine jobs on `aace671` and `0d307de`, respectively. These are observed environments,
not a guarantee for all dependency lower bounds, OS versions or architectures.

| Environment | Executed evidence |
| --- | --- |
| Linux x86_64, Python 3.11 / 3.14 | Full offline suite and clean runtime-first wheel consumers; copied contracts/notebook |
| macOS ARM64, Python 3.14 | Clean runtime-first wheel consumer and constrained quality/native baseline |
| Local macOS 26.6.2 ARM64, CPython 3.14.6 | SS-08 full suite/clean consumer; GDAL 3.12.4, PROJ 9.8.1, GEOS 3.13.1 |
| Native Windows | Not supported for the existing POSIX publication locks; no Windows acceptance claimed |

Linux 3.11/3.14 each ran 352 tests with three absent-regional-artifact skips. All three hosted
consumer cases completed 16 expected-exit steps. Real sources, regional scientific accuracy,
downstream integration and unfamiliar-human onboarding are separate, unrun gates.

## Reproducibility baseline

`quality-python314-macos-arm64.txt` is the SS-07 reproducibility baseline for the installed
runtime/test/quality closure. Its JSON records CPython 3.14.6, macOS 26.6.2 ARM64, GDAL 3.12.4,
PROJ 9.8.1 and GEOS 3.13.1. Fresh isolated constrained and unconstrained wheel installations
were exercised locally. The constrained closure/native versions matched; the unconstrained
solve selected platformdirs 4.12.0 instead of the pinned 4.11.15, with the same native versions.
Ruff 0.16.9,
mypy 2.3.1, pip-audit 2.10.1 and pip 26.2.1 are part of this baseline.
The quality extra requires pip >=26.2 after its expanded closure audit identified
PYSEC-2026-3721 in bootstrap pip 26.1.2; the fixed version is audited, not ignored. This is tested compatibility on
that platform, not proof that every declared lower bound or another OS works. Package metadata
retains dependency ranges. The earlier `python314-macos-arm64.{txt,json}` is historical
runtime/test evidence and is preserved, rather than silently replaced.

To reproduce on a compatible Python 3.14 ARM64 macOS platform (use an explicit wheel path):

```sh
python3.14 -m venv /tmp/seascape-quality
/tmp/seascape-quality/bin/python -m pip install \
  -c docs/environments/quality-python314-macos-arm64.txt \
  '/absolute/path/toolkit_seascape-0.1.0-py3-none-any.whl[test,quality]'
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
defaults/Python 3.11 target. No new per-file exclusions or rule suppressions were added.

Mypy checks these **12 modules**, with annotated functions, checked bodies and unused-ignore warnings:

- `products.py`, `core/geo/crs.py`, `core/artifacts/confinement.py`, `seafloor_physiography/depth.py`
- `demo.py`, `cli.py`, `_cli_diagnostics.py`, `preflight.py`
- `core/config/document.py`, `core/config/data.py`, `core/config/paths.py`, `metric_matrix.py`

The project syntax/type target remains Python 3.11. Existing skipped imports/missing external
stubs remain explicit limits; this is not strict typing of the whole scientific implementation.
Only NumPy's external stubs also use `follow_imports_for_stubs = true`: its exercised release
contains Python 3.12+ stub syntax that mypy cannot parse against the 3.11 target. This narrow
dependency boundary makes array internals opaque; it does not suppress errors in project modules.
Preflight dictionaries now have concrete schema-1 types, without changing serialized reports or
exception behavior. Dynamic YAML and demo/export metadata stay open mappings at their boundaries.

CI retains tests, installed-wheel/notebook checks and security audits. Its quality matrix uses an
unconstrained Linux Python 3.11 solve and the constrained macOS Python 3.14 ARM64 baseline; the
constrained job compares the observed closure/native versions. Each saves and audits runtime,
test and quality dependencies. [Hosted run 36322829881](https://github.com/MarineCast/toolkit-seascape/actions/runs/36322829881)
passed all nine jobs on commit `6ddd5ca`, including Linux 3.11/3.14 consumers and macOS 3.14 ARM64.
Its constrained macOS quality job reproduced the dependency/native baseline on Python 3.14.7,
macOS 14.8.9; these differ from the recorded local interpreter patch/OS. See the progress record
for observed versions and exact acceptance limits. A configured matrix alone is not execution
evidence. Hosted Gitleaks history/tree gates passed; the untouched ignored Graphify hash finding
remains a failed broad local scan, not waived.
