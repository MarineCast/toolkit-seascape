# API overview

The supported consumer path is the public `seascape` product facade. It reads completed schema-3 releases, discovers products and available resolutions, and resolves a checksum-verified artifact at an exact resolution. It does not build or download products.

```python
from seascape import list_products, list_resolutions, resolve_product

workspace = "/absolute/path/to/audited-workspace"
products = list_products(workspace=workspace)
resolutions = list_resolutions(products[0], workspace=workspace)
artifact = resolve_product(
    product=products[0], resolution=resolutions[0], workspace=workspace
)
print(artifact.release_id, artifact.path, artifact.checksum)
```

The example assumes the selected product has at least one gridded resolution. Ungridded products have an empty resolution tuple. In real use, select a known product ID and retain the returned release ID; pass `release_id=` to later calls to avoid following a changing canonical pointer.

| Public interface | Purpose |
| --- | --- |
| `list_products` | Discover logical products in a completed release. |
| `list_resolutions` | Discover exact materialized H3 resolutions for one product. |
| `resolve_product` / `ProductArtifact` | Validate and locate a frozen product with its manifest, checksum, grain, source vintage and support metadata. |
| `seascape.demo.run_demo` | Produce the small synthetic bathymetry acceptance result in an owned workspace. |
| `seascape export-metric-matrix` | Export release-backed H3 fields with namespaced columns and metadata, preserving nulls and QC. |

Read the [Python API reference](../API.md) for signatures, exceptions, and release behavior. The [metric matrix reference](../metric-matrix.md) covers the export contract. Family-specific workflow entry points are documented in their package guides; private implementation helpers are not a stable downstream API.
