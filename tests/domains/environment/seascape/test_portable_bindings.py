"""Relocation retains original content identity and rejects ambiguous bindings."""

import pytest

from seascape.core.artifacts.checksums import checksum_path
from seascape.spatial_support.water_network.load import _verify_artifact


def test_relocated_source_preserves_manifest_identity_and_rejects_changed_bytes(
    tmp_path,
):
    target = tmp_path / "retained.bin"
    target.write_bytes(b"scientific source")
    original = "/old/workspace/source.bin"
    payload = {
        "artifacts": [
            {
                "path": original,
                "checksum": checksum_path(target, logical_name="source.bin"),
            }
        ],
        "_source_bindings": {original: str(target)},
    }
    _verify_artifact(target, payload)
    assert payload["artifacts"][0]["path"] == original
    target.write_bytes(b"different vintage")
    with pytest.raises(ValueError, match="checksum"):
        _verify_artifact(target, payload)


def test_same_filename_is_not_identity(tmp_path):
    target = tmp_path / "source.bin"
    target.write_bytes(b"scientific source")
    payload = {
        "artifacts": [
            {
                "path": "/old/source.bin",
                "checksum": checksum_path(target, logical_name="source.bin"),
            }
        ]
    }
    with pytest.raises(ValueError, match="exactly one"):
        _verify_artifact(target, payload)
