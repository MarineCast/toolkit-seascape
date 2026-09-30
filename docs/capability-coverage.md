# Physical seascape capability coverage

Status distinguishes implemented code from a materialized candidate or validated release. The
checked-in catalog and product index describe **older** materializations; this branch's method
changes need a fresh, source-backed candidate before release. No entry below implies independent
scientific validation, universal coverage, or a regional product built in this branch.

| Capability | Status on this branch | Support and limiting evidence |
| --- | --- | --- |
| GEBCO depth, terrain, geomorphic units | Implemented; new meanings unmaterialized | Direct pixels at R8/R6 for depth; H3 neighborhood at R8 for terrain; GEBCO spacing is not accuracy. |
| GEBCO categorical TID | Implemented but unmaterialized | Optional aligned 2026 TID raster must be supplied locally; fixture only. Source type is not uncertainty. |
| Geometric directional fetch | Implemented but unmaterialized | 16 censored straight-line bearings at R8 from land/water geometry. |
| Shoreline character, proximity, exposure, morphometry | Existing; regional coverage source-dependent | Class lengths and water geometry; new bearing fields await a candidate. |
| Modeled rock presence, sediment texture | Corrected but unmaterialized | Separate dbSEABED measurements; exact December 2025 provider basis needs verification. |
| Physical bottom hardness / hard-substrate area | Data/definition blocked | No justified common rock/sediment areal denominator; new candidate returns null with reason. |
| Sentinel seagrass, annual floating kelp, reef evidence | Corrected but unmaterialized | Positive geometry is not a complete survey footprint. Availability year may be unknown. |
| Fluvial connections, estuary proximity, mapped modifications | Existing, source-dependent | Local inventories and jurisdictional coverage vary; source manifests and QC apply. |
| Intertidal marsh, mudflat, rocky platform | Generic producer fixture-tested; regional sources absent | Explicit tidal-frame support is separate from the marine mask. Regional survey geometry, datum, rights and absence semantics remain unverified. |
| Locally observed eelgrass | Generic producer fixture-tested; regional sources absent | Register jurisdictional survey footprints/events, dates, rights and spatial support; generic satellite seagrass is distinct. |
| Understory kelp and other macroalgae | Generic producer fixture-tested; regional sources absent | Canopy/shoreline maps do not establish understory absence; register benthic survey method and footprint. |
| Coral, sponge, structural bivalve | Data blocked | Point/line evidence cannot become reef-area polygons; register geometry, method, rights and temporal coverage. |
| Observed sediment detail | Data blocked | Register primary samples, measurement basis, units and spatial coverage separately from modeled 0.1° texture. |
| Finer regional bathymetry | Data blocked | Register survey, rights, horizontal/vertical datum, gridding method and source-specific uncertainty. |
| Shoreline density, sinuosity, islands, orientation | Optional producer fixture-tested; regional materialization absent | Source coast and complete land components are required; smoothing and denominator are explicit. |
| Selected outlet relationships (SV-01) | Executable and fixture-tested; regional input and materialization pending | Exact reviewed mouth IDs, canonical water graph; no independent validation. |
| Nearshore transitions (SV-02) | Executable and fixture-tested; regional materialization pending | Raster-footprint areas, water-facing transects and bounded native-scale deep-pixel components. Subpixel connectivity and selected-boundary continuation remain unresolved. |
| Passage sections and sill candidates (SV-03) | Executable and fixture-tested; reviewed registry absent | Candidate shoals are section-maximum proxies. Optional reviewed mapped/validated crest registry is supported but not populated regionally; independent validation pending. |
| Geographic gateways (SV-04) | Executable and fixture-tested; reviewed registry absent | Reviewed graph attachments and crossing edges required; no regional materialization. |
| Mapped habitat mosaic (SV-06) | Generic ingestion and producer fixture-tested; regional providers absent | Distinct marine/intertidal supports; provider rights, time, footprint and class semantics require review. |
| OrcaCast SV-01–SV-06 output | Exact-release consumer implemented; regional output absent | Requires all 27 released products from one audited release; copies native-grain tables and provenance without activating model predictors. |
| Outer-coast shelf geometry (SV-07) | Source blocked | Reviewed shelf delineation unavailable; no product advertised. |
| Estuarine polygons/classes | Data/harmonization blocked | Preserve native B.C./Washington classes until cross-border definitions and tidal support are reviewed. |

For any blocked source, registration needs a provider URL/version, redistribution rights,
geographic and observation-time footprint, available-at time when known, native spacing/geometry,
sampling method, datum/units, explicit absence meaning, uncertainty availability, and a bounded
validation fixture. Adding null columns to claim coverage is not an implementation.
