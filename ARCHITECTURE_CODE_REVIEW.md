# Architecture and Code Review — toolkit-seascape

> Historical pre-fix review. P1/P2 implementation and validation are recorded in
> [review remediation](docs/review-remediation.md); original evidence is retained below.

Review date: 2026-09-19. Baseline HEAD: `deeb1974c4f5270c831d5dc96e902b3b43a4d4dd`, **including the existing working-tree changes**. Line references describe that working tree.

This is a review, not an implementation change. Only this report was added. Existing changes to CI, ignore rules, guidance, README, dependencies, bathymetry download/tests, and notebooks were preserved. In particular, the notebook README, San Juan helper, and validation notebook were already untracked; their successful local validation does not establish that they are available in a clean Git checkout until included in a commit.

## 1. Executive Summary

**The repository is fundamentally well structured and independently installable, but is not yet ready to promise reproducible, immutable production inputs to downstream applications.** Keep the domain layout and finish a small set of contract fixes rather than undertake a broad refactor.

The strongest engineering features are the installed CLI and configuration resources, explicit producer ownership, dependency-ordered candidate workflow, provenance/checksum infrastructure, recoverable publication, and substantial deterministic tests. The main engineering risks are mutable paths returned as immutable products, candidate output paths that can escape isolation, and incomplete configuration invalidation on resume.

The most important scientific defects are confidence/value alignment by row position in the benthic composite, inconsistent handling of the supported bathymetry sign option, and configurable projected coordinates whose numeric units are accepted as meters without enforcement. These were reproduced with small offline counterexamples. They do not establish that existing regional outputs are wrong: the default configuration uses positive-down depth and a meter-based CRS, and current producer ordering can conceal the composite defect.

**Readiness:** suitable for controlled research and standalone toolkit development; production consumer certification should wait for findings F01–F06 and a separately provisioned regional acceptance run. No P0 incident was established; P1 findings below are significant, reproducible contract failures or concrete reliability risks, with their triggers identified.

## 2. Current Architecture

```text
Editable workspace YAML + packaged initialization templates
                  |
External sources: GEBCO; boundary/shoreline vectors; HydroRIVERS;
government river/barrier/estuary inventories; dbSEABED; habitat inventories;
OSM and authoritative physical-structure inventories
                  |
Family downloaders + shared HTTP/ArcGIS/WFS/cache helpers
                  |
Water geometry -> H3 geometry/support -> water graph/connectors/neighborhoods
                  |                         |
                  +------ family builders --+
                         | bathymetry -> geomorphometry -> geomorphic units
                         | coast/width/exposure; rivers/barriers/estuaries
                         | substrate -> hardness; habitats -> composite
                         | physical anthropogenic structures
                         v
             Candidate Parquet/vector/graph products + family manifests
                         |
               catalog -> static eligibility -> product documentation
                         |
                     release audit
                         |
             explicit CLI publication with journal + POSIX locks
                         |
             REPLACEABLE canonical paths + release manifest
                         |
       seascape.products discovery/resolution; snapshots; family APIs
                         |
              downstream applications / research / inspectors
```

`cli.py` dispatches 13 acquisition and 21 inspection selectors. `workflow.py` declares 26 dependency-expanded stages. `core/` owns generic configuration, geometry, artifact, and dataset primitives; `utils/` mixes shared infrastructure with substantive habitat-domain operations. Family builders commonly combine configuration loading, I/O, calculation, validation, and publication, but many extract deterministic calculation helpers.

The review inventoried and parsed all **156 Python modules, 33,216 source lines**, inspected all test-file names, and traced representative source paths across every domain family. Detailed inspection concentrated on public products, workflow/publication, bathymetry/terrain, coast/water networks, habitat aggregation/composition, acquisition, and contracts. This is not a line-by-line scientific certification of every provider or formula.

Guidance reviewed: workspace `../../AGENTS.md` and `../../WORKSPACE.yaml`, `../../.github/INFRASTRUCTURE.md`, repository `AGENTS.md`, README, architecture/contracts/configuration/workflow/development/migration/hardening documents, family guides, package configuration, CI, tests, and both notebooks. No Makefile, separate requirements/environment file, or dependency lock was found; `pyproject.toml` is the installation authority.

