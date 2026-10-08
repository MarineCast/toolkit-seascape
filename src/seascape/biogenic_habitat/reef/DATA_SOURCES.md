# Reef source contract

This package keeps three concepts separate:

1. **Rocky reef** — dbSEABED modeled rock presence is not a verified areal exposed-rock fraction. The current code exports `ROCKY_REEF_FRAC` and modeled rock area as unavailable. Rock presence and sediment composition have different unresolved denominators; physical hardness remains NULL. `POTENTIAL_ROCKY_REEF_SUITABILITY` can renormalize available terrain/depth inputs when hardness is missing; it is a partial model, not physical rock confirmation. A new coarse terrain proxy must receive an explicitly new name.
2. **Biogenic reef** — WDFW oyster-bed polygons and B.C. ShoreZone oyster/mussel observations support generalized mapped bivalve evidence. The reviewed release qualifies 123 of 551 raw combined source records; 427 have no selected bivalve evidence, including 25 explicit none records. The remaining invalid Washington polygon 951 is withheld. Pacific oysters may be cultivated or non-native. Full-hex mapped overlap diagnostics do not establish structural reef fraction or surveyed absence.
3. **Deep coral and sponge** — the previously configured B.C. source is access-only, and the current pipeline exports NULL, confidence 0 and `no_public_export_in_current_pipeline`. This is a pipeline-specific gate, not a claim that all public data are unavailable. The [public DFO sponge polygon lead](https://open.canada.ca/data/en/dataset/8ba7bced-b63f-462a-a8a1-7c7c8a7bcfa4) requires exact layer, rights and scope qualification before ingestion; missing ingestion does not imply habitat absence.

See the [coarse-first v1 plan](../../../../docs/methodology/coarse-v1-plan.md) for source qualification and later upgrades.
