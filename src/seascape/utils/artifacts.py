"""Versioned, checksum-verified publication contracts for seascape artifacts."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from seascape.core.artifacts import (
    PublishedArtifact,
    TransactionalFamilyPublisher,
)
from seascape.core.artifacts.checksums import checksum_path
from seascape.publication import (
    TransactionalSeascapePublisher,
)

from .config import stable_config_hash
from .spatial import h3_cell_set_hash

SEASCAPE_MANIFEST_SCHEMA_VERSION = "3.0.0"
checksum_artifact = checksum_path
REQUIRED_MANIFEST_KEYS = {
    "dataset_family",
    "schema_version",
    "run_id",
    "built_at_utc",
    "resolved_config_hash",
    "source_completeness",
    "sources",
    "upstream_artifacts",
    "attribution",
    "licensing",
    "artifacts",
    "semantic_contracts",
}
REQUIRED_SOURCE_KEYS = {
    "name",
    "license",
    "observation_period",
    "redistribution_restrictions",
    "source_warning",
}


def normalize_source_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Make temporal, licensing, and completeness caveats explicit for one source."""

    record = dict(item)
    period = next(
        (
            record.get(key)
            for key in ("observation_period", "temporal_coverage", "period", "release")
            if record.get(key) not in (None, "")
        ),
        None,
    )
    record["observation_period"] = period or (
        "Not documented in the configured source metadata; consult the authoritative source."
    )
    record.setdefault(
        "redistribution_restrictions",
        "Follow the declared license and authoritative source terms.",
    )
    record.setdefault(
        "source_warning",
        "See product metadata and source documentation for spatial generalization and "
        "source-completeness limitations.",
    )
    return record


SEMANTIC_CONTRACT_KEYS = {
    "ecological_absence",
    "coverage",
    "distance",
    "aggregation",
    "uncertainty",
}


def default_semantic_contracts(**overrides: str) -> dict[str, str]:
    """Return required ecological, aggregation, and missingness semantics."""

    contracts = {
        "ecological_absence": (
            "Observed zero is distinct from unmapped, unsurveyed, unavailable, and missing."
        ),
        "coverage": (
            "Coverage and source availability are retained explicitly and never inferred from zero."
        ),
        "distance": (
            "Disconnected or unavailable distances remain null with a corresponding QC state."
        ),
        "aggregation": (
            "Aggregation preserves source eligibility, support, and missingness semantics."
        ),
        "uncertainty": (
            "Source and derivation uncertainty remain separate from the ecological value."
        ),
    }
    unknown = sorted(set(overrides).difference(SEMANTIC_CONTRACT_KEYS))
    if unknown:
        raise ValueError(f"Unknown seascape semantic contracts: {unknown}")
    contracts.update({key: str(value) for key, value in overrides.items()})
    return contracts