The existing Graphify graph located `DomainBuildStage` and its callers. It is **incomplete/stale relative to this checkout**: `resolve_product` is absent and workflow source locations have shifted. Source/AST inspection superseded it; it was not regenerated. These local graph queries used no LLM graph-generation tokens.

## 3. What Is Working Well

- **Real package independence.** No unresolved internal module paths were found by AST scanning of absolute and relative imports. The installed wheel imported all 155 discovered submodules, plus the root package, with OrcaCast imports actively blocked. No sibling checkout was needed.
- **Focused ownership.** Static terrain, mapped substrate/habitat evidence, hydrologic geometry, and physical structures fit a reusable seascape toolkit. Inspectors are domain QA tools. There is no demonstrated forecast/model-fitting dependency. `modeling/feature_policy.py` is a documented static-eligibility compatibility shim, not active predictive modeling.
- **Useful public interface already exists.** Root exports and `seascape.products` provide discovery, exact resolution selection, frozen metadata, and checksums. Family APIs and the water-network facade offer reusable operations. An entirely new API framework is unnecessary.
- **Strong identity and missingness patterns.** `utils/spatial.py::align_to_model_support` rejects duplicates/out-of-support cells and uses a validated left join. Network outputs retain null distances and reasons for disconnected support. Habitat evidence distinguishes mapped presence, explicit absence, and unsurveyed; modeled substrate is not relabeled as observed habitat.
- **Meaningful spatial tests.** Existing tests cover water-passable edges, components/connectors, radius sums, depth-band closure, water-connected anomalies, circular aspect, shoreline distances, width/sill mechanisms, polygon overlays, percentage conversion, and feature-aware aggregation.
- **Publication engineering deserves preservation.** Journals, backups, fsync, manifest-last promotion, rollback, crash recovery, and reader/writer tests are materially stronger than independent file overwrites. F02 concerns the lifetime of a returned path, not absence of transaction protection.
- **Configuration is mostly appropriately placed.** Provider URLs, source vintages, bounds, resolutions, neighborhood scales, thresholds, and paths are configurable. Domain definitions such as depth bands, documented hardness weights, and categorical ontologies can remain versioned code constants.
- **Offline acceptance uses production code.** The validation notebook calls `run_pipeline` and produces real Parquet/manifests. It does not substitute a notebook-only bathymetry implementation.

## 4. Findings

Severity: P0 = critical correctness/security/data-corruption risk; P1 = significant scientific/architecture/reliability issue; P2 = maintainability/testing or bounded correctness weakness; P3 = cleanup. Findings distinguish demonstrated behavior from risks and optional improvements.

