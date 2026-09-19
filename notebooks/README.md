# Seascape notebooks

Run notebooks from the repository root after installing the notebook extra:

```sh
python -m pip install -e '.[test,notebook]'
jupyter lab notebooks/validation/01_TOOLKIT_VALIDATION.ipynb
```

## Notebook roles

- `01_DATA_EXPLORER.ipynb` runs a live, tightly bounded San Juan Islands bathymetry workflow.
  It writes notebook-owned config, downloaded sources, H3 r6/r8 support, processed Parquet, and
  one interactive HTML inspector under `notebooks/outputs/`. Its Natural Earth land mask is an
  exploratory support mask, not the canonical territorial-water product, so the notebook does not
  publish a Seascape release and is not executed in clean-checkout CI.
- `validation/01_TOOLKIT_VALIDATION.ipynb` verifies that the toolkit imports, initializes a clean
  workspace, exposes its catalog and build graph, runs representative production bathymetry logic
  offline, and produces inspectable outputs.

Execute the validation notebook headlessly without overwriting the committed source:

```sh
jupyter nbconvert \
  --to notebook \
  --execute notebooks/validation/01_TOOLKIT_VALIDATION.ipynb \
  --ExecutePreprocessor.timeout=120 \
  --output seascape-toolkit-validation.ipynb \
  --output-dir /tmp
```

The validation notebook complements pytest; it does not replace the automated suite or establish
regional scientific validity or live provider availability.
