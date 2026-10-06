# Bounded GEBCO subset acquisition

This acquisition-only API implements the reviewed GEBCO_2026 elevation request. It does
not compute metrics or qualify reporting/compute support. The accepted source extent is
west −131.0°, south 45.1°, east −120.2°, north 52.3°; it is an acquisition envelope,
not a reporting domain. Marine membership, graph closure, source accuracy and regional
release remain separately qualified. R6 remains the reporting default; no R5 network is added.

## Contract and provenance

The official [GEBCO_2026 grid](https://www.gebco.net/data-products-gridded-bathymetry-data/gebco2026-grid)
is a 15 arc-second global elevation grid, DOI `10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa`,
released April 2026. Native elevations are metres, negative under water; this adapter preserves
the values, sign, nodata and native grid. A release date is not an observation date. Observation
period stays null. GEBCO assumes mean sea level, but heterogeneous shallow-water inputs can use
other datums. No uniform exact-member datum, vertical conversion or cell accuracy is claimed.
The data are public domain subject to [GEBCO conditions and attribution](https://www.gebco.net/data-products/gridded-bathymetry/terms-of-use).
No new agreement is accepted and no account is created or used. Explicit provider agreement or
account requirements, including HTTP 401/403, stop the run with retained failure evidence.

The exact template selects grid ID 1 `gebco_2026_global`, source ID 1 `gebco_2026`,
format ID 2 `geotiff` (Data). Fresh catalogs must match; no global/version/TID fallback is
allowed. The template has null email, ID `0`, status `new`, one item ID 0, and submission-date
placeholder `REPLACE_WITH_ACTUAL_UTC_AT_SUBMISSION`. Only that date is replaced at execution.
The native GeoTIFF must be one Int16 EPSG:4326 band, 2592 × 1728, north-up, aligned exactly to
the accepted extent, scale 1, offset 0, resolution 1/240 degree. Explicit band units must be
metres. Absent units require the retained provider metre description. Unknown or non-metre
units fail; no conversion/resampling occurs. Header validation does not decode source pixels.

The uncompressed sample array is 8,957,952 bytes. Archive bytes remain provider-dependent;
the preflight estimate was 16MiB, not a promise. One static source vintage is retained, never
copied into annual products or backdated. No source acquisition is silently triggered by
planning, source probes, the synthetic CLI, or the validation notebook.

## Execution and resource limits

The function `acquire_bounded_gebco_subset` in
`seascape.seafloor_physiography.bathymetry.subset_acquisition` takes an exact template path,
an explicit staging workspace, and optional `SubsetBudget`. Calling it submits one real queue
request. Live execution follows independent code review and resource coordination; offline
tests inject a fake session and never contact GEBCO.

Required limits are 64MiB total request/response body transfer, 128MiB retained staging,
512MiB process peak RSS, 900 seconds and one worker. The budgets can be reduced, never
increased. Network headers/TLS overhead are excluded from body accounting. Reads request at
most 64KiB and never deliberately read beyond the remaining transfer allowance. A declared
oversize response is refused before its body; an unknown-length response that reaches the
remaining allowance is refused without reading another byte. Metadata responses have a 1MiB
cap. HTTP compression, redirects and automatic retries are disabled. There is one POST to
`/queue`, followed by `/queue/status/{basketId}` polls at 10-second intervals, then one
`/queue/download/{basketId}` GET. Unknown/failed statuses stop; no automatic resubmission.
HTTP calls have at most 60 seconds timeout and the remaining cooperative time allowance.

Staging checks reserve 64KiB for terminal failure evidence before incoming writes. The ZIP
may contain at most 128 members and 32MiB total declared uncompressed bytes. Every member
path/type/size is checked, including members not extracted. Traversal, absolute/drive paths,
backslashes, duplicate paths, special files, encrypted entries and multiple GeoTIFFs fail.
Only the single GeoTIFF is extracted to a fixed owned filename, with streamed size, SHA256
and ZIP CRC checks. The source ZIP and all response/request evidence remain retained.
RSS/time checks are cooperative, not OS hard bounds on transient allocations; callers should
launch a fresh dedicated process. The retained receipt records actual peak RSS, elapsed time
and body bytes. Partial failed generations are preserved for diagnosis and manual decision;
this adapter never deletes earlier sources or modifies the old production cache.

## Owned evidence and limits

Each run creates a new exclusive `gebco-subset-acquisitions/<uuid>` under staging. It retains
template/submitted JSON, sanitized response headers/status and bounded bodies, source ZIP,
selected native member, and an acquisition or failure receipt. The success receipt binds the
code identity, archive/member hashes, complete retained file inventory, source/catalog
identity, measured grid/units/nodata, acquisition UTC time and resource measurements. It
carries false source-accuracy, shared-reporting, production, artifact-release and regional
release eligibility. It is acquisition evidence, not a scientific audit PASS. It never writes
final `Data/seascape` products. Independent pixel/sample and support qualification must follow
before any source-backed metric table is published.

Requests and Rasterio already belong to runtime dependencies. Offline validation:

```bash
PYTHONPATH=src python -m pytest -q tests/test_gebco_subset_acquisition.py
python -m mypy src/seascape/seafloor_physiography/bathymetry/subset_acquisition.py
```

Then run the repository full suite, quality and documentation gates in `AGENTS.md`.
The required offline notebook remains unchanged because this optional network acquisition
API does not enter its deterministic production-API path. Live acquisition is untested by
these offline checks.
