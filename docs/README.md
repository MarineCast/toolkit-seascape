# Seascape documentation

Start with the [installation and first result](../README.md#install-and-get-a-first-result).
The software package supplies algorithms, configuration templates and an offline demo; it does
not include regional source datasets or an audited release.

## Three user journeys

| Journey | What you need | What it establishes |
| --- | --- | --- |
| [Offline synthetic demo](demo.md) | Installed runtime; a fresh owned workspace | A real production transformation and explicit synthetic acceptance checks |
| [Bounded real-data processing](WORKFLOWS.md#bounded-real-data-processing) | Reviewed source rights/bounds, configured local inputs, suitable scientific settings | An isolated candidate; preflight alone does not validate science or authorize publication |
| [Audited-release consumption](API.md#freeze-and-read-a-release) | An existing completed schema-3 release | Frozen product identities, exact resolution and verified checksums |

The [validation notebook](../notebooks/README.md) is an optional readable client of the demo.
The live explorer is a separate research path with explicit acquisition and exploratory support.

## Current reference

| Document | Purpose |
| --- | --- |
| [Workflow and operation effects](WORKFLOWS.md) | Planning, processing, inspection, promotion and failure guidance |
| [Configuration](CONFIGURATION.md) | Workspace precedence, editable settings, candidate isolation and reuse limits |
| [Stage input reference](stage-inputs.md) | Default prerequisites generated from the existing planner/preflight metadata |
| [Python API](API.md) | Supported producers/readers, exceptions and a release-frozen consumer example |
| [Matrix export](metric-matrix.md) | Key alignment, field provenance, source units/types and legacy limits |
| [Scientific/source contracts](CONTRACTS.md) | Grain, support, CRS, depth sign, missingness and source rights |
| [Reference product index](products.md) | Family guides and the checked-in historical catalog, not a certified current release |
| [Architecture](ARCHITECTURE.md) | Producer ownership and repository map |
| [Development](DEVELOPMENT.md) | Tests, packaging, documentation checks and release-owner boundaries |
| [Tested environments](environments/README.md) | Observed platform coverage, dependency baseline and static-check scope |
| [Roadmap progress](roadmap/PROGRESS.md) | Per-task executed evidence and remaining limits |

## Dated records

[Extraction (2026-09-15)](MIGRATION.md), [hardening (2026-09-17)](hardening-review.md),
[review remediation (2026-09-19)](review-remediation.md) and the
[transfer inventory](migration-inventory.json) record historical work. Their test counts,
consumer/release statements and paths are not current-run evidence. Follow current guides and
the progress record when deciding what has been verified.