| ID | Severity | Area | Finding | Evidence | Recommendation |
| -- | -------- | ---- | ------- | -------- | -------------- |
| F01 | **P1** | Scientific identity | Benthic composite aligns values and confidence by independent row indices, so valid input permutations change scientific output. Inner joins also silently reduce support before publication. | `src/seascape/biogenic_habitat/composite/build.py:98–175`: separate merges at 109/135; richness at 150; positional arrays at 159–175. Reproduction below. | Require identical unique `(H3_INDEX, H3_RESOLUTION)` support; align confidence to values by those keys before every mask/array operation. Fail on missing keys. |
| F02 | **P1** | Public product lifetime | A frozen `ProductArtifact` does not identify immutable bytes after resolution returns. Its path can be overwritten by the next publication. | `src/seascape/products.py:124–184` releases the snapshot on return; `src/seascape/publication.py::stage_candidate` targets canonical paths; `src/seascape/release.py:614–639` promotes replacements. | Resolve persistent release-addressed files, or introduce a supported context-managed read API and explicitly narrow the existing path guarantee. Prefer release-addressed storage for reproducible consumers. |
| F03 | **P1** | Depth/terrain semantics | `negative_elevation` is accepted by bathymetry, but terrain consumers interpret `BATHYMETRY` as positive depth. Aspect and signed position/curvature change; positive-depth classification thresholds receive negative inputs. | `bathymetry/pipeline.py:110–115`, `bathymetry/build.py:329–330`; `geomorphometry/build.py:467–505,606–637`; `geomorphic_units/build.py:255–294,340–370`, all under `src/seascape/seafloor_physiography/`. | Normalize once to a declared positive-down calculation contract using input metadata, or reject unsupported sign combinations before building dependent products. |
| F04 | **P1** | Distance units | A projected CRS is not necessarily meter-based. Isobath distances can be emitted in feet under `_M` columns; several shared consumers do not even enforce projected axes. | `src/seascape/seafloor_physiography/bathymetry/build.py:257–287` checks only `is_projected`; `src/seascape/utils/spatial.py:54–79` returns raw transformed coordinates. Meter/foot reproduction below. | Validate projected horizontal axes and meter units centrally, or explicitly convert linear units. Apply at configuration boundaries used for lengths, areas, and terrain gradients. |
| F05 | **P1** | Candidate isolation | Absolute/custom output paths survive candidate rendering and can write outside the candidate before release approval. The candidate environment also suppresses the canonical family writer lock. | `src/seascape/workflow.py:753–829` rewrites only known relative prefixes and preserves absolute paths; `src/seascape/publication.py:42–44` returns false when `SEASCAPE_CANDIDATE_ROOT` is set. `docs/CONFIGURATION.md` acknowledges isolation limits. | Preflight resolved producer output paths before invoking any builder; reject destinations outside the candidate or map explicitly declared outputs into it. Keep source inputs separately permitted. |
| F06 | **P1** | Resume/reproducibility | Editing named-area bounds in `common.yaml` does not invalidate stage state. Old geometry/products can be reused under a changed intended region. | `src/seascape/workflow.py:837–852,902–939` hashes project/direct domain YAML only; `src/seascape/core/config/common_areas.py:14–18,68–84` loads geographic definitions separately. | Fingerprint the effective scientific configuration and transitive dependencies, including named areas and resolved interpolation; record it in stage and release provenance. |
| F07 | P2 | Semantic schema | Configurable slope quantile is always published as `Q90`, even when configured to 0.95 or another permitted value. | `src/seascape/seafloor_physiography/geomorphometry/build.py:161–163,348,553–555`. | For the existing stable schema, require 0.90; alternatively version a parameterized column/catalog contract. |
| F08 | P2 | Raster scientific assumptions | Native slope validates band count/CRS but assumes unrotated angular pixels and derives gradients before restricting to marine pixels. Coastal land values can affect submarine slope; affine rotation is ignored in step lengths. | `src/seascape/seafloor_physiography/geomorphometry/build.py:304–322`. | Enforce supported affine geometry and document/test the coastal stencil and edge/nodata policy. Treat these as assumptions requiring validation, not proof that default GEBCO outputs are invalid. |
| F09 | P2 | Configuration consistency | Direct APIs resolve composed/interpolated configuration, while workflow preparation reads plain project/direct-include YAML and manually rewrites strings. | `src/seascape/core/config/document.py::_load_recursive,_resolve_values`; `src/seascape/workflow.py:794–829`; acknowledged in `docs/CONFIGURATION.md`. | Use one effective-config resolution path before planning/rebasing; until then explicitly reject unsupported composition before any writes. Coordinate with F05/F06. |
| F10 | P2 | API/maintainability | The consumer facade is useful, but producer APIs, private helper reuse, and “public utils” have inconsistent support boundaries. Shared habitat modules contain domain calculations despite a source-agnostic-utils description. | `src/seascape/__init__.py`, `docs/ARCHITECTURE.md::Interfaces`, `src/seascape/utils/README.md`; `biogenic_habitat/reef/build.py:59` imports `_network_metrics`; `utils/habitat_aggregation.py` owns aggregation semantics. | Document a small supported API with return/error/side-effect contracts. Keep domain helpers explicitly internal unless shared intentionally. Consolidate ownership during fixes, without wholesale directory moves. |
| F11 | P2 | CI/reproducibility | CI exercises installs, tests and wheels, but no explicit lint/type/secret/dependency-vulnerability jobs or reproducible dependency baseline are present. Source uses direct `urllib3` APIs without declaring it directly. | `.github/workflows/ci.yml`; `pyproject.toml` lower-bound dependencies; `src/seascape/seafloor_physiography/bathymetry/download.py:17`. `urllib3` currently arrives through Requests. | Add focused static checks and dependency/security checks without weakening tests; record a validated environment/constraints snapshot and declare direct runtime dependencies. Avoid exact-pinning every library consumer. |
| F12 | P2 | Notebook documentation | README describes the Data Explorer as a canonical-release reader, while the current notebook defaults to live acquisition/building an exploratory Natural Earth mask. | `README.md:52–54`; `notebooks/README.md:11–17`; `notebooks/01_DATA_EXPLORER.ipynb` configuration/download cells; helper `build_exploratory_water_mask`. | Update current docs to the actual side effects and interpretation boundary. Preserve the offline validation/live exploration distinction. |
| F13 | P3 | Compatibility/navigation | Static eligibility compatibility aliases and a stale graph add navigation ambiguity, but are not runtime blockers. | `src/seascape/modeling/feature_policy.py`; graph lacks `resolve_product`; historical `docs/hardening-review.md` describes an earlier notebook. | State deprecation policy for aliases; refresh the local graph after structural work. Keep historical reports dated rather than treating them as current architecture. |

