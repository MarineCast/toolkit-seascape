"""Bounded artifact consumption; byte verification is not source qualification.

No source acquisition, producer execution, publication or implicit path discovery.
The mask and compute registry interfaces are explicit pending shared format agreement.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h3
import pandas as pd
import pyproj
import shapely
from pyproj import Geod
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, box, shape

from seascape._study_contract import canonical_bytes, unique_object
from seascape.core.geo.h3 import cell_to_polygon, polygon_to_cells_overlap
from seascape.study import StudyConfig, StudyConfigError


@dataclass(frozen=True)
class MembershipArtifact:
    """Explicit pinned file; path is relative to the selected config directory."""

    relative_path: str
    sha256: str
    count: int
    resolution: int
    role: str


@dataclass(frozen=True)
class VerifiedStudySupport:
    """Immutable memberships; scientific source/halo qualification remains separate."""

    config_sha256: str
    producer: str
    mask_sha256: str
    mask_revision: str
    reporting_r6: tuple[str, ...]
    native_reporting_r8: tuple[str, ...]
    compute_r6: tuple[str, ...]
    compute_r8: tuple[str, ...]
    identity_json: str

    def provenance(self) -> dict[str, Any]:
        return json.loads(self.identity_json) | {
            "consumer_identity_sha256": hashlib.sha256(
                self.identity_json.encode("utf-8")
            ).hexdigest(),
            "verification": "bytes_memberships_geometry_and_compute_hierarchy",
            "source_qualification": "not_established_by_consumer",
            "halo_distance_completeness": "not_established_by_consumer",
            "production_ready": False,
        }

    def cells(self, resolution: int, *, role: str) -> tuple[str, ...]:
        if type(resolution) is not int or resolution not in (6, 8):
            raise StudyConfigError("Seascape support consumes R6 and R8 only.")
        if role == "reporting":
            return self.reporting_r6 if resolution == 6 else self.native_reporting_r8
        if role == "compute":
            return self.compute_r6 if resolution == 6 else self.compute_r8
        raise StudyConfigError("Support role must be reporting or compute.")

    def consume_table(
        self, frame: pd.DataFrame, resolution: int, *, role: str
    ) -> pd.DataFrame:
        """Require complete keys, retain null/zero values, and select the stated role.

        Reporting accepts compute rows then trims to reporting cells. Compute never
        substitutes reporting-only support for required context. Neither operation
        recomputes values or claims native source coverage.
        """
        required = self.cells(resolution, role=role)
        if "H3_INDEX" not in frame or frame["H3_INDEX"].isna().any():
            raise StudyConfigError("Support table requires non-null H3_INDEX.")
        ids = frame["H3_INDEX"].tolist()
        if any(type(cell) is not str for cell in ids) or len(set(ids)) != len(ids):
            raise StudyConfigError("Support table keys must be unique H3 strings.")
        if set(ids).difference(self.cells(resolution, role="compute")):
            raise StudyConfigError(
                "Support table contains cells outside compute support."
            )
        if set(required).difference(ids):
            raise StudyConfigError("Support table is missing required membership rows.")
        if "H3_RESOLUTION" in frame and not frame["H3_RESOLUTION"].eq(resolution).all():
            raise StudyConfigError("Support table resolution column disagrees.")
        return frame.set_index("H3_INDEX").loc[list(required)].reset_index().copy()


def _read_pinned(
    base: Path, root: Path, relative: str, digest: str, byte_limit: int
) -> bytes:
    if type(relative) is not str or not relative or Path(relative).is_absolute():
        raise StudyConfigError("Artifact path must be explicit and relative.")
    path = (base / relative).resolve()
    if not path.is_relative_to(root):
        raise StudyConfigError(
            "Artifact path escapes the configured resolved data_root."
        )
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise StudyConfigError("Artifact requires a lowercase raw SHA256.")
    try:
        with path.open("rb") as stream:
            raw = stream.read(byte_limit + 1)
    except OSError as exc:
        raise StudyConfigError(f"Cannot read pinned artifact {path}: {exc}") from exc
    if len(raw) > byte_limit:
        raise StudyConfigError("Artifact exceeds the explicit byte budget.")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise StudyConfigError("Artifact raw SHA256 mismatch.")
    return raw


def _membership(
    base: Path,
    root: Path,
    artifact: MembershipArtifact,
    max_cells: int,
    byte_limit: int,
) -> tuple[str, ...]:
    if type(artifact.count) is not int or not 0 <= artifact.count <= max_cells:
        raise StudyConfigError("Membership count exceeds bounds.")
    if type(artifact.resolution) is not int or artifact.resolution not in (6, 8):
        raise StudyConfigError("Seascape membership requires resolution 6 or 8.")
    raw = _read_pinned(base, root, artifact.relative_path, artifact.sha256, byte_limit)
    try:
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise StudyConfigError("Membership IDs must be ASCII.") from exc
    cells = tuple(text.splitlines())
    canonical = ("\n".join(cells) + "\n").encode() if cells else b""
    if cells != tuple(sorted(set(cells))) or raw != canonical:
        raise StudyConfigError(
            "Membership must be sorted unique IDs with terminal newline."
        )
    if len(cells) != artifact.count:
        raise StudyConfigError("Membership count mismatch.")
    if any(
        not re.fullmatch(r"[0-9a-f]{15}", cell)
        or not h3.is_valid_cell(cell)
        or h3.get_resolution(cell) != artifact.resolution
        for cell in cells
    ):
        raise StudyConfigError("Invalid H3 ID or membership resolution.")
    return cells


def _overlap(
    geometry: Polygon | MultiPolygon, resolution: int, max_cells: int
) -> tuple[str, ...]:
    if not hasattr(h3, "polygon_to_cells_experimental"):
        raise StudyConfigError(
            "Positive-area support requires H3 overlap API; no center fallback."
        )
    # Soft heuristic preflight only: H3 may allocate more than max_cells before
    # the post-enumeration check. This is not a strict memory allocation bound.
    envelope = box(*geometry.bounds)
    area, _ = Geod(ellps="WGS84").geometry_area_perimeter(envelope)
    estimate = abs(area) / h3.average_hexagon_area(resolution, unit="m^2") * 16
    if estimate > max_cells:
        raise StudyConfigError("Overlap envelope exceeds bounded enumeration budget.")
    candidates = polygon_to_cells_overlap(geometry, resolution)
    if len(candidates) > max_cells:
        raise StudyConfigError(
            "Soft overlap candidate limit exceeded after enumeration."
        )
    geod = Geod(ellps="WGS84")
    selected = []
    for cell in candidates:
        overlap = cell_to_polygon(cell).intersection(geometry)
        if overlap.area <= 0:
            continue
        parts = overlap.geoms if isinstance(overlap, MultiPolygon) else [overlap]
        if any(abs(geod.geometry_area_perimeter(part)[0]) > 0 for part in parts):
            selected.append(cell)
    return tuple(sorted(selected))


def load_study_support(
    study: StudyConfig,
    *,
    producer: str,
    mask_relative_path: str,
    compute_memberships: tuple[MembershipArtifact, MembershipArtifact],
    max_cells: int = 100_000,
    max_artifact_bytes: int = 16 * 1024 * 1024,
) -> VerifiedStudySupport:
    """Read explicit WGS84 GeoJSON mask and canonical memberships, without writes.

    Provisional mask encoding is one Polygon/MultiPolygon geometry, not a bbox or
    implicit source selection. The shared registry supplies R6 water_reporting;
    separate explicitly pinned compute artifacts supply R6/R8 context. Their source
    qualification and geodesic distance completeness are not established here.
    """
    if type(max_cells) is not int or max_cells <= 0:
        raise StudyConfigError("max_cells must be a positive integer.")
    if type(max_artifact_bytes) is not int or max_artifact_bytes <= 0:
        raise StudyConfigError("max_artifact_bytes must be a positive integer.")
    if type(producer) is not str or not producer.strip():
        raise StudyConfigError(
            "Compute support requires an explicit producer identity."
        )
    base = study.source.parent
    root = study.data_root.resolve()
    config = study.payload
    domain = config["domain"]
    registry = config["grid_registry"]
    if (
        domain["status"] != "approved"
        or domain["geometry_status"] != "source_relative_validated"
        or domain["selection_policy"]["status"] != "approved"
        or domain["selection_policy"]["mask_status"] != "source_relative_validated"
        or registry["status"] != "validated"
    ):
        raise StudyConfigError(
            "Consumer requires validated support metadata before artifact reads."
        )
    reporting = [
        m
        for m in registry["memberships"]
        if m["resolution"] == 6 and m["role"] == "water_reporting"
    ]
    if len(reporting) != 1:
        raise StudyConfigError(
            "Registry must identify exactly one R6 water_reporting artifact."
        )
    spec = MembershipArtifact(**reporting[0])
    r6 = _membership(base, root, spec, max_cells, max_artifact_bytes)
    raw = _read_pinned(
        base, root, mask_relative_path, registry["mask_sha256"], max_artifact_bytes
    )
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
        if payload.get("type") not in ("Polygon", "MultiPolygon") or set(payload) != {
            "type",
            "coordinates",
        }:
            raise ValueError(
                "Expected one WGS84 Polygon/MultiPolygon GeoJSON geometry."
            )
        geometry = shape(payload)
        if geometry.has_z or geometry.is_empty or not geometry.is_valid:
            raise ValueError(
                "Mask must be nonempty, valid, two-dimensional; no implicit repair."
            )
        if (
            not box(-180, -90, 180, 90).covers(geometry)
            or geometry.bounds[2] - geometry.bounds[0] >= 180
        ):
            raise ValueError(
                "Mask coordinates must be WGS84 without antimeridian crossing."
            )
        if not box(*domain["bbox_wgs84"]).covers(geometry):
            raise ValueError("Mask lies outside its declared acquisition envelope.")
    except (ValueError, TypeError, AttributeError, KeyError, GEOSException) as exc:
        raise StudyConfigError(f"Invalid mask geometry: {exc}") from exc
    expected_r6 = _overlap(geometry, 6, max_cells)
    if r6 != expected_r6:
        raise StudyConfigError(
            "R6 reporting registry differs from positive-area mask overlap."
        )
    native_r8 = _overlap(geometry, 8, max_cells)
    if not native_r8:
        raise StudyConfigError("Nonempty reporting mask has no native R8 overlap.")
    if len(compute_memberships) != 2 or {
        (m.resolution, m.role) for m in compute_memberships
    } != {(6, "water_source"), (8, "water_source")}:
        raise StudyConfigError(
            "Compute registry must supply distinct R6/R8 water_source artifacts."
        )
    compute = {
        m.resolution: _membership(base, root, m, max_cells, max_artifact_bytes)
        for m in compute_memberships
    }
    parents = tuple(sorted({h3.cell_to_parent(cell, 6) for cell in compute[8]}))
    if compute[6] != parents:
        raise StudyConfigError("R6 compute support must be the exact R8 parent union.")
    if set(r6).difference(compute[6]) or set(native_r8).difference(compute[8]):
        raise StudyConfigError(
            "Compute support omits reporting or native reporting cells."
        )
    identity = {
        "study_config_sha256": study.config_sha256,
        "producer": producer,
        "geometry_sha256_role": "acquisition_envelope_identity",
        "acquisition_envelope_sha256": domain["geometry_sha256"],
        "reporting_mask_sha256": registry["mask_sha256"],
        "mask_relative_path": mask_relative_path,
        "mask_revision": registry["mask_revision"],
        "h3_version": h3.__version__,
        "cell_polygon_engine": "h3.cell_to_boundary WGS84 longitude/latitude",
        "intersection_engine": f"shapely {shapely.__version__}",
        "positive_area_engine": f"pyproj {pyproj.__version__} Geod WGS84 ellipsoid",
        "registry_artifact_interface_version": 1,
        "overlap_enumeration_limit": "heuristic_preflight_soft_postcheck_not_allocation_bound",
        "registry_artifact_interface_sha256": "38e3f84d8e7b0f59c188abb1da1ca354bb6271c328ac2a7e29504b0ca2f84d01",
        "membership_hash_policy": "sorted_unique_lowercase_ids_terminal_newline_raw_sha256",
        "reporting_membership": reporting[0],
        "native_reporting_r8": {
            "count": len(native_r8),
            "sha256": hashlib.sha256(
                ("\n".join(native_r8) + "\n").encode()
            ).hexdigest(),
        },
        "compute_memberships": [
            vars(m) for m in sorted(compute_memberships, key=lambda m: m.resolution)
        ],
        "producer_buffers": config["producer_buffers"]["seascape"],
        "selection_policy": domain["selection_policy"],
    }
    return VerifiedStudySupport(
        study.config_sha256,
        producer,
        registry["mask_sha256"],
        registry["mask_revision"],
        r6,
        native_r8,
        compute[6],
        compute[8],
        canonical_bytes(identity).decode(),
    )
