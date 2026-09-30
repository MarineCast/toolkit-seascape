# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and software
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Scientific-method
identities and data-release identities are tracked separately from software versions.

## [Unreleased]

### Added

### Changed

### Fixed

### Deprecated

### Removed

## [0.1.1] - 2026-09-30

### Documentation and packaging

- Use an absolute HTTPS URL for the README banner so it renders on PyPI.
- Include documentation, repository, and issue-tracker URLs in package metadata.
- Publish the validated wheel and source distribution through GitHub OIDC Trusted Publishing after
  the GitHub Release is created and the `pypi` environment approves the deployment.
- Limit Rasterio below 1.5.2 so Python 3.14 installs on macOS 14 select a compatible wheel.

## [0.1.0] - 2026-09-30

### Added

- First public-preview package for source-backed bathymetry, terrain, substrate, coastal geometry,
  hydrologic connectivity, mapped habitat evidence, anthropogenic features, and marine H3 support.
- Independently installable `seascape` Python API and CLI with product discovery, immutable release
  resolution, dry-run planning, input preflight, and checksum/provenance validation.
- Offline synthetic demo that exercises the production bathymetry transformation while preserving
  missing depth as null; it is software acceptance, not a regional-data or accuracy claim.
- Explicit scientific-method identities in producer manifests, including
  `geomorphometry_curvature_tpi_v2`, `direct_pixel_support_v2`,
  `geometric_fetch_16_bearings_v1`, and other product-specific interpretations.
- Packaged configuration, schemas, and documentation resources required by clean consumer installs.

### Changed

- Terrain curvature and topographic-position interpretation is identified as
  `geomorphometry_curvature_tpi_v2`; outputs from other method identities must not be assumed
  scientifically equivalent.
- Several product families use explicit versioned interpretations for support, mapped habitat,
  substrate, geomorphic evidence, and coastal structure. Their method identities are recorded in
  product provenance rather than inferred from software version `0.1.0`.

### Scientific limitations

- No regional source data or generated data release is bundled. Source coverage, rights, datum,
  accuracy, and fitness require a separate regional review and immutable data-release record.
- Physical features and mapped evidence do not establish species occurrence, habitat suitability,
  navigation safety, or predictive model readiness.
- The synthetic demo validates software behavior and package resources only; it does not validate
  regional scientific accuracy.

### Packaging

- Python 3.14 package metadata, wheel and source-distribution builds, installed-wheel consumer
  checks, and Linux/macOS CI coverage are provided for the public preview.

[Unreleased]: https://github.com/MarineCast/toolkit-seascape/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/MarineCast/toolkit-seascape/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/MarineCast/toolkit-seascape/releases/tag/v0.1.0
