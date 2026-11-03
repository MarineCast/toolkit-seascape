# Pinned cached-source regional processing

The regional interface operates on explicit local paths, independent of any application checkout.
Inputs are byte-pinned and carry source rights, observation support (including unknown dates),
spatial support and coverage limitations. It never acquires sources or promotes a release by
itself. Native R6 is the default reporting grain; supported R8 methods are direct companions.
Neither this interface nor successful software tests certify the final coastal selection policy.

The reviewed methods retain these definitions:

| Operator | Grain and support | Units / missingness |
| --- | --- | --- |
| Terrain form | Direct R8 native slope, four-hop TPI and qualified graph context | Heuristic classes; every input must be eligible; missing source QC stays null |
| Substrate | Direct R6 representative-point bilinear sampling of four 0.1-degree modeled percent rasters | Fractions; masked neighbors renormalize weights; no valid neighbor is null; rock is separate from sediment composition |
| Seagrass | Full R6 polygons, segmentized at 0.001 degrees before EPSG:6933 projection; all intersecting source blocks | Positive center counts and positive pixel-footprint m² are distinct; zero does not establish surveyed absence |
| Coastal first exit | Densified WGS84 geodesic polyline, at most 100 m segments, connected mapped water from origin | Metres; source exits and configured search limits remain censored |
| Freshwater / estuary | Native R8 H3 centres to qualified provider-terminal / estuary source points in EPSG:32610 | Euclidean metres; freshwater kernel is sum(exp(-distance/5000)); no flow or water-network inference |
| Bivalve | Independent full native R6/R8 polygons with per-class geometric unions and native H3 centres in EPSG:32610 | m² and polygon distance; retain multiplicity and WA/BC overlap diagnostics; generalized evidence is not a reef census |
| Projected geometry | Valid native source, precision-qualified projected topology, exact Cartesian subdivision | No source repair; projected repair retains all original vertices and strict area/boundary guards |
| Static consolidation | Exactly aligned sorted native H3 keys; namespaced direct source columns | Preserve original Arrow types, nulls, metadata and order; never manufacture annual static copies |

Real-source coverage, accuracy, rights and observation dates remain source qualifications rather
than values inferred from a successful run. Fixture tests exercise software, not source completeness.
Input and output directories must be distinct; an existing output is refused. Source bytes are
checked before and after execution. Schema-3 manifests and checksums bind the output bytes; an
operator candidate is not a complete toolkit release or an automatically published product.

## Installed entry point and explicit specification

```bash
seascape regional --spec /explicit/config/regional.json --preflight
seascape regional --spec /explicit/config/regional.json
```

`seascape.regional.runner.run_spec(path, preflight=False)` is the corresponding Python entry
point. The global workspace and study-planning configuration do not select regional inputs.
Preflight verifies byte pins and reports limits; it does not execute or certify operator readiness.
The commands create a new candidate directory only. Publication requires separate independent
review and the established release gates; there is no automatic Data write or current-pointer update.

A spec uses schema 1, an `operator`, native `resolution` (default 6), `output`, `settings`,
`limits`, and explicit `inputs`. Its `domain` requires `id`, `revision`, `support` and
`coverage_status`. Each input requires `path`, `sha256`, and a `qualification` mapping containing
`rights`, `spatial_support`, `coverage_status` and `observation_period`; unknown observation
periods use JSON null. These are retained source declarations, not a license approval or survey
certification. Relative paths resolve against the spec file, never against a sibling checkout.

For files, `sha256` is the raw content hash. For a directory such as a retained file geodatabase,
use `seascape.regional.contract.digest(Path(...))`: hash the UTF-8 canonical JSON list of sorted
component records `{path, raw_sha256}`, with sorted keys and compact separators. Every component
is verified before and after execution; symlink components and empty directories are refused.
Flat native YAML `config` and `common` inputs are mandatory for graph/terrain kernels. Unpinned
configuration includes are refused and temporary common-config selection is restored afterward.

