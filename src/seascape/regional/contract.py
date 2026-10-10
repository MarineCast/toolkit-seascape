"""Explicit byte-bound inputs and immutable operator candidates."""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import h3
import pyarrow.parquet as pq


class RegionalError(ValueError):
    """Invalid regional specification, source or candidate."""


def input_bytes(path: Path) -> int:
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return path.stat().st_size


def digest(path: Path) -> str:
    if path.is_dir():
        components = sorted(p for p in path.rglob("*") if p.is_file())
        if not components or any(p.is_symlink() for p in path.rglob("*")):
            raise RegionalError(
                "Directory input requires nonempty, non-symlink components"
            )
        data = [
            {"path": p.relative_to(path).as_posix(), "raw_sha256": digest(p)}
            for p in components
        ]
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class Input:
    path: Path
    sha256: str
    qualification: dict

    def verify(self):
        if not self.path.exists() or digest(self.path) != self.sha256:
            raise RegionalError(f"Pinned input changed or missing: {self.path}")


@dataclass
class Job:
    spec_path: Path
    spec_sha256: str
    operator: str
    resolution: int
    domain: dict
    inputs: dict[str, Input]
    output: Path
    settings: dict
    limits: dict
    started: float

    @classmethod
    def load(cls, path: Path):
        path = path.resolve()
        spec = json.loads(path.read_text())
        if spec.get("schema") != 1:
            raise RegionalError("Regional spec schema must be 1")
        resolution = spec.get("resolution", 6)
        if type(resolution) is not int or resolution not in (6, 8):
            raise RegionalError("Only explicit native R6/R8 supported")
        domain = spec.get("domain", {})
        if not all(
            domain.get(key) for key in ("id", "revision", "support", "coverage_status")
        ):
            raise RegionalError(
                "Domain requires id, revision, support and coverage_status"
            )
        if not isinstance(spec.get("inputs"), dict) or not spec["inputs"]:
            raise RegionalError("Explicit pinned inputs required")
        inputs = {}
        for name, item in spec["inputs"].items():
            pin = item.get("sha256", "")
            if len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
                raise RegionalError(f"Invalid raw SHA-256: {name}")
            qualification = item.get("qualification", {})
            if not all(
                key in qualification
                for key in (
                    "rights",
                    "spatial_support",
                    "coverage_status",
                    "observation_period",
                )
            ):
                raise RegionalError(f"Input qualification missing: {name}")
            if (
                not qualification["rights"]
                or not qualification["spatial_support"]
                or not qualification["coverage_status"]
            ):
                raise RegionalError(f"Empty input qualification: {name}")
            source = Path(item["path"]).expanduser()
            if not source.is_absolute():
                source = path.parent / source
            inputs[name] = Input(source.resolve(), pin, qualification)
        output = Path(spec["output"]).expanduser()
        if not output.is_absolute():
            output = path.parent / output
        output = output.resolve()
        if output.exists():
            raise RegionalError(f"Output must be new: {output}")
        if any(
            output == item.path or output in item.path.parents
            for item in inputs.values()
        ):
            raise RegionalError("Output contains an input")
        limits = spec.get("limits", {})
        ceilings = {
            "memory_bytes": 1536 * 1024**2,
            "staging_bytes": 512 * 1024**2,
            "seconds": 3600,
            "batch_rows": 4096,
            "input_bytes": 1024**4,
        }
        for key, ceiling in ceilings.items():
            value = limits.setdefault(key, ceiling)
            if type(value) is not int or not 0 < value <= ceiling:
                raise RegionalError(f"Invalid {key}; maximum {ceiling}")
        if (
            sum(input_bytes(item.path) for item in inputs.values())
            > limits["input_bytes"]
        ):
            raise RegionalError("Input byte limit exceeded")
        job = cls(
            path,
            digest(path),
            spec["operator"],
            resolution,
            domain,
            inputs,
            output,
            spec.get("settings", {}),
            limits,
            time.monotonic(),
        )
        job.verify_inputs()
        return job

    def verify_inputs(self):
        if digest(self.spec_path) != self.spec_sha256:
            raise RegionalError("Spec changed during execution")
        for item in self.inputs.values():
            item.verify()

    def source(self, name):
        try:
            return self.inputs[name].path
        except KeyError as exc:
            raise RegionalError(f"Required input missing: {name}") from exc

    def guard(self):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
        elapsed = time.monotonic() - self.started
        size = (
            sum(p.stat().st_size for p in self.output.rglob("*") if p.is_file())
            if self.output.exists()
            else 0
        )
        if (
            peak > self.limits["memory_bytes"]
            or elapsed > self.limits["seconds"]
            or size > self.limits["staging_bytes"]
        ):
            raise RegionalError(
                f"Resource limit: RSS={peak}, elapsed={elapsed}, staging={size}"
            )
        return {
            "peak_rss_bytes": peak,
            "elapsed_seconds": elapsed,
            "staging_bytes": size,
        }

    def keys(self):
        keys = self.source("reporting").read_text().splitlines()
        if (
            not keys
            or keys != sorted(set(keys))
            or any(
                not h3.is_valid_cell(k) or h3.get_resolution(k) != self.resolution
                for k in keys
            )
        ):
            raise RegionalError(
                "Reporting keys must be unique sorted native-resolution H3 cells"
            )
        return keys

    def table(self, name, columns=None):
        reader = pq.ParquetFile(self.source(name))
        if reader.metadata.num_rows > self.settings.get("max_input_rows", 500_000):
            raise RegionalError(f"Input row cap: {name}")
        return reader.read(columns=columns, use_threads=False)

    def finish(self, method, details):
        self.verify_inputs()
        measurements = self.guard()
        paths = sorted(p for p in self.output.rglob("*") if p.is_file())
        files = {
            str(p.relative_to(self.output)): {
                "raw_content_sha256": digest(p),
                "bytes": p.stat().st_size,
            }
            for p in paths
        }
        from seascape import __version__
        from seascape.core.code_identity import package_code_identity

        code_identity = package_code_identity(Path(__file__).resolve().parent)

        manifest = {
            "schema": 3,
            "operator": self.operator,
            "method_version": method,
            "toolkit_version": __version__,
            "code_identity": code_identity,
            "resolution": self.resolution,
            "domain": self.domain,
            "status": "source_scoped_operator_candidate",
            "complete_toolkit": False,
            "published": False,
            "source_acquisition_bytes": 0,
            "inputs": {
                name: {
                    "path": str(item.path),
                    "sha256": item.sha256,
                    "hash_kind": "directory_component_manifest_v1"
                    if item.path.is_dir()
                    else "raw_file_sha256",
                    "qualification": item.qualification,
                }
                for name, item in self.inputs.items()
            },
            "spec_raw_sha256": self.spec_sha256,
            "settings": self.settings,
            "limits": self.limits,
            "measurements": measurements,
            "details": details,
            "files": files,
        }
        path = self.output / "MANIFEST.json"
        path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        checksums = dict(files)
        checksums["MANIFEST.json"] = {
            "raw_content_sha256": digest(path),
            "bytes": path.stat().st_size,
        }
        (self.output / "CHECKSUMS.sha256").write_text(
            "".join(
                f"{item['raw_content_sha256']}  {name}\n"
                for name, item in sorted(checksums.items())
            )
        )
        self.guard()
        return manifest
