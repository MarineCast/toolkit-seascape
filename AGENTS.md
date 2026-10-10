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
