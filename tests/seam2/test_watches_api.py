"""Seam 2: the HTTP API, exercised with an HTTP client against real Postgres."""

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app

HEL_BCN = {
    "name": "Barcelona weekend",
    "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
    "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
    "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
    "adults": 1,
    "price_threshold": {"amount_eur": 120, "basis": "total"},
}


@pytest.fixture
def api(db):
    with TestClient(create_app(db)) as client:
        yield client


def test_create_then_read_a_watch(api):
    created = api.post("/watches", json=HEL_BCN)
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Barcelona weekend"
    assert body["status"] == "active"

    fetched = api.get(f"/watches/{body['id']}")
    assert fetched.status_code == 200
    got = fetched.json()
    assert got["origins"] == {"include": [{"kind": "airport", "code": "HEL"}], "exclude": []}
    assert got["destinations"]["include"] == [{"kind": "airport", "code": "BCN"}]
    assert got["trip_pattern"] == {"preset": "one_way_fixed", "departure": "2026-11-14"}
    assert got["adults"] == 1
    assert got["price_threshold"] == {"amount_eur": 120.0, "basis": "total"}


def test_list_watches_returns_every_watch_newest_first(api):
    api.post("/watches", json=HEL_BCN)
    api.post("/watches", json={**HEL_BCN, "name": "Second"})

    listed = api.get("/watches")
    assert listed.status_code == 200
    assert [w["name"] for w in listed.json()] == ["Second", "Barcelona weekend"]


def test_unknown_watch_is_404(api):
    assert api.get("/watches/999999").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"adults": 0},
        {"origins": {"include": []}},
        {"trip_pattern": {"preset": "one_way_fixed"}},
        {"price_threshold": {"amount_eur": -5, "basis": "total"}},
        {"name": ""},
    ],
)
def test_invalid_watch_is_rejected(api, change):
    assert api.post("/watches", json={**HEL_BCN, **change}).status_code == 422
    assert api.get("/watches").json() == []