| Operator | Required inputs beyond `reporting` (sorted unique H3 text) |
| --- | --- |
| `bathymetry` | `raster`, `compute` sorted native H3 text, `neighborhoods` with source/target H3, minimum hop count and network distance; complete compute depths are retained while graph batches stream |
| `watergraph` | `water` with mapped `water_area`, `extent`, `compute`, native `depth`, independent `context` source/halo certificates, flat `config`, `common` |
| `distance` | `raster`, `extent`, qualified native `shoreline` lines or `land_water` containing one-degree tiled `land_area` and `water_area`; crop and projection qualifications accompany nearest values |
| `native-terrain` | Native R8 `raster`, full compute `depth`, qualified `support`, passable `edges`, `connectors`, flat `config`, `common`; retains five-hop nested context and within-compute diagnostics |
| `shoreline` | Normalized physical `inventory` and native `support`; direct full-cell unique-line unions at R6/R8 |
| `anthropogenic` | Normalized physical `inventory`, `water`; network and unqualified absence metrics remain null |
| `kelp` | `water` and explicitly pinned annual inputs listed in `settings.annual_layers` (`year`, `input`, optional `layer`, `year_column`); unsupported 1993 is refused |
| `coastal` | Native R8 `water`, `extent`, frozen `origins` or full `support` (optional `prior_origins`); fixed 16 bearings, 50 km bound, 100 m geodesic segments |
| `freshwater`, `estuary` | Native R8 finite qualified `inventory`; native H3-centre targets are not shifted into water |
| `bivalve` | Qualified polygon `inventory` with WA_/BC_ `EVIDENCE_CLASS`; direct R6/R8 full polygons and native H3 centres in EPSG:32610 |
| `seagrass` | Native R6 `tile_...` rasters, or `settings.raster_tiles` entries with `input` and retained ZIP `member`; blocks stream without archive extraction |
| `substrate` | Native R6 `support` plus `rock`, `gravel`, `sand`, `mud` native modeled rasters; representative points must lie inside focal H3 with positive mapped-water overlap |
| `terrain-form` | Native R8 `terrain` containing exact-key aligned depth, slope, TPI, marine presence, four-hop completeness and nullable TPI QC |
| `consolidate` | `base` and explicitly pinned append tables; `settings.append` entries declare `input`, `prefix` ending in `__`, and `immutable_release_id` |

Vector sources require registered CRS and valid native geometry. Kelp alone preserves the reviewed
native touching-ring precision normalization (at most 0.01 m² and 1e-10 relative area change),
with evidence retained; this does not authorize broader source repair. Projected repair also
retains original vertices and bounds new-vertex distance to the original boundary at one micrometre.

Proximity input coordinate names default to `X_M`, `Y_M`, `SOURCE_ID`; explicit
`x_column`, `y_column`, `id_column` settings bind existing provider fields. EPSG:32610 remains
fixed. Source selection and finite-query limitations belong in the input qualification. No source
record is automatically upgraded into a physical mouth, surveyed estuary, reef or absence.

The maximum per-run stops are 1.5 GiB process peak RSS, 512 MiB new output, one hour, 4,096 rows
per streaming batch, and one worker. Existing pinned source bytes may exceed staging size;
`input_bytes` is a read-only source budget, not new acquisition. Main-thread execution is required
for a temporary cooperative POSIX alarm. It checks elapsed time, RSS (macOS bytes/Linux KiB
converted to bytes) and candidate size, including long native calls. It is not an OS allocation
reservation. Coordinate real memory demand and total staging before a regional run. A failed run
retains `FAILED.json` and its evidence; it is unusable and must not be published or overwritten.

Acceptance uses `python -m pytest -q tests/regional` plus the full existing suite and quality/docs
gates. Synthetic acceptance covers native orchestration, every producer, native NULL QC,
source/spec tampering, native-grid rejection, archive streaming, exact static joins and time-stop
restoration. Real-data parity is a separate bounded check against immutable retained releases.

Graph certificates must include `qualification.certificate_input_sha256`, exactly matching the pinned `compute`, `water`, `extent`, `config`, and `common` inputs. Native terrain support certificates bind `compute`, `edges`, `connectors`, `raster`, `config`, and `common`; native terrain also requires that explicit compute registry. These bindings prevent reusing complete-context flags with a truncated or changed source graph. They preserve the source qualification and do not independently certify its scientific correctness.
