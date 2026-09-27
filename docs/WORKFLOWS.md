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
seascape --workspace /path/to/seascape-workspace build --only seascape-geomorphometry --dry-run --check-inputs --json
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
| `--check-inputs` | With `--dry-run`, inspect selected local prerequisites; return 1 on required missing, invalid or unverified inputs |
| `--json` | With `--dry-run`, emit one JSON planning/preflight report; without `--check-inputs`, inspection status is `not_run` |
| `--candidate-root PATH` | Reuse an explicit candidate location instead of a timestamped default |
| `--resume` | Reuse stages whose recorded checks pass |
| `--overwrite` | Rebuild rather than reuse valid resume state |
| `--publish` | Promote the candidate after the release gate passes |

The default candidate path is `<workspace>/.seascape/candidates/seascape/<UTC timestamp>`.
Use a distinct directory for each independent run. See the [configuration guide](CONFIGURATION.md)
for which paths are isolated and which changes resume checks detect.

Input preflight uses the same dependency expansion and candidate configuration rendering as
execution. It calls existing family configuration loaders in memory, checks local file readability
and GeoTIFF headers, and identifies exact configured intermediates as `generated_by_plan`. It
never creates a candidate, downloads, hashes source datasets, runs producers, cleans outputs or
publishes. The report includes workspace/config selection, expanded stages, default declarations
and actual configured destinations, publication intent, performed checks, corrective actions and
required/optional flags. Workspace precedence remains `--workspace`, `SEASCAPE_WORKSPACE`, cwd.
Pass the same explicit `--candidate-root` to preflight and execution when reusing the exact printed
destination; the timestamped default is resolved separately for each invocation.

`ready` means only the reported preflight checks passed. `missing_external` identifies an absent
local prerequisite; `invalid` identifies failed configuration/access/header checks;
`unverified` identifies a check this inspection cannot establish; `not_applicable` identifies an
unused operation. Generated files still require producer validation. Vector/Parquet schemas,
feature/pixel values, H3 row identity, coverage, datum, checksums and scientific/release acceptance
are not established. Existing plain `--dry-run` behavior is unchanged.

`--skip` requires existing checksum/config/upstream reuse validation, so lightweight preflight
reports required `unverified` and fails instead of hashing datasets. `--resume` identity and a
requested publication audit are deferred and explicitly visible. Kelp annual-layer usability and
reef partial-inventory usability require their producer inspections; preflight reports these as
required `unverified`, even when individual optional source files exist. Directory/archive content
checks are likewise limited: file readability is not proof of usable extracted data. Correct these
through the family workflow and its source guide; preflight cannot approve a release.

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

## 8. Export a metric matrix

```sh
seascape --workspace /path/to/seascape-workspace export-metric-matrix --resolution 6 --output /path/to/owned-exports/seascape-r6.parquet
```

This resolves a completed release and its archived catalog, verifies artifacts and H3 support,
and writes Parquet with embedded export metadata. Choose a distinct output destination; existing output
requires explicit `--overwrite`. The existing `--legacy-unverified --catalog PATH` mode records
structural evidence from a legacy release, not certified release acceptance. It is not a remedy
for checksum failures in a validated release.

## Operation effects

All local artifact publication below is distinct from remote publication. Source acquisition is
explicit through download commands or family pipeline options. File paths, network access and
source rights remain governed by the selected configuration and owning family's source guide.

