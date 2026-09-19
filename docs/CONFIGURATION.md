# Configuration and workspace layout

[Documentation index](README.md)

## Select the workspace

The workspace is the root for configuration, data and outputs. It is independent of the package
installation. The CLI's `--workspace` option takes precedence over `SEASCAPE_WORKSPACE`; otherwise
the current directory is used. Put the global option before the subcommand:

```sh
seascape --workspace /path/to/seascape-workspace build --dry-run
```

Python and maintenance-module callers can use:

```sh
export SEASCAPE_WORKSPACE=/path/to/seascape-workspace
python -m seascape.maintenance.update_seascape_docs --help
```

Use absolute paths for `--candidate-root`, comparison roots and explicit input/output overrides.
Those arguments are not uniformly rebased against the workspace by every command.

## Configuration files

| File | Purpose |
| --- | --- |
| [config/data/project.yaml](../config/data/project.yaml) | Build entry point; `base_directory`, water-polygon location and `SEASCAPE_LAYER` include |
| [config/data/environment_seascape.yaml](../config/data/environment_seascape.yaml) | Source paths, provider settings, processing parameters, resolutions and family outputs |
| [config/common.yaml](../config/common.yaml) | Named WGS84 bounding boxes used by family loaders |
| [config/data/presentation_settings.yaml](../config/data/presentation_settings.yaml) | Inspection-map output root, basemap and visual settings |
| [config/feature_catalog.yaml](../config/feature_catalog.yaml) | Checked-in reference catalog; candidates regenerate the authoritative release copy |
| `config/feature_eligibility.yaml` | Candidate-generated static eligibility metadata; not an editable input or packaged template |

The shipped project entry point is intentionally small:

```yaml
base_directory: .
water_polygon_processed_out_dir: data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry
SEASCAPE_LAYER: config/data/environment_seascape.yaml
```

`base_directory: .` resolves to the selected workspace in family loaders. Relative configuration
paths resolve from the workspace; include resolution can fall back to the containing document's
directory. Absolute paths remain absolute.

The shared `ConfigDocument` resolves `extends`, deep mapping merges, list replacement,
`${env:NAME}` and `${section.key}` references for both direct APIs and workflow preparation.
Reference cycles fail explicitly. Workflow preparation freezes the resolved domain and named-area
configuration before rebasing output paths; source inputs can remain outside the candidate.

## Geographic and scientific settings

The defaults describe an inherited Northeast Pacific case study. Named areas are `model_area`,
`extended_area` and the much larger `regional_source_area`; inspect their bounds before acquisition
or processing. The regional source extent preserves the prior physical bounds under a
species-neutral name. Editing one bounding box does not automatically update every source-specific
coverage constraint, expected cell count or resolution-dependent parameter.

When adapting a region, review source coverage, water-polygon inputs, H3 resolutions, graph radius,
parent-child aggregation, expected support counts and bathymetry sign together. Preserve depth
units, vertical datum, nodata treatment and the distinction between full-cell and water-clipped
support. Family loaders implement their own validation; there is no single top-level CLI command
that validates every source and artifact without a build.

## Candidate paths and resume limits

The workflow rewrites relative values beneath these prefixes into the candidate:

- `data/processed/domain/environmental_layer/seascape`
- `outputs/domains/environmental_layer/seascape`
- `config/feature_catalog.yaml`
- `config/feature_eligibility.yaml`
- `docs/products.md`

Relative `data/raw` paths use the configured input base (the canonical workspace by default).
Absolute source inputs remain permitted. Output settings and declared stage outputs must resolve
inside the candidate, including through symlinks. Absolute canonical outputs, arbitrary relative
output prefixes outside the candidate, traversal, and non-basename output filenames fail before
builders run. Custom output locations must explicitly resolve inside the candidate. Shared artifact
writers also check the boundary while the candidate environment is active.

Rendered files live under `<candidate>/.seascape/config/`; stage state lives under
`<candidate>/.seascape/stages/`. Reuse checks include the effective configuration, transitive
configuration files, resolved environment values, `common.yaml`, package commit/dirty source
identity, upstream state, declared outputs and file-backed source/upstream manifest records.
Frozen configuration and identity are retained in published generations. Changing included
geographic bounds invalidates reuse. Presentation-only settings and remote sources without a local
immutable identity are not fully fingerprinted; use `--overwrite` or a fresh candidate when
changing those inputs. Do not mutate configuration or candidate files during a build.

Projected/equal-area CRS settings used for planar calculations require projected horizontal axes
in meters. Geographic or feet-based targets fail; selecting a projection suitable for the study
area remains the caller's responsibility. Terrain and sill consumers require explicit
`bathymetry_sign: positive_down` and reject negative numeric depths. Standalone bathymetry may
still emit `negative_elevation`, but those outputs cannot feed these dependent products.
The fixed `SLOPE_Q90_NATIVE_RASTER` schema requires `slope_upper_quantile: 0.90`.

## Packaged templates

`seascape init` copies editable producer configuration into a workspace without overwriting existing
files. It deliberately does not copy checked-in/generated feature catalogs, eligibility metadata,
or product indexes; those are release-derived artifacts.
It does not migrate an older workspace's configuration or replace locally edited templates.
Maintainers must synchronize changed configuration templates with
[src/seascape/resources](../src/seascape/resources); see [development](DEVELOPMENT.md).
