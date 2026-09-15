# Development and validation

[Documentation index](README.md)

## Working in this repository

Read [AGENTS.md](../AGENTS.md), inspect `git status --short`, and preserve unrelated work. This is
an independent repository: run installation, tests and package builds here. Follow the
[architecture map](ARCHITECTURE.md) to put source-specific behavior with its owning family and
reusable behavior in toolkit helpers. Do not introduce application imports or sibling-path imports.

## Checks by change type

| Change | Appropriate checks |
| --- | --- |
| Documentation only | Verify file links and command names; inspect diff; run `git diff --check` |
| Calculation or loader | Focused family tests, meaningful synthetic fixtures and applicable scientific contracts |
| CLI, configuration or package layout | Standalone-package tests, command help, build dry run and wheel installation |
| Publication or orchestration | Workflow/publication tests, dependency ordering and reuse/failure cases |
| Regional processing semantics | Materialized-product checks and candidate/canonical comparison with matching inputs |

From the checkout after installing `.[test]`:

```sh
python -m pytest -q
python -m pytest -q tests/test_standalone_package.py tests/test_workflow.py
seascape build --dry-run
python -m pip wheel . --no-deps --wheel-dir dist
git diff --check
```

The [CI workflow](../.github/workflows/ci.yml) defines Python 3.11 and 3.14 jobs. A configured job
is not evidence it ran. The offline suite includes tests that skip without regional materialized
products; report skips separately from passed checks. Do not infer live provider availability,
map rendering, a full regional rebuild or application compatibility from unit tests.

## Scientific changes

Preserve row identity, units, CRS, vertical datum, resolution, source coverage and missingness.
Test boundary cases such as disconnected graphs, duplicate keys, absent source coverage and
non-finite values. Document intentional formula or schema changes and their downstream impact.
The [contracts](CONTRACTS.md) and family source guides are the detailed reference.

To compare already-built candidate and canonical products:

```sh
python -m seascape.maintenance.validate_seascape_rebuild --canonical-root /path/to/seascape-workspace --candidate-root /path/to/seascape-workspace/.seascape/candidate --output /path/to/comparison.json
```

The comparator reads matching catalog paths and checks schemas, identity, missingness, numeric
values and categorical distributions. It does not build either side. Review its report together
with provenance and configuration differences before concluding that two regional builds agree.

## Generated metadata and documentation

The workflow runs catalog, policy and documentation stages after product construction. Maintainers
can also inspect their interfaces directly:

```sh
python -m seascape.maintenance.update_seascape_feature_catalog --help
python -m seascape.modeling.feature_policy --help
python -m seascape.maintenance.update_seascape_docs --help
```

Catalog generation requires materialized products. Do not regenerate it against an incomplete
workspace and describe the result as a validated release. The product index contains a generated
block; update that block through the generator rather than editing field rows by hand.

After changing editable configuration templates, copy the corresponding files into
`src/seascape/resources/config/`. If `docs/products.md` changes, synchronize
`src/seascape/resources/docs/products.md`. The standalone-package tests check these copies.
The other repository guides in `docs/` are not currently copied by `seascape init`.

## Adding a family or product

1. Define the source rights, output grain, spatial support, units, missingness and provenance.
2. Implement acquisition/validation and builders in the owning family with offline fixtures.
3. Register applicable dataset identities and dependencies in `core/data/catalog.py`.
4. Add workflow stages and declared outputs/manifests to `workflow.py`.
5. Update CLI family selectors when exposing download or inspection commands.
6. Update the catalog generator's product definitions, release requirements, configuration and
   packaged templates as needed; keep identifiers and source module paths consistent.
7. Update the product/source guides and run checks for the affected behavior.

Record what was actually executed, what required missing data, and what remains unverified.
