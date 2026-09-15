# Sentinel-2 seagrass source

The production layer uses Peng et al. (2026), *Global 10-meter seagrass maps*,
Zenodo DOI `10.5281/zenodo.18612240`, for the 2023-2024 period. The archive is
CC BY 4.0 and is checksum- and size-validated by `download.py`.

This is one generic seagrass class derived from Sentinel-2 imagery. The
distributed extent tiles are binary (`1` = mapped seagrass; `0` =
background/nodata), so dense and sparse model classes are intentionally
combined. It is not an eelgrass species map, a field survey, or evidence of
absence outside mapped positive pixels. Its published scope is clear, shallow
coastal water; turbidity and depth therefore remain observation limitations
rather than habitat zeros.
