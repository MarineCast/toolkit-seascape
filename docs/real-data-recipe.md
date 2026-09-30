# Bounded real-data bathymetry recipe

This is a **preparation and candidate** recipe, not a regional build performed for scientific
hardening. The [earlier San Juan pilot](pilots/san-juan.md) documents a different executed revision
and cached inputs; its products are not results of this branch. The installed-wheel
[synthetic demo](demo.md) remains the first-use path without real source files.

Use a fresh workspace and a deliberately small W/S/E/N area such as
`(-123.35, 48.38, -122.70, 49.02)`; inspect the resulting candidate before any release action.
The source requirements are:

1. [GEBCO_2026 Grid](https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2026-grid): request a user-defined GeoTIFF crop for that bounding box through the official download app. Retain its archive metadata, 15-arc-second pixel grid, provider acknowledgement, terms and checksum. Place the extracted raster in the fresh workspace's configured `data/raw/bathymetry/` path; configure its exact filename. GEBCO is public domain with attribution conditions and is not suitable for navigation. Grid spacing is not sounding accuracy.
2. Optional [GEBCO_2026 TID Grid](https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2026-grid): obtain the matching categorical crop from the same release, preserve the source archive/checksum, and set `bathymetry.source.tid_raw_filename` plus `tid_release: "2026"`. The adapter requires identical pixel alignment; if the download app returns a different crop, stop and prepare an aligned provider crop without interpolating identifiers. Omitting TID leaves that optional product unmaterialized.
3. Canonical water-support inputs listed by `seascape ... build --dry-run --check-inputs --json` and [stage inputs](stage-inputs.md). They include jurisdictional boundary/shoreline sources with their own rights. A generalized [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) land mask can support a **separately labeled exploratory** example, not territorial/legal or full scientific release authority. Do not substitute it silently into canonical support.

After `seascape init` in the fresh workspace, edit its copied
`config/data/environment_seascape.yaml` to use the bounded area, local GEBCO filenames and
maximum four workers for support generation. Review `config/common.yaml` for the model area.
Run read-only preflight first:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-bathymetry \
  --dry-run --check-inputs --json > "$SEASCAPE_WORKSPACE/preflight.json"
```

Preflight checks only local paths/headers and planned dependencies. It does not verify source
pixels, alignment, scientific suitability, or permission to publish. If required inputs are
missing, stop and record the missing source by name; do not invoke a broader downloader. With
independently reviewed sources and a ready plan, run the selected stage and its dependencies
into an isolated candidate without `--publish`:

```sh
seascape --workspace "$SEASCAPE_WORKSPACE" build --only seascape-bathymetry \
  --candidate-root "$SEASCAPE_WORKSPACE/.seascape/scientific-hardening-candidate"
```

Inspect output keys, R8/R6 direct
pixel counts, null/QC distributions, TID count closure (if configured), manifests and checksums.
Use the [rebuild comparator](DEVELOPMENT.md#scientific-changes) only when an authorized old and
new candidate with matching source inputs exist. Do not overwrite canonical products or retained
releases. This recipe was **not executed** for this branch because the required regional inputs
are not packaged or acquired here.
