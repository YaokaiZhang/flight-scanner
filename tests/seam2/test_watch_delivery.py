"""Seam 2: a Watch's delivery choice (immediate Alerts or a daily Digest) over HTTP."""

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app

HEL_BCN = {
    "name": "Barcelona weekend",
    "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
    "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
    "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
}


@pytest.fixture
def api(db):
    with TestClient(create_app(db)) as client:
        yield client


def test_a_watch_delivers_immediately_unless_told_otherwise(api):
    created = api.post("/watches", json=HEL_BCN).json()
    assert created["delivery"] == "immediate"


def test_a_watch_can_ask_for_a_daily_digest(api):
    created = api.post("/watches", json={**HEL_BCN, "delivery": "digest"}).json()
    assert api.get(f"/watches/{created['id']}").json()["delivery"] == "digest"


def test_an_unknown_delivery_is_rejected(api):
    assert api.post("/watches", json={**HEL_BCN, "delivery": "weekly"}).status_code == 422
