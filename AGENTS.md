# toolkit-seascape agent guidance

## Scope and current state

Bathymetry, marine geomorphology, coastal geometry, and derived features.

This repository contains the installable `seascape` package extracted from OrcaCast on 2026-09-15.
Read README.md and docs/MIGRATION.md for ownership and validation boundaries.
Preserve unrelated changes and read deeper instructions before editing a subdirectory.

## Shared MarineCast context

Before changing repository boundaries, dependencies, shared schemas, provenance, or application
integration, read the MarineCast [infrastructure guide](https://github.com/MarineCast/.github/blob/HEAD/INFRASTRUCTURE.md).
Resolve local paths from this toolkit's checkout root, not the agent's working directory.
For `MarineCast/Toolkits/toolkit-*`, use `../../.github/INFRASTRUCTURE.md`;
for a flat `MarineCast/toolkit-*` layout, use `../.github/INFRASTRUCTURE.md`.
Prefer that local copy when present; in an independent checkout, read the linked document. If it
cannot be retrieved, report that limitation and use the local contracts below; do not invent a
shared standard. These instructions explicitly request that reading; a sibling repository's
`AGENTS.md` is not automatically inherited.

The infrastructure guide owns cross-repository context. This repository owns its implementation
and scientific contracts. Surface conflicts before changing an interface; do not silently replace
an existing local contract with a proposed ecosystem convention.

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

## Validation and completion

For documentation-only work, inspect `git status --short` and the diff, verify references, and run
`git diff --check` from this repository. Run `python -m pytest -q` from this checkout after installing `.[test]`.
Use `seascape build --dry-run` to inspect stage dependencies. Real acquisition and regional builds
are separate from offline tests; three materialized-product tests skip without regional data.
When adding executable behavior, add appropriate checks and document their exact commands here.
Report tests actually run, unverified source acquisition, and any unrun integration paths.

## Codebase navigation

Use this repository's local Graphify graph for structural implementation, debugging, and
architecture questions before broad searches. Skip graph queries for obvious, single-file edits.
Narrow modules, symbols, callers and dependencies with `query`, `explain`, or `affected`, then
read the relevant source and tests. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design intent.
Source and tests are authoritative; explicit schemas/contracts and architecture docs take
precedence over the graph. Static edges can miss dynamic dispatch or resolve names ambiguously;
fall back to targeted `rg` searches whenever coverage or freshness is insufficient.

Run from this checkout (Graphify CLI package `graphifyy==0.9.62`, Python 3.10+):

```bash
# Install once in an isolated developer environment: python -m pip install graphifyy==0.9.62
graphify extract . --code-only --no-cluster
graphify query "DomainBuildStage" --budget 1500
graphify explain "DomainBuildStage"
graphify affected "<symbol>" --relation calls --depth 2
```

Repeat the extraction command after structural edits: it incrementally detects changed files.
Use `--force` for a full rescan after checking intentional removals if shrink protection blocks
refresh. The graph and caches live in ignored `graphify-out/`; never commit them. `.gitignore`
and `.graphifyignore` both apply. This local AST-only setup does not semantically index prose or
produce clustered architecture reports; read docs/configuration directly when needed.

Codex can use the global Graphify skill (`graphify install --platform codex`) or this section
plus the CLI. The MarineCast workspace documents the machine-local skill installation. From a parent
workspace, change into this checkout before building; queries may instead use
`--graph <checkout>/graphify-out/graph.json`. Keep each repository's graph independent.
The distinct `graphify codex install` command adds repo instructions/hooks; do not run it
over this maintained section. Global skill defaults do not override this repository's scope
or its code-only extraction commands.
Optional `graphify hook install` adds post-commit/post-checkout hooks **and** a merge driver with
`.gitattributes` changes; it is not enabled or recommended by default for these untracked graphs.
See the [upstream CLI reference](https://graphify.com/docs/cli) and `graphify --help` on upgrades.

Graph ownership policy: `graphify-out/` is a disposable, local-only cache per checkout, with no
planned automatic sharing or publication. Share source, navigation configuration and commands;
rebuild the graph locally. Sharing a graph later requires an explicit repository policy change
covering its destination, source revision, generation version, freshness and content review.
