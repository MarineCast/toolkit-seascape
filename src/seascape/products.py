"""Public discovery and immutable resolution of canonical Seascape products."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from seascape.core.artifacts.checksums import checksum_path
from seascape.core.config.paths import project_root
from seascape.publication import SEASCAPE_RELEASE_MANIFEST, SeascapeSnapshot

RELEASE_MANIFEST_PATH = (
    Path("data/processed/domain/environmental_layer/seascape")
    / SEASCAPE_RELEASE_MANIFEST
)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ProductArtifact:
    """Verified identity for one artifact in one completed canonical release."""

    product_id: str
    dataset_id: str
    path: Path
    checksum: str
    checksum_algorithm: str
    schema_version: str
    release_id: str
    producer: str
    producer_code_identity: Mapping[str, Any]
    resolution: int | None
    grain: tuple[str, ...]
    spatial_support: Mapping[str, Any]
    manifest_path: Path | None
    coverage: Mapping[str, Any]
    source_vintage: tuple[Mapping[str, Any], ...]
    rights: Mapping[str, Any]


def _root(workspace: str | Path | None) -> Path:
    return Path(workspace).expanduser().resolve() if workspace else project_root()


def _release_path(root: Path, relative: str | Path) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Release path must be root-relative: {relative}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Release path escapes its generation: {relative}")
    return resolved


def _verified_manifest(
    snapshot: SeascapeSnapshot,
    release_id: str | None = None,
) -> tuple[dict[str, Any], Path]:
    if release_id is not None and not re.fullmatch(r"[a-f0-9]{64}", release_id):
        raise ValueError("release_id must be a 64-character SHA-256 identity.")
    manifest_root = (
        snapshot.canonical_root / ".seascape/releases" / release_id
        if release_id
        else snapshot.canonical_root
    )
    path = _release_path(manifest_root, RELEASE_MANIFEST_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"Completed Seascape release manifest not found: {path}"
        )
    payload = snapshot.read_json(path)
    if int(payload.get("schema_version", 0)) < 3:
        raise ValueError(
            "Release predates durable generations; republish before resolving products."
        )
    identity = payload.get("release_id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValueError("Invalid Seascape release identity.")
    if release_id is not None and identity != release_id:
        raise ValueError("Requested release identity does not match its manifest.")
    if payload.get("artifact_release_passed") is not True:
        raise ValueError("Seascape canonical release is incomplete or unaudited.")
    if not isinstance(payload.get("products"), dict):
        raise ValueError("Seascape release manifest has no product index.")
    expected_root = f".seascape/releases/{identity}"
    if payload.get("storage_root") != expected_root:
        raise ValueError("Invalid release generation root.")
    root = _release_path(snapshot.canonical_root, expected_root)
    archived = snapshot.read_json(_release_path(root, RELEASE_MANIFEST_PATH))
    if archived != payload:
        raise ValueError("Canonical and archived release manifests disagree.")
    for relative, expected in payload.get("family_manifest_checksums", {}).items():
        resolved = _release_path(root, relative)
        if not resolved.is_file() or checksum_path(resolved) != expected:
            raise ValueError(f"Released family manifest checksum mismatch: {relative}")
    for name, record in payload.get("governed_artifacts", {}).items():
        if (
            not isinstance(record, dict)
            or not record.get("path")
            or not record.get("checksum")
        ):
            raise ValueError(f"Invalid governed release artifact entry: {name}")
        resolved = _release_path(root, str(record["path"]))
        if not resolved.is_file() or checksum_path(resolved) != record["checksum"]:
            raise ValueError(f"Governed release artifact checksum mismatch: {name}")
    return payload, root


def list_products(
    *,
    workspace: str | Path | None = None,
    release_id: str | None = None,
) -> tuple[str, ...]:
    """List logical products present in the completed canonical release."""

    with SeascapeSnapshot(_root(workspace)) as snapshot:
        manifest, _generation = _verified_manifest(snapshot, release_id)
        return tuple(
            sorted(
                {str(record["product_id"]) for record in manifest["products"].values()}
            )
        )


def list_resolutions(
    product: str,
    *,
    workspace: str | Path | None = None,
    release_id: str | None = None,
) -> tuple[int, ...]:
    """List exact H3 resolutions released for one logical product."""

    with SeascapeSnapshot(_root(workspace)) as snapshot:
        manifest, _generation = _verified_manifest(snapshot, release_id)
        matching = [
            record
            for record in manifest["products"].values()
            if record.get("product_id") == product
        ]
        if not matching:
            raise KeyError(f"Unknown released Seascape product: {product}")
        return tuple(
            sorted(
                {
                    int(record["resolution"])
                    for record in matching
                    if record.get("resolution") is not None
                }
            )
        )


def resolve_product(
    *,
    workspace: str | Path | None = None,
    product: str,
    resolution: int | None = None,
    release_id: str | None = None,
) -> ProductArtifact:
    """Resolve and checksum-verify one exact artifact from a completed release."""

    root = _root(workspace)
    with SeascapeSnapshot(root) as snapshot:
        release, generation = _verified_manifest(snapshot, release_id)
        matches = [
            record
            for dataset_id, record in release["products"].items()
            if dataset_id == product or record.get("product_id") == product
        ]
        if not matches:
            raise KeyError(f"Unknown released Seascape product: {product}")
        exact = [record for record in matches if record.get("resolution") == resolution]
        if not exact:
            available = sorted(
                record.get("resolution")
                for record in matches
                if record.get("resolution") is not None
            )
            raise KeyError(
                f"Product {product!r} is unavailable at resolution {resolution!r}; "
                f"available resolutions: {available}"
            )
        if len(exact) != 1:
            raise ValueError(
                f"Release product identity is ambiguous for {product!r} at R{resolution}."
            )
        record = exact[0]
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(
                f"Release product path is not canonical-root-relative: {relative}"
            )
        path = _release_path(generation, relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        if record.get("checksum_algorithm") != "sha256":
            raise ValueError("Unsupported Seascape product checksum algorithm.")
        observed = checksum_path(path)
        if observed != record.get("checksum"):
            raise ValueError(
                f"Released product checksum mismatch: {record['dataset_id']}"
            )
        manifest_path = record.get("manifest_path")
        return ProductArtifact(
            product_id=str(record["product_id"]),
            dataset_id=str(record["dataset_id"]),
            path=path,
            checksum=str(record["checksum"]),
            checksum_algorithm="sha256",
            schema_version=str(record["schema_version"]),
            release_id=str(release["release_id"]),
            producer=str(record["producer"]),
            producer_code_identity=_freeze(record.get("producer_code_identity", {})),
            resolution=(
                int(record["resolution"])
                if record.get("resolution") is not None
                else None
            ),
            grain=tuple(str(item) for item in record.get("grain", [])),
            spatial_support=_freeze(record.get("spatial_support", {})),
            manifest_path=(
                _release_path(generation, manifest_path) if manifest_path else None
            ),
            coverage=_freeze(record.get("coverage", {})),
            source_vintage=tuple(
                _freeze(item) for item in record.get("source_vintage", [])
            ),
            rights=_freeze(record.get("rights", {})),
        )


__all__ = ["ProductArtifact", "list_products", "list_resolutions", "resolve_product"]
