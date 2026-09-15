from __future__ import annotations

import pyarrow.parquet as pq
import pytest
import yaml

from seascape.core.config.paths import project_root

CATALOG_PATH = project_root() / "config/feature_catalog.yaml"
KEY_COLUMNS = {"H3_INDEX", "H3_RESOLUTION"}
METRIC_SUBFAMILIES = {
    "anthropogenic",
    "benthic",
    "coastal_configuration",
    "hydrologic_connectivity",
    "seafloor_physiography",
    "spatial_support",
}


def _catalog() -> dict:
    return yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))


def _all_materialized_catalog_paths_exist() -> bool:
    root = project_root()
    catalog = _catalog()
    paths = [
        root / path
        for product in catalog["products"].values()
        if product["metric_family"] == "seascape"
        for path in product["collection"]["paths"].values()
    ]
    for product in catalog["supporting_products"].values():
        if "path" in product:
            paths.append(root / product["path"])
        else:
            paths.extend(
                root / product["path_template"].format(resolution=resolution)
                for resolution in product["resolutions"]
            )
    return bool(paths) and all(path.exists() for path in paths)


requires_materialized_catalog = pytest.mark.skipif(
    not _all_materialized_catalog_paths_exist(),
    reason="materialized seascape artifacts are not part of a clean checkout",
)


def test_seascape_catalog_has_direct_collection_contract() -> None:
    catalog = _catalog()
    products = {
        product_id: product
        for product_id, product in catalog["products"].items()
        if product["metric_family"] == "seascape"
    }
    assert catalog["schema_version"] == 4
    assert catalog["catalog_id"] == "environment.seascape"
    assert catalog["product_count"] == len(catalog["products"])
    assert catalog["feature_entry_count"] == sum(
        product["feature_count"] for product in catalog["products"].values()
    )
    assert catalog["superseded_products"]["eelgrass"]["replacement"] == "seagrass"
    for product_id, product in products.items():
        assert product["common_name"], product_id
        assert product["metric_family"] == "seascape"
        assert product["metric_subfamily"] in METRIC_SUBFAMILIES
        assert product["collection"]["paths"], product_id
        assert product["features"], product_id
        assert product["feature_count"] == len(product["features"])
        assert product["variable_kind_counts"] == {
            kind: sum(feature["variable_kind"] == kind for feature in product["features"].values())
            for kind in catalog["catalog_contract"]["variable_kinds"]
        }
        for column, feature in product["features"].items():
            assert feature["common_name"], (product_id, column)
            assert feature["metric_family"] == product["metric_family"]
            assert feature["metric_subfamily"] == product["metric_subfamily"]
            assert feature["column"] == column
            assert feature["available_resolutions"]
            assert feature["collection_paths"] == {
                resolution: product["collection"]["paths"][resolution]
                for resolution in feature["available_resolutions"]
            }
            assert feature["role"] in catalog["catalog_contract"]["roles"]
            assert feature["variable_kind"] in catalog["catalog_contract"]["variable_kinds"]
            if feature["role"] in {"coverage", "evidence", "support_or_qc", "identifier"}:
                assert feature["variable_kind"] == "metadata"
    assert all(
        product["variable_kind"] == "metadata"
        for product in catalog["supporting_products"].values()
    )


@requires_materialized_catalog
def test_seascape_catalog_matches_materialized_parquet_schemas() -> None:
    catalog = _catalog()
    root = project_root()
    for product_id, product in catalog["products"].items():
        if product["metric_family"] != "seascape":
            continue
        catalog_columns = set(product["features"])
        observed_union: set[str] = set()
        for resolution, relative_path in product["collection"]["paths"].items():
            path = root / relative_path
            assert path.exists(), (product_id, resolution, path)
            observed = set(pq.read_schema(path).names).difference(KEY_COLUMNS)
            observed_union.update(observed)
            available = {
                column
                for column, feature in product["features"].items()
                if int(resolution) in feature["available_resolutions"]
            }
            assert available == observed, (product_id, resolution)
        assert catalog_columns == observed_union, product_id


@requires_materialized_catalog
def test_supporting_product_paths_resolve() -> None:
    catalog = _catalog()
    root = project_root()
    for product in catalog["supporting_products"].values():
        if "path" in product:
            assert (root / product["path"]).exists()
        else:
            for resolution in product["resolutions"]:
                assert (root / product["path_template"].format(resolution=resolution)).exists()


def test_every_resolution_named_seascape_artifact_is_classified() -> None:
    catalog = _catalog()
    root = project_root()
    seascape_root = root / "data/processed/domain/environmental_layer/seascape"
    classified = {
        str((root / path).resolve())
        for product in catalog["products"].values()
        if product["metric_family"] == "seascape"
        for path in product["collection"]["paths"].values()
    }
    for product in catalog["supporting_products"].values():
        if "path" in product:
            classified.add(str((root / product["path"]).resolve()))
        else:
            classified.update(
                str((root / product["path_template"].format(resolution=resolution)).resolve())
                for resolution in product["resolutions"]
            )
    for product in catalog["superseded_products"].values():
        for key, paths in product.items():
            if key.endswith("_paths"):
                classified.update(str((root / path).resolve()) for path in paths.values())
    observed = {
        str(path.resolve()) for path in seascape_root.rglob("*.parquet") if "_RES_" in path.name
    }
    assert classified.issuperset(observed)
