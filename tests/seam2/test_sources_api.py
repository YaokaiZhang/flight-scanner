"""Seam 2: blocked sources over HTTP (for the data-health page)."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from flight_scanner import source_health
from flight_scanner.api import create_app
from flight_scanner.clock import FakeClock
from flight_scanner.db import connect

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def test_blocked_sources_are_listed_until_unblocked(db):
    with TestClient(create_app(db, FakeClock(NOW))) as api:
        assert api.get("/sources/blocked").json() == []

        with connect(db) as conn:
            source_health.block(conn, "wizz", "wizz: turned away (HTTP 429)", NOW)
            source_health.block(conn, "wizz", "a later block does not replace it", NOW)
        [b] = api.get("/sources/blocked").json()
        assert (b["source"], b["reason"]) == ("wizz", "wizz: turned away (HTTP 429)")
        assert datetime.fromisoformat(b["blocked_at"]) == NOW

        with connect(db) as conn:
            assert source_health.unblock(conn, "wizz") is True
            assert source_health.unblock(conn, "wizz") is False
        assert api.get("/sources/blocked").json() == []
