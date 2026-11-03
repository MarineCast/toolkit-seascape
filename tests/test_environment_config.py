"""Dotenv boundaries, geographic overrides, frozen builds and runtime-only credentials."""

import json
import os
import shutil
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from seascape.core.config.common_areas import bbox_for_area
from seascape.core.config.document import ConfigDocument
from seascape.core.config.environment import environment_values
from seascape.utils.habitat_acquisition import _download_http_file
from seascape.workflow import _configuration_identity, _prepare_candidate_config


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("SEASCAPE_ENV_FILE", raising=False)
    for key in tuple(os.environ):
        if key.startswith(
            ("SEASCAPE_MODEL_", "SEASCAPE_EXTENDED_", "SEASCAPE_SOURCE_")
        ):
            monkeypatch.delenv(key)
    (tmp_path / "config").mkdir()
    shutil.copyfile(
        Path(__file__).parents[1] / "config/common.yaml",
        tmp_path / "config/common.yaml",
    )
    return tmp_path


def test_dotenv_precedence_literal_values_and_workspace_isolation(
    workspace, monkeypatch
):
    (workspace / ".env").write_text(
        "export FIXTURE_VALUE=\"value # literal\"\nOTHER_VALUE=foo # comment\nLITERAL_VALUE='$(do-not-run) ${NO_EXPANSION}'\nEMPTY_VALUE=\n"
    )
    before = dict(os.environ)
    values = environment_values()
    assert values["FIXTURE_VALUE"] == "value # literal"
    assert values["OTHER_VALUE"] == "foo"
    assert values["LITERAL_VALUE"] == "$(do-not-run) ${NO_EXPANSION}"
    assert values["EMPTY_VALUE"] == ""
    assert dict(os.environ) == before
    monkeypatch.setenv("FIXTURE_VALUE", "process")
    assert environment_values()["FIXTURE_VALUE"] == "process"
    child = workspace / "child"
    child.mkdir()
    monkeypatch.setenv("SEASCAPE_WORKSPACE", str(child))
    assert "OTHER_VALUE" not in environment_values()
    monkeypatch.setenv("SEASCAPE_ENV_FILE", str(workspace / ".env"))
    assert environment_values()["OTHER_VALUE"] == "foo"


@pytest.mark.parametrize(
    "payload",
    [
        'TOKEN="private-value',
        "TOKEN=private-value extra",
        "TOKEN=private-value\nTOKEN=duplicate",
        "private-value",
    ],
)
def test_dotenv_parse_errors_never_echo_values(workspace, payload):
    (workspace / ".env").write_text(payload)
    with pytest.raises(ValueError) as error:
        environment_values()
    assert "private-value" not in str(error.value)
    assert "line" in str(error.value)


def test_explicit_missing_dotenv_fails(workspace, monkeypatch):
    monkeypatch.setenv("SEASCAPE_ENV_FILE", "missing.env")
    with pytest.raises(FileNotFoundError):
        environment_values()


def test_geographic_defaults_and_reload(workspace):
    assert bbox_for_area("model_area") == dict(
        min_lon=-125.8, min_lat=46.85, max_lon=-121.6, max_lat=50.0
    )
    env = workspace / ".env"
    env.write_text("SEASCAPE_MODEL_MIN_LON=-124\n")
    assert bbox_for_area("model_area")["min_lon"] == -124
    assert bbox_for_area("regional_source_area")["min_lon"] == -180
    env.write_text("SEASCAPE_MODEL_MIN_LON=-123\n")
    assert bbox_for_area("model_area")["min_lon"] == -123


@pytest.mark.parametrize(
    "key,value",
    [
        ("MIN_LON", "nan"),
        ("MIN_LON", "-181"),
        ("MAX_LAT", "91"),
        ("MAX_LAT", "inf"),
        ("MIN_LAT", "51"),
        ("MIN_LON", "invalid"),
        ("MIN_LON", ""),
    ],
)
def test_invalid_geographic_overrides_fail(workspace, key, value):
    (workspace / ".env").write_text(f"SEASCAPE_MODEL_{key}={value}\n")
    with pytest.raises(ValueError):
        bbox_for_area("model_area")


