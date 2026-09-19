# Architecture review remediation — 2026-09-19

All P1/P2 findings F01–F12 in the [pre-fix review](../ARCHITECTURE_CODE_REVIEW.md) have local code,
configuration, documentation or CI corrections. This record supersedes that review's implementation
status, not its historical evidence. Existing unrelated notebook/acquisition/workflow changes were
preserved. No remote publication, regional dataset rebuild or OrcaCast integration was performed.

| Finding | Correction | Regression evidence |
| --- | --- | --- |
| F01, P1 | Exact unique nonnull composite H3 support; confidence aligned to value keys before calculation | Independently permutes every feature/confidence table; rejects missing/duplicate/null/wrong-resolution keys; preserves null versus zero |
| F02, P1 | Transactional copied generations under `.seascape/releases/<release_id>`; historical resolver selection; no generation overwrite | Publish A/B and retain A bytes/manifest; historical resolution; idempotent republish; injected canonical-promotion failure restores A and removes failed generation |
| F03, P1 | Terrain and sill loaders require explicit positive-down sign; numeric negative depth rejected | Unsupported/missing sign rejected by all three loaders; contradictory negative values rejected and nulls retained |
| F04, P1 | Central projected meter-axis validation plus direct spatial/isobath guards | Geographic and foot-based configurations rejected; default UTM accepted; existing physical fixtures retained |
| F05, P1 | Output preflight, declared-output validation, filename checks, symlink confinement and writer guards | Absolute/custom/parent/symlink escapes rejected before builder writes; canonical sentinel unchanged; low-level writer rejection |
| F06, P1 | Effective/transitive config, named-area and resolved environment fingerprint; frozen common config and release provenance | Common bound, inherited YAML and environment-only changes each invalidate resume; unchanged configuration reuses |
| F07, P2 | Fixed Q90 schema requires 0.90 | 0.95 rejected |
| F08, P2 | Supported north-up affine enforced; land/nodata excluded before gradients; method/edge policy recorded | Flat coastal/nodata fixture, rotated rejection, known tilted plane including raster edges |
| F09, P2 | Candidate preparation uses the direct API's resolved configuration path | Composed-value parity, frozen common bounds, explicit reference-cycle failure and custom input base |
| F10, P2 | Small documented consumer/producer API and internal ownership; shared `habitat_network_metrics` replaces private cross-module import | [API contracts](API.md), shared habitat contract tests; no formula change or broad directory migration |
| F11, P2 | Direct urllib3 dependency, quality extra, scoped Ruff/mypy/format gates, Gitleaks, installed dependency audit, outside-checkout wheel checks and recorded scientific environment | Local static/security/package checks below; CI configuration added but hosted jobs not run locally |
| F12, P2 | README matches live San Juan exploratory notebook side effects and Natural Earth mask; offline acceptance remains separate | Notebook guide and current cells inspected; offline production-API notebook executed |

## Executed validation

- Repository tests: **217 passed, three regional-data skips**, including all 24 review regression
  tests. Final full-suite run completed in 7.69 seconds.
- Built a fresh wheel and installed outside the checkout. Imported all 159 package modules with
  OrcaCast imports blocked; 34 product/review tests passed against the installed wheel.
  `pip check`, workspace initialization and the 26-stage CLI dry-run passed.
- Offline validation notebook: all 12 code cells executed, PASS marker verified, no error outputs.
  Output: `/tmp/seascape-hardening-validation.ipynb`; source notebook was not overwritten.
- Ruff bug checks passed over source/tests/scripts; formatting and mypy passed for four hardened
  boundary modules. This is scoped static coverage, not complete legacy strict typing.
- Dependency audit of the recorded runtime/test closure: no known vulnerabilities reported.
  Gitleaks 8.30.1: no leaks reported over all seven Git commits and the nonignored working files.
- Local Graphify code-only graph refreshed (2245 nodes, 6768 edges); cache remains untracked.
- [Scientific environment baseline](environments/README.md) records the macOS ARM64 Python 3.14
  dependency closure plus GDAL, PROJ and GEOS. Hosted Linux Python 3.11/3.14 checks remain CI work.

## Compatibility and scientific limits

Release manifest schema 3 is required by product resolution. Republish existing schema-2 workspaces;
there is no automatic archive migration or generation cleanup. Retained generations consume extra
disk space and must not be manually changed while consumers reference them. Candidate outputs that
previously escaped to custom canonical paths now fail; configure them inside the candidate.

Standalone bathymetry can still emit negative elevation, but terrain/sill consumers require
positive-down inputs. Non-meter planar CRSs and non-Q90 slope settings now fail explicitly.
Native coastal slope sample support can change because land/nodata cannot contribute to gradients;
the angular-distance approximation remains unchanged. Rebuild affected products before comparing
regional outputs. Synthetic tests establish these contracts, not regional error magnitudes.

Three materialized-product tests remain skipped. No live-provider acquisition, complete regional
rebuild/equality comparison, hosted CI execution, remote publishing or downstream application
integration is claimed. Presentation-only configuration and remote sources without local immutable
identity still need explicit rebuild judgment. F13 is P3 and outside this requested fix scope;
its stale local graph portion was refreshed as ordinary navigation maintenance.
