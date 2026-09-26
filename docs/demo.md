# Offline synthetic demo

[Documentation index](README.md) · [Supported APIs](API.md)

From an obtained source checkout, an isolated install and first result are:

```sh
python3 -m venv /tmp/seascape-user
. /tmp/seascape-user/bin/activate
python -m pip install .
DEMO_WORKSPACE="$HOME/seascape-demo"
seascape --workspace "$DEMO_WORKSPACE" demo
```

Installation requires access to declared Python dependencies. After installation the demo uses no
network, credentials, checkout files, pytest, or notebook tooling. Alternatively install a wheel
built from this source with `python -m pip install /path/to/toolkit_seascape-0.1.0-py3-none-any.whl`
(the wheel path is a placeholder for the actual build). Python 3.11+ and POSIX are required by the
existing publication helpers. This session verified a runtime-only wheel on macOS ARM64 Python
3.14.6; hosted Linux checks and other platforms are not newly verified here.

The CLI prints `Synthetic software acceptance: PASS (not a regional release)` only after every
check and figure succeeds, followed by exact output paths. All demo-owned inputs and outputs are
inside `.seascape/demo/` in the selected workspace:

| File | Meaning |
| --- | --- |
| `input/synthetic_bathymetry.tif` | 48 × 48 EPSG:4326 negative-elevation raster, meters, synthetic datum |
| `input/H3_SUPPORT_RES_8.parquet` | Unique H3 r8 support including deliberately unavailable cells |
| `input/H3_WATER_NEIGHBORHOODS_RES_8.parquet` | Bounded synthetic H3 hops, not real coastal passability |
| `config/demo.yaml` | Narrow configuration from packaged defaults; all paths demo-owned |
| `output/BATHYMETRY.parquet` | Production bathymetry output; one row per exact support key |
| `output/bathymetry_manifest.json` | Production family manifest, checksums, synthetic source identity and licensing |
| `report.json` | RUNNING / FAIL / PASS, executed checks, controls, environment and paths |
| `figures/input.png`, `figures/output.png` | Static figures, no basemap tiles/display server; grey means unavailable |

The notebook's bounded raster recipe is reused: elevation starts at −5 m and follows a controlled
gradient over `(-123.20, 48.40, -123.10, 48.50)`. Constant −5 m, exact 0 m, and nodata patches add
hand-checkable controls. H3 aggregation converts valid negative elevation to positive-down depth.
For the constant-depth control, mean depth is 5 m, standard deviation/range are observed **0**,
and the [10,30) m band fraction is **0**. The [0,10) fraction is **1**. Nodata-only and out-of-raster
cells retain null depth and count, not zero. Production's existing marine mask excludes exact sea
level (0 m); this demo does not reinterpret that input as measured marine depth.

Acceptance requires nonempty support and valid depths, exact unique keys/resolution, 2016 eligible
marine pixels, finite-or-null numerics, sign/CRS/nodata, complete depth-band fractions, known constant
values, required synthetic provenance, and real family/input/upstream checksums. The 5 m control
uses 1e-6 m absolute tolerance; fractional partitions use 1e-12, with no relative tolerance. Values
and keys repeat exactly in the tested environment; timestamps/run IDs and plotting bytes need not.
Family `source_completeness=complete` refers only to these generated inputs. No regional survey,
provider availability, genuine water network, real-world accuracy, whole-release audit or downstream
application acceptance is established. Ordinary configs, canonical products and retained releases
are untouched. Matplotlib's font cache and publisher locks/bookkeeping also stay in the demo tree.

Existing demo output is refused. An intentional rerun uses:

```sh
seascape --workspace "$DEMO_WORKSPACE" demo --overwrite
```

Overwrite requires the exact demo ownership marker, refuses symlinks and unreviewed transaction
state, and replaces only known generated files. Unrelated files are retained; no demo directory is
recursively replaced. Failure after computation starts invalidates any previous PASS report. A
process interruption may leave RUNNING and incomplete files; it is never a PASS. Review unresolved
publisher journals rather than bypassing their protection, or choose a fresh workspace.

```python
from seascape.demo import run_demo

result = run_demo("/path/to/fresh-workspace")  # replace this placeholder
print(result.parquet_path, result.report_path, result.checks)
```

The result includes manifest/figure paths and execution metadata. API failures raise normally;
`DemoWorkspaceError` identifies destination safety failures (translated to stderr/nonzero by CLI).
The API restores workspace/candidate/Matplotlib environment overrides on success or failure. Like
existing producer APIs, workspace selection is process-global; avoid concurrent workspace calls
in the same Python process. Separate processes reject overlapping demo writers with a POSIX lock.

For maintainers, `python -m pytest -q tests/test_demo.py` checks regressions. Copy
[`scripts/check_demo.py`](../scripts/check_demo.py) outside the checkout and run it with a clean
runtime-only wheel interpreter and `--workspace /path/to/fresh-workspace`. It rejects development
imports and verifies a Python audit guard against outbound socket/DNS activity and child processes.
This guard is process-level evidence, not an operating-system firewall. The
[portable validation notebook](../notebooks/README.md) presents the same API results from a copied
file, including real checks and environment restoration. It requires the notebook extra; the CLI
demo's runtime dependencies remain unchanged. Consumer-install CI is the later SS-03 task.
