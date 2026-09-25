# Seascape architecture

This package builds static marine-environment features on Seascape Toolkit's canonical water-cell
support. It preserves the ecological mechanism owned by each family: terrain remains terrain,
shoreline geometry remains geometry, hydrologic paths follow the water network, and mapped
habitat evidence is never converted into an unqualified absence.

## Architecture and dependencies

The dependency direction is intentionally one way:

1. `spatial_support` builds territorial-water geometry, water-clipped H3 geometry, canonical
   R8/R6 model support, water-passable edges, terminal connectors, and bounded neighborhoods.
2. `seafloor_physiography`, `coastal_configuration`, and `hydrologic_connectivity` derive
   physical mechanisms from that support.
3. `benthic_substrate`, `biogenic_habitat`, and `anthropogenic` overlay mapped inventories and
   retain their evidence, coverage, and QC states.
4. The feature catalog records every materialized table and field. Static eligibility metadata
   classifies roles, materialization, QC/provenance fields, physical redundancy, and alternate scales.

Eligibility generation inspects every cataloged collection path. A physical feature is eligible
only when at least one materialized resolution contains a non-null value. All-null or unavailable
variables remain cataloged with their provenance and missingness semantics. Alternate scales remain
eligible candidates; downstream applications own predictive feature and scale selection.

Family builders remain orchestration facades. Generic spatial, acquisition, publication, and
inspector primitives live in [`utils`](../src/seascape/utils/README.md); family-specific source normalization,
ecology, aggregation, validation, and map styling stay with the owning family.

## Family guides

- [`spatial_support`](../src/seascape/spatial_support/README.md): water geometry, H3 identity, canonical support,
  graph lineage, and neighborhoods.
- [`seafloor_physiography`](../src/seascape/seafloor_physiography/README.md): bathymetry, geomorphometry, and
  materialized geomorphic-unit classification.
- [`coastal_configuration`](../src/seascape/coastal_configuration/README.md): shoreline distance and character,
  directional exposure, enclosure, width, constriction, and sills.
- [`hydrologic_connectivity`](../src/seascape/hydrologic_connectivity/README.md): mapped freshwater mouths,
  fluvial topology, barriers, passage evidence, and estuaries.
- [`benthic_substrate`](../src/seascape/benthic_substrate/README.md): dbSEABED composition and derived hardness.
- [`biogenic_habitat`](../src/seascape/biogenic_habitat/README.md): seagrass, kelp, reef families, confidence,
  and the model-ready panel.
- [`anthropogenic`](../src/seascape/anthropogenic/README.md): shoreline modification, structures, dredging,
  disposal, artificial reef, and aquaculture features.

`DATA_SOURCES.md` files are the authority and provenance record for a family or leaf product.
The guides above explain mechanisms, commands, outputs, missingness, and validation; they do not
replace source licences or attribution.

## Canonical support and missingness

Every H3 feature producer left-aligns to `load_model_area_support(resolution)`. R8 contains model
area cells with nonzero water overlap. R6 is the exact parent union of those R8 cells, including
geometrically dry hierarchy-only parents where required by the identity contract.

Graph mapping is not graph reachability. Terminal connectors attach otherwise valid support
cells to graph nodes but cannot be traversed as intermediate edges. Disconnected graph values
remain null with lineage and a QC reason; infinity is never a published value. Missing,
unavailable, unsurveyed, and unmapped source states also remain distinct from observed zero.

## Publication contract

Environment builds use a project-mirrored candidate root. Raw inputs remain canonical; processed
dependencies resolve from the candidate when already built there, or from checksum-valid canonical
artifacts. `--resume` reuses only configuration-, input-, and upstream-valid candidate stages, and
`--no-publish` retains the validated candidate without changing stable paths.

Every family stages artifacts and manifest together, checksums the staged bytes once, and promotes
the manifest last through a durable journal with per-destination backups and crash recovery. The
approved full candidate is promoted under one global release transaction; the terminal
`seascape_release_manifest.json` records family-manifest, catalog, policy, README, configuration,
audit, and code lineage.

Official catalog, policy, release, and model readers use `SeascapeSnapshot`, which recovers an
interrupted transaction before acquiring a shared release lock. Writers hold the exclusive lock
through promotion. Direct `pandas.read_parquet` access to canonical stable paths during publication
is unsupported; internal consumers must read through the snapshot/release loader. Manifest v3
retains artifact identity and checksums at the top level and keeps ecological absence, coverage,
distance, aggregation, and uncertainty semantics in `semantic_contracts`.

## Engineering state and research gates

The dependency-aware candidate orchestrator, transactional publication, manifest v3, shared
snapshot lock, canonical 5 km radius operator, reachable-water-area derivative, module ownership
split, and scoped static checks are implemented. The canonical roadmap is
[`TODO.txt`](TODO.txt).

The radius operator is registered as the compressed R8/5 km
`H3_WATER_RADIUS_OPERATOR_RES_8_5000M.npz` support product. Its single materialized derivative,
`H3_REACHABLE_WATER_AREA_RES_8_5000M.parquet`, is reused by anthropogenic and habitat builders;
distance features continue to use multi-source Dijkstra rather than radius-sum semantics.

Unresolved scale-group candidates, all-null fields, and unavailable sources remain excluded from
the default model. Shoreline density, sinuosity, island, archipelago, boundary-density, and coastal
orientation variables remain research-only. Estuarine polygon membership and class remain blocked
until a defensible cross-border polygon ontology exists.

## Materialized products and variables

These tables are generated from `config/feature_catalog.yaml`. Do not
edit them by hand.

<!-- BEGIN GENERATED SEASCAPE PRODUCT INDEX -->
<!-- END GENERATED SEASCAPE PRODUCT INDEX -->

Regenerate or verify the catalog, eligibility metadata, documentation, and release gate with:

```bash
python -m seascape.maintenance.update_seascape_feature_catalog
python -m seascape.governance.feature_eligibility
python -m seascape.maintenance.update_seascape_docs

python -m seascape.maintenance.update_seascape_feature_catalog --check
python -m seascape.governance.feature_eligibility --check
python -m seascape.maintenance.update_seascape_docs --check
python -m seascape.release --output /tmp/seascape_release.json
```

The release audit reads only catalog products with `metric_family: seascape`, rejects unexpected
seascape resolutions, verifies R6/R8 tables against canonical support, checks finite numeric
values, validates current manifests, and enforces depth-band and shoreline denominator rules.

## Inspectors

Inspectors accept `--presentation-config` and route outputs beneath the configured
`base_export_directory` unless `--output` is supplied. They are diagnostic views, not alternative
artifacts. Family styling stays local; basemap, zoom, export root, and shared palettes come from
`config/data/presentation_settings.yaml`.

## Validation

Run the scoped suite and static checks without downloading or publishing canonical data:

```bash
python -m pytest -q -p no:cacheprovider tests/domains/environment/seascape
git diff --check
```

Any rebuild comparison must hold schemas, H3 cell hashes, null counts, infinity counts,
distributions, categorical counts, artifact paths, and model-facing values constant. Catalog unit
metadata corrections are the only approved difference in this remediation.