| Operation | Prerequisites | Network behavior | Writes / replacement and resume | Release effect |
| --- | --- | --- | --- | --- |
| `init` | Writable workspace | None | Packaged config/governance/docs templates; existing files preserved | None |
| `stages`, top-level or family `--help` | Installed package | None | No artifacts | None |
| `demo` / `run_demo` | Fresh owned demo workspace, or intact ownership marker with explicit `--overwrite` | Offline; acquisition disabled | Synthetic fixtures/products/report/figures only in `.seascape/demo`; replacement confined to known owned artifacts | Synthetic software acceptance only |
| `build --dry-run` | Stage selection; reusable artifacts for `--skip` / `--resume` | No acquisition | Prints plan; reuse checks can read/hash existing artifacts; no candidate writes through this CLI | No build or release approval |
| `build --dry-run [--check-inputs] --json` and human input preflight | Selected config; local inputs for input checks | No acquisition; local inspection only | JSON report on stdout or human report; no writes/hashes/producers; failure guidance on stderr | No build or release approval |
| `download FAMILY` | Reviewed config, source rights/access, provider credentials where required | Family-specific HTTP acquisition or local input validation/reuse; see family help/source guide | Configured raw caches, archives and inventories; overwrite/reuse rules vary by family | No whole-release promotion |
| `build` | Configured local inputs and selected dependencies | No downloader is invoked by the candidate runners; source locations must be local | Candidate config/products/manifests/catalog/audit/docs. Fresh directory recommended; producer replacement rules vary, and some producers replace configured outputs even without `--overwrite`. `--resume` / `--skip` require existing identity/checksum validation | Retains candidate by default; selected family products may be published within that candidate |
| `build --resume --publish` | Same candidate/config, valid reuse state, complete passing release audit | No acquisition | Retained generation, canonical compatibility products and release manifest; local journaled promotion. Existing retained releases remain | Whole-release promotion only after existing gates pass |
| `inspect FAMILY` | Existing configured products and presentation config | Local rendering; opening HTML can fetch external basemap tiles | Maps/diagnostics at configured or explicit output paths, which can replace existing visualizations; no resume contract | No scientific release approval |
| `export-metric-matrix` / `build_metric_matrix` | Validated release and archived catalog (or explicit existing legacy mode) | None | Parquet with embedded export metadata at explicit destination; existing output requires `--overwrite`; no resume | Export only; does not publish a release |
| Product discovery/resolution Python facade | Completed release; requested product/resolution/retained identity | None | Reader lock bookkeeping may be created; no data writes | Checksum-verifies existing release/products |
| Direct family Python APIs / `python -m seascape.<family>.<module>` | Family config and required inputs | Varies: pipelines may acquire sources unless their own skip options disable it | Writes configured outputs, family manifests and optional maps. Flags and replacement behavior differ; these are **not isolated candidates** | Family publication where implemented; does not certify/promote a whole release |

Residual hazards: configured direct-family or inspection paths may point at canonical outputs or
standard maps. Choose an owned destination before running them. Candidate producers differ in
replacement behavior; review the configuration and use a fresh candidate to protect prior work.
Resume evidence does not certify new source coverage, units or scientific suitability. Permission,
storage, interruption and unrecognized provider errors can still require detailed debugging;
transaction recovery and release/scientific validation remain mandatory.

## Common problems

Identified failures return exit 1 with the operation, reason, workspace/config or source path,
corrective action and a guide pointer on stderr. Missing configuration, missing local sources,
invalid declared scientific settings, existing export output, incomplete dependencies, checksum
mismatches and publication/recovery failures receive this guidance. Existing JSON preflight fields
and statuses remain authoritative; human guidance does not appear in JSON stdout. Normal build
progress remains human stdout. Family help/parser behavior and Python API exceptions are retained.

Unrecognized errors retain tracebacks. To inspect the original chained exception for an identified
failure, put `--debug` before the command, alongside `--workspace`:

```sh
seascape --workspace /path/to/seascape-workspace --debug build --only seascape-bathymetry
seascape --workspace /path/to/seascape-workspace --debug inspect bathymetry --config config/data/project.yaml
```

`build --debug` is not valid. Debug keeps the same failure code and gates. Preflight remains
read-only and reports its inspection limitations; debug does not run producers to reconstruct
a traceback. Normal CLI diagnostics redact remote locations and sensitive conversion details;
debug tracebacks and provider logs can contain credentials, so review them before sharing.

| Symptom | Next check |
| --- | --- |
| Configuration cannot be found | Confirm workspace selection and run `init` for a new workspace |
| Source input is missing | Inspect the configured path and the family's source guide; a build is not a universal downloader |
| A skipped stage is blocked | Provide valid reusable outputs or remove `--skip` and rebuild |
| Resume reuses output after a geographic/source/code change | Use a fresh candidate or `--overwrite`; see the documented checksum limits |
| Release audit fails | Inspect the reported schema, missingness, manifest or metadata mismatch; correct it before promotion |
| Release/export checksum mismatch | Preserve retained releases; restore verified source bytes or correct and audit a fresh candidate. Do not edit checksums or select legacy mode to clear validation |
| Publication is busy or recovery fails | Wait for the active writer or inspect preserved recovery evidence; keep lock files, journals and trusted releases intact |
| Imports fail in OrcaCast | Application integration remains deferred; use the standalone toolkit interfaces |
