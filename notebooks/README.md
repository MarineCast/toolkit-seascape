# Seascape notebooks

The offline validation notebook is a readable client of the same installed `run_demo` API
used by `seascape demo`. It needs the notebook extra; pytest and a repository checkout are
not runtime prerequisites. The CLI demo needs neither notebook nor test tooling.

From an obtained source checkout:

```sh
python -m pip install '.[notebook]'
jupyter lab notebooks/validation/01_TOOLKIT_VALIDATION.ipynb
```

Alternatively install the extra with an obtained wheel (the absolute wheel path is a placeholder):

```sh
python -m pip install 'toolkit-seascape[notebook] @ file:///absolute/path/to/toolkit_seascape-0.1.0-py3-none-any.whl'
```

Choose the kernel from that installation. The notebook displays its interpreter and package
import path. The wheel does not supply the notebook file; use a supplied copy or copy it from
the repository. The copied file needs no sibling files or checkout discovery.

## Notebook roles

- `validation/01_TOOLKIT_VALIDATION.ipynb` runs the bounded synthetic demo, presents configuration,
  input/support, output grain/schema/control values, static figures, real validation checks and
  provenance. Its default temporary workspace is retained after kernel exit, until manual or
  system temporary-file cleanup. An optional user-selected workspace is described below.
- `01_DATA_EXPLORER.ipynb` performs live San Juan Islands bathymetry exploration. It downloads
  sources and writes notebook-owned config, H3 r6/r8 support, processed Parquet and an interactive
  HTML inspector under `notebooks/outputs/`. Its Natural Earth water mask is exploratory, not
  canonical territorial-water support. It requires its checkout helper, does not certify or inspect
  a completed release, and is not executed in clean-checkout CI. Review its acquisition switches
  and source scope before running; the synthetic demo does not authorize real acquisition.
- Audited-release consumption is a separate route through [`seascape.products`](../docs/API.md),
  using an existing completed release, exact resolution and retained release ID. Neither notebook
  fabricates or establishes that release.

## Execute a copy outside the checkout

Activate the installation's environment, then use this recipe. `VALIDATION_SOURCE` is an explicit
placeholder for an obtained notebook file; it is not a runtime source-tree requirement.

```sh
VALIDATION_SOURCE="/absolute/path/to/01_TOOLKIT_VALIDATION.ipynb"
COPY_DIR="$(mktemp -d)"
RESULT_DIR="$(mktemp -d)"
cp "$VALIDATION_SOURCE" "$COPY_DIR/01_TOOLKIT_VALIDATION.ipynb"
cd "$COPY_DIR"
python -m jupyter nbconvert \
  --to notebook \
  --execute 01_TOOLKIT_VALIDATION.ipynb \
  --ExecutePreprocessor.timeout=120 \
  --output seascape-toolkit-validation.ipynb \
  --output-dir "$RESULT_DIR"
```

Open the executed copy to inspect the displayed checks and workspace/report/figure paths.
The committed source stays unexecuted; execution outputs, local paths and figures belong only
to the separate executed copy. The original source can also be executed with the repository's
existing headless command and a separate output directory.

To retain demo products at a chosen location, set this before launching Jupyter:

```sh
export SEASCAPE_DEMO_WORKSPACE="$HOME/seascape-notebook-demo"
```

The notebook also exposes `DEMO_WORKSPACE` and `OVERWRITE` in its parameter cell. Existing demo
output is refused with `OVERWRITE = False`. Change that value explicitly only for a safe rerun;
the demo's ownership/symlink/transaction checks still apply. All generated inputs, config,
Parquet, manifest, report, PNGs and cache remain in `<workspace>/.seascape/demo`.
The API restores its workspace/candidate/Matplotlib environment overrides in-process.

The [demo guide](../docs/demo.md) explains units, sign, missingness, controls, provenance and
safe overwrite. The notebook displays the demo's actual checks plus environment restoration;
empty checks, failures and report disagreement halt execution. A PASS is synthetic software
acceptance, not regional accuracy, provider availability, a verified water network, release audit
or downstream application acceptance. Figures are inspection aids, not numeric validation gates.

Maintainers can run `python -m pytest -q tests/test_validation_notebook.py` for presentation/source
regressions. For installed-wheel acceptance, copy [`scripts/check_validation_notebook.py`](../scripts/check_validation_notebook.py)
outside the checkout and invoke it with `--notebook`, `--output`, `--forbid-root` and optionally
`--workspace`. The input directory must contain only the copied notebook; output must be separate.
The helper pins a temporary kernel to the calling interpreter and verifies actual execution,
synthetic provenance, no checkout reads/acquisition/outbound Python socket activity, environment
restoration and unchanged source bytes. Jupyter loopback is permitted; this is not an OS firewall.
No global kernel is registered. Hosted consumer-install CI remains SS-03 work.
