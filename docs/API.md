# Supported Python interfaces

[Documentation index](README.md)

## Consumer facade

Import these symbols from `seascape` or `seascape.products`. Keyword-only `workspace` selects the
workspace (otherwise `SEASCAPE_WORKSPACE`, then cwd); optional `release_id` selects a retained
64-character SHA-256 release identity instead of the current canonical release.

| Symbol | Return and contract |
| --- | --- |
| `list_products(*, workspace=None, release_id=None)` | Sorted `tuple[str, ...]` of logical products |
| `list_resolutions(product, *, workspace=None, release_id=None)` | Sorted `tuple[int, ...]`; empty for an ungridded product; unknown product raises `KeyError` |
| `resolve_product(*, product, resolution=None, workspace=None, release_id=None)` | `ProductArtifact`; exact requested resolution, never a fallback; unknown product/resolution raises `KeyError` |
| `ProductArtifact` | Frozen dataclass: `Path` path/optional manifest_path, checksum and algorithm, release/product/dataset/schema identity, optional integer resolution, tuple grain and source vintage, immutable nested provenance/support/coverage/rights mappings |

Discovery validates completed release metadata and governed/family checksums. Resolution also
validates the selected artifact bytes. Missing files raise `FileNotFoundError`; invalid identity,
unsupported old storage schema, incomplete/ambiguous releases or checksum mismatches raise
`ValueError`. Filesystem failures propagate as `OSError`. These calls acquire a workspace reader
lock and may initialize lock bookkeeping, but never build or download products.

The returned path and manifest path belong to `.seascape/releases/<release_id>`. Subsequent
publications retain those bytes. Store the release ID for reproducible future resolution. Canonical
`data/processed/...` paths remain mutable compatibility outputs. Schema-2 releases must be
republished; there is no automatic migration or garbage collection. Administrators must preserve
retained generations while consumers reference them. Checksums detect tampering at resolution,
not arbitrary filesystem edits after resolution. Returned paths do not require an open reader lock.

## Producer entry points

Use `seascape --workspace PATH build` for candidate isolation and the complete release gate.
The CLI documents stage selection, resume, overwrite, acquisition and inspection flags through
`--help`. Direct family APIs write their configured outputs; they do not create isolated candidates
or certify a complete release. Set `SEASCAPE_WORKSPACE` before calling them outside the workspace.

The supported bathymetry facade is `seascape.seafloor_physiography.bathymetry`:

- `load_bathymetry_config(config_path)` returns `BathymetryConfig`, resolving configuration and
  validating settings without acquiring data.
- `run_pipeline(config_path=..., skip_download=..., skip_map=..., overwrite=...)` returns
  `(raw_path, processed_path, map_path)` (the map path can be `None`). It may download sources,
  build configured resolution exports, publish the family manifest transactionally and write maps.
- `build_bathymetry_parquet(config, raster_path=...)` returns the written `Path`; it requires
  configured support inputs and does not alone publish a complete family/release manifest.

Invalid configuration or scientific inputs raise `ValueError`; absent inputs raise
`FileNotFoundError`. Acquisition can propagate HTTP/network exceptions and output failures can
propagate `OSError`. Inspect signatures for optional parameters; do not infer consistent signatures
across other family modules. Other family CLI commands remain supported workflow entry points;
individual implementation imports are not a stable downstream API.

Candidate planning adds `build --dry-run --check-inputs [--json]`. It inspects selected local
configuration, readability and GeoTIFF headers without creating a candidate or executing builders.
JSON schema 1 includes stage order, destinations, publication intent, checks and limitations;
required missing/invalid/unverified prerequisites produce exit 1. `ready` is preflight evidence,
not scientific or release acceptance. Plain `--dry-run` remains supported. Plan objects and input
inspection adapters are internal helpers; see [workflow inspection limits](WORKFLOWS.md).

## Synthetic demo

`seascape.demo.run_demo(workspace, *, overwrite=False)` returns `DemoResult` with demo-root,
Parquet, manifest, report and figure paths, validation checks and execution metadata. It writes
only beneath `<workspace>/.seascape/demo`, invokes production bathymetry with acquisition and
interactive maps disabled, and restores environment overrides. Destination safety failures raise
`DemoWorkspaceError`; calculation, validation and filesystem errors propagate with a FAIL report
once execution starts. Existing output requires explicit overwrite and an intact ownership marker.
See [the demo guide](demo.md) for overwrite limits and process-global environment constraints.

The reserved bathymetry provider `SYNTHETIC` emits explicit synthetic source/license/validation
metadata and requires both `skip_download=True` and `skip_map=True`. Real-provider configuration,
calculation formulas, schemas and release gates are unchanged. This does not create a new live
provider or certify a full release.

## Internal ownership

`core` owns toolkit infrastructure; spatial support owns geometry and water-network contracts.
`utils/habitat_*` owns shared benthic/biogenic scientific calculations and orchestration, not generic
application utilities. `habitat_network_metrics` is an intentional internal shared helper used by
reef and substrate producers; its formulas are unchanged by this hardening. Changes require joint
producer contract tests. Underscore-prefixed functions and implementation modules remain internal.
`SeascapeSnapshot` and `SeascapeReleasePublisher` are exported low-level toolkit infrastructure;
application consumers should use the product facade rather than assembling or mutating releases.
