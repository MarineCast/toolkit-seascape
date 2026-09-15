"""Generate the checkable seascape product and variable index from the unified catalog."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from seascape.core.config.paths import project_root

DEFAULT_CATALOG = Path("config/feature_catalog.yaml")
DEFAULT_README = Path("docs/products.md")
START_MARKER = "<!-- BEGIN GENERATED SEASCAPE PRODUCT INDEX -->"
END_MARKER = "<!-- END GENERATED SEASCAPE PRODUCT INDEX -->"
FAMILY_ORDER = (
    ("spatial_support", "Spatial support"),
    ("seafloor_physiography", "Seafloor physiography"),
    ("coastal_configuration", "Coastal configuration"),
    ("hydrologic_connectivity", "Hydrologic connectivity"),
    ("benthic_substrate", "Benthic substrate"),
    ("biogenic_habitat", "Biogenic habitat"),
    ("anthropogenic", "Anthropogenic"),
)


def _markdown_cell(value: Any) -> str:
    """Escape catalog text for a single Markdown table cell."""

    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _family_key(product_id: str, product: Mapping[str, Any]) -> str:
    """Route one detailed product category to a README architecture family."""

    category = str(product.get("category", ""))
    for family, _label in FAMILY_ORDER:
        if category == family or category.startswith(f"{family}_"):
            return family
    raise ValueError(f"Seascape product {product_id!r} has an undocumented category {category!r}.")


def _render_collection_paths(collection_paths: Any) -> str:
    """Render exact resolution-specific collection paths in one table cell."""

    if not isinstance(collection_paths, Mapping) or not collection_paths:
        return "—"
    return "<br>".join(
        f"R{int(resolution)}: `{_markdown_cell(path)}`"
        for resolution, path in sorted(collection_paths.items(), key=lambda item: int(item[0]))
    )


def _unit_label(unit: Any) -> str | None:
    """Return a compact human-readable unit label when one is encoded."""

    raw = str(unit or "")
    if raw in {"", "not_encoded"}:
        return None
    return {
        "category_or_text": "category/text",
        "count_per_km2": "count/km²",
        "m2": "m²",
        "km2": "km²",
        "m_per_km2": "m/km²",
    }.get(raw, raw.replace("_", " "))


def _short_description(
    feature: Mapping[str, Any],
    role_descriptions: Mapping[str, Any],
) -> str:
    """Summarize the governed field role and encoded unit."""

    role = str(feature.get("role", "unknown"))
    description = str(
        role_descriptions.get(role, f"{role.replace('_', ' ').capitalize()} field.")
    ).rstrip(".")
    unit = _unit_label(feature.get("unit"))
    if unit is not None:
        description += f"; unit: {unit}"
    topology = str(feature.get("topology", ""))
    if topology and topology != "within_cell_or_nonspatial":
        description += f"; topology: {topology.replace('_', ' ')}"
    return _markdown_cell(description + ".")


def _seascape_products(catalog: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    products = catalog.get("products")
    if not isinstance(products, Mapping):
        raise ValueError("Environment feature catalog has no products mapping.")
    selected = [
        (str(product_id), product)
        for product_id, product in products.items()
        if isinstance(product, Mapping) and product.get("metric_family") == "seascape"
    ]
    if not selected:
        raise ValueError("Environment feature catalog contains no seascape products.")
    return sorted(selected, key=lambda item: (str(item[1].get("metric_subfamily")), item[0]))


def render_product_index(catalog: Mapping[str, Any]) -> str:
    """Render product summary and per-family variable dictionaries as Markdown."""

    lines = [
        START_MARKER,
        "### Product summary",
        "",
        "| Product | Family | Resolution | Fields | Status |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    products = _seascape_products(catalog)
    for product_id, product in products:
        collection = product.get("collection", {})
        resolutions = collection.get("resolutions", []) if isinstance(collection, Mapping) else []
        rendered_resolutions = ", ".join(f"R{int(value)}" for value in resolutions) or "native"
        feature_count = int(product.get("feature_count", len(product.get("features", {}))))
        lines.append(
            "| `{product}` | `{family}` | {resolutions} | {features} | Materialized |".format(
                product=product_id,
                family=product.get("metric_subfamily", "unknown"),
                resolutions=rendered_resolutions,
                features=feature_count,
            )
        )

    contract = catalog.get("catalog_contract", {})
    role_descriptions = contract.get("roles", {}) if isinstance(contract, Mapping) else {}
    if not isinstance(role_descriptions, Mapping):
        role_descriptions = {}
    grouped: dict[str, list[tuple[str, Mapping[str, Any]]]] = {
        family: [] for family, _label in FAMILY_ORDER
    }
    for product_id, product in products:
        grouped[_family_key(product_id, product)].append((product_id, product))

    lines.extend(
        [
            "",
            "### Family variable tables",
            "",
            "Every cataloged non-key field is listed, including model variables, coverage,",
            "evidence, support, and QC fields. Paths are the exact collection contracts for",
            "each materialized resolution.",
        ]
    )
    for family, label in FAMILY_ORDER:
        family_products = grouped[family]
        if not family_products:
            continue
        lines.extend(
            [
                "",
                f"#### {label}",
                "",
                "| Sub-family | Variable | Short description | Path | Column |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for product_id, product in sorted(family_products):
            features = product.get("features", {})
            if not isinstance(features, Mapping):
                raise ValueError(f"Seascape product {product_id!r} has no features mapping.")
            subfamily = (
                f"{_markdown_cell(product.get('common_name', product_id))} "
                f"(`{_markdown_cell(product_id)}`)"
            )
            for catalog_column, feature in sorted(features.items()):
                if not isinstance(feature, Mapping):
                    raise ValueError(
                        f"Seascape feature {product_id}.{catalog_column} is not a mapping."
                    )
                variable = _markdown_cell(feature.get("common_name", catalog_column))
                description = _short_description(feature, role_descriptions)
                paths = _render_collection_paths(feature.get("collection_paths"))
                column = _markdown_cell(feature.get("column", catalog_column))
                lines.append(f"| {subfamily} | {variable} | {description} | {paths} | `{column}` |")
    lines.append(END_MARKER)
    return "\n".join(lines)


def update_readme(document: str, generated: str) -> str:
    """Replace exactly one generated-index region in a README document."""

    if document.count(START_MARKER) != 1 or document.count(END_MARKER) != 1:
        raise ValueError("Seascape README must contain exactly one generated index marker pair.")
    before, remainder = document.split(START_MARKER, 1)
    _, after = remainder.split(END_MARKER, 1)
    return before + generated + after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--readme", default=str(DEFAULT_README))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = project_root()
    catalog_path = (root / args.catalog).resolve()
    readme_path = (root / args.readme).resolve()
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    current = readme_path.read_text(encoding="utf-8")
    expected = update_readme(current, render_product_index(catalog))
    if args.check:
        if current != expected:
            raise SystemExit(
                "Generated seascape product and variable index is stale; "
                "run scripts/update_seascape_docs.py."
            )
        print(f"Seascape documentation is current: {readme_path}")
        return 0
    readme_path.write_text(expected, encoding="utf-8")
    print(f"Updated seascape product and variable index: {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