def atomic_write_parquet(frame: Any, destination: Path, *, compression: str = "zstd") -> Path:
    """Write a DataFrame-like object through a same-filesystem temporary artifact."""

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    try:
        if hasattr(frame, "to_parquet"):
            frame.to_parquet(temporary, index=False, compression=compression)
        elif hasattr(frame, "write_parquet"):
            frame.write_parquet(temporary, compression=compression)
        else:
            raise TypeError("atomic_write_parquet requires to_parquet() or write_parquet().")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def parquet_contract(path: Path) -> dict[str, Any]:
    """Return row, schema, and optional H3-set metadata for one Parquet file."""

    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    contract: dict[str, Any] = {
        "row_count": int(parquet.metadata.num_rows),
        "fields": [
            {
                "name": field.name,
                "type": str(field.type),
                "nullable": bool(field.nullable),
            }
            for field in schema
        ],
    }
    if "H3_INDEX" in schema.names:
        values = pq.read_table(path, columns=["H3_INDEX"]).column("H3_INDEX").to_pylist()
        contract["h3_cell_set_hash"] = h3_cell_set_hash(values)
        contract["unique_h3_count"] = len({str(value) for value in values if value is not None})
        normalized = [str(value) for value in values if value is not None]
        try:
            import h3

            resolutions = sorted({int(h3.get_resolution(value)) for value in normalized})
            centers = [h3.cell_to_latlng(value) for value in normalized]
        except (TypeError, ValueError):
            resolutions = []
            centers = []
        if resolutions:
            contract["h3_resolutions"] = resolutions
        if centers:
            latitudes, longitudes = zip(*centers, strict=True)
            contract["spatial_bounds_wgs84"] = {
                "min_lon": float(min(longitudes)),
                "min_lat": float(min(latitudes)),
                "max_lon": float(max(longitudes)),
                "max_lat": float(max(latitudes)),
            }
    metadata = parquet.metadata.metadata or {}
    if "spatial_bounds_wgs84" not in contract and b"geo" in metadata:
        try:
            geo = json.loads(metadata[b"geo"].decode("utf-8"))
            primary = geo.get("primary_column")
            bbox = geo.get("columns", {}).get(primary, {}).get("bbox")
            if isinstance(bbox, list) and len(bbox) >= 4:
                contract["spatial_bounds_wgs84"] = {
                    "min_lon": float(bbox[0]),
                    "min_lat": float(bbox[1]),
                    "max_lon": float(bbox[-2]),
                    "max_lat": float(bbox[-1]),
                }
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            pass
    return contract


def portable_artifact_path(path: Path, *, root: Path) -> str:
    """Return a root-relative path when possible, otherwise an explicit absolute path."""

    resolved = path.resolve()
    candidate_root = os.environ.get("SEASCAPE_CANDIDATE_ROOT")
    roots = [Path(candidate_root).resolve()] if candidate_root else []
    roots.append(root.resolve())
    for portable_root in roots:
        try:
            return str(resolved.relative_to(portable_root))
        except ValueError:
            continue
    return str(resolved)


def artifact_record(path: Path, *, root: Path) -> dict[str, Any]:
    """Describe a published artifact using a portable relative path."""

    resolved = path.resolve()
    record: dict[str, Any] = {
        "path": portable_artifact_path(resolved, root=root),
        "checksum": checksum_path(resolved),
        "size_bytes": resolved.stat().st_size,
    }
    if resolved.suffix.lower() == ".parquet":
        record.update(parquet_contract(resolved))
    return record


def stage_parquet_artifact(
    publisher: TransactionalFamilyPublisher,
    frame: Any,
    destination: Path,
    *,
    compression: str = "zstd",
) -> PublishedArtifact:
    """Stage Parquet and capture its checksum and structural contract once.

    The checksum is calculated from the staged bytes that will be promoted. Parquet
    metadata and the H3 identity column are inspected from that same staged file;
    callers therefore do not need to reopen the promoted artifact to build a
    manifest.
    """

    publisher.stage_parquet(frame, destination, compression=compression)
    return capture_staged_parquet_artifact(publisher, destination)


def capture_staged_parquet_artifact(
    publisher: TransactionalFamilyPublisher,
    destination: Path,
) -> PublishedArtifact:
    """Capture one already-written staged Parquet artifact without rescanning later."""

    staged = publisher.candidate_path(destination)
    contract = parquet_contract(staged)
    return publisher.staged_artifact(
        destination,
        schema=tuple(contract.get("fields", ())),
        row_count=int(contract["row_count"]),
        h3_cell_count=contract.get("unique_h3_count"),
        h3_cell_set_hash=contract.get("h3_cell_set_hash"),
        h3_resolutions=tuple(contract.get("h3_resolutions", ())),
        spatial_bounds_wgs84=contract.get("spatial_bounds_wgs84"),
    )


