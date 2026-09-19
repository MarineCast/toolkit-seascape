# Setup and workflows

[Documentation index](README.md)

## 1. Install from the checkout

Use Python 3.11+ on Linux or macOS with compatible geospatial libraries. Publication uses POSIX
file locks. From the repository root:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
seascape --help
```

Use `python -m pip install .` for a regular installation. Python 3.14 was exercised during extraction;
see the dated [migration report](MIGRATION.md) for the exact verification boundary.

## 2. Initialize and review configuration

The example paths below are placeholders; replace them with absolute paths on your machine.

```sh
seascape --workspace /path/to/seascape-workspace init
seascape --workspace /path/to/seascape-workspace stages
seascape --workspace /path/to/seascape-workspace build --dry-run
```

Review [configuration](CONFIGURATION.md) and the [source contracts](CONTRACTS.md) before running
acquisition. Initialization supplies templates and reference metadata, not regional data.

## 3. Acquire or provide source inputs

Each acquisition family has its own options:

```sh
seascape --workspace /path/to/seascape-workspace download bathymetry --help
seascape --workspace /path/to/seascape-workspace download bathymetry --config config/data/project.yaml
seascape --workspace /path/to/seascape-workspace download water-geometry --config config/data/project.yaml
```

These examples are not a complete acquisition recipe for all families. Supported download selectors
are `water-geometry`, `bathymetry`, `shoreline-characterization`, `freshwater-sources`,
`estuarine-connectivity`, `fluvial-barriers`, `substrate-classification`, `bottom-hardness`,
`seagrass`, `kelp`, `reef`, `habitat-composite` and `anthropogenic`.

Some commands validate local inputs or reuse another family's sources. Follow the owning family's
`DATA_SOURCES.md`, linked through the [product index](products.md), for provider access, licensing,
coverage and local-file requirements. Use each command's help for overwrite behavior.

## 4. Build a candidate

The workflow expects configured source inputs to be available. A subset plan expands dependencies:

```sh
seascape --workspace /path/to/seascape-workspace build --only seascape-geomorphometry --dry-run
```

A full build creates products, metadata and a release audit while retaining the candidate by default:

```sh
seascape --workspace /path/to/seascape-workspace build --candidate-root /path/to/seascape-workspace/.seascape/candidate
```

| Option | Behavior |
| --- | --- |
| `--config PATH` | Select an entry-point YAML; default `config/data/project.yaml` |
| `--only STAGE` | Select a stage and its dependencies; repeat for several targets |
| `--skip STAGE` | Require validated reusable output rather than silently omitting a dependency |
| `--dry-run` | Print the plan without running builders |
| `--candidate-root PATH` | Reuse an explicit candidate location instead of a timestamped default |
| `--resume` | Reuse stages whose recorded checks pass |
| `--overwrite` | Rebuild rather than reuse valid resume state |
| `--publish` | Promote the candidate after the release gate passes |

The default candidate path is `<workspace>/.seascape/candidates/seascape/<UTC timestamp>`.
Use a distinct directory for each independent run. See the [configuration guide](CONFIGURATION.md)
for which paths are isolated and which changes resume checks detect.

## 5. Inspect existing products

Inspectors render diagnostics; they do not replace a scientific release audit. For canonical outputs:

```sh
seascape --workspace /path/to/seascape-workspace inspect bathymetry --help
seascape --workspace /path/to/seascape-workspace inspect bathymetry --config config/data/project.yaml
```

For an unpublished candidate built from the default project entry point:

```sh
seascape --workspace /path/to/seascape-workspace inspect bathymetry --config /path/to/seascape-workspace/.seascape/candidate/.seascape/config/project.yaml --output /path/to/seascape-workspace/.seascape/candidate/bathymetry.html
```

Use explicit inspection output paths when keeping diagnostics inside the candidate; presentation
settings may otherwise route maps into the workspace's standard output directory.

## 6. Publish after review

Use the same configuration and candidate directory:

```sh
seascape --workspace /path/to/seascape-workspace build --candidate-root /path/to/seascape-workspace/.seascape/candidate --resume --publish
```

Publication retains a copied generation under `.seascape/releases/<release_id>` and promotes
canonical compatibility paths and the schema-3 release manifest in one journaled transaction.
It is local artifact publication, not a Git push or a public dataset upload. Direct family APIs
can also publish their own outputs; the candidate workflow's release gate is a separate operation.

## 7. Resolve a published product

Consumers should use the canonical release API instead of copying internal paths:

```python
from seascape.products import list_products, list_resolutions, resolve_product

print(list_products(workspace="/path/to/seascape-workspace"))
print(list_resolutions("bathymetry", workspace="/path/to/seascape-workspace"))
artifact = resolve_product(
    workspace="/path/to/seascape-workspace",
    product="bathymetry",
    resolution=6,
)
```

The resolver holds a consistent snapshot, requires a completed canonical release, validates
governed and family manifests, verifies the selected artifact checksum, and returns immutable
identity/provenance and retained generation paths. Pass `release_id=artifact.release_id` to resolve
a historical generation. Older schema-2 releases require republishing. See [API contracts](API.md).
It never falls back to another resolution. Applications choose predictive
features and scales after freezing these physical products.

## Common problems

| Symptom | Next check |
| --- | --- |
| Configuration cannot be found | Confirm workspace selection and run `init` for a new workspace |
| Source input is missing | Inspect the configured path and the family's source guide; a build is not a universal downloader |
| A skipped stage is blocked | Provide valid reusable outputs or remove `--skip` and rebuild |
| Resume reuses output after a geographic/source/code change | Use a fresh candidate or `--overwrite`; see the documented checksum limits |
| Release audit fails | Inspect the reported schema, missingness, manifest or metadata mismatch; correct it before promotion |
| Imports fail in OrcaCast | Application integration remains deferred; use the standalone toolkit interfaces |
