"""Native-grain retrospective extraction with explicit requested and actual coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from seascape.core.artifacts import TransactionalFamilyPublisher
from seascape.domain_parquets import (
    METADATA_KEY,
    AreaTables,
    _copy_research_tree,
    _io_root,
    list_areas,
    write_areas,
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate study configuration key: {key}")
        result[key] = value
    return result


def _date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Study dates must use YYYY-MM-DD")
    return date.fromisoformat(value)


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@dataclass(frozen=True)
class HistoricalRequest:
    start: date
    end_exclusive: date
    study_id: str
    study_sha256: str
    study_path: str

    @classmethod
    def from_study(cls, path: str | Path) -> HistoricalRequest:
        source = Path(path).expanduser().resolve()
        raw = source.read_bytes()
        try:
            document = json.loads(raw, object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise ValueError("Study configuration is invalid JSON") from exc
        if not isinstance(document, dict) or not isinstance(document.get("time"), dict):
            raise ValueError("An explicit study time request is required")
        time = document["time"]
        if time.get("timezone") != "UTC":
            raise ValueError("Historical Seascape requests require UTC")
        start, end = _date(time.get("start")), _date(time.get("end_exclusive"))
        if start >= end:
            raise ValueError("Historical request must have a positive interval")
        return cls(
            start,
            end,
            str(document.get("study_id", "unspecified")),
            hashlib.sha256(raw).hexdigest(),
            str(source),
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end_exclusive": self.end_exclusive.isoformat(),
            "timezone": "UTC",
            "study_id": self.study_id,
            "study_sha256": self.study_sha256,
            "study_path": self.study_path,
            "selection": "native_interval_overlap",
            "geometry_qualification": "Inherited from source products; not established by reading the request",
        }


@dataclass(frozen=True)
class HistoricalExport:
    output_dir: Path
    report_path: Path
    report: dict[str, Any]


def _select_dynamic(
    table: pa.Table, context: dict[str, Any], request: HistoricalRequest
) -> tuple[pa.Table, list[tuple[date, date]], str]:
    if "date" not in table.column_names or not pa.types.is_date32(table["date"].type):
        raise ValueError("Historical dynamic inputs require native date32 labels")
    if table["date"].null_count:
        raise ValueError("Historical dynamic date labels cannot be null")
    temporal = context.get("temporal_support", {})
    precision = temporal.get("precision")
    if precision == "year":
        if pc.any(
            pc.or_(
                pc.not_equal(pc.month(table["date"]), 1),
                pc.not_equal(pc.day(table["date"]), 1),
            )
        ).as_py():
            raise ValueError("Annual source dates must retain January 1 year labels")
        years = pc.year(table["date"])
        if (
            "OBSERVATION_YEAR" in table.column_names
            and pc.any(pc.not_equal(years, table["OBSERVATION_YEAR"])).as_py()
        ):
            raise ValueError("Annual labels disagree with native observation years")
        upper = request.end_exclusive.year + (
            request.end_exclusive.month != 1 or request.end_exclusive.day != 1
        )
        keep = pc.and_(
            pc.greater_equal(years, request.start.year), pc.less(years, upper)
        )
        selected = table.filter(keep)
        labels = sorted(pc.unique(selected["date"]).to_pylist())
        periods = [(label, date(label.year + 1, 1, 1)) for label in labels]
    elif precision in {"day", "daily"}:
        selected = table.filter(
            pc.and_(
                pc.greater_equal(table["date"], pa.scalar(request.start)),
                pc.less(table["date"], pa.scalar(request.end_exclusive)),
            )
        )
        periods = [
            (label, label + timedelta(days=1))
            for label in sorted(pc.unique(selected["date"]).to_pylist())
        ]
    elif precision in {"composite", "multi_year_composite"}:
        start_col, end_col = (
            temporal.get("start_column"),
            temporal.get("end_exclusive_column"),
        )
        if not start_col or not end_col or start_col == end_col:
            raise ValueError(
                "Composite support requires distinct start/end interval columns"
            )
        for column in (start_col, end_col):
            if (
                column not in table.column_names
                or not pa.types.is_date32(table[column].type)
                or table[column].null_count
            ):
                raise ValueError(
                    "Composite support requires non-null date32 interval columns"
                )
        if pc.any(pc.greater_equal(table[start_col], table[end_col])).as_py():
            raise ValueError("Composite support intervals must be positive")
        if pc.any(pc.not_equal(table["date"], table[start_col])).as_py():
            raise ValueError("Composite date labels must retain the interval start")
        selected = table.filter(
            pc.and_(
                pc.greater(table[end_col], pa.scalar(request.start)),
                pc.less(table[start_col], pa.scalar(request.end_exclusive)),
            )
        )
        pairs = (
            selected.select([start_col, end_col])
            .group_by([start_col, end_col])
            .aggregate([])
            .to_pylist()
        )
        periods = sorted((row[start_col], row[end_col]) for row in pairs)
    else:
        raise ValueError("Dynamic temporal precision is undocumented or unsupported")
    return selected, periods, str(precision)


def export_history(
    *,
    study_config: str | Path,
    input_dir: str | Path,
    output_dir: str | Path,
    report_path: str | Path | None = None,
    overwrite: bool = False,
    require_known_availability: bool = False,
) -> HistoricalExport:
    """Extract existing evidence; this never acquires sources or certifies model readiness."""
    request = HistoricalRequest.from_study(study_config)
    source = Path(input_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    report_dest = (
        Path(report_path).expanduser().resolve()
        if report_path
        else output.parent / "historical-coverage.json"
    )
    if (
        output == source
        or output.is_relative_to(source)
        or source.is_relative_to(output)
    ):
        raise ValueError("Historical output must be separate from the source tree")
    if report_dest.is_relative_to(output) or report_dest.is_relative_to(source):
        raise ValueError(
            "Place the historical report outside flat input/output directories"
        )
    if not overwrite and (
        (output.exists() and any(output.iterdir())) or report_dest.exists()
    ):
        raise FileExistsError(
            "Historical output/report exists; inspect it before --overwrite"
        )
    areas = list_areas(output=source)
    catalog = json.loads((source / "catalog.json").read_text())
    requested_years = list(
        range(request.start.year, (request.end_exclusive - timedelta(days=1)).year + 1)
    )
    reports, hashes, selected_areas = [], {}, {}
    for area in areas:
        variants: dict[str, list[pa.Table]] = {"static": [], "dynamic": []}
        variant_fields: dict[str, dict[str, Any]] = {"static": {}, "dynamic": {}}
        variant_contexts: dict[str, dict[str, Any]] = {"static": {}, "dynamic": {}}
        for kind in ("static", "dynamic"):
            for resolution, filename in sorted(catalog[area].get(kind, {}).items()):
                path = source / filename
                hashes[filename] = _digest(path)
                table = pq.read_table(path)
                context = json.loads(
                    (table.schema.metadata or {}).get(METADATA_KEY, b"{}")
                )
                known_availability = context.get("availability_known") is True
                if require_known_availability and not known_availability:
                    raise ValueError(
                        f"Historical source availability is unknown: {filename}"
                    )
                rows_before = table.num_rows
                periods: list[tuple[date, date]] = []
                precision = "static_reference"
                if kind == "dynamic":
                    table, periods, precision = _select_dynamic(table, context, request)
                years = [
                    year
                    for year in requested_years
                    if any(
                        start < date(year + 1, 1, 1) and end > date(year, 1, 1)
                        for start, end in periods
                    )
                ]
                detail = {
                    "area": area,
                    "kind": kind,
                    "resolution": int(resolution),
                    "source_file": filename,
                    "source_sha256": hashes[filename],
                    "input_rows": rows_before,
                    "output_rows": table.num_rows,
                    "temporal_precision": precision,
                    "native_source_periods": [
                        {"start": s.isoformat(), "end_exclusive": e.isoformat()}
                        for s, e in periods
                    ],
                    "years_with_source_time_support": years
                    if kind == "dynamic"
                    else None,
                    "requested_years_without_source_time_support": [
                        y for y in requested_years if y not in years
                    ]
                    if kind == "dynamic"
                    else None,
                    "coverage_interpretation": "Source time support only; never evidence of complete spatial survey coverage",
                    "historical_availability": "known"
                    if known_availability
                    else "unknown_retrospective_only",
                    "role": "static_reference_context_not_historical_observations"
                    if kind == "static"
                    else "native_dated_evidence",
                    "inherited_limits": context.get("limits", {}),
                }
                reports.append(detail)
                if not table.num_rows:
                    continue
                context["historical_request"] = request.metadata()
                context["historical_extraction"] = detail
                context["input_last_updated_utc"] = context.get("last_updated_utc")
                table = table.replace_schema_metadata(
                    {
                        **(table.schema.metadata or {}),
                        METADATA_KEY: json.dumps(context, sort_keys=True).encode(),
                    }
                )
                variants[kind].append(table)
                variant_contexts[kind][str(resolution)] = context
                for field, definition in context.get("fields", {}).items():
                    variant_fields[kind].setdefault(field, {}).update(
                        {str(resolution): definition.get(str(resolution), definition)}
                    )
        combined = {}
        for kind, tables in variants.items():
            if tables:
                joined = pa.concat_tables(tables, promote_options="permissive")
                # One combined table is split by the existing flat writer. Preserve
                # per-resolution source context rather than inheriting the first schema.
                context = {
                    "fields": variant_fields[kind],
                    "resolution_contexts": variant_contexts[kind],
                    "historical_request": request.metadata(),
                    "availability_known": all(
                        c.get("availability_known") is True
                        for c in variant_contexts[kind].values()
                    ),
                    "limits": {
                        "model_readiness_established": False,
                        "operational_historical_replay_established": False,
                        "source_qualifications": "See resolution_contexts; all source limits retained",
                    },
                }
                for identity_field in (
                    "reporting_mask_file_sha256",
                    "reporting_mask_geometry_sha256",
                ):
                    identities = [
                        c.get(identity_field) for c in variant_contexts[kind].values()
                    ]
                    declared = {value for value in identities if value is not None}
                    if len(declared) > 1:
                        raise ValueError(
                            "Historical variants use different reporting mask identities"
                        )
                    if declared and all(value is not None for value in identities):
                        context[identity_field] = identities[0]
                if kind == "dynamic":
                    temporal = [
                        c.get("temporal_support", {})
                        for c in variant_contexts[kind].values()
                    ]
                    if any(t != temporal[0] for t in temporal):
                        raise ValueError(
                            "Temporal support differs between native resolution variants"
                        )
                    context["temporal_support"] = temporal[0]
                combined[kind] = joined.replace_schema_metadata(
                    {METADATA_KEY: json.dumps(context, sort_keys=True).encode()}
                )
        if combined:
            selected_areas[area] = AreaTables(**combined)
    if not selected_areas:
        raise ValueError("No source evidence intersects the historical request")
    for filename, expected in hashes.items():
        if _digest(source / filename) != expected:
            raise ValueError(f"Concurrent historical source change: {filename}")
    report = {
        "status": "extracted_with_source_qualifications",
        "request": request.metadata(),
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(source),
        "output_dir": str(output),
        "variants": reports,
        "source_hashes": hashes,
        "static_layers_backdated": False,
        "missing_years_filled": False,
        "daily_expansion": False,
        "model_readiness_established": False,
        "operational_historical_replay_established": False,
    }
    report_dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_dest.with_suffix(report_dest.suffix + ".part")
    try:
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        # Historical exports are complete snapshots. Reusing the flat writer's
        # output lock prevents a concurrent writer, and a fresh stage removes
        # areas that no longer intersect a changed request on --overwrite.
        with TransactionalFamilyPublisher(_io_root(output)) as writer:
            staged = writer.stage_path(output)
            write_areas(selected_areas, output=staged)
            _copy_research_tree(output, staged)
            writer.publish()
        temporary.replace(report_dest)
    finally:
        temporary.unlink(missing_ok=True)
    return HistoricalExport(output, report_dest, report)


def add_history_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--study-config", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--require-known-availability", action="store_true")


def run_history_cli(args: argparse.Namespace) -> int:
    result = export_history(
        study_config=args.study_config,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        report_path=args.report,
        overwrite=args.overwrite,
        require_known_availability=args.require_known_availability,
    )
    print(
        json.dumps(
            {
                "output_dir": str(result.output_dir),
                "report": str(result.report_path),
                "status": result.report["status"],
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_history_arguments(parser)
    return run_history_cli(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
