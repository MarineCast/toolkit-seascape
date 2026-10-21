# Seascape Toolkit

<p align="center">
  <picture>
    <source srcset="docs/assets/seascape-underwater-banner.png">
    <img src="https://raw.githubusercontent.com/MarineCast/toolkit-seascape/main/docs/assets/seascape-underwater-banner.png" alt="Ink coastal cross-section showing islands, seafloor terrain, and kelp" width="100%">
  </picture>
</p>

**The shape, composition, and connectivity of the marine environment.**

[Documentation site](https://marinecast.github.io/toolkit-seascape/) · [Variables](https://marinecast.github.io/toolkit-seascape/variables/) · [Methods](https://marinecast.github.io/toolkit-seascape/methodology/) · [Examples](https://marinecast.github.io/toolkit-seascape/examples/)

Seascape Toolkit turns reviewed geospatial sources into reproducible physical and structural marine features. It supports bathymetry and terrain, modeled substrate, shoreline and waterbody geometry, freshwater connections, mapped vegetation and reef evidence, built coastal features, and the H3 water support that relates them. It is an independently installable Python package; no OrcaCast checkout is required.

The toolkit is for researchers, GIS users, and downstream applications that need analysis-ready features with source lineage, spatial support, and explicit missingness. Physical conditions and mapped evidence do **not** establish species occurrence or habitat suitability. Regional source data are not bundled. Completed outputs are flat per-area Parquets in `Data/Seascape` plus one `catalog.json` tracking when each area was last updated.

## v0.1.1 status and compatibility

**v0.1.1 is a public preview**, not a stable `1.0` contract. It supports Python 3.14 on the Linux
x86_64 and macOS ARM64 environments exercised by CI. Other operating systems are not currently
claimed. During `0.x`, documented minor releases may change APIs, CLI behavior, schemas, variables,
or scientific methods; patch releases preserve intended public and scientific contracts.

The toolkit records source lineage, configuration, checksums, spatial support, missingness, and
versioned scientific interpretations so results can be reproduced and compared. Those records do
not remove source-specific limitations: regional coverage, rights, horizontal CRS, vertical datum,
resolution, and accuracy must be reviewed for each source. The synthetic demo does not
validate regional accuracy, species habitat, navigation safety, or predictive fitness.

Data use stable filenames: `<area>-r<resolution>-static.parquet` has one row per native H3 cell;
`<area>-r<resolution>-dynamic.parquet`, when available, adds a `date` column. There are at most two
Parquets per area and resolution, no dated filenames, no data releases and no retained generations.
Definitions, units, source context and coverage limits live inside Parquet metadata.
`catalog.json` is the only companion file for these H3 tables. Optional separately keyed research
objects live in `research/` and are preserved by rebuilds. Study registries reference these
canonical products without maintaining duplicate study copies. See [data layout](docs/metric-matrix.md).
Software and scientific methods still have their own version policies; see the
[software release process](docs/development/releases.md).

## Install and get a first result

After publication to PyPI, install the software with Python 3.14:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install toolkit-seascape
```

For a reproducible installation, pin a published version, for example
`python -m pip install toolkit-seascape==0.1.1` once that version is available on PyPI.
Installation retrieves declared Python dependencies; the package does not include regional
scientific datasets.

Contributors and maintainers validating the source-install quick start can clone
[the repository](https://github.com/MarineCast/toolkit-seascape) and run the following from its
root. This exercised source path also checks the documentation example:

<!-- BEGIN QUICKSTART install -->
```sh
SEASCAPE_ENV="$PWD/.venv"
python3.14 -m venv "$SEASCAPE_ENV"
. "$SEASCAPE_ENV/bin/activate"
python -m pip install 'pip>=26.2'
python -m pip install .
python -m pip check
```
<!-- END QUICKSTART install -->

For iterative development in the cloned checkout, use
`python -m pip install -e '.[test,docs,quality]'`.

Leave the checkout and select a fresh owned workspace:

<!-- BEGIN QUICKSTART demo -->
```sh
cd "$(mktemp -d "${TMPDIR:-/tmp}/seascape-first-result.XXXXXX")"
export SEASCAPE_WORKSPACE="$PWD/seascape-workspace"
seascape --workspace "$SEASCAPE_WORKSPACE" demo
```
<!-- END QUICKSTART demo -->

The CLI prints `Synthetic software acceptance: PASS (not a regional release)` after validating the production bathymetry transform on synthetic inputs. It reports paths to Parquet, manifest, JSON report, and figures under `$SEASCAPE_WORKSPACE/.seascape/demo/`. Missing depth stays null; this is a software check, not a regional accuracy claim. See the [full quick start](https://marinecast.github.io/toolkit-seascape/getting-started/quick-start/) and [demo guide](docs/demo.md).

## What to read next

| Goal | Documentation |
| --- | --- |
| Install and configure | [Installation](https://marinecast.github.io/toolkit-seascape/getting-started/installation/) · [Configuration](docs/CONFIGURATION.md) |
| Find exact fields and coverage limits | [Variable catalog](https://marinecast.github.io/toolkit-seascape/variables/) · [Product index](docs/products.md) · [Capability coverage](docs/capability-coverage.md) |
| Review sources and calculations | [Data sources](https://marinecast.github.io/toolkit-seascape/data-sources/) · [Methodology](https://marinecast.github.io/toolkit-seascape/methodology/) · [Scientific contracts](docs/CONTRACTS.md) |
| Process real inputs | [Bounded workflow](docs/WORKFLOWS.md#bounded-real-data-processing) · [Stage prerequisites](docs/stage-inputs.md) |
| Read current area tables | [Python API](docs/API.md) · [Metric matrix](docs/metric-matrix.md) |
| Contribute or release | [Development guide](docs/DEVELOPMENT.md) · [Release process](docs/development/releases.md) · [Documentation site source](docs/index.md) |

Source rights and attribution are provider-specific; the software license is [Apache-2.0](LICENSE). The [documentation site](https://marinecast.github.io/toolkit-seascape/) is built with MkDocs Material and deployed from `main` by GitHub Actions. Contributors can run it locally with `python -m pip install -e ".[docs]"`, `mkdocs serve`, and `mkdocs build --strict`.

The explicit coastal shared-study profile, named outlet/passage/gateway research products and
remaining source qualifications are documented in [source closure](docs/source-closure.md).

## Kelp extent

The [Kelp contract](docs/kelp.md) defines one dataset with **Annual Kelp Extent**
and **Kelp Extent (All Time)**. Both measure mapped positive bed-extent polygon
unions in full native H3 cells, m². All available historical survey years are
retained; undated Canadian legacy mapping is explicitly qualified in All Time.
Missing evidence is unknown, not an absence mask. The current producer replaces
separate annual-footprint and mapped-kelp-mosaic output families.

## Seagrass extent

The [Seagrass contract](docs/seagrass.md) exposes only **Seagrass Extent (All Time)** in **Biogenic Habitats**. It unions mapped WA eelgrass polygons, legacy BC CRIMS polygons and positive 2019–2020 / 2023–2024 Sentinel-2 composite footprints, retaining all original dates, methods and species resolution as provenance. The annual generated feature was retired without removing its mapped evidence from All Time. Overlaps count once; missing positive evidence remains unknown.

## Bivalve extent

The [Bivalve contract](docs/bivalve.md) defines the static **Bivalve Extent (All-Time)** mapped-bed union, source admission, temporal caveats and bounded replay. Scientific source identity and provenance remain distinct from the Biogenic Habitats presentation family.
