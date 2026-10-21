# Supported Python interfaces

[Documentation index](README.md)

<a id="consumer-facade"></a>
## Current area tables

`seascape.products` and `seascape` expose `list_areas`, `read_area`, `write_areas`
and `AreaTables`. The default directory is `Data/Seascape` below `SEASCAPE_WORKSPACE`
(or cwd). Pass `output=` to select that directory explicitly. Files have stable
names and are replaced in place. No release ID, frozen path or retained generation
is part of this interface. `read_area` returns a fully loaded Arrow table under
the writer lock; consumers can also read the Parquets directly.

Publication staging, recovery journals and the stable lock inode live outside the
delivery parent at `output.parent.parent/.marinecast-work/seascape/<destination-hash>`.
Successful publication removes staged data/backups; only small control directories
and the reusable lock remain. Default successful builds already remove their owned
computation scratch. Explicit work roots and failed builds remain resumable; supplied
source inputs and other workflows' caches are never swept. `Data/Seascape` contains
only current flat products/catalog and its separately keyed `research/` tables.

## Read a current table

Set `SEASCAPE_WORKSPACE` to a workspace with built flat outputs.

<!-- BEGIN CONSUMER EXAMPLE -->
```python
import os
from pathlib import Path

from seascape import list_areas, read_area

output = Path(os.environ["SEASCAPE_WORKSPACE"]) / "Data/Seascape"
print(list_areas(output=output))
table = read_area("bathymetry", resolution=6, output=output)
print(table.num_rows, table.column_names)
```
<!-- END CONSUMER EXAMPLE -->

`read_area("kelp", resolution=6, dynamic=True, output=output)` reads the dated variant when present.
A missing area/resolution/variant raises `KeyError`. If several resolutions exist,
`resolution=` is required; there is no silent fallback or combined-resolution read. Preserve native H3 resolution, nulls,
units and per-metric quality/coverage fields. Embedded `seascape_domain` metadata
contains field definitions, source context and temporal support. A date labeling
an annual survey does not establish a survey day or daily coverage.

<a id="freeze-and-read-a-release"></a>
Historical release readers have moved to `seascape.legacy_products` solely for
migration of existing workspaces. Normal builds and the current consumer interface
never create data releases.

## Producer entry points

