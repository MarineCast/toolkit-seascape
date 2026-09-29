"""Presentation of identified user failures at the installed CLI boundary only."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import TracebackType

import yaml
from pyproj.exceptions import CRSError

# Match the leaf validator, not every ValueError raised underneath a producer.
# An error from a calculation, dependency or unlisted helper remains a traceback.
_CONFIG_SITES = {
    "seascape.core.config.document": {
        "load",
        "_load_recursive",
        "_lookup",
        "_resolve_values",
    },
    "seascape.core.config.common_areas": {
        "_common_areas",
        "bbox_for_area",
        "bbox_from_config",
        "resolve_range_config",
    },
    "seascape.core.geo.crs": {"require_metric_crs"},
    "seascape.utils.config": {"require_mapping"},
    "seascape.preflight": {"_contract"},
    "seascape.seafloor_physiography.depth": {"require_positive_down_config"},
    "seascape.spatial_support.water_geometry.config": {"load_water_geometry_config"},
    "seascape.spatial_support.water_geometry.download": {
        "load_water_geometry_source_config"
    },
    "seascape.spatial_support.h3_geometry.build": {
        "load_h3_geometry_config",
        "load_yaml_config",
    },
    "seascape.spatial_support.water_network.config": {"load_water_network_config"},
    "seascape.seafloor_physiography.bathymetry.pipeline": {
        "load_bathymetry_config",
        "_required",
    },
    "seascape.seafloor_physiography.geomorphometry.build": {
        "load_geomorphometry_config"
    },
    "seascape.seafloor_physiography.geomorphic_units.build": {
        "load_geomorphic_units_config"
    },
    "seascape.coastal_configuration.shoreline_characterization.build": {
        "load_shoreline_config"
    },
    "seascape.coastal_configuration.shoreline_characterization.download": {
        "load_source_config"
    },
    "seascape.coastal_configuration.shoreline_proximity.build": {
        "load_shoreline_proximity_config"
    },
    "seascape.coastal_configuration.exposure_and_enclosure.build": {
        "load_exposure_enclosure_config"
    },
    "seascape.coastal_configuration.waterbody_morphometry.build": {
        "load_waterbody_morphometry_config"
    },
    "seascape.hydrologic_connectivity.freshwater_sources.build": {
        "load_river_mouth_build_config"
    },
    "seascape.hydrologic_connectivity.freshwater_sources.download": {
        "load_freshwater_download_config"
    },
    "seascape.hydrologic_connectivity.fluvial_connectivity.topology": {
        "load_fluvial_connectivity_config"
    },
    "seascape.hydrologic_connectivity.fluvial_connectivity.selected_outlets_build": {
        "load_selected_outlet_config"
    },
    "seascape.coastal_configuration.nearshore_build": {"load_nearshore_config"},
    "seascape.coastal_configuration.passage_build": {"load_passage_config"},
    "seascape.coastal_configuration.gateway_build": {"load_gateway_config"},
    "seascape.coastal_configuration.coast_complexity_build": {"load_coast_complexity_config"},
    "seascape.biogenic_habitat.mosaic_build": {"load_mosaic_config"},
    "seascape.hydrologic_connectivity.estuarine_connectivity.build": {
        "load_estuarine_connectivity_config"
    },
    "seascape.hydrologic_connectivity.estuarine_connectivity.download": {
        "load_estuarine_download_config"
    },
}
_WORKFLOW_SETTINGS = {
    "selected_stages",
    "plan_domain_layer_build",
    "_render_candidate_config",
    "_validate_candidate_outputs",
    "_prepare_candidate_config",
}
_PUBLICATION_MODULES = {"seascape.publication", "seascape.core.artifacts.publication"}
_RELEASE_VALIDATORS = {
    "_seascape_products",
    "_catalog_table_audit",
    "_manifest_audit",
    "_governance_audit",
    "_radius_operator_audit",
    "_depth_band_audit",
    "_shoreline_audit",
    "build_release_audit",
    "publish_candidate_release",
}

EXPECTED_TYPES = (OSError, ValueError, KeyError, RuntimeError, yaml.YAMLError)


def safe_detail(value: object) -> str:
    """Avoid printing remote credentials or quoted conversion/config values.

    Debug tracebacks are deliberately unfiltered and must be reviewed before sharing.
    """
    text = str(value)
    if text.startswith(("could not convert", "invalid literal")):
        return (
            "Invalid numeric configuration value; inspect the selected configuration."
        )
    # Config validators can interpolate arbitrary quoted user values (e.g. an
    # unknown area). Keep the setting/requirement, omit the supplied literal.
    expected_literals = {"positive_down", "negative_elevation", "wilson"}
    text = re.sub(
        r"(['\"])(.*?)\1",
        lambda match: (
            match.group(0)
            if match.group(2) in expected_literals
            else "<redacted value>"
        ),
        text,
    )
    if re.search(r"[A-Za-z][A-Za-z0-9+.-]*:/", text) or re.search(
        r"(?i)(password|secret|token|api[_-]?key)[\"\']?\s*[=:]", text
    ):
        return "<redacted sensitive detail>"
    return text.replace("\n", " ")


@dataclass(frozen=True)
class Diagnostic:
    reason: str
    action: str
    guide: str = "docs/WORKFLOWS.md#common-problems"


def _sites(tb: TracebackType | None) -> list[tuple[str, str]]:
    sites = []
    while tb is not None:
        sites.append(
            (tb.tb_frame.f_globals.get("__name__", ""), tb.tb_frame.f_code.co_name)
        )
        tb = tb.tb_next
    return sites


def identify_failure(exc: BaseException) -> Diagnostic | None:
    """Return guidance only for a known failure; never alter the exception."""
    sites = _sites(exc.__traceback__)
    module, function = sites[-1] if sites else ("", "")
    config = function in _CONFIG_SITES.get(module, set())
    publication = any(m in _PUBLICATION_MODULES for m, _ in sites)
    if (
        isinstance(exc, CRSError)
        and ("seascape.core.geo.crs", "require_metric_crs") in sites
    ):
        return Diagnostic(
            "Invalid declared scientific projected CRS",
            "Correct the projected_crs/equal_area_crs setting in the selected configuration; use a region-appropriate projection with horizontal axes in meters.",
            "docs/CONFIGURATION.md; docs/CONTRACTS.md",
        )
    if isinstance(exc, FileExistsError):
        return Diagnostic(
            f"Output already exists: {safe_detail(exc.filename or exc)}",
            "Keep trusted output; choose a fresh candidate or a distinct export destination. Review ownership before any explicit overwrite.",
        )
    if isinstance(exc, FileNotFoundError):
        if function == "_record_stage_state" and module == "seascape.workflow":
            return Diagnostic(
                safe_detail(exc),
                "Inspect the producer failure and restore its declared output before dependent stages or publication.",
            )
        if config or any(m == "seascape.core.config.document" for m, _ in sites):
            return Diagnostic(
                f"Configuration is missing: {safe_detail(exc.filename or exc)}",
                "Confirm --workspace and --config, including referenced files. For a new workspace run seascape --workspace PATH init and review its templates.",
                "docs/CONFIGURATION.md",
            )
        return Diagnostic(
            f"Required local input is missing: {safe_detail(exc.filename or exc)}",
            "Check the configured path and the owning family's source guide. Supply the approved input or build its upstream stage; acquisition is a separate operation.",
        )
    if isinstance(exc, yaml.YAMLError) and any(
        m == "seascape.core.config.document" for m, _ in sites
    ):
        mark = getattr(exc, "problem_mark", None)
        location = (
            f" (line {mark.line + 1}, column {mark.column + 1})"
            if mark is not None
            else ""
        )
        return Diagnostic(
            "Invalid configuration YAML" + location,
            "Correct the YAML syntax in the selected or referenced configuration.",
            "docs/CONFIGURATION.md",
        )
    if isinstance(exc, (ValueError, KeyError, TypeError)) and config:
        return Diagnostic(
            f"Invalid configuration: {safe_detail(exc.args[0] if isinstance(exc, KeyError) and exc.args else exc)}",
            "Correct the reported setting using the configuration and source contracts; preserve declared CRS, units, sign and missingness.",
            "docs/CONFIGURATION.md; docs/CONTRACTS.md",
        )
    if (
        isinstance(exc, ValueError)
        and module == "seascape.preflight"
        and function == "preflight_build"
        and str(exc) == "Resolved output escapes candidate"
    ):
        return Diagnostic(
            str(exc),
            "Correct the selected family's output paths; all resolved outputs must stay inside the fresh candidate.",
        )
    if (
        isinstance(exc, ValueError)
        and module == "seascape.workflow"
        and function in _WORKFLOW_SETTINGS
    ):
        return Diagnostic(
            safe_detail(exc),
            "Review the selected stages (seascape stages), config and candidate confinement; use a fresh candidate inside the selected workspace.",
        )
    if isinstance(exc, ValueError) and (
        module == "seascape.products"
        and function in {"_verified_manifest", "_release_path", "resolve_product"}
        or module == "seascape.metric_matrix"
        and function
        in {
            "_read_catalog",
            "_legacy_status",
            "_validated_table",
            "build_metric_matrix",
        }
        or module == "seascape.release"
        and function in _RELEASE_VALIDATORS
        or module == "seascape.publication"
        and function in {"__init__", "stage_candidate"}
    ):
        return Diagnostic(
            f"Release/export validation failed: {safe_detail(exc)}",
            "Preserve canonical products and retained releases. Inspect the reported contract/checksum and candidate audit; correct the candidate or restore verified source bytes before retrying. Do not bypass validation.",
            "docs/WORKFLOWS.md#6-publish-after-review; docs/API.md",
        )
    if (
        isinstance(exc, RuntimeError)
        and module == "seascape.core.artifacts.publication"
        and function in {"_exclusive_parent", "_recover_owned"}
    ):
        return Diagnostic(
            f"Publication failed: {safe_detail(exc)}",
            "Wait for the active writer or inspect preserved transaction recovery evidence. Keep locks, journals and retained releases intact; retry only after recovery succeeds.",
        )
    if isinstance(exc, OSError) and publication:
        return Diagnostic(
            f"Publication I/O failed: {safe_detail(exc)}",
            "Check destination permissions, free space and recovery evidence. Keep transaction journals and trusted releases intact before retrying.",
        )
    if isinstance(exc, PermissionError):
        return Diagnostic(
            f"Local access denied: {safe_detail(exc.filename or exc)}",
            "Check read/write permissions for the selected input or owned output directory; preserve existing trusted artifacts.",
        )
    return None


def build_operation(exc: BaseException) -> str:
    """Recover stage context without changing API exception types or chaining."""
    tb = exc.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if (
            frame.f_globals.get("__name__") == "seascape.workflow"
            and frame.f_code.co_name == "run_domain_layer_build"
        ):
            stage = frame.f_locals.get("stage")
            if stage is not None:
                return f"build / {stage.name}"
        tb = tb.tb_next
    return "build"
