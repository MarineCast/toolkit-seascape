# Bottom-hardness derivation contract

This product has no independent remote source. Its downloader delegates to the
substrate-classification acquisition, and its build stage applies fixed,
documented weights to the modeled dbSEABED rock, gravel, sand, and mud
composition. Boulder, cobble, and mixed are unsupported in the four-grid source
contract and contribute zero only where the raster inputs are valid.

`BOTTOM_HARDNESS_INDEX` is therefore a deterministic derivative of the
substrate product. It is not acoustic backscatter, measured consolidation, or a
calibrated hardness probability. The substrate confidence and unmapped flags
are carried forward under `BOTTOM_HARDNESS_*` names.
