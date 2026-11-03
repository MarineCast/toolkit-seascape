# Python API and flat exports

The current consumer interface reads flat per-area files from `Data/Seascape`.
There are no data release identities or retained generation paths.

```python
from seascape import list_areas, read_area

print(list_areas())
table = read_area("bathymetry", resolution=6)
```

`read_area("kelp", resolution=6, dynamic=True)` selects the dated variant if present.
The [Python API reference](../API.md) gives signatures and missing-file behavior.
The [data layout](../metric-matrix.md) explains the two-file limit, native H3
resolution, embedded definitions/source context and small update catalog.

`seascape build` processes local inputs and writes the current area files.
`seascape export` converts existing producer tables without release resolution.
Historical readers under `seascape.legacy_products` support explicit migration
only; they are outside the current data workflow.
