from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from seascape import release


def _product(family: str, resolution: int, path: str, feature_count: int = 1) -> dict:
    return {
        "metric_family": family,
        "feature_count": feature_count,
        "features": {"VALUE": {}},
        "collection": {"paths": {resolution: path}},
    }


def test_catalog_table_audit_excludes_non_seascape_products(monkeypatch, tmp_path) -> None:
    reads: list[Path] = []

    def fake_read(path: Path, **_kwargs) -> pd.DataFrame:
        if "H3_MODEL_AREA_SUPPORT" not in str(path):
            reads.append(path)
        return pd.DataFrame({"H3_INDEX": ["marine"], "VALUE": [1.0]})

    monkeypatch.setattr(release.pd, "read_parquet", fake_read)
    catalog = {
        "products": {
            "seascape": _product("seascape", 8, "seascape.parquet"),
            "weather_r4": _product("meteorological", 4, "weather-r4.parquet"),
            "weather_r5": _product("meteorological", 5, "weather-r5.parquet"),
        }
    }

    results = release._catalog_table_audit(tmp_path, catalog)

    assert [(item["product"], item["resolution"]) for item in results] == [("seascape", 8)]
    assert reads == [tmp_path / "seascape.parquet"]


def test_catalog_table_audit_rejects_unexpected_seascape_resolution(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        release.pd,
        "read_parquet",
        lambda *_args, **_kwargs: pd.DataFrame({"H3_INDEX": ["marine"]}),
    )
    catalog = {"products": {"bad": _product("seascape", 7, "bad.parquet")}}

    with pytest.raises(ValueError, match="supports only R6 and R8"):
        release._catalog_table_audit(tmp_path, catalog)


def test_release_counts_only_seascape_catalog_entries(monkeypatch, tmp_path) -> None:
    catalog = {
        "product_count": 3,
        "feature_entry_count": 99,
        "products": {
            "marine_a": _product("seascape", 8, "a.parquet", 2),
            "marine_b": _product("seascape", 6, "b.parquet", 3),
            "weather": _product("meteorological", 4, "weather.parquet", 94),
        },
    }
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")
    monkeypatch.setattr(release, "_catalog_table_audit", lambda *_args: [])
    monkeypatch.setattr(release, "_manifest_audit", lambda *_args: {})
    monkeypatch.setattr(release, "_depth_band_audit", lambda *_args: [])
    monkeypatch.setattr(release, "_shoreline_audit", lambda *_args: [])
    monkeypatch.setattr(
        release,
        "_governance_audit",
        lambda *_args: {"model_policy_complete": False},
    )
    monkeypatch.setattr(release, "_radius_operator_audit", lambda *_args: {})

    audit = release.build_release_audit(tmp_path, catalog_path)

    assert audit["catalog_product_count"] == 2
    assert audit["catalog_feature_entry_count"] == 5
