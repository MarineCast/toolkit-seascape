# Examples and workflows

Choose a path that matches the evidence you have. The first path is fully offline; the other two require reviewed source inputs or an existing release.

| Path | Start here | Result and limit |
| --- | --- | --- |
| 1. Offline first result | [Quick start](../getting-started/quick-start.md) and [demo details](../demo.md) | Synthetic bathymetry Parquet, manifest, report, figures; validates a small transform, not a region. |
| 2. Bounded real-data candidate | [Preparation and processing](../WORKFLOWS.md#bounded-real-data-processing), [configuration](../CONFIGURATION.md), [San Juan pilot](../pilots/san-juan.md) | A candidate based on reviewed local inputs; preflight and exploratory pilot results are not blanket release approval. |
| 3. Existing audited release | [Freeze and read a release](../API.md#freeze-and-read-a-release), [metric matrix](../metric-matrix.md) | Exact release/product/resolution artifact and optional H3 export, with source nulls and QC preserved. |

The [validation notebook](https://github.com/MarineCast/toolkit-seascape/blob/main/notebooks/README.md) is an optional readable client of the offline demo. It calls production APIs and is separate from the [San Juan live explorer](../pilots/san-juan.md), which has explicit acquisition and exploratory support. Examples requiring real inventories intentionally use configured paths and source review rather than pretending a public dataset is bundled.
