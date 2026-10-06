# Bounded native source contract

`seascape.study_native` implements an adjacent receipt without modifying study-v1 or the root
registry schema. This interface retains exact bytes, source-relative evidence and bounded execution.
It does not certify scientific accuracy, enable regional publication or acquire sources.

## Entry points and scopes

`run_native_source_probe(manifest_path, data_root, workspace)` requires `native_source_probe`.
It measures one named cached native raster over explicitly supplied R6/R8 cells, with no approved
mask, shared reporting membership or metric-release claim. It retains inputs, full-cell native pixel
coverage, transformed footprint, resource evidence and EPSG:32610 distance diagnostics.

`run_real_source_pilot(study, support, manifest_path, workspace, configs)` requires
`real_source_pilot`, verified bathymetry support and exactly resolution-6/8 bathymetry settings.
The receipt lives beside the explicit study config, with `../Data` artifact confinement. Mandatory
bathymetry is the only selected capability; optional terrain and other families remain unselected.
Evidence type is explicitly `synthetic_software_acceptance` or
`compiled_elevation_information_product`; synthetic API exercises emit
`status=software_contract_acceptance` and `real_source_pilot_executed=false`. Source evidence type
is preserved in route provenance rather than inferred as real from the API name.
The API is validated with synthetic evidence. No real shared-mask pilot has been executed.

The caller supplies already verified, bounded memberships. The pilot recaptures their exact bytes
and the mask rather than enumerating a whole regional mask again. A full study that exceeds the
small pilot cell budget cannot be passed through this API as a bounded pilot. Regional support
construction and any separately qualified subset selection remain owner responsibilities.

## Exact receipt fields

The JSON object requires exactly `interface_version` (integer 1), `scope`, `source`, `evidence`,
`source_identity`, `measured_header`, `interpretation`, `probe_cells`, `execution_budget` and
`qualification`. Duplicate object keys are rejected. All paths resolve relative to the manifest
under the explicit resolved Data root; escaping paths and outside symlinks are rejected.

Every artifact record has `role`, `relative_path`, `raw_sha256` (lowercase exact-byte SHA256),
`byte_size` (positive integer) and `encoding`. The source is `native_elevation` / `GeoTIFF`.
`evidence` is a nonempty artifact list. Raw hashes differ from toolkit filename-and-bytes checksums.

`source_identity` has `provider_asset_id`, `evidence_type`, `archive_artifact`, `member_name`, `version`, `observation_period`, `date_precision`,
`retrieved_at`, `as_of`, `license_id`, `license_evidence_sha256` and
`interpretation_evidence_sha256`. Both evidence hashes must resolve to captured evidence artifacts. A known archive is an exact
artifact record included in captured evidence; a missing retained-cache archive stays explicitly
null and cannot be claimed as verified. The native raster member remains independently pinned.
Observation precision is `unknown`, `year`, `month`, `day` or `range`; unknown observations remain
null and annual vintages cannot be replaced by fabricated full dates. Unknown cache retrieval time
may be null. Known retrieval/as-of timestamps include timezone. Provider identity, source-document
accuracy and rights interpretation require reviewed evidence; text fields alone do not prove them.

`measured_header` has `band`, `crs_wkt`, `authority`, `axis_order`, `affine`, `width`, `height`,
`dtype`, `pixel_interpretation`, `scale`, `offset`, `nodata`, `validity_mask_policy` and `band_units`.
The actual captured header must match. First-pilot inputs must be single-band, north-up EPSG:4326,
15-arc-second grids with identity scale/offset. Axis order is `longitude_latitude`; validity policy
is `rasterio_mask_and_finite`. No conversion, implicit resampling or vertical-datum inference occurs.

`interpretation` has `units=m`, `raw_sign=negative_elevation`, `output_sign=positive_down`,
`vertical_reference`, `vertical_reference_status` and `transformation=none`. Vertical status is
`documented_source_relative` or `unknown`; unknown datum is rejected by the real pilot. A documented
GEBCO mixed-source mean-sea-level assumption remains a source-relative limitation, not uniform datum
certification. Band-unit metadata may be absent; metre interpretation then needs the pinned source
documentation. The source must not be relabeled as a uniformly observed bathymetric survey.

`probe_cells` contains unique explicit R6/R8 cell strings. The real pilot requires the exact compute
membership union. Full-H3 native pixel-center sampling remains the scientific grain; the water mask
selects reporting cells, rather than clipping their native statistical sample to the water polygon.

## Qualification evidence for the real pilot

Probe `qualification` is null. Pilot qualification requires exactly `artifact`, `method`, `version`,
`producer=bathymetry`, `checked_at`, `status=source_relative_checked`, `bindings` and `evidence`.
The captured qualification artifact requires `bindings`, `method_settings`, `method_version`,
`mask`, `coverage`, `graphs`, `checks` and `evidence`.

