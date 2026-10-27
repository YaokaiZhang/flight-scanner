"""Seam 1: the raw store keeps few files (segments) and copies finished days to an archive.

The archive here is an in-memory stand-in for the Databricks volume (its HTTP contract is in
seam3/test_raw_archive_contract.py); the scans, the manifest and reprocessing are the real ones.
"""

import gzip
from pathlib import Path

import pytest

from flight_scanner.db import connect
from flight_scanner.raw_archive import RawArchiveUnavailable, archive_raw
from flight_scanner.raw_store import pack_loose

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "fake"


def hel_bcn_watch(threshold_eur: float) -> dict:
    return {
        "name": "Barcelona weekend",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "adults": 1,
        "price_threshold": {"amount_eur": threshold_eur, "basis": "total"},
    }


class MemoryArchive:
    name = "memory"

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.down = False

    def upload(self, rel: str, data: bytes) -> None:
        if self.down:
            raise RawArchiveUnavailable("volume down")
        self.files[rel] = data

    def download(self, rel: str) -> bytes:
        return self.files[rel]


@pytest.fixture
def archive(pipeline) -> MemoryArchive:
    a = MemoryArchive()
    pipeline.raw_store.archive = a
    return a


def scan(pipeline, payload="hel-bcn-2026-11.json"):
    pipeline.fake.replay(PAYLOADS / payload, route=("HEL", "BCN"))
    pipeline.run()


def local_files(pipeline) -> list[Path]:
    return sorted(p for p in pipeline.raw_store.root.rglob("*") if p.is_file())


def archive_now(pipeline, archive):
    with connect(pipeline.runtime.db, autocommit=True) as conn:
        return archive_raw(conn, pipeline.raw_store, archive, pipeline.clock.now(), keep_days=14)


def test_scans_append_their_payloads_to_one_file_per_day(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    for _ in range(3):
        scan(pipeline)
        pipeline.clock.advance(minutes=30)

    [segment] = local_files(pipeline)
    stored = pipeline.raw_store.list("fake", pipeline.clock.now().date())
    assert len(stored) == 3
    assert {s.path for s in stored} == {segment}
    assert all(s.read() == (PAYLOADS / "hel-bcn-2026-11.json").read_bytes() for s in stored)


def test_finished_days_are_archived_then_pruned_locally_and_still_reprocess(pipeline, archive):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    scan(pipeline)
    [segment] = local_files(pipeline)

    assert archive_now(pipeline, archive).uploaded == 0  # today's segment is still being written

    pipeline.clock.advance(days=1)
    report = archive_now(pipeline, archive)
    assert (report.uploaded, report.pruned) == (1, 0)
    [(rel, data)] = archive.files.items()
    assert data == segment.read_bytes() and rel.startswith("source=fake/date=2026-10-21/")
    assert archive_now(pipeline, archive).uploaded == 0  # unchanged: not uploaded again

    pipeline.clock.advance(days=14)
    assert archive_now(pipeline, archive).pruned == 1
    assert not segment.exists()

    report = pipeline.rebuild()  # the pruned payload is read back from the archive
    assert report.payloads == 1 and report.leg_prices > 0


def test_an_unavailable_archive_keeps_everything_local_and_retries(pipeline, archive):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    scan(pipeline)
    pipeline.clock.advance(days=20)
    archive.down = True

    report = archive_now(pipeline, archive)

    assert report.status == "unavailable" and report.pruned == 0
    assert len(local_files(pipeline)) == 1
    archive.down = False
    report = archive_now(pipeline, archive)
    assert (report.status, report.uploaded, report.pruned) == ("ok", 1, 1)


def test_a_segment_that_grew_after_its_upload_is_uploaded_again_before_pruning(pipeline, archive):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    scan(pipeline)
    pipeline.clock.advance(days=1)
    archive_now(pipeline, archive)
    [segment] = local_files(pipeline)
    segment.chmod(0o644)
    with segment.open("ab") as f:  # a late write into an archived day
        f.write(gzip.compress(b"{}", mtime=0))

    pipeline.clock.advance(days=14)
    report = archive_now(pipeline, archive)

    assert (report.uploaded, report.pruned) == (1, 1)
    assert gzip.decompress(next(iter(archive.files.values()))).endswith(b"{}")


def test_payloads_stored_one_file_each_are_packed_into_segments(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    scan(pipeline)
    # turn the stored payload back into a pre-segment file: one gzip file, manifest = its path
    with connect(pipeline.runtime.db, autocommit=True) as conn:
        [row] = conn.execute("SELECT id, path FROM landing.raw_payloads").fetchall()
        body = pipeline.raw_store.open(row["path"]).read()
        legacy = pipeline.raw_store.root / "source=fake/date=2026-10-21/090000000000Z-abc.json.gz"
        legacy.write_bytes(gzip.compress(body, mtime=0))
        legacy.chmod(0o444)
        conn.execute(
            "UPDATE landing.raw_payloads SET path = %s WHERE id = %s", (str(legacy), row["id"])
        )
        for p in local_files(pipeline):
            if p != legacy:
                p.unlink()

        assert pack_loose(conn, pipeline.raw_store) == 1

        [path] = conn.execute("SELECT path FROM landing.raw_payloads").fetchone().values()
    assert not legacy.exists()
    assert pipeline.raw_store.open(path).read() == body
    assert pipeline.rebuild().payloads == 1


def test_old_days_without_an_archive_are_kept(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    scan(pipeline)
    pipeline.clock.advance(days=30)

    pipeline.run_lakehouse()  # the daily job; no archive configured: nothing is touched

    assert len(local_files(pipeline)) == 1


def test_the_daily_job_archives_the_raw_store(pipeline, archive):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    scan(pipeline)
    pipeline.clock.advance(days=1)

    pipeline.run_lakehouse()

    assert len(archive.files) == 1
