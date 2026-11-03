# Seagrass source evidence

The [canonical Seagrass contract](../../../../docs/seagrass.md) documents source rights, eligible geometry, species and temporal support. All Time geometrically unions the WA DNR Whatcom 1995 and Skagit 1996 remotely mapped eelgrass class polygons with legacy BC CRIMS eelgrass polygons and the retained Peng et al. (2026) Sentinel-2 2019–2020 and 2023–2024 positive classified pixel footprints (CC BY 4.0, DOI 10.5281/zenodo.18612240).

The annual generated feature is retired; original survey years remain provenance. Unknown observation dates stay unknown; CRIMS map dates and composite endpoints never become observation years. Relative abundance/importance never scales footprint area. Generic satellite seagrass remains modeled, with no species resolution and clear-water/depth/turbidity limits. Background/nodata is not field absence. Monitoring sample frames, point/line evidence and all Kelp are excluded from mapped area. Per-record original attributes, source methods, periods, species resolution and recorded geometry processing remain in the internal normalized inventory and source/quality metadata.

The satellite component is one generic seagrass class derived from Sentinel-2 imagery. The
distributed extent tiles are binary (`1` = mapped seagrass; `0` =
background/nodata), so dense and sparse model classes are intentionally
combined. It is not an eelgrass species map, a field survey, or evidence of
absence outside mapped positive pixels. Its published scope is clear, shallow
coastal water; turbidity and depth therefore remain observation limitations
rather than habitat zeros.

## Checksum convention and bounded cached-source evidence

The download manifest's `sha256` uses the repository's `checksum_path`:
SHA-256 over the UTF-8 filename followed by the complete compressed archive
bytes, without a separator. It is not the raw-byte SHA-256 printed by `shasum`.
Compare matching algorithms; record raw-content and repository checksums under
separate explicit names. Do not replace a retained expected digest to resolve
a comparison made with different input conventions. Configured MD5 checks use
raw content. Neither convention hashes an extracted TIFF or normalized product.

A 2026-10-08 sample-only qualification checked 32 block-aligned 256×256 windows
across the three TIFFs intersecting the established regional bbox. Of 2,097,152
sampled pixels, 53,839 were valid class 1; the other 2,043,313 were declared zero
nodata/background. Positive samples occurred in three northeast-tile blocks
and four southeast-tile blocks; eight northwest-tile samples were all nodata.
This purposeful sample is not representative regional coverage, full-cell H3
area, field-observed presence or absence. Cached source/configuration evidence
supplies the model meaning and 2023–2024 composite period; a live provider
metadata refresh was unavailable. Retained CC BY 4.0 attribution must accompany
any future qualified derived product. See the [coarse-v1 plan](../../../../docs/methodology/coarse-v1-plan.md).
