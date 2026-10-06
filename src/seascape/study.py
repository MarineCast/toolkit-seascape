"""Portable, explicit study-v1 planning; production membership integration pending."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seascape._study_contract import canonical_bytes, validate


class StudyConfigError(ValueError):
    """Invalid study selection or unsupported study execution."""


@dataclass(frozen=True)
class StudyConfig:
    """Frozen content identity; resolved locations are separate from canonical hashes."""

    source: Path
    canonical_json: str
    config_sha256: str
    raw_file_sha256: str
    data_root: Path

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)

    def provenance(self) -> dict[str, Any]:
        config = self.payload
        return {
            "schema_version": 1,
            "study_id": config["study_id"],
            "config_source": str(self.source),
            "config_sha256": self.config_sha256,
            "raw_file_sha256": self.raw_file_sha256,
            "geometry_sha256": config["domain"]["geometry_sha256"],
            "domain_revision": config["domain"]["revision"],
            "domain_status": config["domain"]["status"],
            "reporting_bbox_wgs84": config["domain"]["bbox_wgs84"],
            "requested_time": config["time"],
            "product": config["products"]["seascape"],
            "producer_buffers": config["producer_buffers"]["seascape"],
            "resolved_data_root": str(self.data_root),
            "grid_registry": config["grid_registry"],
            "contract": config,
            "integration_status": "planning_only",
            "production_ready": False,
            "static_time_policy": "source vintages retained; no annual duplication or backdating",
        }


_STUDY: ContextVar[StudyConfig | None] = ContextVar("seascape_study", default=None)


def load_study_config(
    path: str | Path | None = None, *, planning: bool = False
) -> StudyConfig | None:
    """Explicit path wins over the optional environment fallback; never guess a path."""
    selected = path if path is not None else os.environ.get("MARINECAST_STUDY_CONFIG")
    if selected is None:
        return None
    if not str(selected):
        raise StudyConfigError("Study config path must not be empty.")
    source = Path(selected).expanduser().resolve()
    try:
        raw = source.read_bytes()
        config, identity = validate(source, require_approved=not planning)
        if source.read_bytes() != raw:
            raise StudyConfigError("Study config changed while being validated.")
        content = canonical_bytes(config)
        return StudyConfig(
            source,
            content.decode("utf-8"),
            identity["config_sha256"],
            hashlib.sha256(raw).hexdigest(),
            Path(identity["resolved_data_root"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StudyConfigError(f"Invalid study config {source}: {exc}") from exc


def current_study() -> StudyConfig | None:
    return _STUDY.get()


def require_study_execution(*, planning: bool = False) -> None:
    """Protect orchestration callers as well as the CLI before candidate writes."""
    if current_study() is not None and not planning:
        raise StudyConfigError(
            "Study-config production integration is not enabled: marine reporting "
            "membership and compute-halo integration remain pending."
        )


@contextmanager
def study_context(
    study: StudyConfig | None, *, planning: bool = False
) -> Iterator[None]:
    """Never launch producers with an unintegrated shared reporting membership."""
    if study is not None and not planning:
        if study.payload["domain"]["status"] != "approved":
            raise StudyConfigError(
                "Domain remains proposed; production requires approval."
            )
        raise StudyConfigError(
            "Study-config production integration is not enabled: validated marine reporting "
            "membership must replace territorial-water selection first. Use build --dry-run."
        )
    token = _STUDY.set(study)
    try:
        yield
    finally:
        _STUDY.reset(token)


def apply_study_config(config: dict[str, Any]) -> dict[str, Any]:
    """Render only planning overrides; retain full identity in the effective fingerprint."""
    study = current_study()
    if study is None or "areas" in config:
        return config
    result = deepcopy(config)
    buffers = study.payload["producer_buffers"]["seascape"]
    result["marinecast_study"] = study.provenance()
    result["marinecast_study_contract"] = study.payload
    if "h3_geometry" in result:
        result["h3_geometry"]["buffer_m"] = buffers["water_geometry_m"]
    for family in (
        "shoreline_proximity",
        "exposure_and_enclosure",
        "waterbody_morphometry",
        "fluvial_connectivity",
    ):
        if family in result:
            result[family]["processing"]["network_context_buffer_km"] = (
                buffers["coastal_network_m"] / 1000
            )
    if "freshwater_sources" in result:
        download = result["freshwater_sources"]["download"]
        download["context_buffer_km"] = buffers["freshwater_context_m"] / 1000
        for name, source in download.get("sources", {}).items():
            jurisdiction = (
                "bc"
                if name.startswith("bc_")
                else "us"
                if name.startswith("us_")
                else None
            )
            if jurisdiction and "context_buffer_km" in source:
                source["context_buffer_km"] = (
                    buffers["river_source_context_m"][jurisdiction] / 1000
                )
    if "estuarine_connectivity" in result:
        result["estuarine_connectivity"]["download"]["context_buffer_km"] = (
            buffers["catchment_context_m"] / 1000
        )
    return result
