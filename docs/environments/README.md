# Validated environment baseline

`python314-macos-arm64.txt` records exact installed versions in the runtime/test dependency closure;
the companion JSON records Python/platform and Rasterio/GDAL, PyProj/PROJ and Shapely/GEOS versions.
This is an observed macOS Python 3.14 baseline, not a universal lock or a claim of Linux equivalence.
Library dependency declarations keep compatible ranges; `urllib3` is now declared directly.

Regenerate from the environment used for validation:

```sh
python scripts/environment_snapshot.py --output docs/environments/python314-macos-arm64
```

Use the text file as pip constraints (`-c`) when reproducing on a compatible platform. Availability
of binary wheels and native libraries still matters. CI separately solves Python 3.11/3.14 on Linux;
it saves its own scientific environment snapshot and audits the installed runtime/test closure.

Install `.[test,quality]` for Ruff, mypy and pip-audit. Ruff's bug checks cover source, tests and scripts;
format and strict function-annotation checks currently cover four hardened boundary modules. This
is deliberately incremental, not a claim that the entire legacy codebase is strictly typed/formatted.
Gitleaks scans Git history and current files; dependency auditing requires network access and fails
when it cannot complete. A clean scan does not establish absence of all vulnerabilities or secrets.
