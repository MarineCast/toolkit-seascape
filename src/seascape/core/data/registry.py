from __future__ import annotations

from collections.abc import Iterator

from .contracts import DatasetId, DatasetSpec


class DatasetRegistry:
    def __init__(self) -> None:
        self._specs: dict[DatasetId, DatasetSpec] = {}

    def register(self, spec: DatasetSpec) -> DatasetSpec:
        if spec.dataset_id in self._specs:
            raise ValueError(f"Dataset already registered: {spec.dataset_id}")
        self._specs[spec.dataset_id] = spec
        return spec

    def get(self, dataset_id: str | DatasetId) -> DatasetSpec:
        key = DatasetId(str(dataset_id))
        try:
            return self._specs[key]
        except KeyError as exc:
            raise KeyError(f"Unknown dataset: {dataset_id}") from exc

    def __iter__(self) -> Iterator[DatasetSpec]:
        return iter(sorted(self._specs.values(), key=lambda item: item.dataset_id))


DATASETS = DatasetRegistry()
