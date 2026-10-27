"""Seam 3: the raw archive on a Databricks volume, through a scripted HTTP transport.

Files API shapes as documented (PUT /api/2.0/fs/directories{path}, PUT/GET
/api/2.0/fs/files{path}); an upload/download round trip was checked once against the live
Free Edition workspace.
"""

from urllib.parse import quote

import pytest

from flight_scanner.config import Settings
from flight_scanner.raw_archive import (
    DatabricksVolume,
    RawArchiveError,
    RawArchiveUnavailable,
    build_raw_archive,
)
from flight_scanner.sources.polite_http import HttpResponse
from flight_scanner.testing.scripted_http import FakeTimer, ScriptedTransport

HOST = "https://adb-123.cloud.databricks.com"
VOLUME = "/Volumes/flight_scanner/bronze/raw"
REL = "source=travelpayouts/date=2026-10-27/090000Z-42.gz"
FILE = quote(f"{VOLUME}/{REL}")  # "=" travels as %3D


def volume(*responses) -> tuple[DatabricksVolume, ScriptedTransport]:
    timer = FakeTimer()
    transport = ScriptedTransport(*responses, timer=timer)
    return DatabricksVolume(HOST, "tok", VOLUME, transport=transport, sleep=timer.sleep), transport


def test_upload_creates_the_folder_then_overwrites_the_file():
    v, t = volume(HttpResponse(204, {}, b""), HttpResponse(204, {}, b""))

    v.upload(REL, b"\x1f\x8bsegment")

    (m1, u1, h1, _, _), (m2, u2, h2, b2, _) = t.calls
    assert (m1, u1) == ("PUT", f"{HOST}/api/2.0/fs/directories" + FILE.rsplit("/", 1)[0])
    assert (m2, u2) == ("PUT", f"{HOST}/api/2.0/fs/files{FILE}?overwrite=true")
    assert b2 == b"\x1f\x8bsegment"
    assert h1["Authorization"] == h2["Authorization"] == "Bearer tok"


def test_download_returns_the_stored_bytes():
    v, t = volume(HttpResponse(200, {}, b"\x1f\x8bsegment"))

    assert v.download(REL) == b"\x1f\x8bsegment"
    assert t.calls[0][:2] == ("GET", f"{HOST}/api/2.0/fs/files{FILE}")


def test_outages_are_retried_then_reported_unavailable():
    v, t = volume(HttpResponse(503, {}, b""), OSError("reset"), HttpResponse(503, {}, b""))

    with pytest.raises(RawArchiveUnavailable):
        v.download(REL)
    assert len(t.calls) == 3


def test_quota_answers_are_unavailable_and_other_client_errors_are_errors():
    v, _ = volume(HttpResponse(429, {}, b"slow down"))
    with pytest.raises(RawArchiveUnavailable):
        v.download(REL)

    v, _ = volume(HttpResponse(403, {}, b"no permission"))
    with pytest.raises(RawArchiveError):
        v.download(REL)


def test_built_from_env_only_when_turned_on():
    base = {"DATABRICKS_HOST": "adb-123.cloud.databricks.com", "DATABRICKS_TOKEN": "tok"}

    assert build_raw_archive(Settings.from_env(base)) is None
    archive = build_raw_archive(Settings.from_env({**base, "FS_RAW_ARCHIVE": "databricks"}))
    assert isinstance(archive, DatabricksVolume)
    assert archive.host == HOST and archive.volume == VOLUME
    with pytest.raises(ValueError, match="DATABRICKS_TOKEN"):
        build_raw_archive(Settings.from_env({"FS_RAW_ARCHIVE": "databricks"}))
