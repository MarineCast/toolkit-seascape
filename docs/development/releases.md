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
Git tag, GitHub Release, or PyPI version. Conversely, a package-only fix need not change a
method identity or data-release identity. A change in scientific meaning **must** receive an explicit
new method identity—even if it ships alongside an independently chosen software version.

## Software releases

Software releases use Semantic Versioning and immutable tags named `vX.Y.Z`. The committed static
version in `pyproject.toml`, installed distribution version `X.Y.Z`, tag `vX.Y.Z`, and GitHub
Release version must agree exactly. The release workflow validates that invariant; it never
edits the version.

During the `0.x` public-preview phase:

- **Patch** (`0.1.0` → `0.1.1`) is for corrections and implementation, documentation, packaging, or
  performance fixes that preserve intended scientific meaning and public contracts.
- **Minor** (`0.1.0` → `0.2.0`) may contain documented API, schema, CLI, variable, producer, or
  method changes. Every scientific-meaning change must be prominent in the changelog and notes.
- **Major** `1.0.0` is reserved for a future stable public contract.

`CHANGELOG.md` is the reviewed record of user-facing changes. The workflow's GitHub Release notes
identify the public preview, installation command, and linked scientific changes and limitations.

## PyPI publication

The software release path is:

```text
merge to main → create version tag → immutable tagged checkout → version validation
→ build wheel and sdist once → Twine/distribution validation → clean consumer installation
→ upload validated files as a GitHub Actions artifact → GitHub Release
→ GitHub pypi environment approval → OIDC / Trusted Publishing → PyPI
```

The GitHub Release and PyPI upload consume the exact validated wheel and source distribution.
The PyPI job downloads the Actions artifact; it does not rebuild. Pull requests and pushes to
`main` do not run this publication path. The release job needs `contents: write` to create the
GitHub Release. Only the separate publishing job receives `id-token: write`.

No PyPI token or long-lived publishing credential is stored in GitHub. GitHub obtains a
short-lived OIDC identity for the `publish-pypi` job in the `pypi` environment; PyPI checks the
repository, `release.yml` workflow, and environment identity against its Trusted Publisher
configuration. Configure the GitHub environment with required reviewers and deployment
restrictions before publication.

In GitHub repository settings, create the `pypi` environment, require a reviewer, and allow
deployments from the `main` dispatch ref and release tags matching `v*`. As of 2026-09-30,
the PyPI project endpoint returned 404, so use PyPI's account-level pending publisher form
for the first upload. Register the distribution name `toolkit-seascape`, owner `MarineCast`,
repository `toolkit-seascape`, workflow filename `release.yml`, and environment `pypi`.
Do not create a GitHub secret. A pending publisher does not reserve the PyPI name until
the first successful upload.

PyPI package files and version numbers are immutable. A failed publication after the GitHub
Release exists must use the documented backfill for the same validated assets, if possible, or
a new software version. Never replace a PyPI version or move a Git tag.

### Existing release backfill

The `v0.1.0` tag and GitHub Release already exist, while PyPI returned no `0.1.0` version on
2026-09-30. Do not push `v0.1.0` again. Once this workflow is on `main` and the GitHub `pypi`
environment and PyPI Trusted Publisher are configured, dispatch `release.yml` from `main` with
`tag=v0.1.0`. The backfill accepts only an existing version tag, checks out its exact commit,
confirms tag/version identity and the matching GitHub Release, and checks that the version is
absent from PyPI. It downloads the existing Release files, verifies their GitHub-recorded
SHA-256 digests, builds once from the tagged commit, and requires identical archive member names,
contents, types, and modes. It then runs Twine, distribution, and clean consumer validation on the
existing files before the PyPI job uploads those exact GitHub Release bytes. The backfill never
edits the tag or GitHub Release.

Rebuilding an old tag can change archive timestamps or owner fields even when member contents
are identical. If the content comparison fails, the backfill stops safely; investigate, then
release a new version from reviewed source rather than replacing `v0.1.0` assets. Project URLs added
after the `v0.1.0` tag cannot appear in its immutable wheel or sdist; they will appear in the next
version built from the updated source.

The tagged `v0.1.0` metadata also retains an unbounded Rasterio dependency. As of 2026-09-30,
an ordinary Python 3.14 installation on macOS 14 can select Rasterio 1.5.2, which lacks a
compatible macOS 14 wheel and needs a separate GDAL source-build setup. The new source metadata
caps Rasterio below 1.5.2, but the backfill cannot change `v0.1.0`. Review this limitation before
choosing the first PyPI publication version.

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
   and installed-consumer validation, uploads the validated files, and creates the GitHub Release.
6. Approve the `pypi` environment deployment. The dependent job publishes the uploaded files
   with PyPI Trusted Publishing after confirming the version is not already on PyPI.
7. Review the PyPI files, GitHub Release assets, and notes. Do not attach regional or generated
   scientific data.

The workflow uses `gh release create` for new tags; it fails if that release already exists.
For the existing `v0.1.0` release, use `gh workflow run release.yml --ref main -f tag=v0.1.0`
only after the GitHub and PyPI configuration above is complete. This dispatch does not create
a new Git tag or GitHub Release.