### Reproduced counterexamples and limits

All probes used temporary data; no real product was changed.

- **F01:** `_build_resolution` received two feature rows A/B and complete matching confidence keys. A had seagrass presence and full coverage; B was unmapped. Initially richness was `A=1, B=null`. Reversing only the seagrass confidence table and resetting its index produced `A=null, B=0`. `pandas.read_parquet` was substituted with copies of these tiny tables; the production composite calculation ran unchanged. This violates permutation invariance even with unique keys. The release audit verifies cell sets/ranges, so unchanged support does not expose this misassignment. Missing-support reduction is a separate direct-builder weakness; the full release audit can catch reduced support.
- **F02:** used the existing `tests/test_products.py::_release_fixture`, resolved bathymetry, then replaced the same artifact through `SeascapeReleasePublisher`. The previously returned object's `path` read different bytes and `checksum_path(path) != artifact.checksum`. This exercised the publication primitive, not a second full regional release; the full release publisher uses the same canonical destinations. A checksum verified earlier cannot protect a later read after the lock is released.
- **F03:** the existing planar test geometry with positive depth `10 + x` gives approximately `(slope=45°, aspect=90°)`. Negating depth, as the supported output option does, gives `(45°, 270°)` through the same `_plane_metrics`. There is no sign normalization between the bathymetry Parquet read and `_derive_metrics`. This is a semantic inconsistency between supported configurations, not a claim that the positive-down default is wrong.
- **F04:** identical H3 center/contour inputs produced `DISTANCE_TO_ISOBATH_10_M=423.43781553` with EPSG:32610 and `1389.23167825` with `+proj=utm +zone=10 +datum=WGS84 +units=ft +type=crs`. Ratio: `3.2808399`. Both were accepted; the second numeric result is feet under a meter label.
- **F05:** `_rebase_candidate_values` returned an absolute canonical artifact destination unchanged. Source inspection confirms the rendered `base_directory` is canonical, so arbitrary relative output prefixes also remain canonical-relative. This probe demonstrated path routing; it deliberately did not run a destructive external-output builder.
- **F06:** `_configuration_checksum` remained identical before/after changing only the workspace's `config/common.yaml`. The loader separately resolves named geographic areas from that file. A full regional stale-result build was not run; the omitted invalidation input is directly established.

## 5. Public API Assessment

**Intended consumer API:** `from seascape import ProductArtifact, list_products, list_resolutions, resolve_product` or the documented `seascape.products` equivalents. Preserve exact resolution selection and no fallback. Frozen nested metadata is a good contract; F02 limits the artifact bytes, not the dataclass immutability.

**Intended advanced interfaces:** `SeascapeSnapshot` for lock-scoped reads; `seascape.spatial_support.water_network` for graph/config/load/distance operations; `seascape.seafloor_physiography.bathymetry.run_pipeline` and its configuration/build functions; CLI `init`, `stages`, `build`, `download`, and `inspect`. Explicitly document that direct family calls have their own overwrite/publication behavior and do not inherit whole-workflow candidate isolation.

**Accidental or underspecified API:** internal `.build` helpers, `core.data.registry.DATASETS` as a discovery mechanism for applications, workflow dataclasses used outside orchestration, private underscore helpers imported across modules, and compatibility names under `modeling`. Existing documented direct builders should not be abruptly removed. Mark support levels and migrate examples toward facade exports as those APIs stabilize.

