from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from seascape.hydrologic_connectivity.fluvial_connectivity import (
    build as fluvial,
)


def test_fluvial_mouth_attachment_retains_connector_lineage(monkeypatch) -> None:
    mouths = gpd.GeoDataFrame(
        {"FLUVIAL_MOUTH_ID": ["mouth"]},
        geometry=[Point(-123.0, 48.5)],
        crs="EPSG:4326",
    )
    graph = SimpleNamespace(cell_to_position={"graph-cell": 4})
    config = SimpleNamespace(
        projected_crs="EPSG:32610",
        mouth_coast_tolerance_m=500.0,
        mouth_graph_snap_max_km=2.0,
    )
    captured = {}

    def fake_attachment(_graph, longitudes, latitudes, _water, **kwargs):
        captured["longitude"] = float(longitudes[0])
        captured["latitude"] = float(latitudes[0])
        captured.update(kwargs)
        return pd.DataFrame(
            {
                "GRAPH_H3_INDEX": ["graph-cell"],
                "GRAPH_CONNECTOR_DISTANCE_M": [125.0],
                "SOURCE_TO_WATER_DISTANCE_M": [5.0],
                "WATER_PATH_FRACTION": [1.0],
                "QC_REASON": [None],
            }
        )

    monkeypatch.setattr(fluvial, "attach_points_to_graph", fake_attachment)

    attached = fluvial._snap_mouths_to_graph(mouths, graph, object(), config)

    assert attached.loc[0, "_GRAPH_INDEX"] == 4
    assert attached.loc[0, "GRAPH_SNAP_DISTANCE_M"] == 125.0
    assert attached.loc[0, "GRAPH_CONNECTOR_WATER_PATH_FRACTION"] == 1.0
    assert captured["source_water_max_distance_m"] == 500.0
    assert captured["graph_connector_max_distance_m"] == 2_000.0
