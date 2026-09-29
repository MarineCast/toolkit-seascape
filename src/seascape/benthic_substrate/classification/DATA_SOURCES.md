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
