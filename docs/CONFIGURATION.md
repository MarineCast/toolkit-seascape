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
| [config/feature_catalog.yaml](../config/feature_catalog.yaml) | Reference/generated product and field metadata |
| [config/model_feature_policy.yaml](../config/model_feature_policy.yaml) | Reference/generated materialization and scale eligibility policy |

The shipped project entry point is intentionally small:

```yaml
base_directory: .
water_polygon_processed_out_dir: data/processed/domain/environmental_layer/seascape/spatial_support/water_geometry
SEASCAPE_LAYER: config/data/environment_seascape.yaml
```

`base_directory: .` resolves to the selected workspace in family loaders. Relative configuration
paths resolve from the workspace; include resolution can fall back to the containing document's
directory. Absolute paths remain absolute.

The shared `ConfigDocument` supports `extends`, deep merging of mappings, replacement of lists,
`${env:NAME}` environment values and `${section.key}` references. However, the workflow candidate
preparation reads the project document and its direct `SEASCAPE_LAYER` include as plain YAML.
For full workflow builds, use explicit values in those documents; do not assume arbitrary composed
or interpolated configurations are fully resolved before candidate paths are rewritten.

## Geographic and scientific settings

The defaults describe an inherited Northeast Pacific case study. Named areas include `model_area`,
`extended_area` and a much larger `full_area`; inspect their bounds before acquisition or processing.
Some inherited names refer to species ranges, but names alone do not impose ecological meaning on
toolkit outputs. Editing one bounding box does not automatically update every source-specific
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
- `config/model_feature_policy.yaml`
- `docs/products.md`

Relative `data/raw` paths continue to use the canonical workspace. Absolute paths are preserved,
and arbitrary custom output prefixes are not automatically isolated. Review the rendered candidate
configuration before using customized paths; keep standard relative output locations unless the
owning workflow has been adapted for another layout.

Rendered files live under `<candidate>/.seascape/config/`; stage state lives under
`<candidate>/.seascape/stages/`. Reuse checks hash the entry-point YAML and direct domain include,
upstream stage state and declared outputs. They do not automatically hash every referenced source,
`common.yaml`, presentation file or code change. After such changes, use a fresh candidate or force
the relevant stages to rebuild with `--overwrite` instead of trusting `--resume` alone.

## Packaged templates

`seascape init` copies packaged resources into a workspace without overwriting existing files.
It does not migrate an older workspace's configuration or replace locally edited templates.
Maintainers must synchronize changed configuration templates with
[src/seascape/resources](../src/seascape/resources); see [development](DEVELOPMENT.md).
