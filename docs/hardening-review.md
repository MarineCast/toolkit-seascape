# Hardening review — 2026-09-17

## Baseline and defects

- Baseline: `main` at `89f0bc42d85131914a12c714a6723f9af42c81ee`.
- Pre-existing work: `notebooks/01_DATA_EXPLORER.ipynb` was modified before hardening began and
  was retained, then completed as part of the requested notebook work.
- Root cause of clean-checkout CI collection failure: unscoped `data/` and `outputs/` ignore rules
  hid `src/seascape/core/data/`, `config/data/`, and
  `src/seascape/resources/config/data/`. The local editable install could see those files while a
  GitHub checkout could not. Ignore rules are now root-scoped.
- Recovered originals: the three editable YAML files and their packaged copies, plus the
  Seascape-only 75-entry dataset registry/contracts/catalog. `validation.py` was restored from the
  originating toolkit-owned core contract. All 75 dependencies resolve inside this package.

## Architectural decisions

- Physical calculations and domain families are unchanged. The release path is now physical
  products → catalog → static feature eligibility → documentation → fail-closed audit → publication.
- Predictive rolling-origin metrics and one-standard-error scale selection were removed from the
  release dependency. Alternate physical scales remain eligible metadata; applications select them.
- `seascape.products` resolves only completed canonical releases, verifies governed/family manifests
  and exact artifact checksums, and returns frozen product identity/provenance.
- Stage state includes commit/dirty source-tree identity and file-backed source/upstream checksums.
- `seascape init` copies editable producer configuration only. Generated catalog, eligibility and
  product-index artifacts are release-derived and are not packaged as workspace templates.
- `regional_source_area` preserves the former `full_area` bounds. Unused SRKW/Transient areas were
  removed without changing `model_area` or producer formulas.
- `anthropogenic` remains physical built-environment structure, not activity or observer effort.

## Files removed or replaced

- Removed stale packaged generated metadata: resource feature catalog, model policy, and generated
  product index.
- Replaced model-performance policy with `seascape.governance.feature_eligibility`; the former
  module is a static-eligibility compatibility shim only.
- Replaced the orchestration notebook with a read-only immutable-release data explorer.

## Validation

- Python 3.14 full collection: 189 tests; the full offline suite passed 186 with 3 explicit skips
  for absent materialized regional products.
- `pip check` passed in the known-good runtime environment.
- A clean-cache wheel built through PEP 517 and installed without dependencies into a fresh
  system-site-packages virtual environment. From outside the checkout, CLI help, workspace init,
  the 26-stage dry run, all 75 registry entries, and required package/config resources passed.
  Generated catalog/model-policy templates were absent from both the wheel and initialized
  workspace. The installed wheel also passed the four synthetic immutable-product resolver tests.
- Editable and packaged configuration copies match byte-for-byte; CI YAML parses; notebook schema,
  kernel metadata, and read-only cell constraints pass; `git diff --check` passes.
- CI now runs the install, collection, full suite, CLI, init, dry run, clean wheel, outside-checkout
  smoke test, and diff check on Python 3.11 and 3.14. Python 3.11 is not installed on this host, so
  its configured CI leg was not executed locally.

## Remaining external/data blockers

- No live providers were contacted and no regional products were rebuilt or promoted.
- Full candidate-versus-canonical scientific equality still requires provisioned source data.
- OrcaCast consumer integration and predictive model evaluation remain separate application work.