Typing is useful on the product dataclass and many configuration/result objects, but geometry/dataframe contracts often use `Any`; column schemas and invariants carry more information than annotations alone. Errors appropriately include `FileNotFoundError`, `KeyError`, and `ValueError`, but there is no consolidated public error contract. Document these before adding an exception hierarchy.

Minimum recommended boundary: product discovery/resolution plus safe reads, workspace initialization, a small explicit set of family builders/config loaders, and the water-network facade. Keep release mutation available to producer workflows but distinguish it from ordinary consumer imports. Python callers currently rely on process-wide `SEASCAPE_WORKSPACE`; concurrent workspaces in one process are not a demonstrated supported use case. Snapshot reads also create locks and perform recovery, so read-only mounted workspaces are not supported by this implementation.

No broken runtime import cycle was observed. An AST graph that includes type-checking and function-local imports finds a bathymetry component involving `pipeline`, `build`, `download`, and `inspect`; reverse imports are type-only or CLI-local. Do not report this as an import failure. Moving the configuration dataclasses into a leaf config module could simplify future changes, but is not urgent.

## 6. Test Coverage Assessment

| Category | Existing protection | High-value gap |
| --- | --- | --- |
| Unit/regression | Plane slope/flat aspect, circular statistics, depth bands, width/constriction/sills, classification and static eligibility | Sign equivalence; configurable quantile semantic identity |
| Data contracts | Unique support, fractions, manifests, checksums, source classification, missingness and three-state evidence | Composite permutation invariance and exact feature/confidence support before calculation |
| Geospatial correctness | Small water graphs, disconnected paths, radius operators, polygon overlays, shoreline projection, raster sampling | Meter-versus-feet rejection/conversion; rotated affine and coastal/nodata slope stencils |
| Integration | Workflow closure/reuse/failure/seed behavior; family publication and recovery; synthetic notebook bathymetry pipeline | Candidate confinement with custom outputs; named-area/config-composition invalidation; multi-family synthetic acceptance |
| Package/import | AST application-import guard, package resources, template parity, CLI family help, outside-checkout wheel smoke in CI | Run broad installed-module imports and scientific smoke against that exact wheel in CI |
| Release | Manifest-last ordering, crash rollback, reader/writer blocking, schema/support audit, resolver checksums | Read after a second publication; persistent resolution of a prior release identity |
| Regional | Three materialized-product tests exist | They skip without data; need a separately provisioned release validation job/run |

Tests mostly protect real behavior. Exact registry/stage counts and `CORE_FEATURES` membership assertions are weaker maintenance alarms; they should complement dependency/identity and calculated-result tests, not be removed simply to reduce count failures. Private-helper tests are useful for exact math but cannot establish that production joins preserve identity.

**Validation executed in this review:**

- Python 3.14: `python -m pytest -q` → **187 passed, 3 skipped**, 6.17 seconds. Skips: two materialized feature-catalog tests and one materialized network-consumer test.
- Built `toolkit_seascape-0.1.0-py3-none-any.whl` with `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/seascape-review-wheel`.
- Installed that wheel using `--no-deps --ignore-installed` into `/tmp/seascape-review-venv`, created with `--system-site-packages`. From `/tmp`, confirmed the package file was inside that venv; imported all 155 submodules with OrcaCast imports blocked; initialized a temporary workspace and planned all 26 stages. `pip check` passed. This verifies package resources/import independence, **not a fresh third-party dependency solve**.
- Parsed all source modules and resolved internal import-module targets: no missing targets. Source application-import test passed in pytest.
- Executed `notebooks/validation/01_TOOLKIT_VALIDATION.ipynb` headlessly to `/tmp/seascape-review-validation.ipynb`: all 12 code cells executed and final **`SEASCAPE TOOLKIT VALIDATION: PASS`**. Initial attempts hit sandbox kernel-socket restrictions, then an unactivated CLI PATH; the successful run enabled local sockets and put the selected Python environment on PATH. Neither was treated as a package defect.
- Ran the six bounded probes described above. These are review evidence, not newly committed tests.

