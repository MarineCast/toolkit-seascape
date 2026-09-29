# README regional map

The README image is a static cartographic export of the existing
[San Juan exploratory pilot](pilots/san-juan.md), replicate 1. It replaces the synthetic
illustration in “What you get”; the [offline demo](demo.md) remains synthetic and does
not reproduce this regional result. No source acquisition or producer rerun is involved.

## Figure contract

- **Question:** where are the example products, and what do their depth values represent?
- **Surface:** a PNG in the README, rendered with Matplotlib/GeoPandas; a geographic
  choropleth of existing clipped H3 R8 cells, not a smoothed raster or invented basemap.
- **Values:** `BATHYMETRY`, the production mean depth in metres, positive down; joined to
  existing geometry one-to-one by `H3_INDEX`. All 4,660 cells remain represented:
  4,384 have depth and 276 have null depth. Available means span 1–354 m.
- **Encoding:** fixed linear 0–400 m scale, mint `#ECFDF5` through teal `#0F766E` to
  deep blue-teal `#06465A`, matching the README diagram and banner. Gray means unavailable;
  pale ocean outside pilot support is distinct from land and from shallow valid depth.
- **Context:** named islands/waterways, approximate editorial place-label anchors,
  a Pacific Northwest locator, projected true-north arrow and 10 km UTM scale bar.
  Labels are orientation aids, not an authoritative gazetteer or jurisdiction layer.
- **Projection:** WGS 84 / UTM zone 10N (EPSG:32610). Geometry is reprojected for display;
  stored values and original products are unchanged. No interpolation or null filling.

## Sources and limits

Depth: GEBCO Compilation Group (2026), GEBCO 2026 Grid,
DOI [10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa](https://doi.org/10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa).
The cached input has 15 arc-second spacing; that is not a claim of uniform measurement
resolution or accuracy. Land: Natural Earth v5.1.1, 1:10 million cartographic land polygons.
Both sources are public domain; see the pilot's source references and acknowledgement.
This figure does not imply provider endorsement.

The generalized coastline and exploratory water support can omit small islands or simplify
channels. This is not a navigation chart, a complete audited regional release, or evidence
of model readiness. Source coverage, missingness and scientific limitations remain those
of the pilot. Only the rendered illustration and checksum evidence are committed, not the
cached source datasets or scientific products. Historical manifests are unchanged.

## Reproduction

Use an existing Seascape development environment with its declared plotting/geospatial
runtime dependencies, the documented replicate-1 pilot workspace, and the existing extracted
Natural Earth cache. The renderer refuses a different bathymetry product identity, checks
manifest artifacts, validates one-to-one cell identity, and rejects depths beyond its scale.
It does not download missing inputs. If the temporary pilot workspace is gone, this exact
render is unavailable until the approved inputs/products are restored; do not silently rebuild.

From the checkout, with explicit paths to those existing inputs:

```sh
MPLCONFIGDIR=/tmp/seascape-map-mpl python scripts/render_readme_map.py \
  --workspace /private/tmp/seascape-pilot-01-20260927/replicate-1 \
  --land notebooks/outputs/data/raw/natural_earth/ne_10m_land/ne_10m_land.shp \
  --output docs/assets/san-juan-bathymetry.png
```

The adjacent [render evidence](assets/san-juan-bathymetry.json) records production-helper
checksums for the product, geometry, land input, rendered image, and the displayed cell counts
and depth range. Rendering writes only the requested PNG and JSON. The script does not change
scientific calculations, package APIs, source caches, canonical products, or retained releases.

## Validation of this export

At source base `fcd0a83`, using `/tmp/seascape-roadmap-dev/bin/python` and the matching
`ruff` executable, all following commands exited 0:

- The rendering command above: 4,660 cells, 4,384 available, 276 unavailable; the PNG
  was opened and inspected for geography, label placement, legend and source notes.
- `python scripts/check_docs.py`: 42 documents, 183 local links, 26 stages; external
  URLs were not checked by this offline validator.
- `python -m pytest -q tests/test_documentation.py`: 16 passed.
- `python -m pytest -q`: 410 passed, 3 skipped, 101 warnings. The three skips require
  materialized regional artifacts outside the clean-checkout tests; existing warnings
  concern affine-operation deprecations and a Folium tile-provider API key.
- `ruff check src tests scripts`, `ruff format --check src tests scripts` (238 files),
  `python -m mypy` (12 configured source modules), and `git diff --check`: passed.
- An additional assertion compared the marked README quickstart blocks byte-for-byte
  with HEAD, verified the exported PNG against its recorded checksum, and checked
  that available plus unavailable cells equals the total. Image size: 2160 × 1620.

The final renderer emitted no warnings. An earlier preview projected entire source features
before clipping, producing Shapely warnings; clipping in geographic coordinates before
reprojection corrected that display-only issue. No package build, fresh source acquisition,
producer rerun, release promotion, or new human-acceptance trial was performed.
