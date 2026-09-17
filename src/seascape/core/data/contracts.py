from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa

from seascape.core.artifacts import ArtifactRef, RunManifest


class DatasetId(str):
    """Validated logical identity for a durable dataset."""

    def __new__(cls, value: str):
        parts = value.split(".")
        if len(parts) < 3 or any(not part.replace("_", "").isalnum() for part in parts):
            raise ValueError(f"Invalid dataset id: {value!r}")
        return str.__new__(cls, value)


class DatasetLayer(StrEnum):
    SOURCE = "source"
    NORMALIZED = "normalized"
    DOMAIN = "domain"
    FEATURE = "feature"
    PUBLISHED = "published"


class DatasetFormat(StrEnum):
    PARQUET = "parquet"
    GEOPARQUET = "geoparquet"
    COG = "cog"
    JSON = "json"
    NPZ = "npz"
    DIRECTORY = "directory"


class ProcessingMode(StrEnum):
    RETROSPECTIVE = "retrospective"
    AS_OF = "as_of"


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: DatasetId
    layer: DatasetLayer
    format: DatasetFormat
    path_template: str
    producer: str
    schema_version: str = "1"
    schema: pa.Schema | None = None
    primary_key: tuple[str, ...] = ()
    partition_keys: tuple[str, ...] = ()
    dependencies: tuple[DatasetId, ...] = ()
    allowed_modes: tuple[ProcessingMode, ...] = (
        ProcessingMode.RETROSPECTIVE,
        ProcessingMode.AS_OF,
    )
    sensitivity: str = "internal"

    def path(self, *, data_root: Path, artifact_root: Path, output_root: Path) -> Path:
        return Path(
            self.path_template.format(
                data_root=data_root, artifact_root=artifact_root, output_root=output_root
            )
        )


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    dataset_id: str
    schema_valid: bool = True
    key_unique: bool = True
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def require_valid(self) -> None:
        if not self.valid:
            raise ValueError("; ".join(self.errors) or f"Invalid dataset: {self.dataset_id}")


@dataclass(frozen=True)
class StageRequest:
    config: Any
    inputs: tuple[ArtifactRef, ...] = ()
    data_root: Path = Path("data")
    artifact_root: Path = Path("artifacts")
    output_root: Path = Path("outputs")
    run_id: str = "default"
    mode: ProcessingMode = ProcessingMode.RETROSPECTIVE
    knowledge_cutoff: str | None = None
    force: bool = False
    resume: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class CollectionRequest(StageRequest):
    offline: bool = False
    days: int = 15
    bbox: tuple[float, float, float, float] | None = None
    strict: bool = True


@dataclass(frozen=True)
class StageResult:
    outputs: tuple[ArtifactRef, ...]
    validations: tuple[ValidationReport, ...]
    manifest: RunManifest | None = None
    skipped: bool = False
