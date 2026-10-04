# Release checklist

This is the historical v0.1.0 preparation checklist. Its unchecked items are not a
statement about current release state; the project now declares 0.1.1. See the
[completion review](completion-review.md) for current local fixes and validation
boundaries. Use fresh evidence for the exact revision before any new release.

## v0.1.0 preparation record (historical)

- [ ] Consolidated reviewed work is merged into `main`.
- [ ] CI passes on the supported platform/Python matrix.
- [ ] README identifies `v0.1.0` as a public preview.
- [ ] Compatibility expectations are documented.
- [ ] Scientific limitations are documented.
- [ ] `pyproject.toml` contains version `0.1.0`.
- [ ] `CHANGELOG.md` contains a `0.1.0` release section.
- [ ] Software/method/data identities are documented separately.
- [ ] `python -m build` succeeds from a clean checkout.
- [ ] `python -m twine check dist/*` succeeds.
- [ ] Wheel installs into a fresh environment.
- [ ] Package imports outside the source checkout.
- [ ] CLI smoke test succeeds.
- [ ] Offline demo succeeds from the installed artifact.
- [ ] Wheel contents have been reviewed.
- [ ] Release notes document installation.
- [ ] Release notes document highlights.
- [ ] Release notes document compatibility.
- [ ] Release notes document scientific changes.
- [ ] Release notes document important scientific caveats.
- [ ] Git tag will be `v0.1.0`.
- [ ] GitHub Release will be `v0.1.0`.
- [ ] Existing tags/releases have not been overwritten.
- [ ] Regional scientific data is not included or published by the release workflow.

Record the exact commit and successful CI run before tagging. Any subsequent change invalidates that
evidence and requires the affected checks to run again. See the [release process](releases.md).
