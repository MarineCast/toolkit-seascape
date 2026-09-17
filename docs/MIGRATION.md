# OrcaCast seascape extraction — 2026-09-15

> This is the dated extraction record. Subsequent clean-checkout repairs, static feature-eligibility
> ownership, immutable product resolution and validation are recorded in
> [hardening-review.md](hardening-review.md).

## Result

`toolkit-seascape` owns seascape acquisition, processing, inspection, product metadata and release
publication. The distribution installs the `seascape` package and CLI. Installation and tests do
not require OrcaCast or sibling toolkits. OrcaCast's seascape producer tree, producer tests,
configuration, maintenance scripts, producer registry entries and build stages were removed.

## Preserved and changed

| Before | After | Reason |
| --- | --- | --- |
| `orcacast.domains.environment.seascape` | `seascape` | Independent Can you package ownership |
| OrcaCast shared config/geometry/artifact imports | Toolkit-owned support modules | No application dependency |
| Root discovery from source-file location | Current directory or `SEASCAPE_WORKSPACE` / `--workspace` | Regular wheel installations can use an external data workspace |
| Seascape release also rebuilds and promotes weather | 26 seascape-only stages and release gate | Separate physical domains and ownership |
| Combined environment catalog | Separate seascape and meteorological catalogs | Each producer owns its metadata |
| Application-only bathymetry entry point | Explicit download and inspection CLI entry points | Both operations work independently of rebuilding |
| Seascape producer registrations in application catalog | 75 toolkit dataset registrations | All toolkit dependencies resolve locally |

The original 125 seascape Python modules and their scientific formulas were carried over, with
namespace/path changes. Source/license guides, producer tests, the regional configuration, policy,
product catalog and maintenance code moved with them. Generic shared helpers were copied into
the toolkit and remain in OrcaCast for its other domains. No compatibility seascape package remains
inside OrcaCast.

`migration-inventory.json` records the originating Git revision, source working-tree SHA-256 values
and destination paths for 177 directly transferred files. It includes the pre-existing uncommitted
shoreline acquisition change and acquisition-identity test. Their content was migrated from the
working tree, not reset to HEAD. Other OrcaCast worktree changes were preserved.

Additional extracted portions were the dataset registry, generic workflow engine and its seven
orchestration tests. OrcaCast's mixed registry, workflow, CLI, configuration catalogs, environmental
catalog generator, generated catalog and CI were edited at the ownership boundary. Its seascape-only
lint config was retired. MarineCast organization documentation now reflects the implemented toolkit.

## Deferred OrcaCast integration

Application-owned species analyses and consumers were retained. They are not toolkit producers.
These source modules still reference the former internal package and need explicit integration in
a subsequent change:

- `models/sightings/smoothing.py`
- `models/sightings/model_zoo.py`
- `domains/whale/sightings/aggregation.py`
- `domains/whale/sightings/imputation/marine.py`
- `domains/whale/sightings/imputation/surface.py`
- `publishing/prep/geo.py`

Application feature assembly, research notebooks and models also reference product paths or the
old model-policy path. They must select toolkit products and manifests explicitly when integration
resumes. This extraction does **not** claim that those application paths can currently run.
OrcaCast's old `data build environment` and `data build sightings universe` producer commands were
removed; its weather, population, sightings-consumer and viewshed commands remain.

Large raw sources, processed products and research outputs remain in their existing locations.
No data was downloaded, copied into tracked source, redistributed or rebuilt regionally. Configure
a toolkit workspace and provide/acquire its inputs before a production build. Reference metadata
is inherited from prior materializations, not certified evidence of a release of this package.

## Executed validation

- **181 passed, 3 skipped** in the standalone offline suite on Python 3.14. Skips require regional
  materialized products. Original calculation, acquisition identity, graph, missingness, manifest,
  publication and policy tests were retained.
- All 13 download-family and 21 inspection-family CLI help routes passed.
- Wheel built and installed without installing OrcaCast as a dependency. The test virtual environment
  reused existing third-party scientific libraries; a fresh dependency download was not exercised.
- From `/tmp`, **150 installed modules imported with OrcaCast imports explicitly blocked**.
- Installed CLI initialized a separate workspace and planned all **26** release stages.
- Installed Python API built a synthetic R6 universe of **19 unique water cells** and passed
  resolution, schema, manifest and artifact-checksum validation.
- All **75** registered dataset dependencies resolved inside the toolkit.
- Every source file parsed using Python 3.11 syntax rules. Python 3.11 runtime validation is
  configured in CI but was not executed locally; the remote CI job was not run.
- Generated product documentation passed its `--check` command.
- OrcaCast: **11 focused meteorological/catalog tests passed**; remaining 13 workflow stages
  resolved and its build-command help loaded. This is not a full application integration test.
- Git whitespace checks and transfer-inventory checks passed in the affected checkouts.

Live provider access, complete regional rebuild/equality comparison, map rendering, production
release promotion and full OrcaCast model/forecast execution were not performed. No commits or
remote pushes were made. See README.md for reproducible install and execution commands.
