# Seascape Toolkit documentation

The toolkit downloads or validates source inputs, builds physical marine-environment products,
and publishes validated releases. Installable distribution: `toolkit-seascape`; import package
and command: `seascape`.

## Start here

1. Follow [setup and workflows](WORKFLOWS.md) to install the package, initialize a workspace,
   acquire inputs, and plan a build.
2. Read [configuration](CONFIGURATION.md) before changing geographic areas, sources or outputs.
3. Use [architecture](ARCHITECTURE.md) to locate the code that owns a product or operation.
4. Read [development and validation](DEVELOPMENT.md) before changing calculations or publication.

## Reference

| Document | Purpose |
| --- | --- |
| [Python API](API.md) | Supported entry points, errors and side effects |
| [Review remediation](review-remediation.md) | P1/P2 corrections and validation evidence |
| [Environment baseline](environments/README.md) | Python and native-library versions |
| [Scientific and source contracts](CONTRACTS.md) | Grain, units, support, missingness, provenance and source rights |
| [Product index](products.md) | Family guides, cataloged fields, collection paths and inspection guidance |
| [H3 metric matrix](metric-matrix.md) | Single-Parquet export, source validation and field semantics |
| [Migration report](MIGRATION.md) | Extraction scope, executed checks and deferred OrcaCast integration |
| [Hardening review](hardening-review.md) | Clean-checkout repairs, architecture decisions, validation and remaining blockers |
| [Transfer inventory](migration-inventory.json) | Original file hashes and transferred destinations |

Source-specific `DATA_SOURCES.md` files remain beside their producers. The product index links
to those family guides rather than duplicating provider-specific instructions here.

## What these docs establish

The repository contains an independently installable package, CLI, configuration templates and
an offline test suite. It does not ship the regional source datasets. Installing the package or
initializing a workspace does not download sources, rebuild regional products or certify a release.
The migration report records the validation performed during extraction; it is a dated record,
not an assertion that subsequent changes have passed those checks. OrcaCast integration is deferred.

Return to the [repository overview](../README.md).
