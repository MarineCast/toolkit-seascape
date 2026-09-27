# Three workflows and operation effects

[Documentation index](README.md)

## Offline synthetic demo

Follow the [source installation and first-result commands](../README.md#install-and-get-a-first-result).
Keep its active environment and `SEASCAPE_WORKSPACE`. No editable install, test extra, notebook,
source credentials or data acquisition is needed. Interpretation and safe reruns are in the
[demo guide](demo.md). A synthetic PASS does not establish a regional release.

## Bounded real-data processing

Use a new owned workspace for real inputs. The block below uses the workspace from the quickstart
and only initializes templates and prints a plan; it does not acquire data or build products.
For a separate real-data project, first set `export SEASCAPE_WORKSPACE="/absolute/path/to/owned-workspace"`
(the path is an explicit placeholder). Do not point it at an existing application/data checkout.

<!-- BEGIN QUICKSTART plan -->
```sh
seascape --workspace "$SEASCAPE_WORKSPACE" init
seascape --workspace "$SEASCAPE_WORKSPACE" stages
seascape --workspace "$SEASCAPE_WORKSPACE" build --dry-run
```
<!-- END QUICKSTART plan -->

Before a real build, make the [specific configuration edits](CONFIGURATION.md#before-a-bounded-build).
Inspect the [generated stage input reference](stage-inputs.md) and each family's `DATA_SOURCES.md`
through the [product index](products.md#family-guides). Review source identity, redistribution rights,
spatial bounds and acquisition size. The defaults include a very large `regional_source_area`;
a small analysis area does not guarantee a small provider download. No real-data acquisition or
measured operating envelope is established by the offline guide; that is the separate SS-10 gate.

Family help is safe to inspect, for example:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" download bathymetry --help
```

Actual `download FAMILY --config config/data/project.yaml` commands can contact providers and
write caches. They require separately reviewed source/bounds/resource authorization. Some
families validate local inventories instead. Builds expect configured local sources and never
serve as a universal downloader. Inspect preflight before selecting a fresh candidate.

### Plan and build a candidate

The workflow expects configured source inputs to be available. A subset plan expands dependencies:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-geomorphometry --dry-run
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-geomorphometry --dry-run --check-inputs --json
```

A full build creates products, metadata and a release audit while retaining the candidate by default:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --candidate-root "$SEASCAPE_WORKSPACE/.seascape/candidate"
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

### Inspect existing products

Inspectors render diagnostics; they do not replace a scientific release audit. For canonical outputs:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" inspect bathymetry --help
seascape --workspace "$SEASCAPE_WORKSPACE" inspect bathymetry --config config/data/project.yaml
```

For an unpublished candidate built from the default project entry point:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" inspect bathymetry --config "$SEASCAPE_WORKSPACE/.seascape/candidate/.seascape/config/project.yaml" --output "$SEASCAPE_WORKSPACE/.seascape/candidate/bathymetry.html"
```

Use explicit inspection output paths when keeping diagnostics inside the candidate; presentation
settings may otherwise route maps into the workspace's standard output directory.

### Publish after review

Use the same configuration and candidate directory:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --candidate-root "$SEASCAPE_WORKSPACE/.seascape/candidate" --resume --publish
```

Publication retains a copied generation under `.seascape/releases/<release_id>` and promotes
canonical compatibility paths and the schema-3 release manifest in one journaled transaction.
It is local artifact publication, not a Git push or a public dataset upload. Direct family APIs
can also publish their own outputs; the candidate workflow's release gate is a separate operation.

## Consume an audited release

Use an existing completed schema-3 workspace and the [freeze-and-read Python example](API.md#freeze-and-read-a-release).
The resolver never builds missing products or substitutes a resolution. Preserve retained releases;
checksum failures require restoring verified bytes or auditing a new candidate, not editing metadata.

For a single keyed Parquet export, use the [matrix guide](metric-matrix.md). It freezes one generation,
retains null/zero and evidence distinctions, and records source units/types/checksums. Explicit legacy
mode establishes structural evidence only; it is not a remedy for release checksum failures.

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
seascape --workspace "$SEASCAPE_WORKSPACE" --debug build --only seascape-bathymetry
seascape --workspace "$SEASCAPE_WORKSPACE" --debug inspect bathymetry --config config/data/project.yaml
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
