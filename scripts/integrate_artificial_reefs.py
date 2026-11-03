"""Integrate reviewed reef coordinates and retained NOAA ESI; no network access."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

import pyarrow.parquet as pq

from seascape.anthropogenic.artificial_reefs import (
    digest,
    enrich_native,
    inventory,
    noaa_sites,
    published_sites,
    reconcile,
)
from seascape.core.artifacts import TransactionalFamilyPublisher
from seascape.domain_parquets import _catalog, _io_root, validate_table
from seascape.reviewed_delivery import restore_native, stage_compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    cache, root, work = (p.resolve() for p in (args.cache, args.delivery, args.work))
    if cache.is_relative_to(root) or work.is_relative_to(root):
        raise ValueError("Source and working evidence must be outside delivery")
    work.mkdir(parents=True, exist_ok=True)
    archive = cache / "PugetSnd_2006_GDB.zip"
    receipt = json.loads((cache / "PugetSnd_2006_GDB.zip.receipt.json").read_text())
    if digest(archive) != receipt["sha256"]:
        raise ValueError("NOAA acquisition checksum mismatch")
    primary, sources = published_sites()
    if digest(cache / "wdfw_2025.pdf") != sources["wdfw"]["sha256"]:
        raise ValueError("WDFW reviewed PDF checksum mismatch")
    noaa = noaa_sites(archive)
    records, checks = reconcile(primary, noaa)
    normalized = inventory(records)
    inventory_path = cache / "ARTIFICIAL_REEF_SOURCE_INVENTORY.parquet"
    # Source evidence is immutable and content-addressed; a later run never
    # silently changes bytes referenced by delivered metadata.
    candidate_inventory = work / "inventory.parquet"
    normalized.to_parquet(candidate_inventory, index=False)
    inventory_path = inventory_path.with_stem(
        inventory_path.stem + "-" + digest(candidate_inventory)[:16]
    )
    if inventory_path.exists():
        if digest(inventory_path) != digest(candidate_inventory):
            raise ValueError("Existing reef source inventory differs")
    else:
        inventory_path.write_bytes(candidate_inventory.read_bytes())
    sources["noaa"] = {
        **receipt,
        "metadata_url": "https://www.fisheries.noaa.gov/inport/item/40620",
        "vintage": "2006 atlas, reef source WDFW 2005",
        "rights": "CC0-1.0",
    }
    evidence = {
        "inventory_path": str(inventory_path),
        "inventory_sha256": digest(inventory_path),
        "transcription_sha256": digest(
            Path(
                str(files("seascape").joinpath("resources/artificial_reef_sites.json"))
            )
        ),
        "sources": sources,
        "cross_checks": checks,
        "tolerance_m": 250,
        "policy": "same-site WDFW preferred; unmatched NOAA contributes; False is not surveyed absence",
    }
    catalog = _catalog(root)
    names = list(catalog["anthropogenic"]["static"].values())
    if set(names) != {f"anthropogenic-r{r}-static.parquet" for r in (6, 8)}:
        raise ValueError("Expected existing R6 and R8 Anthropogenic delivery")
    baseline = {name: digest(root / name) for name in [*names, "catalog.json"]}
    unrelated = {
        str(p.relative_to(root)): digest(p)
        for p in root.rglob("*")
        if p.is_file()
        and str(p.relative_to(root)) not in baseline
        and p.name != ".DS_Store"
    }
    native, reports, input_bindings = {}, [], {}
    for name in names:
        before = pq.read_table(root / name)
        if b"seascape_review" not in (before.schema.metadata or {}):
            raise ValueError(
                "This enrichment requires the current audited compact Anthropogenic contract"
            )
        input_bindings[name] = json.loads(before.schema.metadata[b"seascape_review"])
        original = restore_native(before)
        table, report = enrich_native(original, records, evidence=evidence)
        validate_table(table, dynamic=False)
        native[name] = table
        # A scoped enrichment may change only the reef family and its metadata.
        for column in original.column_names:
            if "ARTIFICIAL_REEF" not in column and not original[column].equals(
                table[column]
            ):
                raise ValueError("Unrelated native field changed: " + column)
        report.update(file=name, before_sha256=baseline[name])
        reports.append(report)
    summary = {
        "checked": "2026-11-01",
        "published": False,
        "sources": sources,
        "source_records": len(records),
        "canonical_sites": int(normalized.IS_CANONICAL.sum()),
        "cross_checks": checks,
        "products": reports,
        "input_audits": input_bindings,
        "inventory": evidence,
        "python": platform.python_version(),
        "code_sha256": digest(Path(__file__)),
        "producer_sha256": digest(
            Path(__file__).parents[1] / "src/seascape/anthropogenic/artificial_reefs.py"
        ),
    }
    # Candidate publication exercises the same audit projection/readback, bounded
    # to the two small Anthropogenic files; no whole-area dataset copies.
    audit_root = work / "audit"
    with TransactionalFamilyPublisher(_io_root(root)) as writer:
        if any(digest(root / n) != checksum for n, checksum in baseline.items()):
            raise ValueError("Concurrent source change before reef publication")
        for name, table in native.items():
            public = stage_compact(
                "anthropogenic", table, audit_root=audit_root, writer=writer
            )
            target = writer.stage_path(root / name if args.publish else work / name)
            pq.write_table(public, target, compression="zstd")
            if not pq.read_table(target).equals(public, check_metadata=True):
                raise ValueError("Reef candidate readback mismatch")
        if args.publish:
            catalog["anthropogenic"]["last_updated_utc"] = datetime.now(
                timezone.utc
            ).isoformat()
            target = writer.stage_path(root / "catalog.json", terminal=True)
            target.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
        writer.publish()
    for name in names:
        path = root / name if args.publish else work / name
        restored = restore_native(pq.read_table(path))
        if not restored.equals(native[name], check_metadata=True):
            raise ValueError("Published reef audit differs from candidate")
    for relative, checksum in unrelated.items():
        if digest(root / relative) != checksum:
            raise ValueError("Unrelated delivery file changed: " + relative)
    summary["published"] = args.publish
    summary["unrelated_files_unchanged"] = len(unrelated)
    summary["output_sha256"] = {
        name: digest((root if args.publish else work) / name) for name in names
    }
    (work / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "published",
                    "source_records",
                    "canonical_sites",
                    "products",
                    "unrelated_files_unchanged",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