CI has Python 3.11/3.14 install, dependency consistency, collection, full tests, CLI/init/dry run, wheel/outside-checkout resource checks, and whitespace checks. A separate Python 3.11 notebook job is configured. Remote job results and local Python 3.11 runtime behavior were not checked. The CI wheel environment reuses system packages, and the suite runs before the isolated wheel smoke; this is good packaging coverage but not a pristine dependency-environment matrix. No explicit formatting/linting/typing/security scan is configured in the inspected workflow; organization-side services were not inspected.

**Notebook review:** the offline notebook is a useful new-developer acceptance path with temporary synthetic data, config inspection, actual processing, outputs, provenance, plots, and PASS/FAIL gates. The Data Explorer is a separate live San Juan workflow with notebook-owned outputs and a clearly labeled exploratory land mask. Its helper provides case-study preparation, downloading, validation, and orchestration around package commands. Keep that exploratory mask outside production logic. The helper injects checkout `src` into subprocess `PYTHONPATH` (`notebooks/_san_juan_workflow.py:67–73`), so a successful explorer run does not certify the installed wheel. The live explorer was inspected, not executed.

## 7. Scientific / Geospatial Risks

| Contract | Actual implementation / assessment |
| --- | --- |
| Coordinates and axis order | Bathymetry requires a single-band EPSG:4326 raster; H3 receives latitude/longitude explicitly; shared PyProj transformations use `always_xy=True`. No evidence supports claiming all distances are incorrectly computed in degrees. F04 concerns missing validation of configurable target units. |
| Distances | Straight projected distances, geodesic segments, and shortest water-path distances remain distinct. Fetch is bounded directional water reach. Isobath distance is nearest **raster-edge crossing point**, not distance to a reconstructed continuous contour; discretization and missing context can affect it. Benchmark exact contour fixtures before changing the method. |
| Geometry | Canonical support differentiates full cells, clipped water, representatives, graph eligibility, and connectors. Water validity and graph passability have dedicated tests. The inherited territorial-water assembly includes regional boundary logic and a configured 75-km Alaska endpoint tolerance; reusing it worldwide needs a different source/region acceptance case, not merely a new bbox. |
| Raster resolution and edges | Bathymetry aggregates marine pixel centers into H3 cells with explicit valid-pixel counts. It is sample-based support, not exact raster/H3 area intersection. Native slope uses angular-spacing approximations and an unvalidated rotation assumption; review F08. No regional error magnitude was measured. |
| Vertical units and sign | GEBCO values are treated as negative elevations in meters; positive elevations are excluded from bathymetry. The sign option controls output, not source interpretation. Source vertical datum must remain provenance; the reviewed calculations do not implement datum harmonization. F03 blocks interchangeable signed outputs in dependent terrain calculations. |
| Aggregation | Bathymetry recomputes parent depth-band fractions from pixel counts; habitat uses feature-aware area sums, minima, weights, and evidence rules. These are preferable to averaging every field. F01 shows why identity must survive independently ordered tables. Mapped area zero alone does not imply surveyed absence. |
| Terrain classes | Canyon/seamount/knoll/channel labels derive from configured terrain-position, slope, relief, depth and geometric-context scores plus minimum mapping units. Treat them as operational derived classes, not independently observed geology or species suitability. Tests of rule mechanics do not validate regional geological classification accuracy. |
| Width/openness | Width uses 16 rays/8 opposing axes with censoring indicators; fetch/openness are bounded by configured search distance. These are scale-specific geometric summaries, not true global minimum channel width or hydrodynamic exposure. Preserve these labels and censoring semantics. |
| Provenance and time | Mostly static source snapshots; named source vintages, retrieval timestamps, model support, code identity, and checksums are retained. Acquisition time is not survey time; kelp persistence distinguishes bases. F06 omits an effective configuration dependency; F02 prevents stable retention through a mutable path. |
| Missing data | Most disconnected/unavailable/nodata states remain explicit. Composite fill-to-zero is often followed by coverage gating, so it is not inherently an absence bug; F01 makes that gate apply to the wrong cell. Bilinear substrate sampling renormalizes over valid neighbors (`utils/habitat_raster.py::sample_raster_bilinear`), an explicit partial-support interpolation policy worth testing at nodata boundaries. |

No target-label-dependent transformation was found in reviewed producer paths. Static eligibility does not substitute for downstream predictive feature selection. Source rights recorded in configuration/manifests were inspected as metadata; licenses and live source availability were not independently revalidated.

