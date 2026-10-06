"""Offline transfer/security checks; synthetic pixels never qualify real GEBCO."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from seascape.seafloor_physiography.bathymetry import subset_acquisition as acquisition


class Raw:
    def __init__(self, body):
        self.stream = io.BytesIO(body)
        self.requested = []
        self.received = 0

    def read(self, size, *, decode_content):
        assert decode_content is False
        self.requested.append(size)
        value = self.stream.read(size)
        self.received += len(value)
        return value


class Response:
    def __init__(self, body, *, status=200, headers=None, length=True):
        self.status_code = status
        self.headers = {} if headers is None else dict(headers)
        if length:
            self.headers.setdefault("Content-Length", str(len(body)))
        self.raw = Raw(body)
        self.closed = False

    def close(self):
        self.closed = True


def response_json(value, **kwargs):
    return Response(json.dumps(value).encode(), **kwargs)


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        assert kwargs["headers"]["Accept-Encoding"] == "identity"
        assert 0 < kwargs["timeout"] <= 60
        return self.responses.pop(0)


@pytest.fixture
def template(tmp_path):
    path = tmp_path / "subset-request.template.json"
    path.write_text(
        json.dumps(
            {
                "id": "0",
                "email": None,
                "submission_date": "REPLACE_WITH_ACTUAL_UTC_AT_SUBMISSION",
                "processing_status": "new",
                "items": [
                    {
                        "id": 0,
                        "grid_id": 1,
                        "data_source_ids": [1],
                        "formats": [2],
                        "left": -131.0,
                        "right": -120.2,
                        "top": 52.3,
                        "bottom": 45.1,
                    }
                ],
            }
        )
    )
    return path


@pytest.fixture(scope="module")
def native_tif(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-native") / "native.tif"
    # Native dimensions/grid, explicitly synthetic zero pixels; no scientific compute.
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2592,
        height=1728,
        count=1,
        dtype="int16",
        crs="EPSG:4326",
        transform=from_origin(-131, 52.3, 1 / 240, 1 / 240),
        nodata=-32767,
        compress="DEFLATE",
    ) as raster:
        raster.write(np.zeros((1728, 2592), dtype="int16"), 1)
        raster.set_band_unit(1, "m")
    return path


def zipped(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return out.getvalue()


def catalogs():
    return [
        response_json(
            [
                {
                    "id": 1,
                    "name": "gebco_2026_global",
                    "projection": "EPSG:4326",
                    "description": "Global 15 arc-second elevation in meters. Published April 2026.",
                    "data_sources": [{"id": 1, "name": "gebco_2026"}],
                }
            ]
        ),
        response_json([{"id": 2, "name": "geotiff", "category": "Data"}]),
    ]


def session_for(archive):
    return Session(
        [
            *catalogs(),
            response_json({"basketId": "offline-basket"}),
            response_json({"status": "finished"}),
            Response(archive),
        ]
    )


def run(template, tmp_path, session, **kwargs):
    return acquisition.acquire_bounded_gebco_subset(
        template, tmp_path / "owned", _session=session, **kwargs
    )


def failure(tmp_path):
    generations = list((tmp_path / "owned" / "gebco-subset-acquisitions").iterdir())
    assert len(generations) == 1
    return generations[0], json.loads(
        (generations[0] / "failure-receipt.json").read_bytes()
    )


def test_success_retains_exact_bytes_request_receipt_and_nonqualification(
    template, tmp_path, native_tif
):
    archive = zipped(
        [("subset/native.tif", native_tif.read_bytes()), ("readme.txt", b"fixture")]
    )
    session = session_for(archive)
    result = run(template, tmp_path, session)
    generation = Path(result["generation"])
    assert (generation / "source.zip").read_bytes() == archive
    assert (
        generation / "GEBCO_2026_ELEVATION_NATIVE_EXTENT.tif"
    ).read_bytes() == native_tif.read_bytes()
    assert (
        result["archive"]["archive_raw_sha256"] == hashlib.sha256(archive).hexdigest()
    )
    assert (
        result["archive"]["member_raw_sha256"]
        == hashlib.sha256(native_tif.read_bytes()).hexdigest()
    )
    assert result["native_header"]["width"] == 2592
    assert result["native_header"]["height"] == 1728
    assert result["native_header"]["band_units"] == "m"
    assert result["native_header"]["pixel_decode_performed"] is False
    assert result["observation_period"] is None
    assert (
        result["production_ready"]
        is result["regional_release_eligible"]
        is result["artifact_release_passed"]
        is False
    )
    assert result["resources"]["workers"] == 1
    assert result["resources"]["total_body_bytes"] <= 64 * 1024**2
    for name, digest in result["inventory_raw_sha256"].items():
        assert hashlib.sha256((generation / name).read_bytes()).hexdigest() == digest
    posts = [c for c in session.calls if c[0] == "POST"]
    assert len(posts) == 1
    payload = json.loads(posts[0][2]["data"])
    assert payload["email"] is None
    assert payload["submission_date"] != "REPLACE_WITH_ACTUAL_UTC_AT_SUBMISSION"
    assert payload["items"] == json.loads(template.read_bytes())["items"]
    assert (generation / "acquisition-receipt.json").is_file()
    # Another invocation uses another generation, preserving earlier bytes.
    second = run(template, tmp_path, session_for(archive))
    assert second["generation"] != result["generation"]
    assert (generation / "source.zip").read_bytes() == archive


@pytest.mark.parametrize(
    "change",
    [{"left": -180.0}, {"data_source_ids": [1, 3]}, {"formats": [1]}, {"grid_id": 2}],
)
def test_other_extent_source_or_format_rejected_before_network(
    template, tmp_path, change
):
    value = json.loads(template.read_bytes())
    value["items"][0].update(change)
    template.write_text(json.dumps(value))
    session = Session([])
    with pytest.raises(acquisition.SubsetAcquisitionError, match="exact accepted"):
        run(template, tmp_path, session)
    assert not session.calls
    assert not (tmp_path / "owned").exists()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"headers": {"Content-Length": str(65 * 1024**2)}}, "transfer"),
        (
            {"status": 302, "headers": {"Location": "https://elsewhere/global.zip"}},
            "redirect",
        ),
        ({"headers": {"Content-Encoding": "gzip"}}, "transport"),
        ({"headers": {"Content-Length": "x"}}, "Content-Length"),
    ],
)
def test_archive_refused_before_body_read(template, tmp_path, kwargs, match):
    session = session_for(b"zip")
    response = Response(b"zip", **kwargs)
    session.responses[-1] = response
    with pytest.raises(acquisition.SubsetAcquisitionError, match=match):
        run(template, tmp_path, session)
    assert response.raw.received == 0 and response.closed
    generation, receipt = failure(tmp_path)
    assert not (generation / "source.zip").exists()
    assert receipt["no_automatic_resubmission"] is True
    assert sum(c[0] == "POST" for c in session.calls) == 1


def test_unknown_length_stops_without_one_extra_byte(template, tmp_path):
    response = Response(b"x" * 10000, length=False)
    session = session_for(b"")
    session.responses[-1] = response
    with pytest.raises(acquisition.SubsetAcquisitionError, match="Unknown-size"):
        run(
            template,
            tmp_path,
            session,
            budget=acquisition.SubsetBudget(transfer_bytes=3000),
        )
    generation, receipt = failure(tmp_path)
    assert receipt["resources"]["total_body_bytes"] == 3000
    assert response.raw.received < 10000
    assert (generation / "source.zip").stat().st_size == response.raw.received


def test_truncated_body_retained_without_resubmission(template, tmp_path):
    session = session_for(b"")
    session.responses[-1] = Response(b"partial", headers={"Content-Length": "20"})
    with pytest.raises(acquisition.SubsetAcquisitionError, match="Truncated"):
        run(template, tmp_path, session)
    generation, _ = failure(tmp_path)
    assert (generation / "source.zip").read_bytes() == b"partial"
    assert sum(c[0] == "POST" for c in session.calls) == 1


@pytest.mark.parametrize(
    "name",
    [
        "../evil.tif",
        "/absolute.tif",
        "folder\\evil.tif",
        "C:/evil.tif",
        "folder/./evil.tif",
    ],
)
def test_archive_paths_rejected_and_zip_retained(template, tmp_path, name, native_tif):
    archive = zipped([(name, native_tif.read_bytes())])
    session = session_for(archive)
    with pytest.raises(acquisition.SubsetAcquisitionError, match="Unsafe"):
        run(template, tmp_path, session)
    generation, _ = failure(tmp_path)
    assert (generation / "source.zip").read_bytes() == archive
    assert not (generation / "GEBCO_2026_ELEVATION_NATIVE_EXTENT.tif").exists()


@pytest.mark.parametrize(
    "kind", ["symlink", "two_tiffs", "duplicate", "too_many", "not_zip"]
)
def test_archive_structure_rejected(template, tmp_path, kind):
    if kind == "symlink":
        info = zipfile.ZipInfo("native.tif")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        members = [(info, b"target")]
    elif kind == "two_tiffs":
        members = [("a.tif", b"a"), ("b.tif", b"b")]
    elif kind == "duplicate":
        members = [("a.tif", b"a"), ("a.tif", b"b")]
    else:
        members = [(f"{n}.txt", b"a") for n in range(129)]
    archive = b"notzip" if kind == "not_zip" else zipped(members)
    with pytest.raises(acquisition.SubsetAcquisitionError):
        run(template, tmp_path, session_for(archive))
    generation, _ = failure(tmp_path)
    assert (generation / "source.zip").read_bytes() == archive


def test_member_size_and_staging_refused_before_extraction(
    template, tmp_path, native_tif, monkeypatch
):
    original = zipfile.ZipFile.infolist

    def oversized(self):
        members = original(self)
        members[0].file_size = 33 * 1024**2
        return members

    monkeypatch.setattr(zipfile.ZipFile, "infolist", oversized)
    with pytest.raises(acquisition.SubsetAcquisitionError, match="32MiB"):
        run(
            template,
            tmp_path,
            session_for(zipped([("native.tif", native_tif.read_bytes())])),
        )
    generation, _ = failure(tmp_path)
    assert not (generation / "GEBCO_2026_ELEVATION_NATIVE_EXTENT.tif").exists()


def test_stage_reservation_refuses_incoming_archive(template, tmp_path):
    session = session_for(b"x" * 20000)
    with pytest.raises(acquisition.SubsetAcquisitionError, match="staging"):
        run(
            template,
            tmp_path,
            session,
            budget=acquisition.SubsetBudget(staging_bytes=80000),
        )
    generation, _ = failure(tmp_path)
    assert not (generation / "source.zip").exists()
    assert sum(p.stat().st_size for p in generation.iterdir()) <= 80000


@pytest.mark.parametrize("units", ["ft", "unknown"])
def test_header_units_rejected_after_retaining_zip(
    template, tmp_path, native_tif, units
):
    changed = tmp_path / "changed.tif"
    changed.write_bytes(native_tif.read_bytes())
    with rasterio.open(changed, "r+") as raster:
        raster.set_band_unit(1, units)
    archive = zipped([("native.tif", changed.read_bytes())])
    with pytest.raises(ValueError, match="unit"):
        run(template, tmp_path, session_for(archive))
    generation, _ = failure(tmp_path)
    assert (generation / "source.zip").read_bytes() == archive
    assert not (generation / "acquisition-receipt.json").exists()


@pytest.mark.parametrize("change", ["crs", "affine", "scale", "offset", "shape"])
def test_header_grid_mismatch_rejected(tmp_path, native_tif, change):
    changed = tmp_path / "changed.tif"
    changed.write_bytes(native_tif.read_bytes())
    if change == "shape":
        with rasterio.open(
            changed,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="int16",
            crs="EPSG:4326",
            transform=from_origin(-131, 52.3, 1 / 240, 1 / 240),
        ) as raster:
            raster.write(np.zeros((2, 2), dtype="int16"), 1)
    else:
        with rasterio.open(changed, "r+") as raster:
            if change == "crs":
                raster.crs = "EPSG:4269"
            elif change == "affine":
                raster.transform = from_origin(-131 + 1e-8, 52.3, 1 / 240, 1 / 240)
            elif change == "scale":
                raster.scales = (2,)
            else:
                raster.offsets = (1,)
    with pytest.raises(acquisition.SubsetAcquisitionError, match="native header/grid"):
        acquisition._header(changed, {"description": "meters"})


@pytest.mark.parametrize(
    "response",
    [
        response_json({"account_required": True}),
        Response(b"", status=403),
        response_json({"message": "accept terms"}, status=400),
    ],
)
def test_explicit_account_agreement_stops_and_is_reported(template, tmp_path, response):
    session = Session([response])
    with pytest.raises(acquisition.ProviderAgreementRequired):
        run(template, tmp_path, session)
    _, receipt = failure(tmp_path)
    assert receipt["status"] == "account_or_agreement_required"
    assert not any(c[0] == "POST" for c in session.calls)


def test_changed_catalog_no_post(template, tmp_path):
    session = Session([response_json([{"name": "gebco_2025_global"}]), catalogs()[1]])
    with pytest.raises(acquisition.SubsetAcquisitionError, match="Fresh catalog"):
        run(template, tmp_path, session)
    assert not any(c[0] == "POST" for c in session.calls)


def test_queue_failure_no_resubmit(template, tmp_path):
    session = session_for(b"")
    session.responses[3] = response_json({"status": "failed"})
    with pytest.raises(acquisition.SubsetAcquisitionError, match="queue failed"):
        run(template, tmp_path, session)
    _, receipt = failure(tmp_path)
    assert receipt["basket_id"] == "offline-basket"
    assert sum(c[0] == "POST" for c in session.calls) == 1


def test_time_and_memory_limits_checked_before_network(template, tmp_path, monkeypatch):
    monkeypatch.setattr(
        acquisition.resource,
        "getrusage",
        lambda _: type("Usage", (), {"ru_maxrss": 1024 * 1024 * 1024})(),
    )
    session = Session([])
    with pytest.raises(acquisition.SubsetAcquisitionError, match="RSS/time"):
        run(template, tmp_path, session)
    assert not session.calls
    # An expired cooperative clock is refused before network too.
    monkeypatch.setattr(
        acquisition.resource,
        "getrusage",
        lambda _: type("Usage", (), {"ru_maxrss": 0})(),
    )
    values = iter([0, 2])
    monkeypatch.setattr(acquisition.time, "monotonic", lambda: next(values))
    with pytest.raises(acquisition.SubsetAcquisitionError, match="RSS/time"):
        run(
            template,
            tmp_path,
            session,
            budget=acquisition.SubsetBudget(elapsed_seconds=1),
        )


@pytest.mark.parametrize(
    "field", ["transfer_bytes", "staging_bytes", "memory_bytes", "elapsed_seconds"]
)
def test_budget_cannot_exceed_accepted_ceiling(field):
    with pytest.raises(acquisition.SubsetAcquisitionError):
        acquisition.SubsetBudget(**{field: 10**12})


@pytest.mark.parametrize(
    "response",
    [
        response_json(
            {"message": "Please accept the terms"},
            headers={"Content-Type": "application/json"},
        ),
        Response(b"Account required", headers={"Content-Type": "text/html"}),
    ],
)
def test_success_status_archive_agreement_still_stops(template, tmp_path, response):
    session = session_for(b"")
    session.responses[-1] = response
    with pytest.raises(acquisition.ProviderAgreementRequired):
        run(template, tmp_path, session)
    generation, receipt = failure(tmp_path)
    assert receipt["status"] == "account_or_agreement_required"
    assert not (generation / "source.zip").exists()
    assert sum(c[0] == "POST" for c in session.calls) == 1


def test_identity_uses_executed_package_not_staging_checkout(
    template, tmp_path, native_tif, monkeypatch
):
    roots = []

    def identity(root):
        roots.append(root)
        return {
            "git_revision": "offline-pin",
            "dirty": False,
            "source_tree_sha256": "fixture",
        }

    monkeypatch.setattr(acquisition, "package_code_identity", identity)
    result = run(
        template,
        tmp_path,
        session_for(zipped([("native.tif", native_tif.read_bytes())])),
    )
    assert roots == [Path(acquisition.__file__).resolve().parent] * 2
    assert result["code_identity"]["git_revision"] == "offline-pin"
