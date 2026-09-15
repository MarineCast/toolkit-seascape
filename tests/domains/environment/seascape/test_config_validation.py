from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from seascape.core.config.paths import project_root
from seascape.seafloor_physiography.bathymetry.pipeline import (
    load_bathymetry_config,
)
from seascape.spatial_support.water_network.config import (
    load_water_network_config,
)


@pytest.fixture
def seascape_config() -> dict:
    path = project_root() / "config/data/environment_seascape.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "environment_seascape.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda raw: raw["water_network"].update(resolutions=[5]), "exactly H3 r6 and r8"),
        (
            lambda raw: raw["water_network"].update(maximum_neighborhood_hops=0),
            "maximum neighborhood hops must be positive",
        ),
        (
            lambda raw: raw["water_network"].update(minimum_water_fraction=1.1),
            r"must be in \[0, 1\]",
        ),
    ],
)
def test_water_network_rejects_invalid_configuration(
    tmp_path, seascape_config, mutator, message
) -> None:
    payload = deepcopy(seascape_config)
    mutator(payload)
    with pytest.raises(ValueError, match=message):
        load_water_network_config(_write_config(tmp_path, payload))


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("bathymetry_sign", "unsigned", "must be 'positive_down'"),
        ("h3_resolution", 16, "must be between 0 and 15"),
    ],
)
def test_bathymetry_rejects_incompatible_sign_and_resolution(
    tmp_path, seascape_config, key, value, message
) -> None:
    payload = deepcopy(seascape_config)
    payload["bathymetry"]["processing"][key] = value
    with pytest.raises(ValueError, match=message):
        load_bathymetry_config(_write_config(tmp_path, payload))


def test_bathymetry_rejects_missing_required_path(tmp_path, seascape_config) -> None:
    payload = deepcopy(seascape_config)
    del payload["bathymetry"]["processing"]["h3_grid_path_template"]
    with pytest.raises(ValueError, match="Missing required config key"):
        load_bathymetry_config(_write_config(tmp_path, payload))
