"""The raw store's cloud copy: a Databricks Unity Catalog volume, over the Files API.

    archive = build_raw_archive(settings)              # None unless FS_RAW_ARCHIVE=databricks
    archive_raw(conn, raw_store, archive, now, keep_days)   # the daily `lakehouse` job

Every segment of a finished day (UTC) is uploaded to <volume>/<its path in the raw store>, made
read-only, and recorded with its size in `landing.raw_segments`. A segment that grew after its
upload (a late write) is uploaded again. Local copies older than `keep_days` are deleted once the
recorded size matches, so the store keeps about two weeks of segments on disk; the raw store
reads older payloads back from the volume. Never on the alerting path: an unreachable or
over-quota volume is reported, nothing is pruned, and the next day's run retries.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

import psycopg

from flight_scanner.config import Settings
from flight_scanner.raw_store import RawStore
from flight_scanner.sources.polite_http import HttpResponse, Transport, urllib_transport

KEEP_DAYS = 14
_QUOTA = re.compile(r"quota|resource_exhausted|rate limit", re.IGNORECASE)


class RawArchiveUnavailable(Exception):
    """The archive can't be reached right now (network, 5xx, quota): try again later."""


class RawArchiveError(Exception):
    """The archive refused the request (e.g. a bad token or a missing volume)."""


class RawArchive(Protocol):
    name: str

    def upload(self, rel: str, data: bytes) -> None: ...

    def download(self, rel: str) -> bytes: ...


class DatabricksVolume:
    name = "databricks"

    def __init__(
        self,
        host: str,
        token: str,
        volume: str,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 2,
        request_timeout: float = 120.0,
    ):
        self.host = host.rstrip("/")
        if not self.host.startswith("http"):
            self.host = "https://" + self.host
        self.token = token
        self.volume = volume.rstrip("/")
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self.max_retries = max_retries
        self.request_timeout = request_timeout

    def upload(self, rel: str, data: bytes) -> None:
        path = f"{self.volume}/{rel}"
        self._call("PUT", f"/api/2.0/fs/directories{quote(path.rsplit('/', 1)[0])}")
        self._call("PUT", f"/api/2.0/fs/files{quote(path)}?overwrite=true", data)

    def download(self, rel: str) -> bytes:
        return self._call("GET", f"/api/2.0/fs/files{quote(f'{self.volume}/{rel}')}").body

    def _call(self, method: str, path: str, body: bytes | None = None) -> HttpResponse:
        headers = {"Authorization": f"Bearer {self.token}"}
        if body is not None:
            headers["Content-Type"] = "application/octet-stream"
        url = self.host + path
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                resp = self.transport(method, url, headers, body, self.request_timeout)
            except OSError as e:
                if last:
                    raise RawArchiveUnavailable(f"{method} {path}: {e}") from e
            else:
                text = resp.body[:500].decode("utf-8", "replace")
                if resp.status == 429 or (resp.status >= 400 and _QUOTA.search(text)):
                    raise RawArchiveUnavailable(f"{method} {path}: {resp.status} {text}")
                if resp.status < 400:
                    return resp
                if resp.status < 500:
                    raise RawArchiveError(f"{method} {path}: {resp.status} {text}")
                if last:
                    raise RawArchiveUnavailable(f"{method} {path}: {resp.status}")
            self.sleep(2.0 * 2**attempt)
        raise AssertionError("unreachable")


def build_raw_archive(settings: Settings) -> RawArchive | None:
    """FS_RAW_ARCHIVE=databricks turns the archive on (see .env.example); empty = off."""
    env = settings.env
    kind = env.get("FS_RAW_ARCHIVE", "").strip().lower()
    if not kind:
        return None
    if kind != "databricks":
        raise ValueError(f"unknown FS_RAW_ARCHIVE {kind!r} (expected 'databricks' or empty)")
    missing = [k for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN") if not env.get(k)]
    if missing:
        raise ValueError(f"FS_RAW_ARCHIVE=databricks needs {', '.join(missing)}")
    catalog = env.get("FS_DATABRICKS_CATALOG") or "flight_scanner"
    return DatabricksVolume(
        host=env["DATABRICKS_HOST"],
        token=env["DATABRICKS_TOKEN"],
        volume=env.get("FS_RAW_VOLUME") or f"/Volumes/{catalog}/bronze/raw",
    )


def keep_days(settings: Settings) -> int:
    return int(settings.env.get("FS_RAW_LOCAL_DAYS") or KEEP_DAYS)


@dataclass
class ArchiveReport:
    status: str = "ok"  # ok | unavailable
    uploaded: int = 0
    pruned: int = 0
    detail: str = ""


def archive_raw(
    conn: psycopg.Connection,
    store: RawStore,
    archive: RawArchive,
    now: datetime,
    keep_days: int = KEEP_DAYS,
) -> ArchiveReport:
    report = ArchiveReport()
    today = now.astimezone(UTC).date()
    prune_before = today - timedelta(days=keep_days)
    archived = {
        r["path"]: r["bytes"] for r in conn.execute("SELECT path, bytes FROM landing.raw_segments")
    }
    for segment in sorted(store.root.glob("source=*/date=*/*.gz")):
        day = date.fromisoformat(segment.parent.name.removeprefix("date="))
        if day >= today:  # still being written
            continue
        rel = segment.relative_to(store.root).as_posix()
        size = segment.stat().st_size
        if archived.get(rel) != size:
            try:
                archive.upload(rel, segment.read_bytes())
            except RawArchiveUnavailable as e:
                report.status, report.detail = "unavailable", str(e)
                return report
            segment.chmod(0o444)
            conn.execute(
                """INSERT INTO landing.raw_segments (path, bytes, archived_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (path) DO UPDATE
                   SET bytes = EXCLUDED.bytes, archived_at = EXCLUDED.archived_at""",
                (rel, size, now),
            )
            report.uploaded += 1
        if day < prune_before:
            segment.unlink()
            report.pruned += 1
            if not any(segment.parent.iterdir()):
                segment.parent.rmdir()
    return report
