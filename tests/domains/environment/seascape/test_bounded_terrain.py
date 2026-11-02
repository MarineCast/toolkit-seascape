"""Chunk boundaries retain the complete dependency halo and strict graph checks."""

from types import SimpleNamespace

import h3
import pandas as pd
import pytest

from seascape.core.artifacts.checksums import checksum_path
from seascape.seafloor_physiography.geomorphometry import bounded
from seascape.seafloor_physiography.geomorphometry.build import (
    _derive_metrics,
    load_geomorphometry_config,
)
from seascape.utils.spatial import water_neighborhood_lookup


def test_bounded_matches_full_and_rejects_nonlocal_corruption(tmp_path, monkeypatch):
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(48.5, -123, 8), 3))
    rows = []
    for a in cells:
        for b in cells:
            hops = h3.grid_distance(a, b)
            if hops <= 4:
                rows.append(
                    dict(
                        SOURCE_H3_INDEX=a,
                        TARGET_H3_INDEX=b,
                        H3_RESOLUTION=8,
                        MINIMUM_HOP_COUNT=hops,
                        NETWORK_DISTANCE_M=hops * 100.0,
                        CONNECTIVITY_STATUS="connected",
                        QC_REASON="",
                        WATER_MASK_VERSION="test",
                        SPATIAL_SUPPORT_VERSION="test",
                    )
                )
    frame = pd.DataFrame(rows)
    path = tmp_path / "neighbors.parquet"
    frame.to_parquet(path, index=False)
    network = SimpleNamespace(
        neighborhood_path=lambda r: path, maximum_neighborhood_hops=4
    )
    monkeypatch.setattr(bounded, "load_water_network_config", lambda _: network)
    monkeypatch.setattr(
        bounded,
        "_manifest",
        lambda _: dict(artifacts=[dict(path=str(path), checksum=checksum_path(path))]),
    )
    monkeypatch.setattr(
        bounded, "load_model_area_support", lambda *a: pd.DataFrame({"H3_INDEX": cells})
    )
    source = pd.DataFrame(
        {
            "H3_INDEX": cells,
            "BATHYMETRY": [30.0 + (i % 7) ** 2 for i in range(len(cells))],
        }
    )
    cfg = load_geomorphometry_config()
    lookups = {n: water_neighborhood_lookup(frame, maximum_hops=n) for n in (1, 2, 4)}
    expected = (
        _derive_metrics(source, cfg, lookups)
        .sort_values("H3_INDEX")
        .reset_index(drop=True)
    )
    actual = bounded.derive_bounded(source, cfg, "unused", chunk_size=5)
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    frame.loc[frame.index[-1], "NETWORK_DISTANCE_M"] = -1
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="nonnegative"):
        bounded.derive_bounded(source, cfg, "unused", chunk_size=5)
