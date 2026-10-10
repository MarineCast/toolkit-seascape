# toolkit-seascape agent guidance

## Scope and current state

Bathymetry, marine geomorphology, coastal geometry, and derived features.

The toolkit owns species-neutral product schemas, static feature eligibility and immutable release
resolution. Applications own prediction targets, temporal validation, predictive feature/scale
selection, model fitting and evaluation.

This repository contains the installable `seascape` package extracted from OrcaCast on 2026-09-15.
Preserve unrelated changes and read deeper instructions before editing a subdirectory.

## Shared MarineCast context

For boundary, dependency, shared schema/provenance, or application-integration changes, read
[INFRASTRUCTURE.md](https://github.com/MarineCast/.github/blob/HEAD/INFRASTRUCTURE.md).
In the grouped workspace use `../../.github/INFRASTRUCTURE.md`; in a flat clone layout use
`../.github/INFRASTRUCTURE.md`, resolving from this checkout. Otherwise use the linked copy;
if unavailable, report the limitation without inventing a shared standard. Sibling instructions
are not inherited. Local implementation contracts remain authoritative; surface conflicts.

## Domain contracts

Preserve horizontal CRS, vertical datum, depth/elevation sign conventions, units, raster alignment,
and nodata masks. Define the spatial scale and neighborhood used by derived terrain metrics.
Keep land/water classification and missing coverage explicit. Geomorphology describes physical
features; species habitat suitability belongs in a downstream application.

## Implementation boundaries

- Keep this toolkit species-neutral and independently installable; do not require an OrcaCast
  checkout or import through sibling filesystem paths.
- Before adding a pipeline, define source rights, input/output grain, units, spatial and temporal
  support, missingness, provenance, and validation in the repository documentation.
- Add dependency declarations and runnable setup/validation commands with the implementation;
  do not copy viewshed's GDAL stack or commands unless this toolkit actually needs them.
- Prefer deterministic calculations and small synthetic/offline fixtures. Keep credentials,
  downloads, and large generated products out of tracked source.
- Keep unknown and unavailable values distinct from observed zero. Validate uniqueness and join
  cardinality rather than silently dropping conflicting records.

## Task routing and checks

Use isolated Python 3.14: `python -m pip install -e '.[test]'`. No local skills are required;
load only the matching guidance. Run `git status --short` before edits and preserve unrelated work.

| Task | Guidance and required checks |
| --- | --- |
| Setup / extraction history | [README](README.md) / [migration](docs/MIGRATION.md), respectively |
| Ownership or imports | [Architecture](docs/ARCHITECTURE.md), relevant tests, then full suite |
| Scientific or product change | [Contracts](docs/CONTRACTS.md), focused tests, then full suite |
| Documentation or examples, including prose-only | References/diff; `python scripts/check_docs.py`; `python -m pytest -q tests/test_documentation.py` |
| Planner / input preflight | [Offline checks](docs/agent-checks.md#offline-demo-checks): preflight/workflow tests, then full suite |
| Demo / CLI / diagnostics | [Offline checks](docs/agent-checks.md#offline-demo-checks): demo/diagnostic/product tests and wheel-runtime acceptance as applicable |
| User-visible workflow, schema, workspace or representative API | [Validation notebook](docs/agent-checks.md#validation-notebook); assess notebook update and run its applicable checks |
| Validation notebook / packaging / consumer acceptance | [Offline checks](docs/agent-checks.md#offline-demo-checks), relevant tests/full suite and clean installed-package checks |
| Executable documentation checks | [Documentation checks](docs/agent-checks.md#documentation-checks), full suite and review-hardening checks |
| Audit / promotion / passage sections | [Review-hardening checks](docs/agent-checks.md#review-hardening-checks), regression/release/passage tests, full suite and quality/security/package checks |
| Acquisition, regional processing or release execution | [Workflows](docs/WORKFLOWS.md), explicit inputs/outputs and release gates; separate from software tests |

For behavior changes, run the smallest relevant tests first, then `python -m pytest -q` and every
matching conditional gate. Prose-only edits require the focused documentation checks above,
not the full package suite. Detailed commands and acceptance boundaries are preserved in
[conditional agent checks](docs/agent-checks.md); do not preload unrelated sections.
`seascape build --dry-run` inspects stage dependencies, not scientific success. Three
materialized-product tests skip without regional data. Add appropriate checks for new behavior
and document their exact commands in the matching check guide.

## Navigation and completion

Use scoped `rg` for known paths/literals. An existing local `graphify-out/graph.json` may locate
relationships after checking relevant manifest/source coverage and freshness; fall back to source
search if missing/stale/incomplete. Known symbols use `explain` before filtered callers; no-match
is not proof of no usage, and `--budget` is not a hard cap. Read current source/tests; they outrank
schemas/contracts, architecture and graphs. Optional [navigation details](docs/agent-checks.md#codebase-navigation)
retain the commands, code-only maintenance and local-only sharing policy. Do not install, refresh,
export, enable hooks/merge drivers or overwrite instructions merely for a question.

Inspect the diff, verify names/references and run `git diff --check`. Report checks actually run,
skips/missing inputs, acquisition and unrun regional/native/integration paths accurately. Keep
credentials/downloads/generated outputs untracked. Historical reports, synthetic publisher tests,
notebook acceptance and hosted job configuration do not certify a current regional release.

## Shared study planning adapter

`seascape.study` validates explicit study-v1 JSON with its packaged schema. No implicit
workspace/sibling config discovery is permitted. The adapter supports planning and synthetic core
software acceptance only; production stays
blocked until marine reporting membership and distinct compute halos are integrated. Preserve
standalone behavior and do not relax this hold based only on domain.status=approved.
For adapter/config/CLI changes run `python -m pytest -q tests/test_study.py tests/test_preflight.py
tests/test_workflow.py tests/test_cli_diagnostics.py`, then the full suite and quality/docs gates
above. Fixtures are provenance/software checks, not shared-domain certification.
For shared-support artifact/consumer changes first run `python -m pytest -q tests/test_study_support.py
tests/test_study.py`, then the full suite and quality/docs gates. The support reader and explicit
bathymetry cell API do not enable CLI production or certify source/halo qualification.
For bounded scientific study routes run `python -m pytest -q tests/test_study_support.py
tests/domains/environment/seascape/test_bathymetry_contracts.py
tests/domains/environment/seascape/test_geomorphometry_contracts.py`, then full suite and quality/docs
gates. Check `python -m mypy src/seascape/study_support.py src/seascape/study_routes.py` in addition
to configured interface checks. Synthetic route provenance never qualifies a regional release.
For the synthetic study core CLI also check `python -m mypy src/seascape/study_core.py` and run
`tests/test_study_support.py` for mandatory/optional capability closure, retained schema3 software
release verification and tamper rejection. The owned fixture namespace and false regional release
eligibility are required; do not reuse the fixture audit as a regional audit PASS.
For native receipt/probe/pilot changes run `tests/test_study_native.py` and `tests/test_study_support.py`,
then the full suite and quality/docs gates. Include `src/seascape/study_native.py` in explicit mypy
checks. The bounded source probe is non-reporting; real pilot evidence must stay source-relative,
with false regional/artifact publication eligibility and no automatic acquisition.
For bounded GEBCO acquisition changes run `tests/test_gebco_subset_acquisition.py`, then the full
suite and quality/docs gates. Explicitly check `python -m mypy
src/seascape/seafloor_physiography/bathymetry/subset_acquisition.py`.
See [acquisition contract](docs/gebco-subset-acquisition.md). Offline fixtures never submit real
queue requests or qualify reporting support. Live source acquisition is a separate reviewed,
resource-coordinated action; preserve ZIP, receipts and old cache bytes.
For explicit source land/water adoption run `tests/test_source_partition.py`, then full suite
and quality/docs checks. Check `python -m mypy src/seascape/spatial_support/water_geometry/partition.py`.
See [partition adoption](docs/source-land-water-partition.md). Retain tile/union semantics and
source exceptions; the engineering reporting selector never becomes the definition of water.

For bounded graph execution run `tests/test_bounded_graph_execution.py` and
`tests/domains/environment/seascape/spatial_support/test_water_network.py`, then the full suite,
quality and documentation checks. Verify retained regional pilot parity before a regional run.
See [bounded graph execution](docs/bounded-watergraph-execution.md). Output-source batching must
retain the full traversal graph, connector semantics and scientific source/halo qualifications.

For physical shoreline length changes run
`python -m pytest -q tests/domains/environment/seascape/test_shoreline_characterization.py`,
then the full suite, quality and documentation checks. Verify source-record repetition,
partial overlaps, classification-availability disagreements and nearby distinct lines.
Physical numerators and denominators count geometric unions, while source evidence retains
all records. See the producer's `DATA_SOURCES.md`; survey coverage remains separate.

For anthropogenic source classification changes run
`python -m pytest -q tests/domains/environment/seascape/test_anthropogenic_contracts.py`,
then the full suite, quality and documentation checks. Verify that Approved and Prohibited
shellfish harvest classifications cannot establish aquaculture footprint/presence or suppress
OSM aquaculture records; legitimate physical inventory matches still govern deduplication.

For DNR annual kelp processing-era changes run
`python -m pytest -q tests/domains/environment/seascape/test_kelp_processing_eras.py`,
then the full suite, quality and documentation checks. Preserve vector/CAD 1989–1992,
unsurveyed 1993, approximately 20 m raster 1994–2009 and approximately 4 m raster 2010–2024.
Processing labels must not change source geometry, observation years or scientific values.
