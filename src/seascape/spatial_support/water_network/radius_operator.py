"""Reusable canonical marine-radius aggregation operator."""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

from seascape.core.artifacts.checksums import checksum_path
from seascape.utils.spatial import h3_cell_set_hash

from .graph import WaterGraph, target_graph_mapping


@dataclass(frozen=True)
class RadiusSumOperator:
    """Target-by-canonical-support CSR membership for one marine radius."""

    cells: np.ndarray
    source_cells: np.ndarray
    target_source_indices: np.ndarray
    indptr: np.ndarray
    indices: np.ndarray
    radius_m: float
    graph_checksum: str
    support_hash: str
    source_support_hash: str
    water_mask_version: str
    spatial_support_version: str
    connector_semantics: str = (
        "source connector plus graph path plus target connector; direct self-support retained"
    )

    def __post_init__(self) -> None:
        if self.radius_m <= 0:
            raise ValueError("RadiusSumOperator radius must be positive.")
        if len(self.indptr) != len(self.cells) + 1:
            raise ValueError("RadiusSumOperator indptr length does not match support.")
        if self.target_source_indices.shape != (len(self.cells),):
            raise ValueError("RadiusSumOperator target/source mapping is invalid.")
        if len(set(self.source_cells.astype(str))) != len(self.source_cells):
            raise ValueError("RadiusSumOperator source support must be unique.")
        if len(self.target_source_indices) and (
            int(self.target_source_indices.min()) < 0
            or int(self.target_source_indices.max()) >= len(self.source_cells)
        ):
            raise ValueError("RadiusSumOperator target/source mapping is out of bounds.")
        if self.indptr[0] != 0 or self.indptr[-1] != len(self.indices):
            raise ValueError("RadiusSumOperator CSR offsets are invalid.")
        if len(self.indices) and (
            int(self.indices.min()) < 0 or int(self.indices.max()) >= len(self.source_cells)
        ):
            raise ValueError("RadiusSumOperator contains an out-of-support source index.")
        observed_hash = h3_cell_set_hash(self.cells.astype(str))
        if observed_hash != self.support_hash:
            raise ValueError("RadiusSumOperator support hash is invalid.")
        observed_source_hash = h3_cell_set_hash(self.source_cells.astype(str))
        if observed_source_hash != self.source_support_hash:
            raise ValueError("RadiusSumOperator source-support hash is invalid.")
        if not np.array_equal(
            self.source_cells[self.target_source_indices].astype(str),
            self.cells.astype(str),
        ):
            raise ValueError("RadiusSumOperator target cells are not mapped to themselves.")

    @classmethod
    def build(
        cls,
        graph: WaterGraph,
        support_cells: list[str],
        *,
        radius_m: float,
        graph_checksum: str,
        source_cells: list[str] | None = None,
    ) -> "RadiusSumOperator":
        """Build exact radius membership once using bounded target Dijkstra searches."""

        if radius_m <= 0:
            raise ValueError("RadiusSumOperator radius must be positive.")
        cells = np.asarray([str(cell) for cell in support_cells], dtype=str)
        if len(set(cells.tolist())) != len(cells):
            raise ValueError("RadiusSumOperator support cells must be unique.")
        sources = np.asarray(
            [str(cell) for cell in (source_cells if source_cells is not None else support_cells)],
            dtype=str,
        )
        if len(set(sources.tolist())) != len(sources):
            raise ValueError("RadiusSumOperator source support must be unique.")
        source_lookup = {cell: index for index, cell in enumerate(sources.tolist())}
        missing_targets = sorted(set(cells.tolist()).difference(source_lookup))
        if missing_targets:
            raise ValueError(
                "RadiusSumOperator source support omits target cells: "
                + ", ".join(missing_targets[:5])
            )
        target_source_indices = np.asarray(
            [source_lookup[cell] for cell in cells.tolist()], dtype=np.int64
        )
        positions, connectors, _reasons = target_graph_mapping(graph, cells.tolist())
        source_positions, source_connectors, _source_reasons = target_graph_mapping(
            graph, sources.tolist()
        )
        sources_by_position: dict[int, list[tuple[int, float]]] = {}
        for source_index, (position, connector) in enumerate(
            zip(source_positions, source_connectors, strict=True)
        ):
            if position >= 0 and np.isfinite(connector) and connector <= radius_m:
                sources_by_position.setdefault(int(position), []).append(
                    (source_index, float(connector))
                )
        indptr = np.zeros(len(cells) + 1, dtype=np.int64)
        indices: list[int] = []
        for target_index, (start, target_connector) in enumerate(
            zip(positions, connectors, strict=True)
        ):
            included = {int(target_source_indices[target_index])}
            if start >= 0 and np.isfinite(target_connector) and target_connector <= radius_m:
                cutoff = radius_m - float(target_connector)
                distances = {int(start): 0.0}
                queue = [(0.0, int(start))]
                while queue:
                    current, position = heapq.heappop(queue)
                    if current > distances[position] + 1e-9 or current > cutoff:
                        continue
                    for source_index, source_connector in sources_by_position.get(position, ()):
                        if current + source_connector <= cutoff + 1e-9:
                            included.add(source_index)
                    neighbors, weights = graph.neighbors_of(position)
                    for neighbor, weight in zip(neighbors, weights, strict=True):
                        neighbor_position = int(neighbor)
                        candidate = current + float(weight)
                        if (
                            candidate <= cutoff
                            and candidate < distances.get(neighbor_position, np.inf) - 1e-9
                        ):
                            distances[neighbor_position] = candidate
                            heapq.heappush(queue, (candidate, neighbor_position))
            indices.extend(sorted(included))
            indptr[target_index + 1] = len(indices)
        return cls(
            cells=cells,
            source_cells=sources,
            target_source_indices=target_source_indices,
            indptr=indptr,
            indices=np.asarray(indices, dtype=np.int64),
            radius_m=float(radius_m),
            graph_checksum=str(graph_checksum),
            support_hash=h3_cell_set_hash(cells.astype(str)),
            source_support_hash=h3_cell_set_hash(sources.astype(str)),
            water_mask_version=graph.water_mask_version,
            spatial_support_version=graph.spatial_support_version,
        )

    def apply(
        self,
        values: np.ndarray,
        *,
        eligible_sources: np.ndarray,
    ) -> np.ndarray:
        """Apply radius sums without converting missing/ineligible values to evidence."""

        numeric = np.asarray(values, dtype=np.float64)
        eligible = np.asarray(eligible_sources, dtype=bool)
        if numeric.shape != eligible.shape:
            raise ValueError("RadiusSumOperator values and eligibility must have the same shape.")
        if not np.isfinite(numeric[eligible]).all():
            raise ValueError("Eligible RadiusSumOperator source values must be finite.")
        prepared = np.zeros(len(self.source_cells), dtype=np.float64)
        if numeric.shape == (len(self.source_cells),):
            prepared[eligible] = numeric[eligible]
        elif numeric.shape == (len(self.cells),):
            prepared[self.target_source_indices[eligible]] = numeric[eligible]
        else:
            raise ValueError(
                "RadiusSumOperator values and eligibility must match target or source support order."
            )
        matrix = csr_matrix(
            (
                np.ones(len(self.indices), dtype=np.float64),
                self.indices,
                self.indptr,
            ),
            shape=(len(self.cells), len(self.source_cells)),
        )
        return np.asarray(matrix @ prepared).reshape(-1)

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema_version": 1,
            "radius_m": self.radius_m,
            "graph_checksum": self.graph_checksum,
            "support_hash": self.support_hash,
            "source_support_hash": self.source_support_hash,
            "water_mask_version": self.water_mask_version,
            "spatial_support_version": self.spatial_support_version,
            "connector_semantics": self.connector_semantics,
        }
        np.savez_compressed(
            destination,
            cells=self.cells.astype(str),
            source_cells=self.source_cells.astype(str),
            target_source_indices=self.target_source_indices,
            indptr=self.indptr,
            indices=self.indices,
            metadata=np.asarray(json.dumps(metadata, sort_keys=True)),
        )
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "RadiusSumOperator":
        source = Path(path)
        with np.load(source, allow_pickle=False) as payload:
            metadata = json.loads(str(payload["metadata"].item()))
            return cls(
                cells=payload["cells"].astype(str),
                source_cells=payload["source_cells"].astype(str),
                target_source_indices=payload["target_source_indices"].astype(np.int64),
                indptr=payload["indptr"].astype(np.int64),
                indices=payload["indices"].astype(np.int64),
                radius_m=float(metadata["radius_m"]),
                graph_checksum=str(metadata["graph_checksum"]),
                support_hash=str(metadata["support_hash"]),
                source_support_hash=str(metadata["source_support_hash"]),
                water_mask_version=str(metadata["water_mask_version"]),
                spatial_support_version=str(metadata["spatial_support_version"]),
                connector_semantics=str(metadata["connector_semantics"]),
            )

    def validate_lineage(
        self,
        *,
        graph_path: Path,
        support_cells: list[str],
        source_support_cells: list[str] | None = None,
    ) -> None:
        if checksum_path(graph_path) != self.graph_checksum:
            raise ValueError("RadiusSumOperator graph checksum is stale.")
        if h3_cell_set_hash(support_cells) != self.support_hash:
            raise ValueError("RadiusSumOperator support lineage is stale.")
        if (
            source_support_cells is not None
            and h3_cell_set_hash(source_support_cells) != self.source_support_hash
        ):
            raise ValueError("RadiusSumOperator source-support lineage is stale.")


__all__ = ["RadiusSumOperator"]
