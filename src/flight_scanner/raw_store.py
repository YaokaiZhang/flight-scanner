"""The raw store: every source response, byte-for-byte, append-only, partitioned by source and date.

Layout: <root>/source=<source>/date=<YYYY-MM-DD>/<HHMMSS>Z-<pid>.gz
Each file is a segment: the payloads one process stored that day, each its own gzip member
(mtime 0), appended back to back (concatenated members are still one valid gzip file). One
segment per process and day keeps the store to a couple of files per scan rather than one per
response, which matters under a file-count quota. The manifest row in `landing.raw_payloads`
holds the payload's ref, `source=<s>/date=<d>/<segment>@<offset>:<length>`.

Payloads stored before segments are one gzip file each, referenced by their absolute path;
`pack_loose` moves them into segments. With an archive (raw_archive.py), finished days are
copied to the cloud and pruned locally after a while; `open` then reads the archived copy.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg

from flight_scanner.sources.base import RawPayload, ScanRequest

if TYPE_CHECKING:
    from flight_scanner.raw_archive import RawArchive

_REF = re.compile(r"(?P<file>.+)@(?P<offset>\d+):(?P<length>\d+)")


@dataclass(frozen=True)
class StoredPayload:
    ref: str  # what the manifest stores
    path: Path  # the local file holding it (may have been pruned once archived)
    sha256: str
    body: bytes = field(repr=False)

    def read(self) -> bytes:
        return self.body


class RawStore:
    def __init__(self, root: Path, archive: RawArchive | None = None):
        self.root = Path(root)
        self.archive = archive
        self._segments: dict[tuple[int, Path], Path] = {}  # (pid, partition) -> open segment
        self._fetched: tuple[str, bytes] | None = None  # the last segment read from the archive

    def partition(self, source: str, day: date) -> Path:
        return self.root / f"source={source}" / f"date={day.isoformat()}"

    def put(self, raw: RawPayload) -> StoredPayload:
        member = gzip.compress(raw.body, mtime=0)
        part = self.partition(raw.source, raw.fetched_at.astimezone(UTC).date())
        segment, offset = self._append(part, member)
        rel = segment.relative_to(self.root).as_posix()
        sha = hashlib.sha256(raw.body).hexdigest()
        return StoredPayload(f"{rel}@{offset}:{len(member)}", segment, sha, raw.body)

    def _append(self, part: Path, member: bytes) -> tuple[Path, int]:
        """Append to this process's segment of the partition; a new one if it can't be written
        (an archived segment is read-only). Only one process ever writes a segment."""
        key = (os.getpid(), part)
        for _ in range(2):
            segment = self._segments.get(key)
            if segment is None:
                part.mkdir(parents=True, exist_ok=True)
                segment = part / f"{datetime.now(UTC):%H%M%S}Z-{os.getpid()}.gz"
                self._segments[key] = segment
            try:
                fd = os.open(segment, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            except PermissionError:
                del self._segments[key]
                continue
            try:
                offset = os.fstat(fd).st_size
                view = memoryview(member)
                while view:
                    view = view[os.write(fd, view) :]
            finally:
                os.close(fd)
            return segment, offset
        raise PermissionError(f"cannot write a segment in {part}")

    def open(self, ref: Path | str) -> StoredPayload:
        m = _REF.fullmatch(str(ref))
        name = m["file"] if m else str(ref)
        path = Path(name) if Path(name).is_absolute() else self.root / name
        if m is None:  # a whole file, stored before segments
            data = self._bytes(path, 0, None)
        else:
            data = self._bytes(path, int(m["offset"]), int(m["length"]))
        body = gzip.decompress(data)
        return StoredPayload(str(ref), path, hashlib.sha256(body).hexdigest(), body)

    def _bytes(self, path: Path, offset: int, length: int | None) -> bytes:
        if path.exists():
            with path.open("rb") as f:
                f.seek(offset)
                return f.read() if length is None else f.read(length)
        if self.archive is None:
            raise FileNotFoundError(path)
        rel = path.relative_to(self.root).as_posix()
        if self._fetched is None or self._fetched[0] != rel:
            self._fetched = (rel, self.archive.download(rel))
        data = self._fetched[1]
        return data[offset:] if length is None else data[offset : offset + length]

    def list(self, source: str, day: date) -> list[StoredPayload]:
        part = self.partition(source, day)
        if not part.exists():
            return []
        out = []
        for segment in sorted(part.glob("*.gz")):
            rel = segment.relative_to(self.root).as_posix()
            for offset, length in _members(segment.read_bytes()):
                out.append(self.open(f"{rel}@{offset}:{length}"))
        return out


def _members(data: bytes) -> Iterator[tuple[int, int]]:
    """(offset, length) of each complete gzip member; a torn tail (a crashed write) is skipped."""
    pos = 0
    while pos < len(data):
        d = zlib.decompressobj(zlib.MAX_WBITS | 16)
        d.decompress(data[pos:])
        if not d.eof:
            return
        end = len(data) - len(d.unused_data)
        yield pos, end - pos
        pos = end


def pack_loose(conn: psycopg.Connection, store: RawStore) -> int:
    """Move payloads stored one file each (before segments) into segments; returns how many.
    Each payload is appended, its manifest row repointed, then its old file removed, so an
    interruption at worst leaves an unreferenced copy in a segment."""
    rows = conn.execute(
        "SELECT id, source, fetched_at, path, sha256 FROM landing.raw_payloads "
        "WHERE path !~ '@[0-9]+:[0-9]+$' ORDER BY id"
    ).fetchall()
    moved = 0
    for row in rows:
        old = store.open(row["path"])
        if old.sha256 != row["sha256"]:
            raise ValueError(f"raw payload {row['path']} does not match its manifest sha256")
        new = store.put(
            RawPayload(row["source"], ScanRequest(row["source"], {}), row["fetched_at"], old.body)
        )
        with conn.transaction():
            conn.execute(
                "UPDATE landing.raw_payloads SET path = %s WHERE id = %s", (new.ref, row["id"])
            )
        old.path.unlink()
        moved += 1
    return moved
