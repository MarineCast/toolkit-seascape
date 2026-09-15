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

The H3 output is modeled evidence. Rock is retained as exposed-rock fraction;
gravel, sand, and mud are compositionally closed within the remaining non-rock
fraction. dbSEABED does not separately support boulder, cobble, or mixed in this
four-raster contract, so those fields are zero only where all four inputs are
valid. Raster nodata remains null. The public catalog metadata does not state a
dataset licence, so redistribution terms must be confirmed before publishing
the source rasters outside this research pipeline.
