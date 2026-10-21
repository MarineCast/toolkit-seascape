# Source closure and shared-study integration

This local study uses source-derived research geometry authorized on 2026-10-16. It combines
GSHHG 2.3.7 with BC Freshwater Atlas coast and river delimiters for Muchalat/Knight inlet heads
and Active/Porlier/Sansum channel connections. The geodesic offshore reach is 22,224 m with a
10 m numerical envelope; source positional accuracy and historical shorelines are unestablished.
Agency name points select physical source water faces and identify channels; they do not define
boundaries. Research axes and local bank sections retain analyst-selected extent and grid limits.

The current registry selects 463 native R5, 2,427 native R6 and 13,461 native R7 reporting cells;
Seascape retains 81,380 native R8 companions. Viewshed has separate 26,573 land and 20,686 water
source cells, including mixed cells in both roles. Its explicit 32 km source extent includes
30 km LOS, a 1 km AOI margin and a 1 km conservative projection/numerical guard. Complete native
terrain and canopy paths still need their own coverage verification before a weight rebuild.

The study has 30 named main-basin outlets, 24 local gateway geometries and 13 bounded passage
axes. All 30 outlets attach at R8 after five coordinate-source repairs: four FWA river endpoints
and the official GNIS Queets mouth coordinate. R6 source/target and route limitations remain
explicit. Source-to-mask registration gaps, terminal connector costs and original basin identity
are retained. No terminal connector is introduced as a canonical transit edge. These are research
bindings, not a complete inventory of delta branches or every coastal passage.

## Resolved source paths

The official USGS final legacy NHD HU4 archives replace the unavailable map-service path for this
study. The regional raw extract contains 839,637 flowline occurrences. Native adaptation retains
839,626 unambiguous features, quarantines two conflicting occurrences of one permanent ID and
keeps source-member identities for identical overlaps. Explicit NHDFlow network-end records resolve
2,885 terminal flags; 8,614 features retain unknown terminal status. The integrated mixed-source
inventory contains 8,222 mapped mouth candidates and 312 widths measured from mapped polygons.
Configured/default widths retain their estimation provenance; the inventory is not discharge,
plume extent, a complete physical mouth census or an annual historical reconstruction.

NOAA's Puget Sound 2014 and Juan de Fuca 2015 NAVD88 DEMs supply numeric floating-point subsets for
three passage analyses. The service's default 8-bit GeoTIFF rendering was rejected. Float source
values, CRS, actual grid, datum, sign and checksums are retained; no local datum conversion is
applied. The source products include historical surveys and interpolated cells, so datum reference
qualification is not current observation accuracy or a validated controlling depth. Remaining
passages retain nominal CHS NONNA diagnostics with unresolved heterogeneous contributing datums.

## Outputs and use

The explicit study request and pinned mask/support manifest are selected through the standalone
[shared-study API](API.md#explicit-shared-study-selection). The flat study catalog lives at
`Data/Seascape/catalog.json`. Named inventories, long relationships, cross sections and route
diagnostics live under `Data/Seascape/research/`, separately from the flat per-H3 tables. The study
mask, memberships and source-support registry live under `Data/Study/vancouver-island-columbia/`;
their manifest references the canonical domain products. Byte checksums and native support remain
attached to reads. No duplicate study-specific domain product directory is maintained.

The historical extraction has 13 areas and 21 native resolution/time variants. Canonical storage
also retains six older areas, yielding 19 areas and 33 variants. Older-only areas retain their
original source context and do not acquire the new mask qualification through relocation. New
versions replace matching areas, including removal of stale omitted variants. Fourteen additional
named-object and long relationship artifacts are pinned in the research manifest. Regional
readback checks verified exact byte identities, key uniqueness, relationship cardinality,
missing-data states and source connector cost components. The R8 outlet table contains 2,441,400
rows and the R8 gateway table 1,953,120 rows, including explicit unavailable or disconnected states.
All 30 outlet sources attach at R8; eight remain unavailable at R6. Gateway route diagnostics
retain 19 reachable alternate routes and five graph disconnections at R8. A graph disconnection
does not independently establish a physically critical gateway.

The 196 passage sections include 53 sections with qualified source datum references across three
passages. Maximum depth is available for 42 sections and complete area for eight; 89 sections are
bank-censored. All canonical depth fields remain null for the other 143 sections, and no sill
candidate passed the configured criteria. Depth availability does not establish surveyed accuracy.

Seascape's structural R6 products contain 2,445 parent unions of selected R8 cells. The independent
native R6 registry contains 2,427 cells: three have no structural counterpart and 21 structural
parents are outside the native selection. The public study reader reports these differences;
it does not fabricate the three missing records or substitute full native-cell denominators.
Exposure and waterbody writers serialize unavailable distances as Arrow nulls with retained QC.
Their manifests inherit the configured water-source lineage and source rights.

The requested modeling window remains `[2009-01-01,2027-01-01)` UTC. Annual mapped kelp positive
footprints provide 2009–2024 source evidence, with 2025–2026 unavailable. Seagrass is retained at
its native 2019–2020 and 2023–2024 composite support. The DFO mapped substrate classes cover about
16.49% of reporting water and do not populate a calibrated physical hardness index. Static source
vintages remain static reference layers. Missing years, unmapped areas and incomplete measurements
remain missing; none establish observed ecological absence.

## Remaining scientific qualifications

Source datum qualification is unavailable for ten passages. Bank-censored or incomplete-depth
sections cannot establish complete area or depth-threshold width. Derived sill candidates are
separate from mapped and confirmed sills; no confirmed regional sill inventory is supplied.
Independent tidal-frame qualification, complete mapped habitat classes, calibrated physical
hardness and unpublished source years remain unavailable. These limits keep full-catalog physical
qualification and model readiness false. The shared selection does not approve ecological fits,
imputation, prediction, deployment or redistribution.

GSHHG retains LGPL terms, BC FWA retains the Open Government Licence–BC, and the IHO Sea Areas v3
selection source retains its dataset-specific CC BY-NC-SA 4.0 terms. No commercial redistribution
clearance is implied. Primary source records:

- [BC Freshwater Atlas](https://www2.gov.bc.ca/gov/content/data/geographic-data-services/topographic-data/freshwater)
- [USGS NHD data access](https://www.usgs.gov/3d-hydrography-program/access-3dhp-data-products)
- [USGS NHDFlow dictionary](https://www.usgs.gov/ngp-standards-and-specifications/national-hydrography-dataset-nhd-data-dictionary-miscellaneous)
- [NOAA Puget Sound NAVD88 DEM](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.dem:5165)
- [NOAA Juan de Fuca NAVD88 DEM](https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ngdc.mgg.dem:11514/html)
- [CHS NONNA source-datum limitations](https://www.chs-shc.gc.ca/help-aide/faq-eng.html?wbdisable=true)
- [IHO Sea Areas v3 source and licence](https://www.vliz.be/en/imis?module=dataset&dasid=5444)
