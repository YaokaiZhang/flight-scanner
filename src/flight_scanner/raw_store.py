"""The raw store: every source response, byte-for-byte, immutable, partitioned by source and date.

Layout: <root>/source=<source>/date=<YYYY-MM-DD>/<HHMMSSffffff>Z-<sha12>.<ext>.gz
Files are gzip (mtime 0, so identical bytes give identical files), written atomically via a
hard link that refuses to overwrite, then made read-only. Storing identical bytes at the same
instant is idempotent. The manifest row in `landing.raw_payloads` points at the path.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date
from pathlib import Path

from flight_scanner.sources.base import RawPayload


@dataclass(frozen=True)
class StoredPayload:
    path: Path
    sha256: str

    def read(self) -> bytes:
        return gzip.decompress(self.path.read_bytes())


class RawStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def partition(self, source: str, day: date) -> Path:
        return self.root / f"source={source}" / f"date={day.isoformat()}"

    def put(self, raw: RawPayload) -> StoredPayload:
        sha = hashlib.sha256(raw.body).hexdigest()
        at = raw.fetched_at.astimezone(UTC)
        ext = "json" if "json" in raw.content_type else "bin"
        part = self.partition(raw.source, at.date())
        part.mkdir(parents=True, exist_ok=True)
        path = part / f"{at:%H%M%S%f}Z-{sha[:12]}.{ext}.gz"
        fd, tmp = tempfile.mkstemp(dir=part, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
                gz.write(raw.body)
            os.chmod(tmp, 0o444)
            try:
                os.link(tmp, path)
            except FileExistsError:
                if StoredPayload(path, sha).read() != raw.body:
                    raise
        finally:
            os.unlink(tmp)
        return StoredPayload(path, sha)

    def open(self, path: Path | str) -> StoredPayload:
        p = Path(path)
        data = gzip.decompress(p.read_bytes())
        return StoredPayload(p, hashlib.sha256(data).hexdigest())

    def list(self, source: str, day: date) -> list[StoredPayload]:
        part = self.partition(source, day)
        if not part.exists():
            return []
        return [self.open(p) for p in sorted(part.glob("*.gz"))]
