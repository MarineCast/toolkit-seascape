# Packaged scientific source reproduction

Latest packaged acceptance: [1 November installed producer closeout](installed-producer-closeout.md).
It records fresh terrain/substrate runs, metric-only exports and quantified precision results.
Earlier task-directory evidence may no longer be available; retained source/candidate paths
and the new evidence root are distinguished in that report.


These producer paths use scientific inputs directly. They do not restore historical
coverage/audit tables. Final export follows the [metric-only contract](metric-only-exports.md);
optional native diagnostics and receipts stay in the work directory. Existing deliveries
must remain separate from candidates until discrepancies are reviewed.

## Portable scientific source bindings

`water_network.source_bindings` maps each **exact original artifact path** in the
canonical manifest to its current retained file path. Relative target paths resolve
against the configured base directory. The original manifest is unchanged. Unknown
or duplicate bindings reject; each loaded file must match the original checksum.
A similar filename or scientific vintage is insufficient. Geometry, support and graph
inputs remain scientifically required; this manifest is source identity, not a historical
coverage-output prerequisite.

```yaml
water_network:
  source_bindings:
    data/processed/original/H3_WATER_NEIGHBORHOODS_RES_8.parquet: /retained/H3_WATER_NEIGHBORHOODS_RES_8.parquet
```

Use the actual original manifest path as the key; the example is not a dataset location.
Water-mask and spatial-support versions remain checked. No global environment override
turns checksum validation off.

## Bounded terrain

```bash
SEASCAPE_WORKSPACE=/candidate/workspace python -m seascape.seafloor_physiography.geomorphometry.build --config /candidate/workspace/config/data/environment_seascape.yaml
```

The configured bathymetry table, native raster and canonical water-neighborhood inputs
are required. Terrain uses 1,024-cell chunks, preserving the complete metric-radius
neighborhood plus the additional slope dependency halo. All neighborhood records are
validated in complete source groups before calculation; duplicates, missing self rows,
nonfinite distances, invalid hops and outside-support targets still reject. The native
raster slope calculation uses the actual raster, not a historical terrain export.

Plane fitting centers depths before least squares to reduce cancellation on nearly flat
terrain. This preserves the OLS definition and the existing undefined-flat-aspect rule.
Independent 60-digit calculations support the accuracy improvement. Historical tolerance
failures are reported, not hidden by changing thresholds. The original delivery remains
unchanged even when current arithmetic is more accurate.

## Streamed mapped substrate

```bash
seascape mapped-substrate --source /retained/inventory.parquet --source-sha256 EXPECTED_SHA256 --support /retained/water-support.parquet --support-sha256 EXPECTED_SHA256 --keys /study/r6.txt --work /candidate/new-index --output /candidate/Data/Seascape --rights "SOURCE_LICENSE" --geometry-policy make_valid
```

Use known expected input hashes from the retained source receipt. The inventory must
carry GeoParquet CRS/geometry metadata, unique `RECORD_ID` and explicitly classified
`CLASS_CODE` values 1/2/3 (hard/mixed/soft). The support supplies native H3 identity and
scientific water geometry. Streaming batches build a disk spatial index before geometry
intersection. Cross-class overlap retains the original conflict rule and null fractions.
Empty intersections contain no substitute record and yield null mapped evidence.

The default coordinate operation is the current installed PROJ selection. Explicit
`--coordinate-operation historical-no-grid` selects the documented EPSG:3005-to-6933
pipeline without a datum grid for historical reproduction; it rejects other source CRSs.
This changes coordinate-operation provenance, not the default scientific vintage.
The exact pipeline, source/index hashes and geometry policy are recorded in the work
manifest. `--geometry-policy make_valid` is an explicit choice; rejection is the default.

The command writes native diagnostics and missing-support keys to its work directory,
then exports metric-only tables through `write_areas`. It does not replace a source gap
with zero. Index work directories must be new. Resource guards remain necessary for
large regional runs; reduce `--batch-size` if spatial batches become large.

## Limits

These paths cannot supply absent classified shoreline, qualified BC estuary geometry,
the original anthropogenic water mask or positive reef evidence. Source-access denials
remain manual prerequisites. Three unsupported R6 cells are reported separately:
`861299397ffffff`, `86129955fffffff`, `8628f1617ffffff`. Do not fabricate values or add
status columns to the final metric schema.
