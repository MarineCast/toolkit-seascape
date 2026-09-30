# Installation

Seascape Toolkit is an independently installable Python package with a `seascape` command. The current package metadata requires Python **3.14**. A source checkout is the documented installation route; do not infer a PyPI or tagged release from these commands.

Clone the repository, create an isolated environment, and install from its root:

```sh
git clone https://github.com/MarineCast/toolkit-seascape.git
cd toolkit-seascape
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install 'pip>=26.2'
python -m pip install .
python -m pip check
seascape --help
```

Installation downloads declared Python dependencies. The package does **not** install regional rasters, shoreline inventories, or an audited release. Review [tested environments](../environments/README.md) if native geospatial dependencies need troubleshooting.

## Select a workspace

Use a directory you own for inputs, candidate products, and demo output. The command below initializes editable configuration but does not acquire source datasets:

```sh
export SEASCAPE_WORKSPACE="/absolute/path/to/your/seascape-workspace"
seascape --workspace "$SEASCAPE_WORKSPACE" init
```

An offline first result needs no prior initialization; follow the [quick start](quick-start.md). For real data, inspect [configuration](../CONFIGURATION.md) and [required stage inputs](../stage-inputs.md) before running builders.

## Work on this documentation site

From the repository root, install the documentation extra in an isolated Python 3.14 environment:

```sh
python -m pip install -e '.[docs]'
mkdocs serve
```

Open <http://127.0.0.1:8000/toolkit-seascape/>. Before a pull request, run `mkdocs build --strict` and `python scripts/check_docs.py`. The generated `site/` directory is ignored by Git; the deployment workflow uploads it as a Pages artifact.
