# Software release process

## Three independent identities

The word “release” can refer to different things. These identities are related through provenance,
but they are not interchangeable.

| Identity | Example | Meaning |
| --- | --- | --- |
| Software version | `toolkit-seascape 0.1.0` | Code, Python API, CLI, schemas, algorithms, and packaging. |
| Scientific method version | `geomorphometry_curvature_tpi_v2` | The exact scientific interpretation implemented by a producer or transformation. |
| Data release | An immutable release ID or dated generation | Exact inputs, configuration, checksums, method versions, and materialized outputs. |

A rebuild with changed source inputs can create a new data release without changing the package,
Git tag, GitHub Release, or eventual PyPI version. Conversely, a package-only fix need not change a
method identity or data-release identity. A change in scientific meaning **must** receive an explicit
new method identity—even if it ships alongside an independently chosen software version.

## Software releases

Software releases use Semantic Versioning and immutable tags named `vX.Y.Z`. The committed static
version in `pyproject.toml`, installed distribution version `X.Y.Z`, tag `vX.Y.Z`, and GitHub
Release name `vX.Y.Z` must agree exactly. The release workflow validates that invariant; it never
edits the version.

During the `0.x` public-preview phase:

- **Patch** (`0.1.0` → `0.1.1`) is for corrections and implementation, documentation, packaging, or
  performance fixes that preserve intended scientific meaning and public contracts.
- **Minor** (`0.1.0` → `0.2.0`) may contain documented API, schema, CLI, variable, producer, or
  method changes. Every scientific-meaning change must be prominent in the changelog and notes.
- **Major** `1.0.0` is reserved for a future stable public contract.

`CHANGELOG.md` is the reviewed record of user-facing changes. Release notes are prepared from
`.github/RELEASE_TEMPLATE.md`; they must state status, installation, compatibility, scientific
changes, and limitations. A future PyPI Trusted Publishing job may publish the **same** artifacts
built once by this workflow. It must not rebuild them independently or use long-lived credentials.

## Scientific method versions

Each scientifically meaningful producer or transformation records an explicit identity, such as:

```text
geomorphometry_curvature_tpi_v2
survey_opportunity_asof_v2
bathymetry_slope_v1
```

The identifier describes interpretation—not a refactor, commit, or package version. A formula,
threshold, support neighborhood, missingness rule, classification meaning, or other interpretive
change requires review and a new method identity. Behavior-preserving implementation fixes need a
software patch but should not fabricate a new scientific method.

## Data releases

Materialized datasets have separate immutable identities. Their manifest should record the release
ID and timestamp/date, software version, all method versions, source datasets and versions, source
checksums, configuration, region/AOI, horizontal CRS and vertical datum, units and sign conventions,
nodata semantics, and output checksums.

Data publication is intentionally outside the software release workflow. A data rebuild does not
trigger PyPI publishing, a Git tag, or a GitHub software release. The tag workflow neither downloads
scientific sources nor builds, uploads, or assigns identities to regional products.

## Immutability

Never overwrite a Git tag, replace an existing GitHub Release artifact, republish the same PyPI
version, or silently replace a scientific data release. Correct a problem by issuing a new software,
method, or data identity as appropriate, and preserve the superseded record.

## Maintainer procedure

1. Complete the [release checklist](release-checklist.md) on the exact commit intended for release.
2. Update the static project version and move reviewed changelog entries out of `Unreleased`.
3. Merge to `main` and confirm required CI for that exact commit.
4. Create and push an annotated `vX.Y.Z` tag. Do not move or reuse an existing tag.
5. The tag workflow checks the clean checkout and version, builds wheel and sdist once, runs Twine
   and installed-consumer validation, then creates the same-named GitHub Release with both files.
6. Review the published assets and notes. Do not attach regional or generated scientific data.

The workflow uses `gh release create`; it fails if that release already exists. There is no active
PyPI publication step. When publishing is added, use GitHub OIDC/Trusted Publishing and consume the
workflow's already validated artifacts.
