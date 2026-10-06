# Configuration and workspace layout

[Documentation index](README.md)

## Select the workspace

The workspace is the root for configuration, data and outputs. It is independent of the package
installation. The CLI's `--workspace` option takes precedence over `SEASCAPE_WORKSPACE`; otherwise
the current directory is used. Use `SEASCAPE_WORKSPACE` from the
[first-result guide](../README.md#install-and-get-a-first-result), or select your own absolute owned
path (the `/absolute/path/to/owned-workspace` below is a placeholder). Put the global option before the subcommand:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --dry-run
```

Python and maintenance-module callers can use:

```sh
export SEASCAPE_WORKSPACE="/absolute/path/to/owned-workspace"
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

For an explicitly B.C.-only case, set `water_geometry.build.jurisdictions: [bc]` in the
workspace's Seascape configuration. The water-geometry builder then consumes only Canadian
marine-region and territorial-zone layers and records the selected jurisdiction; default
`[bc, us]` retains the cross-border source contract. Set `download.active_jurisdictions: [bc]`
in each selected B.C./Washington habitat or shoreline family to disable its `wa_` sources.
Kelp records a generalized-only B.C. evidence state rather than requiring the Washington
annual archive. A disabled source cannot be read even if a stale local file exists. These
explicit switches do not infer jurisdiction from a bounding box; review area and source
coverage before claiming a complete B.C. product. Other nationally scoped sources need
their own applicability review. Preflight reports selected inputs without acquiring them.

An optional, locally acquired matching GEBCO TID raster can be enabled with
`bathymetry.source.tid_raw_filename` and `tid_release`. Exact categorical grid alignment and
release declarations are required; TID does not supply numeric uncertainty.

## Before a bounded build

Start with the workspace initialized in the [workflow guide](WORKFLOWS.md#bounded-real-data-processing).
Edit its files, not the installation's packaged resources. These are configuration requirements,
not authorization to acquire the configured sources:

| Workspace setting | Required review/edit |
| --- | --- |
| `config/common.yaml`: `areas.*.bbox_wgs84` | Set explicit intended WGS84 bounds; inspect every selected area's use, especially `regional_source_area` |
| `environment_seascape.yaml`: `water_geometry.build.area`, `h3_geometry.area`, `water_network.area` / `model_area` | Choose compatible source, counting and analysis support; review expected cell counts and graph parameters together |
| `bathymetry.area`, `bathymetry.source.*` | Confirm provider/release/grid, source rights, local raster path and actual source extent; provider request bounds may be larger than analysis bounds |
| `bathymetry.processing.*` | Keep matching H3 support paths/resolutions, positive-down meters for dependent terrain, projected-meter distance CRS and an owned destination |
| Other selected families' `source` / `processing` settings | Supply their exact reviewed local inventories; preserve source vintage, coverage and missingness |
| `presentation_settings.yaml` | Choose owned inspection outputs; opening maps can fetch basemap tiles |

The [stage reference](stage-inputs.md) is generated from default template preflight metadata;
it cannot replace inspection of your edited configuration. For your selected stages, run:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-bathymetry --dry-run --check-inputs --json
```

In an initialized workspace without datasets this returns exit 1 with `missing_external` or
`unverified` requirements. That is expected missing-input evidence. `ready` covers only the stated
config/path/header inspections, not values, datum, support/cardinality, rights, hashes or science.
A small pilot, acquisition/resource limits and real-data validation remain separate reviewed work.

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

## Explicit shared study planning

The optional global `--study-config PATH` selects MarineCast study-v1 JSON. An explicit path
wins over `MARINECAST_STUDY_CONFIG`; there is no default filename search or sibling import.
Without either selection, the standalone configuration and workspace rules above are unchanged.
The validator uses a packaged copy of the pinned v1 schema, so planning also works outside the
MarineCast checkout. `storage.data_root` must be relative to the JSON file; when `--workspace`
is omitted the selected workspace is its resolved data root plus `seascape`.

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" --study-config /absolute/path/to/study.v1.json \
  build --dry-run --json --only seascape-bathymetry
```

This adapter is **planning only**. A proposed domain is allowed only for explicit dry runs.
Production through the adapter is blocked even if a study changes to approved: the current
territorial-water selection must first be replaced with validated marine reporting membership,
and producer compute halos must be integrated independently of the reporting rectangle.
The current approved selection policy covers ocean-side coastal water within 22,224 m of the
qualified intended reach plus requested inland waters. Policy approval does not certify geometry,
materialize the water mask or validate the registry. Each of those pending states rejects a
production load. Even claims that all states are validated cannot enable the unfinished adapter.
No stage readiness result certifies shared-domain coverage; JSON includes
`study_production_ready=false` and an explicit support warning. Existing source paths remain
producer inputs, not proof that they cover the requested rectangle.

Current v1 requires the complete coastal field group: `bbox_role`, `geometry_status` and
`selection_policy`. Missing, null or malformed policies fail validation in planning and production;
superseded rectangle-only study documents must be updated before selection. Standalone use without
a selected study retains its existing area rules. The rectangle is exclusively an
acquisition/planning envelope, not the reporting universe; requesting it as `model_area`
fails rather than including far-offshore water.
The planner applies recorded geometry, coastal-network, freshwater, jurisdictional-river and
catchment buffer settings. Other named source/compute areas are not silently resized. The output
includes the complete parsed contract, policy approval and pending certification status,
canonical config and geometry hashes, raw-file hash, domain revision/status, requested dates,
resolved Data root, product resolution and native-companion policy. The effective configuration
fingerprint includes those identities. A changed date, buffer or geometry invalidates reuse.
Provenance distinguishes the envelope identity from reporting-mask identity; the latter is pending.
The synchronized schema accepts domain approval provenance and revision notes. Approved status
requires an explicit approval record with a timezone-bearing timestamp. Validation, parsed content,
canonical identity and raw-file identity use one captured byte snapshot; a later file revision does
not change the already loaded record. The raw-file hash describes that captured snapshot.
The public API is `seascape.study.load_study_config(path, planning=True)` and the scoped
`study_context(study, planning=True)`; use it only around read-only planners. Orchestration
rejects a producer run inside that context before creating a candidate.

The requested 2009–2026 window does not make static bathymetry an annual observation series.
Retain source vintage, observation/availability distinctions and actual source cutoffs. Do not
repeat static tables by year, backdate modern evidence or manufacture future measurements.
The portable validation notebook remains a standalone bathymetry/demo client; this optional,
blocked production integration does not change its required offline workflow.

### Bounded shared-support consumer

`seascape.study_support.load_study_support` consumes explicitly located, pinned artifacts without
downloads or writes. The root contract is unchanged. The packaged registry interface pins config-relative artifact paths:
paths resolve against the
selected study JSON directory and must remain beneath its configured resolved `data_root`, including
through symlinks. Legitimate `../Data/...` paths are accepted; CWD and toolkit location play no role.
The shared R6
`water_reporting` artifact follows the documented raw SHA256 policy: sorted unique lowercase
H3 IDs, one per line, ending in a newline; an empty membership is a zero-byte file.
Count, resolution, checksum and complete positive-area
ellipsoidal overlap with the pinned mask are checked. IDs selected by centers or the acquisition envelope
cannot substitute for mask membership. Mask geometry is not silently repaired or simplified.

The provisional mask interface accepts an explicit pinned EPSG:4326 GeoJSON Polygon/MultiPolygon
geometry. Its raw SHA256 must match `grid_registry.mask_sha256`; the mask revision comes from that
registry. This mask encoding remains provisional until its qualification-manifest format is frozen;
it does not change the shared JSON schema. The confirmed membership interface is pinned at raw SHA256
`38e3f84d8e7b0f59c188abb1da1ca354bb6271c328ac2a7e29504b0ca2f84d01`.
Separately pinned `MembershipArtifact` records with
role `water_source` supply R6 and R8 compute context. The caller must identify the `producer`;
its identity distinguishes support caches, and bathymetry refuses another producer's support.
No single common halo is inferred from these files. R6 compute support must equal the R8 parent
union and contain all R6 reporting cells; R8 compute support must contain all independently derived
native reporting cells. Direct positive-area R6 reporting and the R8 compute parent union have
distinct semantics and are not silently substituted for each other. R5 water networks are refused.

The reader defaults to 16 MiB per artifact and 100,000 cells, with a conservative envelope-based
enumeration check before H3 filling. Bounds may refuse a large complex mask; this read-only API is
not a production footprint estimator. H3's overlap API is required; center-fill fallback is refused.
The returned immutable memberships record the pinned config, mask, membership artifacts, H3 library
version, cell polygon/intersection/ellipsoidal area engines and scientific buffers in a portable
consumer identity. Read bytes are also the bytes hashed and parsed, so validation is not based on a second read of a changing file.

Bathymetry's `load_h3_cells(config, study_support=support, support_role="reporting")` uses these
memberships through an explicit API argument. `support_role="compute"` selects full compute context.
The existing standalone grid path remains unchanged when no support is supplied. This does not
wire the study CLI into the bathymetry pipeline or authorize a producer run. For already computed
tables, `support.consume_table(frame, resolution, role="reporting")` requires all reporting rows,
trims compute-only rows and preserves nulls, zeros and status columns. `role="compute"` requires
every compute row; reporting-only support cannot replace halo support. Duplicate, null, wrong
resolution and out-of-support keys fail rather than being silently dropped.

**Verification is not qualification.** The consumer does not establish source rights, source
coverage, coastal reach/waterbody classification, the 22,224 m coastal selection method or producer
halo distance completeness. Its provenance explicitly reports those limitations and
`production_ready=false`. All current study CLI/context/orchestration production gates remain.
Before removing them, integrate qualified source/mask manifests and each producer's actual reporting,
network, native raster and halo routes, then independently validate their scientific outputs.
