"""Explicit bounded scientific producer routes, separate from release orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from shapely.geometry import Polygon, mapping, shape

from seascape._study_contract import canonical_bytes
from seascape.core.geo.h3 import cell_to_polygon
from seascape.seafloor_physiography.bathymetry.build import _aggregate_raster
from seascape.seafloor_physiography.depth import validate_native_metre_band_units
from seascape.seafloor_physiography.geomorphometry.build import (
    _derive_metrics,
    _native_raster_slope_summary,
    output_columns,
    validate_geomorphometry_settings,
)
from seascape.spatial_support.water_network.validation import validate_neighborhoods
from seascape.study import StudyConfig, StudyConfigError
from seascape.study_support import VerifiedStudySupport, _read_pinned
from seascape.utils.spatial import water_neighborhood_lookup

if TYPE_CHECKING:
    from seascape.seafloor_physiography.bathymetry.pipeline import BathymetryConfig
    from seascape.seafloor_physiography.geomorphometry.build import GeomorphometryConfig


@dataclass(frozen=True)
class PinnedInput:
    """Source or upstream exact bytes; metadata retains source vintage and rights."""

    relative_path: str
    sha256: str
    metadata_json: str


@dataclass
class RoutedProduct:
    """Computed context and reporting selection; not a certified release."""

    reporting: pd.DataFrame
    compute: pd.DataFrame
    provenance_json: str

    def provenance(self) -> dict[str, Any]:
        return json.loads(self.provenance_json)

    def write_reporting(self, path: str | Path) -> Path:
        """Write one static table with embedded provenance, refusing overwrite."""
        return self._write(path, self.reporting, "reporting")

    def write_compute(self, path: str | Path) -> Path:
        """Retain separate scientific compute context with embedded lineage."""
        return self._write(path, self.compute, "compute")

    def _write(self, path: str | Path, frame: pd.DataFrame, role: str) -> Path:
        destination = Path(path)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        metadata = dict(table.schema.metadata or {})
        metadata[b"marinecast_study_route"] = canonical_bytes(
            self.provenance() | {"artifact_role": role}
        )
        with destination.open("xb") as stream:
            pq.write_table(table.replace_schema_metadata(metadata), stream)
        return destination


def _capture(
    study: StudyConfig, spec: PinnedInput, byte_limit: int
) -> tuple[bytes, dict[str, Any]]:
    raw = _read_pinned(
        study.source.parent,
        study.data_root,
        spec.relative_path,
        spec.sha256,
        byte_limit,
    )
    metadata = json.loads(spec.metadata_json)
    required = {"version", "observation_period", "license", "evidence_type"}
    if not isinstance(metadata, dict) or not required.issubset(metadata):
        raise StudyConfigError(
            "Pinned input metadata requires vintage, rights and evidence type."
        )
    return raw, {
        "relative_path": spec.relative_path,
        "raw_sha256": spec.sha256,
        "source_metadata": metadata,
        "qualification": "not_established_by_route",
    }


def _context(
    study: StudyConfig,
    support: VerifiedStudySupport,
    producer: str,
    resolution: int,
    byte_limit: int,
    max_rows: int,
) -> tuple[str, ...]:
    if support.config_sha256 != study.config_sha256 or support.producer != producer:
        raise StudyConfigError("Producer support and selected study identity disagree.")
    if (
        type(byte_limit) is not int
        or byte_limit <= 0
        or type(max_rows) is not int
        or max_rows <= 0
    ):
        raise StudyConfigError(
            "Source byte and row/pixel budgets must be positive integers."
        )
    return support.cells(resolution, role="compute")


def _raster(raw: bytes, max_pixels: int) -> dict[str, Any]:
    with rasterio.io.MemoryFile(raw) as memory, memory.open() as raster:
        if raster.count != 1 or raster.crs is None or raster.crs.to_epsg() != 4326:
            raise StudyConfigError("Native source must be single-band WGS84.")
        try:
            validate_native_metre_band_units(raster.units[0])
        except ValueError as exc:
            raise StudyConfigError(str(exc)) from exc
        if raster.width * raster.height > max_pixels:
            raise StudyConfigError("Native raster exceeds decoded pixel budget.")
        return {
            "crs": raster.crs.to_string(),
            "bounds_wgs84": list(raster.bounds),
            "transform": list(raster.transform),
            "width": raster.width,
            "height": raster.height,
            "nodata": raster.nodata
            if raster.nodata is None or np.isfinite(raster.nodata)
            else str(raster.nodata),
            "footprint_wgs84": mapping(
                Polygon(
                    [
                        raster.transform * point
                        for point in (
                            (0, 0),
                            (raster.width, 0),
                            (raster.width, raster.height),
                            (0, raster.height),
                            (0, 0),
                        )
                    ]
                )
            ),
        }


def _parquet(raw: bytes, max_rows: int) -> pd.DataFrame:
    if pq.ParquetFile(BytesIO(raw)).metadata.num_rows > max_rows:
        raise StudyConfigError("Native table exceeds decoded row budget.")
    return pd.read_parquet(BytesIO(raw))


def _graph(
    raw: bytes,
    cells: tuple[str, ...],
    resolution: int,
    maximum_hops: int,
    max_rows: int,
) -> pd.DataFrame:
    if type(maximum_hops) is not int or maximum_hops < 1:
        raise StudyConfigError(
            "Graph hop support must be an explicit positive integer."
        )
    graph = _parquet(raw, max_rows)
    # Existing scientific validator enforces one self row per context cell,
    # unique graph pairs, valid hop/distance ranges and no outside targets.
    validate_neighborhoods(
        graph, pd.DataFrame({"H3_INDEX": cells}), resolution, maximum_hops=maximum_hops
    )
    if any(type(value) is not str for value in graph.SOURCE_H3_INDEX) or any(
        type(value) is not str for value in graph.TARGET_H3_INDEX
    ):
        raise StudyConfigError("Graph keys must remain canonical H3 strings.")
    return graph


def _bind_graph(
    source: dict[str, Any],
    study: StudyConfig,
    support: VerifiedStudySupport,
    resolution: int,
    maximum_hops: int,
) -> None:
    metadata = source["source_metadata"]
    membership = next(
        m
        for m in support.provenance()["compute_memberships"]
        if m["resolution"] == resolution
    )
    expected = {
        "study_config_sha256": study.config_sha256,
        "mask_sha256": support.mask_sha256,
        "compute_membership_sha256": membership["sha256"],
        "maximum_graph_hops": maximum_hops,
    }
    if any(
        metadata.get(key) != value or type(metadata.get(key)) is not type(value)
        for key, value in expected.items()
    ):
        raise StudyConfigError(
            "Pinned graph metadata must match study, mask, compute membership and hop support."
        )


def _product(
    output: pd.DataFrame,
    study: StudyConfig,
    support: VerifiedStudySupport,
    producer: str,
    resolution: int,
    sources: list[dict[str, Any]],
    raster: dict[str, Any],
    settings: dict[str, Any],
    coverage: np.ndarray,
) -> RoutedProduct:
    # Strict consumer performs the final trim only after scientific context work.
    output = support.consume_table(output, resolution, role="compute")
    output["H3_RESOLUTION"] = resolution
    extent = shape(raster["footprint_wgs84"])
    output["NATIVE_EXTENT_STATUS"] = [
        "full_cell_within_native_extent"
        if extent.covers(cell_to_polygon(cell))
        else "cell_extends_outside_native_extent"
        for cell in output.H3_INDEX
    ]
    output["NATIVE_SAMPLE_STATUS"] = coverage
    reporting = support.consume_table(output, resolution, role="reporting")
    provenance = {
        "schema_version": 1,
        "producer": producer,
        "h3_resolution": resolution,
        "study": study.provenance(),
        "support": support.provenance(),
        "sources": sources,
        "native_raster": raster,
        "scientific_settings": settings,
        "compute_count": len(output),
        "reporting_count": len(reporting),
        "missing_native_sample_count": int(
            (reporting.NATIVE_SAMPLE_STATUS != "valid_native_samples").sum()
        ),
        "native_extent_partial_count": int(
            (reporting.NATIVE_EXTENT_STATUS != "full_cell_within_native_extent").sum()
        ),
        "scientific_scope": "compute_context_first_reporting_trim_afterward",
        "sampling_grain": "full H3 cells; valid native marine pixel centers; reporting mask selects cells only",
        "graph_completeness": "not_established_by_route",
        "source_completeness": "source_relative_coverage_recorded_not_regionally_qualified",
        "production_ready": False,
        "release_eligible": False,
        "static_time_policy": "one static table; retained source vintages; no backdating",
    }
    provenance["route_identity_sha256"] = hashlib.sha256(
        canonical_bytes(provenance)
    ).hexdigest()
    return RoutedProduct(reporting, output, canonical_bytes(provenance).decode())


def route_bathymetry(
    config: BathymetryConfig,
    study: StudyConfig,
    support: VerifiedStudySupport,
    *,
    raster: PinnedInput,
    neighborhoods: PinnedInput,
    maximum_graph_hops: int,
    max_input_bytes: int = 16 * 1024 * 1024,
    max_pixels_and_rows: int = 1_000_000,
) -> RoutedProduct:
    """Execute existing direct pixel, quantile, band, anomaly and contour methods."""
    resolution = config.h3_resolution
    cells = _context(
        study, support, "bathymetry", resolution, max_input_bytes, max_pixels_and_rows
    )
    if config.local_depth_anomaly_neighborhood_rings > maximum_graph_hops:
        raise StudyConfigError("Anomaly rings exceed declared graph support.")
    depth_raw, depth_source = _capture(study, raster, max_input_bytes)
    graph_raw, graph_source = _capture(study, neighborhoods, max_input_bytes)
    _bind_graph(graph_source, study, support, resolution, maximum_graph_hops)
    native = _raster(depth_raw, max_pixels_and_rows)
    graph = _graph(
        graph_raw, cells, resolution, maximum_graph_hops, max_pixels_and_rows
    )
    settings = {
        name: getattr(config, name)
        for name in (
            "bathymetry_sign",
            "depth_quantiles",
            "local_depth_anomaly_neighborhood_rings",
            "isobath_levels_m",
            "isobath_distance_projected_crs",
        )
    }
    output = _aggregate_raster(
        depth_raw, list(cells), resolution, neighborhoods=graph, **settings
    )
    coverage = np.where(
        output.BATHYMETRY_PIXEL_COUNT.notna(),
        "valid_native_samples",
        "no_valid_native_marine_pixels",
    )
    return _product(
        output,
        study,
        support,
        "bathymetry",
        resolution,
        [depth_source, graph_source],
        native,
        settings,
        coverage,
    )


def route_geomorphometry(
    config: GeomorphometryConfig,
    study: StudyConfig,
    support: VerifiedStudySupport,
    *,
    bathymetry: PinnedInput,
    raster: PinnedInput,
    neighborhoods: PinnedInput,
    maximum_graph_hops: int,
    max_input_bytes: int = 16 * 1024 * 1024,
    max_pixels_and_rows: int = 1_000_000,
) -> RoutedProduct:
    """Execute existing native-slope and graph-scale terrain methods over context."""
    resolution = config.h3_resolution
    if type(resolution) is not int or resolution != 8:
        raise StudyConfigError(
            "Geomorphometry scientific route supports native R8 only; no implicit R6 resampling."
        )
    try:
        validate_geomorphometry_settings(config)
    except (ValueError, TypeError) as exc:
        raise StudyConfigError(str(exc)) from exc
    cells = _context(
        study,
        support,
        "geomorphometry",
        resolution,
        max_input_bytes,
        max_pixels_and_rows,
    )
    required_hops = {
        config.neighbor_ring,
        config.openness_radius_rings,
        *config.neighborhood_rings,
    }
    if max(required_hops) > maximum_graph_hops:
        raise StudyConfigError("Terrain rings exceed declared graph support.")
    depth_raw, depth_source = _capture(study, bathymetry, max_input_bytes)
    raster_raw, raster_source = _capture(study, raster, max_input_bytes)
    graph_raw, graph_source = _capture(study, neighborhoods, max_input_bytes)
    _bind_graph(graph_source, study, support, resolution, maximum_graph_hops)
    native = _raster(raster_raw, max_pixels_and_rows)
    depth_metadata = pq.ParquetFile(BytesIO(depth_raw)).metadata.metadata or {}
    try:
        upstream = json.loads(depth_metadata[b"marinecast_study_route"])
        identity = {
            key: value
            for key, value in upstream.items()
            if key not in {"artifact_role", "route_identity_sha256"}
        }
        if (
            upstream["artifact_role"] != "compute"
            or upstream["producer"] != "bathymetry"
            or upstream["study"]["config_sha256"] != study.config_sha256
            or upstream["support"]["reporting_mask_sha256"] != support.mask_sha256
            or upstream["h3_resolution"] != resolution
            or hashlib.sha256(canonical_bytes(identity)).hexdigest()
            != upstream["route_identity_sha256"]
        ):
            raise ValueError("Upstream route identity mismatch.")
    except (KeyError, ValueError, TypeError) as exc:
        raise StudyConfigError(
            "Geomorphometry requires matching routed compute bathymetry provenance."
        ) from exc
    depth_source["upstream_route_identity_sha256"] = upstream["route_identity_sha256"]
    source = support.consume_table(
        _parquet(depth_raw, max_pixels_and_rows), resolution, role="compute"
    )
    graph = _graph(
        graph_raw, cells, resolution, maximum_graph_hops, max_pixels_and_rows
    )
    lookups = {
        hops: water_neighborhood_lookup(graph, maximum_hops=hops)
        for hops in required_hops
    }
    output = _derive_metrics(source[["H3_INDEX", "BATHYMETRY"]], config, lookups)
    slope = _native_raster_slope_summary(
        raster_raw, set(cells), resolution, config.slope_upper_quantile
    )
    output = output.drop(
        columns=["SLOPE_MEAN_NATIVE_RASTER", "SLOPE_Q90_NATIVE_RASTER"]
    ).merge(slope, on="H3_INDEX", how="left", validate="one_to_one")[
        output_columns(config.neighborhood_rings)
    ]
    coverage = np.where(
        output.SLOPE_MEAN_NATIVE_RASTER.notna(),
        "valid_native_samples",
        "no_valid_native_slope_stencil",
    )
    settings = {
        name: getattr(config, name)
        for name in (
            "projected_crs",
            "neighbor_ring",
            "neighborhood_rings",
            "minimum_neighbors",
            "ruggedness_algorithm",
            "slope_upper_quantile",
            "openness_radius_rings",
            "openness_bearing_sectors",
            "curvature_index_scale_per_m",
        )
    }
    return _product(
        output,
        study,
        support,
        "geomorphometry",
        resolution,
        [depth_source, raster_source, graph_source],
        native,
        settings,
        coverage,
    )