## 8. Performance Findings

No regional profiling was run, so **no demonstrated regional bottleneck** is claimed.

| Candidate | Classification | Evidence and next measurement |
| --- | --- | --- |
| Whole-raster bathymetry/slope processing | Likely bottleneck for larger rasters | `_aggregate_raster` and `_native_raster_slope_summary` load full arrays, allocate coordinate/mask arrays, and convert marine pixels to H3 in Python. Time/RSS at two representative raster sizes; only then add bounded windows/chunks with slope halos and equivalence tests. |
| Sixteen geometry rays per cell | Likely bottleneck | Exposure `_directional_fetch_matrix` and width `_directional_shore_distances` repeat nested cell/bearing operations. Profile both over identical support and consider a shared deterministic ray result only if inputs/scales match. |
| Repeated hashing and reads | Likely I/O cost | Resume repeatedly hashes declared directories, input artifacts and package identity; product lookup checks all family/governed manifests plus the selected artifact. Measure bytes read and warm/cold lookup/resume time before caching; preserve integrity checks. |
| Many small H3-neighborhood fits and spatial overlays | Plausible workload cost, unmeasured | Geomorphometry loops over cells/rings; habitat overlays and source processing allocate dataframes/geometries. Profile representative workloads before parallelizing or replacing readable code. |

There is no basis here for a new distributed execution framework, persistent workspace-wide graph, or speculative vectorization rewrite. Existing reusable radius operators and explicit graph structures are sensible assets.

## 9. Recommended Architecture

Retain the current directory structure. The necessary changes are stronger boundaries within it:

```text
One effective configuration + dependency fingerprint
                    |
       validated sources / explicit support and units
                    |
       candidate-confined family calculations
       (key-aligned data; normalized depth semantics)
                    |
         schemas + family manifests + release audit
                    |
      persistent release identity and stable released bytes
                    |
        small consumer API with safe read lifetime
```

| Current problem | Proposed change | Expected benefit | Migration risk |
| --- | --- | --- | --- |
| Resolved products point to replaceable files | Release-addressed storage/resolution, with canonical pointer for latest release | Repeatable reads and multi-product consistency | Medium/high: storage layout, cleanup and consumer lifetime contracts need tests; preserve canonical compatibility during migration |
| Multiple config paths and string-prefix rebasing | Resolve effective config once; classify source/output paths; preflight outputs | Consistent direct/workflow behavior and enforceable isolation | Medium: preserve legacy path interpretation and explicitly reject unsupported cases |
| Habitat confidence independent from values | Align once by declared keys at composite input | Prevent silent cross-cell contamination | Low/medium: expected failure for formerly accepted incomplete inputs |
| Shared domain helpers hidden under utilities | Document ownership now; extract a narrowly named habitat-domain helper only when touched | Clearer dependency boundaries | Low if internal; preserve supported imports if later moved |

Do not introduce a shared MarineCast core package, force all functions into generic interfaces, or reorganize families for visual symmetry. OrcaCast remains a consumer. This review confirms no runtime application import in the toolkit; it does not re-audit or certify the application's deferred integration paths.

## 10. Prioritized Action Plan

### Fix Now