def test_build_freezes_bounds_and_identity_tracks_region_not_unused_token(workspace):
    env = workspace / ".env"
    env.write_text(
        "SEASCAPE_MODEL_MIN_LON=-124\nSEASCAPE_HTTP_BEARER_TOKEN=private-value\n"
    )
    config = workspace / "config/project.yaml"
    config.write_text(
        "base_directory: .\nsource:\n  bearer_token_env: SEASCAPE_HTTP_BEARER_TOKEN\n"
    )
    initial = _configuration_identity(config)
    candidate = workspace / "work"
    frozen = _prepare_candidate_config(
        config, canonical_root=workspace, candidate_root=candidate
    )
    for path in frozen.parent.iterdir():
        assert "private-value" not in path.read_text()
    env.write_text("SEASCAPE_MODEL_MIN_LON=-123\nSEASCAPE_HTTP_BEARER_TOKEN=rotated\n")
    assert initial != _configuration_identity(config)
    assert (
        bbox_for_area("model_area", common_config_path=frozen.parent / "common.yaml")[
            "min_lon"
        ]
        == -124
    )
    env.write_text("SEASCAPE_MODEL_MIN_LON=-124\nSEASCAPE_HTTP_BEARER_TOKEN=rotated\n")
    assert initial == _configuration_identity(config)
    assert (
        ConfigDocument.load(config).data["source"]["bearer_token_env"]
        == "SEASCAPE_HTTP_BEARER_TOKEN"
    )


@pytest.mark.parametrize("failure", [None, "request", "status", "stream"])
def test_http_token_is_request_scoped_and_errors_are_sanitized(workspace, failure):
    (workspace / ".env").write_text("SEASCAPE_HTTP_BEARER_TOKEN=private-value\n")
    calls = []

    def status():
        if failure == "status":
            raise requests.HTTPError("private-value")

    def chunks(**kwargs):
        if failure == "stream":
            raise requests.ConnectionError("private-value")
        yield b"fixture"

    def request(*args, **kwargs):
        calls.append(kwargs)
        if failure == "request":
            raise requests.ConnectionError("private-value")
        return SimpleNamespace(raise_for_status=status, iter_content=chunks, headers={})

    session = SimpleNamespace(request=request, headers={})
    source = {
        "url": "https://example.invalid/input",
        "bearer_token_env": "SEASCAPE_HTTP_BEARER_TOKEN",
    }
    if failure:
        with pytest.raises(RuntimeError) as error:
            _download_http_file(session, source, workspace / "result", timeout=1)
        assert "private-value" not in "".join(traceback.format_exception(error.value))
        assert not (workspace / "result").exists()
    else:
        assert (
            _download_http_file(session, source, workspace / "result", timeout=1) == 7
        )
        _download_http_file(
            session,
            {"url": "https://another.invalid/input"},
            workspace / "public",
            timeout=1,
        )
        assert "headers" not in calls[-1]
    assert calls[0]["headers"] == {"Authorization": "Bearer private-value"}
    assert session.headers == {}
    assert "private-value" not in json.dumps(source)


@pytest.mark.parametrize(
    "url,token",
    [
        ("http://example.invalid/input", "present"),
        ("https://example.invalid/input", ""),
    ],
)
def test_authentication_errors_precede_network(workspace, url, token):
    (workspace / ".env").write_text(f"SEASCAPE_HTTP_BEARER_TOKEN={token}\n")
    with pytest.raises(ValueError):
        _download_http_file(
            None,
            {"url": url, "bearer_token_env": "SEASCAPE_HTTP_BEARER_TOKEN"},
            workspace / "result",
            timeout=1,
        )