`seascape.benthic_substrate.areal.build_areal_class_fractions(inventory, support,
classes=..., source_context=...)` computes conditional mapped substrate classes on native H3 water
support. Same-class overlaps are unioned; conflicting classes withhold fractions and retain QC.
Mapped-source coverage and unknown physical hardness remain separate; see
[areal substrate classes](regional-completion.md#areal-substrate-classes).

The current Kelp family API is
`seascape.biogenic_habitat.kelp.extents.build_kelp_extents(inventory, full_cells,
source_context=..., start_year=None, end_year=None, include_undated=None)`.
It returns `KelpExtentResult` with one `AreaTables` pair: annual mapped-positive
extent and its All Time geometric union, in full-native-H3 m². The
`kelp.build.build_kelp_habitat` orchestrator publishes the two cadence variants
and internal lineage together. Default uses all available history, including
explicitly flagged undated legacy polygons; explicit year bounds exclude those
unless requested. See [Kelp extent](kelp.md) for source/date and null semantics.
The historical helper below is retained for compatibility and is not a second
active producer or delivery dataset.

`seascape.biogenic_habitat.kelp.native.build_native_annual_footprints(inventory, full_cells,
water_cells, start_year=..., end_year=..., source_context=...)` measures annual positive polygon
unions independently on native full-H3 and static water supports. Missing map years and cells
without positive evidence retain explicit gaps/nulls. It never infers survey opportunity or absence;
see [historical data](historical-data.md#native-annual-positive-footprints).

`seascape.spatial_support.coastal_policy_build.build_coastal_policy(config_path)` builds explicit
source registries into a coastal reporting mask, native memberships and a wider graph context.
Its manifest binds source bytes and code; successful processing does not establish modern shoreline,
tidal or historical coverage. See [regional completion](regional-completion.md).

`seascape.spatial_support.water_network.load_model_area_geometry(resolution, config_path)`
loads checksum-verified water-clipped reporting geometry (`water_clipped=False` selects full cells).
Canonical graph/context geometry remains separate. Optional coast, nearshore, passage and mosaic
producers use these reporting keys while their graph algorithms retain contextual routes.

`seascape.historical.HistoricalRequest.from_study(path)` reads an explicit UTC modeling request.
`seascape.historical.export_history(study_config=..., input_dir=..., output_dir=...)` extracts
native dated records and static references with a coverage report. It preserves source support,
nulls, unknown availability and missing years; it does not certify model readiness. See
[historical data](historical-data.md) for temporal and overwrite contracts.

`seascape.biogenic_habitat.seagrass.native.build_native_positive_footprints(archive, keys,
resolution=..., composite_start_year=..., composite_end_year=...)` computes separate native
pixel-centre counts and full-H3 positive-footprint amounts from a local compressed binary raster
source. It never downloads, extracts, upsamples R6 values or invents surveyed absence.
`combine_native_composites(tables)` in the same module retains explicit composite intervals,
matching native support and per-period source contexts in a dynamic table.

`seascape.utils.geometry_quality.audit_polygon_inventory(frame, policy=...)` returns a copied
inventory and a keyed topology audit. Invalid geometry rejects by default; explicit repair or
quarantine retains source identity and records changes without certifying the source geometry.

Use `seascape --workspace PATH build` to process local sources and write flat area tables.
The CLI documents stage selection, resume, overwrite, acquisition and inspection flags through
`--help`. Direct family APIs write their configured outputs; they do not create isolated candidates
or export the current flat layout. Set `SEASCAPE_WORKSPACE` before calling them outside the workspace.

The supported bathymetry facade is `seascape.seafloor_physiography.bathymetry`:

- `load_bathymetry_config(config_path)` returns `BathymetryConfig`, resolving configuration and
  validating settings without acquiring data.
- `run_pipeline(config_path=..., skip_download=..., skip_map=..., overwrite=...)` returns
  `(raw_path, processed_path, map_path)` (the map path can be `None`). It may download sources,
  build configured resolution exports, publish the family manifest transactionally and write maps.
- `build_bathymetry_parquet(config, raster_path=...)` returns the written `Path`; it requires
  configured support inputs and does not alone publish a complete family/release manifest.

New bathymetry candidates use direct native-pixel assignment at each H3 resolution for **all**
depth statistics, counts and bands. H3 hierarchical parenting and direct coarser assignment can
differ at boundaries, so a hierarchy-only R6 parent retains null direct depth and counts. Older
releases with mixed-support R6 counts remain immutable and must be interpreted under their
archived method. See the [historical pilot boundary case](pilots/san-juan.md#acceptance-and-measured-envelope)
and the [hardening register](scientific-hardening.md).

When a selected water mask has `water_geometry_manifest.json`, H3/support and bathymetry
builders verify its artifact identity before publication and retain its source/completeness and
manifest lineage. Explicit exploratory support stays model-ineligible in additive
`metadata.water_geometry_provenance`; no schema or scientific formula changes. The San Juan
helper now publishes an exploratory mask manifest and uses explicit exploratory support versions.
An older San Juan mask bearing its exploratory `AREA` label without a manifest is rejected;
rebuild it in an approved disposable workspace rather than relabeling historical products.
Legacy masks without that declaration retain existing absence behavior. These checks do not
independently certify a source boundary's legal authority or grant release eligibility.

Invalid configuration or scientific inputs raise `ValueError`; absent inputs raise
`FileNotFoundError`. Acquisition can propagate HTTP/network exceptions and output failures can
propagate `OSError`. Inspect signatures for optional parameters; do not infer consistent signatures
across other family modules. Other family CLI commands remain supported workflow entry points;
individual implementation imports are not a stable downstream API.

Candidate planning adds `build --dry-run --check-inputs [--json]`. It inspects selected local
configuration, readability and GeoTIFF headers without creating a candidate or executing builders.
JSON schema 1 includes stage order, destinations, publication intent, checks and limitations;
required missing/invalid/unverified prerequisites produce exit 1. Failed configuration checks
add optional `detail` (safe reason) and `error_type` (exception class name), preserving all schema-1
required fields and statuses. Readers must tolerate optional fields. `path` identifies the failing
include/document when available, otherwise the selected configuration entry point; YAML reasons
include one-based line/column without source snippets. `ready` is preflight evidence,
not scientific or release acceptance. Plain `--dry-run` remains supported. Plan objects and input
inspection adapters are internal helpers; see [workflow inspection limits](WORKFLOWS.md).

The installed CLI translates identified missing files, existing destinations, configuration
validators, blocked dependencies and release/publication failures into guidance on stderr and
exit 1. Family argument errors still exit 2; forwarded help still exits 0, and family return codes
are retained. JSON planning stdout remains one report, including on failure. Python API exception
types, exception causes, return values and release checks are unchanged. Workflow callers retain
the existing re-raise default and `continue_on_error` result behavior. The private workflow failure
reporter only lets the CLI suppress raw stage exception text; it is not a supported producer API.

Unlisted calculation, dependency or programming errors still raise with their traceback. Only
known validator sites are translated; an arbitrary `ValueError` or `RuntimeError` is not assumed
to be a user mistake. To expose chained detail for translated failures, put the global option
**before the command**: `seascape --workspace PATH --debug build ...` (also supported for demo,
download, inspect and export). The private preflight failure reporter passes the original caught
exception only to the explicitly requested CLI debug sink, never into JSON or process-global
state. Debug writes unfiltered tracebacks to stderr, including with `--json`, and keeps the same
failure status. It does not execute a failed preflight or bypass any gate.
Tracebacks can contain sensitive provider/configuration detail; review them before sharing.
See [diagnostic examples and operation effects](WORKFLOWS.md#common-problems).

## Candidate audit compatibility

New candidate audits use schema 3 and include `audited_inputs`, a map from
candidate-relative product and governed-metadata paths to content checksums.
Promotion requires a literal boolean `artifact_release_passed: true` and an
unchanged inventory, including during staging under the writer lock. Re-audit
older unbound candidates before promotion. Retained release schema 3 and existing
release-reader signatures are unchanged. See [scientific contracts](CONTRACTS.md)
for the separately versioned passage measurement correction.

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

## Explicit shared-study selection

`load_study_config(path, planning=False)` reads the portable v1 request. The optional environment
variable `MARINECAST_STUDY_CONFIG` is used only when no explicit path is given. Each installed
toolkit carries its own schema; Seascape imports no workspace or sibling Python module.
`load_study_membership(path, resolution=6, role="water_reporting")` additionally verifies the exact
mask, support manifest, membership bytes, count, ordering, H3 resolution and safe Data-root paths.
Production selection rejects pending geometry and registries. The packaged
`resources/study.example.v1.json` is a pending planning example, not regional evidence.

```python
from seascape import load_study_membership, read_study_area, read_study_research

study = "/path/to/config/study.v1.json"
membership = load_study_membership(study)
bathymetry = read_study_area("bathymetry", study_config=study)
outlets = read_study_research("outlet-relationships-r6", study_config=study)
sections = read_study_research("passage-cross-sections", study_config=study)
```

`read_study_area` uses `products.seascape.catalog_relative_path`. It selects exact native R6 IDs,
retains producer support and records missing/excluded IDs in `study_selection` metadata. Structural
R6 child unions remain distinct from direct native R6 polygon support. Missing R6 variants are
not manufactured from R8. `read_study_research` consumes byte-pinned long relationships and named
object tables from the shared manifest; R8 companions retain producer-native support.

The catalog can be the canonical `Data/Seascape/catalog.json`; a study does not require its own
product copy. Named object tables may live under `Data/Seascape/research/`. Area writes and
historical output replacement preserve that separate object directory. Older canonical areas
without the study's reporting-mask identity fail study selection rather than inheriting a new mask.

Selected outlets may supply `selected_outlets.inventory_path` with explicit coordinate-source
identity, version, feature ID and rights. Basin attributes can remain HydroRIVERS while a reviewed
FWA endpoint or official GNIS stream-mouth coordinate supplies location. Gateway outputs retain
unmapped targets and explicitly unresolved source attachments at each resolution. An unresolved
route cannot establish the effect of gateway removal.

Passage sources can be configured globally or per registry row. A per-row `DEPTH_RASTER_PATH`
requires `DEPTH_SOURCE_ID`, `DEPTH_SOURCE_VERSION`, `DEPTH_RIGHTS`,
`DEPTH_SOURCE_VERTICAL_DATUM`, `DEPTH_UNITS=m`, `DEPTH_ELEVATION_CONVENTION=positive_up` and a
boolean `DEPTH_DATUM_QUALIFIED`. Qualified source and passage datums must agree. Raster scale and
offset are applied before conversion to positive-down depth; an unscaled rendered byte raster is
rejected. Each source file is checksum-bound in the family manifest. `NOMINAL_*` diagnostics stay
separate when a source datum is unresolved. Qualification of the source reference does not validate
navigation clearance, a controlling sill, current shoreline position or ecological model readiness.

Outlet inventories and long relationships retain source-to-water registration distance separately
from the water-entry-to-graph connector. Their sum is the terminal cost included in network
relationships. These source registration gaps are positional limitations, not measured river
channel lengths. Inventory attachment status and canonical node IDs are recorded per resolution.

## Canonical Seagrass extent

`seascape.biogenic_habitat.seagrass.extents.build_seagrass_extents(inventory, full_cells, source_context=...)` returns `SeagrassExtentResult` with a static-only `AreaTables` result (`dynamic=None`). `seagrass.build.build_seagrass_habitat` publishes two native-resolution static files, retained inventory and standard manifest transactionally. It supports explicit `inventory`, `full_cells`, `output` and `source_context` for bounded replay without acquisition. See [Seagrass](seagrass.md) for source eligibility and dates. The older `native.build_native_positive_footprints` and `combine_native_composites` remain explicit composite compatibility APIs; their interval amounts are not separately exposed scientific choices in the current family and cannot replace the all-history geometric union.

## Bivalve mapped-bed API

`seascape.biogenic_habitat.bivalve.extents.build_bivalve_extents` returns static-only `AreaTables` and a source/geometry report. `bivalve.build.build_bivalve_habitat` writes the canonical area at explicit native resolutions; inputs and output are required and acquisition is separate. See [Bivalve](bivalve.md).