| Finding | Files likely affected | Expected change | Risk | Validation method |
| --- | --- | --- | --- | --- |
| F01 | `src/seascape/biogenic_habitat/composite/build.py`; benthic contract tests | Validate exact key support, join confidence to feature order by keys, reject support loss before computation | Low/medium; may expose malformed historical inputs | Independently permute every input; compare sorted output by H3; reject missing/duplicate keys; verify null/zero distinction |
| F02 | `src/seascape/products.py`, `publication.py`, `release.py`; product/publication tests and API docs | Establish a safe read lifetime immediately; implement persistent release-addressed artifacts for durable product resolution | Medium/high; storage and compatibility behavior | Publish A then B; old A handle must retain A bytes or explicitly fail under a documented scoped API; test concurrent reads and interrupted promotion |
| F03 | Bathymetry metadata; `seafloor_physiography/geomorphometry/build.py`, `geomorphic_units/build.py`; relevant contract tests | Normalize verified source sign or reject negative-elevation dependent builds before output | Medium scientific change; preserve positive-down baseline | Same synthetic seabed in both encodings must yield equivalent aspect/TPI/classes after normalization; missing/contradictory sign metadata fails |
| F04 | `utils/spatial.py`, relevant config loaders, bathymetry distance helper, terrain/coastal tests | Require meter-based projected axes or convert units explicitly | Low/medium; reject previously accepted unsafe configs | Equivalent meter/feet CRSs give equal meter results or feet CRS is rejected; reject geographic CRS for planar meter operations; preserve default results |
| F05 | `workflow.py`, publication candidate checks, workflow tests | Preflight every resolved output before a builder can run; reject escape paths | Medium; affects customized workspaces | Absolute canonical, arbitrary relative, `..`, and symlink escape fixtures leave sentinel canonical files unchanged; allowed source paths still work |
| F06 | `workflow.py`, `core/config/document.py`, `core/config/common_areas.py`, workflow tests | Include effective named-area and transitive config identity in reuse checks | Medium; intentional broader rebuilds | Change only `common.yaml` and require rebuild; test included configs/env interpolation; unchanged config still reuses |

### Fix Next

- F07: pin the `Q90` contract to 0.90 or version the schema deliberately.
- F08: add exact native-raster slope fixtures for affine geometry, coastline transitions, nodata neighborhoods and boundaries; enforce/document supported assumptions.
- F09: unify direct/API workflow configuration resolution, building on F05/F06 rather than creating another config abstraction.
- F10: document supported Python symbols, typed return shapes, exceptions, workspace side effects, and consumer read lifetime. Use the water-network facade in new consumers.
- F11: add targeted static/security/dependency checks, installed-wheel imports, and an environment snapshot. Capture Rasterio/GDAL, PROJ and GEOS versions for regional release evidence.
- F12: reconcile README with the live exploratory notebook, and ensure the existing untracked notebook files are included when that work is committed.
- After correctness fixes, perform a provisioned candidate-versus-canonical regional comparison with `seascape.maintenance.validate_seascape_rebuild`, reviewing intended differences and provenance. Offline tests alone cannot complete this gate.

### Later

- Profile the performance candidates before optimization.
- Document a compatibility-alias deprecation horizon and refresh the disposable local graph.
- Consider a small bathymetry config-module extraction only when it reduces actual edit coupling.
- Consider moving visualization dependencies to an optional extra only if package size/startup requirements justify the migration. They are declared runtime dependencies today, not missing optional-dependency errors.

### Proposed focused Codex implementation tasks

1. **Key-align the benthic composite.** Fix F01 and add permutation/missing-key regression fixtures without changing feature formulas.
2. **Provide a safe product read API.** Define and test a context-managed resolution/read lifetime; correct immutable-byte claims while maintaining compatibility.
3. **Persist release-addressed products.** Extend publication/resolution to retain old release bytes; test two releases, recovery and concurrency. Keep garbage collection out of this task.
4. **Enforce depth-sign semantics.** Normalize or reject unsupported terrain inputs with exact planar/classification tests.
5. **Validate metric coordinate units.** Add one shared check and apply to bathymetry, terrain and coastal calculations; preserve default outputs.
6. **Enforce candidate output confinement.** Add preflight path validation and sentinel-based escape tests; do not touch source acquisition behavior.
7. **Complete scientific config fingerprints.** Include named-area/transitive config dependencies and test resume invalidation.
8. **Unify workflow config resolution.** Replace plain-YAML divergence with the existing resolver, preserving documented path semantics.
9. **Stabilize slope metadata and raster assumptions.** Enforce quantile naming, affine support, and documented coastal/nodata stencils with tiny rasters.
10. **Document the supported API and notebook roles.** Correct current workflow descriptions and define compatibility/support levels without moving directories.
11. **Strengthen CI and environment evidence.** Add wheel import/scientific smoke and targeted lint/type/security checks; declare direct dependencies and record a validated environment.
12. **Profile and validate a provisioned region.** Record time/RSS, run scientific comparison gates, and report unavailable sources separately. Do not publish or integrate OrcaCast implicitly.

No implementation tasks above were performed during this review. Live acquisition, regional rebuilding, real release promotion, map/browser QA, remote CI, and OrcaCast forecasting/integration remain unverified.
