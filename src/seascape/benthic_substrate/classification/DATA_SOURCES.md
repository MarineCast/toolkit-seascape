# dbSEABED substrate source

This pipeline downloads the December-2025 dbSEABED global 0.1-degree GeoTIFFs
published through HUB Ocean's Ocean Data Platform. Rock/hard-bottom presence is
an IDW3D percentage surface. Gravel, sand, and mud are CoDA-closed percentage
surfaces interpolated with IDW3D. All four files use the same global grid and
cross the Canada-U.S. border without a source seam.

The exact public dataset UUIDs, raw-file IDs, expected byte counts, version,
and attributions are pinned in `config/data/environment_seascape.yaml`.
`download.py` fetches and manifests those files. The unrelated public
`bmi-dbseabed` example rasters are Gulf of Mexico products and are not used.

The H3 output is modeled evidence sampled at the water-support representative point,
not an areal survey of each H3 cell. The source's rock-presence grid is kept separate
from gravel, sand, and mud texture grids; it is **not** multiplied by the complement
of their values or treated as measured rock areal cover. `SUBSTRATE_ROCK_FRAC` is a
legacy field name for the modeled rock-presence score; new consumers should use
`SUBSTRATE_MODELED_ROCK_PRESENCE_SCORE`. `SUBSTRATE_GRAVEL_FRAC`, `SAND_FRAC`, and
`MUD_FRAC` retain source texture percentages. The sediment-only entropy uses those
three values only where they close within 0.001 of one. It does not combine rock with
sediment. Unsupported boulder, cobble, and mixed fields are null, not physical zeros.
`SUBSTRATE_INTERPOLATED_COVERAGE_FRAC` is deprecated and null because one point sample
cannot establish areal coverage; `SUBSTRATE_POINT_SAMPLE_AVAILABLE` records sampling
availability. Nodata and invalid percentages remain unavailable or fail validation.

The [USGS dbSEABED format overview](https://www.usgs.gov/programs/cmhrp/science/usseabed-data-format-and-content)
and [USGS parsing discussion](https://www.usgs.gov/programs/coastal-and-marine-hazards-and-resources-program/science/parsing-dbseabed)
describe sediment texture and fuzzy rock membership as distinct measurements. The
separately pinned December 2025 HUB Ocean rock and sediment catalogs in configuration
were not accessible for a line-by-line unit and compatibility verification during
this update. The conservative method therefore does not assert that their four rasters
form one physical composition. Confirm their exact versioned provider documentation,
sampling basis, and redistribution license before restoring any joint physical
index or publishing source rasters. Earlier immutable releases retain historical
four-part closure and must not be reinterpreted as the v2 separate-measurement output.

## Exact provider metadata addendum (2026-10-08)

The public [HUB Ocean STAC API documentation](https://docs.hubocean.earth/reference/stac-api/)
provides a metadata route independent of the unavailable catalog pages. The exact
[rock item](https://api.hubocean.earth/api/stac/collections/21438ada-2891-4aa8-8831-75e342c83e20/items/e36187d8-c249-45ed-af53-47a06f52cf5d)
and [sediment item](https://api.hubocean.earth/api/stac/collections/21438ada-2891-4aa8-8831-75e342c83e20/items/5065080c-b9e7-4e08-b1f5-3a757007cade)
were verified through a small official search response. Both titles
identify `[ver202512]` and both declare `cc-by-4.0`. Preserve attribution and
original cached receipts; their older unspecified-license text is historical.
Do not substitute an older January product's terms.

Rock metadata states modeled percentage coverage, including bedrock, consolidated
sediments, coral frameworks and biogenic/chemogenic hardgrounds. This is broader
than a measured lithic-rock fraction. Sediment metadata identifies Wentworth size
classes and CoDA/IDW3D, but does not specify the stored TIFF percent/fraction scale.
Cached headers have scale 1, offset 0, no unit tags and nodata −99. Configuration
percent units remain to qualify against exact file encoding before processing.
No metadata establishes one joint physical rock-plus-sediment composition;
measured hardness and areal H3 habitat/survey fractions remain unsupported.

### Exact sediment file encoding verified

A small official raw-file Arrow listing for dataset
`5065080c-b9e7-4e08-b1f5-3a757007cade` was structurally decoded on 2026-10-08.
Rows `43bb37e3-a2f`, `c6e23264-ac2` and `13b201b8-e1b` identify the configured
gravel, sand and mud GeoTIFFs directly, each with a file-specific fraction (%)
description. Their sizes, float32 grid, CRS, affine and nodata −99 match cached
headers. This resolves the stored-percent qualification noted above; it is not
inferred from PNG units or numerical closure. Local value bounds, missingness,
bilinear renormalization and conditional sediment closure passed the reviewed
direct native R6 pilot and regional numerical validation. Modeled rock percentage was separately qualified
by its exact STAC record. No joint rock-plus-sediment composition or measured
hardness is established by this metadata.
