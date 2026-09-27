# Offline research candidate and maintainer handoff

VERIFY-01 review, September 27, 2026. Tested source commit:
**`50675db2bef48d3e48de56ec02a5c98a992808ca`**, on
`feature/seascape-repository-organization-updates`. FIX-01 (`f98a36b`) and FIX-02 (`9755f94`)
are separate commits. README installs immutable `9755f94f4ae50957f5c1af5316afb3e3cda26e54`,
which contains both fixes; the tested child adds external-wheel regressions and that README pin,
with identical package source bytes. The subsequent handoff changes repository documentation
only and is not substituted for this tested artifact. Earlier SS-11 evidence remains dated in
[progress and exact commands](roadmap/PROGRESS.md#focused-review-fixes-september-27).

**Decision: software acceptance supports review of an offline research candidate. Hold public
release approval.** Human usability, version-policy approval and classic branch-protection review
remain pending. [SS-10](pilots/san-juan.md) remains blocked; no real-data gate, regional scientific
certification or production-readiness claim is made. A feature push is not merge/tag/package/data
publication permission.

## Proposed release notes

### New capabilities

- A runtime-only installed-wheel demo uses the production bathymetry transformation with tiny
  synthetic fixtures, explicit provenance, real Parquet/manifests, validation results and offline
  figures. All demo artifacts belong to `.seascape/demo`.
- A copied validation notebook calls the same demo API outside the source tree. It explains
  inputs, output schema, sign/units, null/zero behavior and acceptance limits.
- Read-only input preflight reports actual stage dependencies, external prerequisites and
  promised intermediates. Three user journeys distinguish the demo, bounded processing and
  audited-release consumption.
- Clean consumer jobs exercise Linux Python 3.11/3.14 x86_64 and macOS Python 3.14 ARM64;
  documentation, environment, formatting, lint/type, dependency and secret gates are explicit.

### Fixed software defects and stronger checks

The runtime consumer no longer inherits development packages or source-tree imports. Missing
dependencies/resources and attempted outbound calls fail tested acceptance cases. CLI errors
have actionable diagnostics and optional debug traces. Future GEBCO manifests now carry
public-domain terms and source acknowledgement consistently; historical manifests retain their
original labels. Caught preflight failures retain safe reason/type, document/setting context and
original unfiltered debug tracebacks on stderr, including alongside JSON. Regressions cover analytic terrain cases,
H3 alignment/missingness, retained-release identity, failure/recovery/resume boundaries and
matrix exports. Formatting was separated from semantic changes during the roadmap.
Matrix export now rejects empty support and destinations that alias an input catalog, canonical
manifest or retained generation, preserving valid existing outputs on failure.

### Compatibility and scientific impact

The toolkit remains independently installable, Python 3.11+, with the declared geospatial runtime.
Demo, preflight and CLI diagnostics are additive. Existing configuration defaults, public producer
APIs, canonical products and retained releases were preserved. No formula, threshold, units,
depth sign, CRS/datum, nodata, H3 support or release gate changed. Source/attribution metadata
intentionally changes for future GEBCO outputs; optional `terms_url` uses the existing manifest
contract. Schema-1 preflight adds optional `detail`/`error_type` while retaining required fields
and statuses. Unknown provider rights remain explicitly unverified; synthetic licensing stays
unchanged. Code identity and future manifest/release hashes may change; resume validation is retained.
New failure diagnostics do not relax validation. Matrix signatures and physical output values
are unchanged, but formerly accepted invalid empty/unsafe exports now raise `ValueError`; callers
must provide nonempty support and a separate safe destination.

### Known limits and unrun paths

Synthetic software checks do not validate survey coverage, source vertical-datum accuracy,
regional coastlines, every product's science, downstream predictive usefulness or model readiness.
Three materialized-product tests skip without regional inputs. No live acquisition, regional
rebuild/comparison, real-data numerical/visual QA, whole real-data release audit, redistribution,
downstream application integration or Windows-native publication ran in this review.

FIX-01 corrects future GEBCO source/attribution rights metadata; historical manifests keep their
original labels. VERIFY-01 supplies corrected-candidate software evidence only. A future real-data
run still needs valid canonical support or explicitly validated
exploratory support, and approved disposable-workspace publication/resource scope. Retained
manifests must not be rewritten. The Python offline guard does not firewall native extensions.
The unfamiliar-user trial is **pending**: the owner confirmed no unfamiliar tester is available.
Automated fresh-install simulations are separate evidence, not a human usability study.

## Version and artifacts

Package metadata already declares **`0.1.0`**. The prior SS-11 review found no declared
versioning policy; local tags remain empty. Retain `0.1.0` as the tested candidate's base version; approval of the public
version and any prerelease designation is blocked on the maintainer's policy decision. No new
version was assigned, no tag created and no registry release assumed. If the owner chooses a
different version, commit it and rebuild/revalidate that exact commit before release.

The local sdist and its wheel were rebuilt using the existing isolated build environment, with
fresh isolated backend environments for both archive steps, then checked
for metadata and all required resources. The wheel's package bytes match the candidate source;
neither archive contains source datasets, retained products or graph caches. Artifact hashes:

| Artifact | SHA-256 |
| --- | --- |
| `toolkit_seascape-0.1.0.tar.gz` | `bcde19c639eb073432682fa0c456ba216ac6f72e9dd9b8d041b5724b5729fdc4` |
| `toolkit_seascape-0.1.0-py3-none-any.whl` | `37a255153795e5a815113608f7b8949d49ad10a94b7e12dbf2b3812dd99ed4d3` |

These are local candidate assets, not uploaded release assets. Hosted consumers independently
built and tested distributions from the same immutable commit; that is not a transfer of this
local wheel to Linux. Archive-byte equality across independent builds is not asserted. The
[candidate CI run](https://github.com/MarineCast/toolkit-seascape/actions/runs/36345268484)
completed successfully with **nine jobs** on the exact corrected commit. Local gates passed: **398 tests / 3 expected
regional skips**, **175 external-wheel tests**, runtime-only demo (15 checks), copied notebook
(15 production / 16 notebook checks), static/docs/dependency/secret checks. Its decoded logs and
local reports are referenced in progress. Linux consumer interpreters were 3.11.16/3.14.7
x86_64; macOS consumer was 3.14.7 ARM64. The documented source-install quickstart also passed
locally and in all three hosted consumer jobs. Both new synthetic figures were inspected;
that visual evidence does not establish real-data QA.

## Maintainer go/no-go checklist

| Gate | Current evidence | Remaining action |
| --- | --- | --- |
| Exact candidate and software gates | Local checks and nine hosted jobs on the named candidate; skip/guard boundaries explicit in progress | Review the intended diff; any code/version/package change requires equivalent gates on its exact commit |
| Unfamiliar-user acceptance | Owner confirms no tester; automated wheel/source-install simulations only | Have a new user follow README, locate Parquet/report/figures, explain synthetic provenance and null/zero, and report confusing steps |
| Real-data claims | SS-10 blocked runbook/preflight, not execution | Resolve its gates before making real-data claims; otherwise label the release offline research only |
| Version policy | Existing `0.1.0`; policy/tags absent | Approve policy and final release version; rebuild if metadata changes |
| Rules and merge policy | Ruleset inventory including parents and public effective `main` rules both returned empty arrays; classic protection read returned integration 403 | Authorized maintainer must inspect classic protection and effective UI settings; do not infer no protection from 403 |
| Merge | Repository metadata enables squash, merge commits and rebase; auto-merge disabled | Select the intended merge strategy and exact commit under reviewed policy; none was performed |
| Tagged/package release | No tag, registry publication or release upload | Obtain explicit authorization; use tested artifact hashes or rebuild the same immutable commit with equivalent verification |
| Release assets | Local wheel/sdist, checksums, environment and acceptance reports available outside source | Include concise release notes/limits and reports; exclude datasets, credentials, personal paths and caches from uploads |

Current observed check names to review with the maintainer (no settings were changed):

```text
test (3.11)
test (3.14)
consumer-install (ubuntu-latest, 3.11, x64, Linux, x86_64)
consumer-install (ubuntu-latest, 3.14, x64, Linux, x86_64)
consumer-install (macos-14, 3.14, arm64, Darwin, arm64)
quality (ubuntu-latest, 3.11, x64)
quality (macos-14, 3.14, arm64, docs/environments/quality-python314-macos-arm64.txt)
notebook-validation
secrets
```

The empty ruleset/effective-rule responses are prior SS-11 observations, not authorization to change
settings or proof that classic protection is absent. Retain all applicable software/security checks
when the maintainer reviews requirements. Do not turn missing human/data/admin evidence into PASS.
There is no SS-12. The next action is owner resolution of these explicit gates, not automatic
promotion, unbounded source acquisition or another toolkit implementation.