def build_manifest(
    *,
    dataset_family: str,
    run_id: str,
    resolved_config: Any,
    artifacts: Sequence[Path | PublishedArtifact],
    project_root: Path,
    sources: Sequence[Mapping[str, Any]],
    upstream_artifacts: Sequence[Mapping[str, Any]],
    attribution: Sequence[Mapping[str, Any]],
    source_completeness: str,
    semantic_contracts: Mapping[str, str] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the common seascape manifest payload."""

    def portable_metadata_paths(value: Any) -> Any:
        if isinstance(value, Mapping):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                if key == "path" and isinstance(item, (str, Path)) and "://" not in str(item):
                    normalized[str(key)] = portable_artifact_path(Path(item), root=manifest_root)
                else:
                    normalized[str(key)] = portable_metadata_paths(item)
            return normalized
        if isinstance(value, (list, tuple)):
            return [portable_metadata_paths(item) for item in value]
        return value

    if source_completeness not in {"complete", "partial", "unavailable"}:
        raise ValueError("source_completeness must be complete, partial, or unavailable.")
    candidate_root = os.environ.get("SEASCAPE_CANDIDATE_ROOT")
    manifest_root = Path(candidate_root).resolve() if candidate_root else project_root
    source_records = [normalize_source_record(item) for item in sources]
    for record in source_records:
        if record.get("path"):
            record["path"] = portable_artifact_path(Path(str(record["path"])), root=manifest_root)
    artifact_records = [
        (
            item.to_dict(path=portable_artifact_path(item.path, root=manifest_root))
            if isinstance(item, PublishedArtifact)
            else artifact_record(item, root=manifest_root)
        )
        for item in artifacts
    ]
    licensing = [
        {"source": item.get("name"), "license": item.get("license")}
        for item in source_records
        if item.get("license")
    ]
    bounds = [
        item["spatial_bounds_wgs84"] for item in artifact_records if "spatial_bounds_wgs84" in item
    ]
    h3_resolutions = sorted(
        {
            int(resolution)
            for item in artifact_records
            for resolution in item.get("h3_resolutions", [])
        }
    )
    payload: dict[str, Any] = {
        "dataset_family": dataset_family,
        "schema_version": SEASCAPE_MANIFEST_SCHEMA_VERSION,
        "run_id": str(run_id),
        "built_at_utc": datetime.now(UTC).isoformat(),
        "resolved_config_hash": stable_config_hash(resolved_config),
        "source_completeness": source_completeness,
        "sources": source_records,
        "upstream_artifacts": [
            {
                **dict(item),
                "path": portable_artifact_path(Path(str(item["path"])), root=manifest_root),
            }
            for item in upstream_artifacts
        ],
        "attribution": [dict(item) for item in attribution],
        "licensing": licensing,
        "h3_resolutions": h3_resolutions,
        "artifacts": artifact_records,
        "semantic_contracts": dict(semantic_contracts or default_semantic_contracts()),
    }
    if bounds:
        payload["spatial_bounds_wgs84"] = {
            "min_lon": min(item["min_lon"] for item in bounds),
            "min_lat": min(item["min_lat"] for item in bounds),
            "max_lon": max(item["max_lon"] for item in bounds),
            "max_lat": max(item["max_lat"] for item in bounds),
        }
    if metadata:
        if "product_contract" in metadata:
            raise ValueError(
                "Manifest v3 does not accept metadata.product_contract; use semantic_contracts."
            )
        payload["metadata"] = portable_metadata_paths(metadata)
    validate_manifest(payload, project_root=manifest_root, verify_artifacts=False)
    return payload


def validate_manifest(
    payload: Mapping[str, Any],
    *,
    project_root: Path,
    verify_artifacts: bool,
) -> None:
    """Validate required manifest fields and, optionally, artifact checksums."""

    missing = sorted(REQUIRED_MANIFEST_KEYS.difference(payload))
    if missing:
        raise ValueError(f"Seascape manifest is missing required keys: {missing}")
    if payload["schema_version"] != SEASCAPE_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported seascape manifest schema version.")
    contracts = payload["semantic_contracts"]
    if not isinstance(contracts, Mapping) or set(contracts) != SEMANTIC_CONTRACT_KEYS:
        raise ValueError(
            "Seascape semantic_contracts must contain exactly: "
            + ", ".join(sorted(SEMANTIC_CONTRACT_KEYS))
        )
    if any(not isinstance(value, str) or not value.strip() for value in contracts.values()):
        raise ValueError("Every seascape semantic contract must be non-empty text.")
    if not isinstance(payload["sources"], list):
        raise ValueError("Seascape manifest sources must be a list.")
    for source in payload["sources"]:
        if not isinstance(source, Mapping) or not source.get("name"):
            raise ValueError("Each seascape source must have a name.")
        if not source.get("license"):
            raise ValueError(f"Seascape source lacks licensing: {source.get('name')}")
        missing_source = sorted(
            key for key in REQUIRED_SOURCE_KEYS if source.get(key) in (None, "")
        )
        if missing_source:
            raise ValueError(
                f"Seascape source {source.get('name')} lacks publication fields: "
                f"{missing_source}"
            )
    for upstream in payload["upstream_artifacts"]:
        if (
            not isinstance(upstream, Mapping)
            or not upstream.get("path")
            or not upstream.get("checksum")
        ):
            raise ValueError("Each upstream artifact must include path and checksum.")
    if not isinstance(payload["attribution"], list) or not payload["attribution"]:
        raise ValueError("Seascape manifest must retain required attribution.")
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Seascape manifest must identify at least one artifact.")
    if not verify_artifacts:
        return
    for artifact in artifacts:
        path = Path(str(artifact["path"]))
        resolved = path if path.is_absolute() else project_root / path
        if not resolved.exists():
            raise FileNotFoundError(f"Manifest artifact does not exist: {resolved}")
        observed = checksum_path(resolved)
        if observed != artifact.get("checksum"):
            raise ValueError(
                f"Manifest checksum mismatch for {resolved}: "
                f"expected {artifact.get('checksum')}, observed {observed}."
            )


class StagedParquetFamily:
    """A staged family awaiting its terminal manifest and one promotion."""

    def __init__(
        self,
        publisher: TransactionalFamilyPublisher,
        artifacts: Sequence[PublishedArtifact],
    ) -> None:
        self.publisher = publisher
        self.artifacts = tuple(artifacts)
        self.run_id = publisher.run_id
        self._closed = False

    def publish_manifest(self, destination: Path, payload: Mapping[str, Any]) -> tuple[Path, ...]:
        """Stage the terminal manifest, promote the family, and clean staging state."""

        if self._closed:
            raise RuntimeError("Staged Parquet family is already closed.")
        try:
            self.publisher.stage_manifest(destination, payload)
            return self.publisher.publish()
        finally:
            self.publisher.__exit__(None, None, None)
            self._closed = True

    def abort(self) -> None:
        """Discard the staged family without changing any destination."""

        if not self._closed:
            self.publisher.__exit__(None, None, None)
            self._closed = True


def stage_parquet_family(
    output_dir: Path,
    outputs: Sequence[tuple[Any, Path]],
    *,
    run_id: str | None = None,
) -> StagedParquetFamily:
    """Stage a complete Parquet family and return its captured artifact records."""

    publisher = TransactionalSeascapePublisher(output_dir, run_id=run_id)
    publisher.__enter__()
    try:
        artifacts = [
            stage_parquet_artifact(publisher, frame, destination) for frame, destination in outputs
        ]
    except Exception:
        publisher.__exit__(None, None, None)
        raise
    return StagedParquetFamily(publisher, artifacts)


def load_manifest(path: Path) -> dict[str, Any]:
    """Read a JSON manifest with a contextual structure error."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest root must be a mapping: {path}")
    return payload
