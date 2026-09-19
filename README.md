# Seascape Toolkit

Species-neutral source acquisition, processing, inspection, and publication of marine seascape
products. The installable distribution is **`toolkit-seascape`**; the Python package and command
are **`seascape`**. No OrcaCast checkout or installation is required.

## Documentation

Start with the [documentation index](docs/README.md) for setup, workflows, configuration,
architecture and development guidance.

## Install

Python 3.11+ on Linux or macOS, with compatible geospatial wheels/libraries (Rasterio/GDAL,
GeoPandas, PyProj and Shapely). The extraction was executed with Python 3.14; other supported
versions have syntax coverage but have not yet been exercised locally. Publication uses POSIX
file locks; native Windows is not supported.

```sh
python -m pip install -e '.[test]'
seascape --help
python -m pytest -q
```

For a regular installation, use `python -m pip install .` or install a built wheel. Editable
installation is optional. Source data and generated products are not included in the package.

## Validate the toolkit

Install the test and notebook tooling from the repository root, then run the automated suite and
the human-readable offline acceptance workflow:

```sh
python -m pip install -e '.[test,notebook]'
python -m pytest -q
jupyter lab notebooks/validation/01_TOOLKIT_VALIDATION.ipynb
```

The notebook can also run headlessly without modifying the committed copy:

```sh
jupyter nbconvert \
  --to notebook \
  --execute notebooks/validation/01_TOOLKIT_VALIDATION.ipynb \
  --ExecutePreprocessor.timeout=120 \
  --output seascape-toolkit-validation.ipynb \
  --output-dir /tmp
```

`pytest` provides automated correctness and regression coverage. The
[toolkit validation notebook](notebooks/validation/01_TOOLKIT_VALIDATION.ipynb) provides an
inspectable, offline smoke/acceptance workflow over production APIs. The
[Data Explorer](notebooks/01_DATA_EXPLORER.ipynb) defaults to live source acquisition and a bounded
San Juan Islands exploratory build, including a Natural Earth water mask. It writes local data and
is not a certified regional release or part of clean-checkout CI. Review the
[notebook guide](notebooks/README.md) before running it.

## Choose a data workspace

All config, source, candidate, and output paths belong to a workspace. Commands default to the
current directory; `--workspace` or `SEASCAPE_WORKSPACE` chooses another root. Installed modules
never infer a writable workspace from `site-packages`. The init command leaves existing files intact.

```sh
seascape --workspace /path/to/seascape-workspace init
seascape --workspace /path/to/seascape-workspace stages
seascape --workspace /path/to/seascape-workspace build --dry-run
```

Edit `config/common.yaml` for named geographic areas and `config/data/environment_seascape.yaml`
for sources, resolutions, processing, outputs and maps. The supplied regional configuration is
inherited from the Northeast Pacific case study. Some source products require local provision
or provider access; their `DATA_SOURCES.md` files describe provenance and rights. Initialization
copies configuration and reference metadata only; it does not download data or certify a release.

## Download, process, inspect

```sh
seascape --workspace /path/to/seascape-workspace download bathymetry --help
seascape --workspace /path/to/seascape-workspace download bathymetry --config config/data/project.yaml
seascape --workspace /path/to/seascape-workspace download water-geometry --config config/data/project.yaml
seascape --workspace /path/to/seascape-workspace build --only seascape-geomorphometry --dry-run
seascape --workspace /path/to/seascape-workspace build --candidate-root /path/to/seascape-workspace/.seascape/candidate
seascape --workspace /path/to/seascape-workspace inspect bathymetry --help
```

Download commands use each source's existing cache, overwrite and validation behavior. A full
build expects the configured source inputs to be present. `--only` expands dependencies, `--skip`
requires validated reusable products, and `--resume` checks configuration, dependencies and output
checksums. Builds produce isolated candidates. Add **`--publish`** to promote a candidate only after
its release audit passes. Run inspectors against the candidate's rendered configuration when
inspecting unpublished products. Do not run two builds against the same candidate directory.

Acquisition commands exist for water geometry, bathymetry, shoreline characterization, freshwater,
estuaries, barriers, substrate, hardness, seagrass, kelp, reef, habitat composite and anthropogenic
structures. Some validate configured local inputs rather than downloading publicly available data.

Python entry points are available under `seascape.<family>`. For example:

```python
from seascape.seafloor_physiography.bathymetry import run_pipeline
run_pipeline(config_path="config/data/project.yaml", skip_download=True, skip_map=True)
```

Set `SEASCAPE_WORKSPACE` when calling Python APIs from a different working directory. Catalog,
species-neutral feature eligibility, documentation and rebuild comparison tools are installed
under `seascape.maintenance` and `seascape.governance`; each accepts `--help` through `python -m`.

Applications should resolve immutable canonical products through the public API rather than
encoding toolkit-internal paths:

```python
from seascape.products import resolve_product

artifact = resolve_product(
    workspace="/path/to/seascape-workspace",
    product="bathymetry",
    resolution=6,
)
print(artifact.release_id, artifact.path, artifact.checksum)
```

`list_products` and `list_resolutions` provide discovery. Resolution is exact and every returned
artifact is checked against a completed release. Paths are retained under `.seascape/releases/<release_id>`;
pass `release_id=artifact.release_id` to select the same release later. See the [API contract](docs/API.md). Applications such as OrcaCast own
target definition, temporal validation, feature/scale selection, model fitting and evaluation.

## Products and contracts

- Spatial support: water polygons, H3 grids, full-cell counting universes, marine support,
  passable water graphs, connectors, neighborhoods, and radius operators.
- Physical seascape: bathymetry, geomorphometry, geomorphic units, shorelines, proximity,
  exposure/enclosure and waterbody shape.
- Hydrology: freshwater sources, fluvial connectivity/barriers and estuarine connectivity.
- Substrate and habitat structure: classification, hardness, seagrass, kelp, reefs and composites.
- Physical built-environment structures, source inventories, quality flags and artifact lineage;
  this is not vessel, access, observer, recreation or effort modeling.

See [scientific and source contracts](docs/CONTRACTS.md), the [product index](docs/products.md),
and the [migration report](docs/MIGRATION.md). The [review remediation record](docs/review-remediation.md) describes scientific validation,
coastal slope stencil changes, and durable release storage introduced after extraction. Products describe
physical conditions and evidence, not species occurrence or habitat preference.

## Validation boundary

Offline tests cover calculations, acquisition identity, missingness, graph contracts, publication,
configuration and orchestration. Three tests require materialized regional products and skip in a
clean checkout. A successful install or test run does not establish a regional rebuild or live
provider availability. OrcaCast integration is deferred. No datasets have been redistributed.
