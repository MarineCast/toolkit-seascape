from __future__ import annotations

import runpy
from pathlib import Path


def test_generated_index_filters_and_orders_seascape_products() -> None:
    script = Path(__file__).parents[4] / "scripts" / "update_seascape_docs.py"
    functions = runpy.run_path(str(script))
    catalog = {
        "products": {
            "weather": {"metric_family": "meteorological"},
            "second": {
                "metric_family": "seascape",
                "metric_subfamily": "benthic",
                "category": "biogenic_habitat",
                "common_name": "Second product",
                "feature_count": 2,
                "collection": {"resolutions": [8, 6]},
                "features": {
                    "SECOND_COLUMN": {
                        "common_name": "Second variable",
                        "column": "SECOND_COLUMN",
                        "collection_paths": {6: "second-r6.parquet", 8: "second-r8.parquet"},
                        "unit": "m2",
                        "role": "predictor",
                        "topology": "water_network",
                    }
                },
            },
            "first": {
                "metric_family": "seascape",
                "metric_subfamily": "anthropogenic",
                "category": "anthropogenic",
                "common_name": "First product",
                "feature_count": 1,
                "collection": {"resolutions": [8]},
                "features": {
                    "FIRST_COLUMN": {
                        "common_name": "First variable",
                        "column": "FIRST_COLUMN",
                        "collection_paths": {8: "first.parquet"},
                        "unit": "count",
                        "role": "state",
                    }
                },
            },
        },
        "catalog_contract": {
            "roles": {
                "predictor": "Model-facing numeric covariate.",
                "state": "Presence, absence, reachability, or another explicit state.",
            }
        },
    }

    rendered = functions["render_product_index"](catalog)

    assert "weather" not in rendered
    assert rendered.index("`first`") < rendered.index("`second`")
    assert "R8, R6" in rendered
    assert "#### Biogenic habitat" in rendered
    assert "#### Anthropogenic" in rendered
    assert "| First product (`first`) | First variable |" in rendered
    assert "Presence, absence, reachability, or another explicit state; unit: count." in rendered
    assert "Model-facing numeric covariate; unit: m²; topology: water network." in rendered
    assert "R8: `first.parquet`" in rendered
    assert "`FIRST_COLUMN`" in rendered
