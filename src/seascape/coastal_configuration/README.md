# Coastal configuration

## Purpose and non-goals

This family measures how shoreline and waterbody geometry shape marine space: proximity,
directional exposure, enclosure, width, constriction, sill candidates, and physical shoreline
character. It does not model weather, waves, tides, or legal shoreline status.

## Sources, dependencies, and resolutions

All products depend on canonical water/land context and the water graph. Proximity, exposure, and
morphometry are R8. Shoreline characterization is built at R8 and feature-aware aggregated to R6.
See [`shoreline_characterization/DATA_SOURCES.md`](shoreline_characterization/DATA_SOURCES.md) for
the shoreline inventory authority and cross-border normalization contract.
Deferred shoreline-density, sinuosity, island, and orientation research is tracked only in the
canonical seascape [`roadmap`](../TODO.txt); leaf directories do not maintain separate TODO lists.

## Commands

```bash
python -m seascape.coastal_configuration.shoreline_proximity.build
python -m seascape.coastal_configuration.exposure_and_enclosure.build
python -m seascape.coastal_configuration.waterbody_morphometry.build
python -m seascape.coastal_configuration.shoreline_characterization.build
```

Each leaf `inspect` module accepts `--presentation-config`, `--input` where applicable, and
`--output`.

## Artifacts and publication

Artifacts mirror leaf packages beneath the processed `coastal_configuration/` directory. Every
builder stages its complete artifact set with a manifest v3 and promotes that manifest last through
the recoverable family publisher.

## Missingness, QC, and R8 to R6 aggregation

Directional fetch and width are physical geometric mechanisms, not graph hop counts. Network
distance remains null when disconnected. Shoreline fractions divide by physically classified
length; unclassified mapped length changes coverage and is not absence. R6 lengths are summed and
fractions recomputed from denominators.

## Inspection and validation

Family-specific colors and legends remain local. Shared presentation settings control basemap,
zoom, and output routing. Mechanism tests cover directional fetch, proximity, width/constriction,
sill rules, shoreline denominator closure, finite outputs, and support identity.