Bindings include study canonical hash; mask raw hash/revision/exact-file-byte hash policy; reporting
R6 and native R8 membership hashes; compute membership hashes keyed by resolution; the two selected
bathymetry capabilities; and canonical method-settings hash. The manifest and artifact bindings
must exactly match verified support and configured science.

Mask fields are `artifact`, `revision`, `encoding` and `source_qualification_artifact`. Encoding is
`RFC7946_WGS84_Polygon_or_MultiPolygon_exact_UTF8_bytes`, retaining holes. Mask bytes must parse as a
valid nonempty polygon, agree with registry identity and have pinned source-relative qualification
binding `mask_raw_sha256` and `status=source_relative_checked`. The domain owner's ENC/CanVec/CUSP
archive/member identities, transforms, seams, nonarea records, rights and reach evidence remain in
that pinned qualification artifact; this consumer does not independently certify those source
interpretations or physical boundary accuracy.

`coverage` pins an independently prepared Parquet artifact. It must equal measured full-cell native
coverage, including H3 key/resolution, support role, expected pixels, valid marine pixels, land,
nodata, outside-crop counts, fractions, native extent and missingness statuses. Output role is
`native_source_probe`: it describes native evidence, even when consumed by a source-relative pilot.
All count partitions sum to expected pixels. Grid coverage and valid marine samples are separate;
a full footprint containing nodata cannot become complete valid marine support.

Each of the two `graphs` has `resolution`, `nodes`, `edges`, `neighborhoods`,
`passability_evidence` and `maximum_hops`. Artifact records pin all inputs. Passability evidence
binds node/edge/mask hashes, `status=source_relative_checked` and
`canonical_edge_and_connector_completeness=true`. Actual BFS closure over the pinned passable edges
must equal declared minimum-hop neighbors for reporting focal cells, and all required depth cells
must be present. Missing dependencies reject the pilot. Node/edge construction and connector
completeness require owner evidence; BFS equality alone cannot establish omitted-edge completeness.
The qualification checks explicitly cover `mask_source_relative`,
`canonical_graph_edges_and_connectors` and `source_interpretation`.

`verify_graph_dependency_closure` also supports optional terrain's composed dependency bound:
`max(anomaly_hops, summary_hops + neighbor_fit_hops, openness_hops)`. Four-hop terrain summaries with
one-hop local fits require five-hop depth closure. This check does not enable terrain in this pilot.
The common terrain validator enforces stable Q90=0.90, Wilson, unique valid rings including the fit
ring, valid openness sectors, finite positive curvature scale, metric CRS and 15-arc-second native
resolution at config-loader, manifest and direct-route boundaries.

## Coverage, resources and retention

Raster footprint uses all four transformed outer corners. Coverage enumerates full-cell grid
centers, including expected pixels outside the crop, with separate land/nodata/outside causes.
Native gradient stencils are not qualified by this bathymetry-only pilot. Isobath results retain
`nearest_contour_observed_within_pinned_source_crop`, `global_nearest_claim=false` and existing
crop-relative missing-contour status. EPSG:32610 is preserved; actual source extent, area-of-use
membership and projected-versus-geodesic edge diagnostics accompany the receipt. None certifies
regional projection accuracy.

The budget requires integer `network_bytes=0`, `workers=1`, `max_input_bytes_each`,
`max_total_staging_bytes`, `max_decoded_pixels`, `max_rows`, `max_h3_candidates`,
`memory_stop_bytes` and `elapsed_stop_seconds`. Ceilings are 16MiB per input, 128MiB new retained staging, one million
pixel work, 100,000 decoded rows, 2,000 explicit cells and 900 seconds. Per-input bytes, total retained
inputs/output allowance and current free space are checked before generation creation. Peak RSS and
elapsed time are checked cooperatively between phases and native row windows. These are not OS hard
allocation guarantees: coordinate actual RAM before execution and supervise existing scientific
calls, which can allocate transiently before the next check.

Only after preflight passes are immutable UUID generations created beneath `native-source-probes`
or `.seascape/real-source-pilots`. Exact input snapshots, coverage and raw-byte inventories are
retained; sources/generations are never overwritten. Pilot computation uses retained input snapshots.
The input receipt and package code identity are retained; code changes during computation reject
the pilot. Independent row-window counts are checked for all computed cells, with native statistics/quantiles
checked for a sampled reporting cell at each resolution. Post-creation failures retain a failure
receipt; preflight failures produce no generation or writes. These receipts are outside the regional
release resolver and deliberately retain `production_ready=false`, `artifact_release_passed=false`
and `regional_release_eligible=false`. They cannot be consumed as a common regional audit PASS.
