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


# --- Places on Watches (ticket 03) -------------------------------------------------------------

SUN = {
    **HEL_BCN,
    "name": "Sun, not Sweden",
    "origins": {"include": [{"kind": "city", "code": "FI-helsinki"}]},
    "destinations": {
        "include": [{"kind": "region", "code": "europe"}, {"kind": "country", "code": "EG"}],
        "exclude": [{"kind": "country", "code": "SE"}],
    },
}


def test_watch_with_regions_countries_cities_and_exclusions(api):
    created = api.post("/watches", json=SUN)
    assert created.status_code == 201, created.text
    w = api.get(f"/watches/{created.json()['id']}").json()

    assert w["destinations"]["exclude"] == [{"kind": "country", "code": "SE"}]
    names = {(p["kind"], p["code"]): p["name"] for p in w["places"]}
    assert names[("region", "europe")] == "Europe"
    assert names[("country", "SE")] == "Sweden"
    assert names[("city", "FI-helsinki")] == "Helsinki"

    europe = api.post("/places/resolve", json={"include": [{"kind": "region", "code": "europe"}]})
    egypt = api.post("/places/resolve", json={"include": [{"kind": "country", "code": "EG"}]})
    sweden = api.post("/places/resolve", json={"include": [{"kind": "country", "code": "SE"}]})
    expected = (
        sum(r.json()["airport_count"] for r in (europe, egypt)) - sweden.json()["airport_count"]
    )
    assert w["resolved"] == {"origins": 1, "destinations": expected}


@pytest.mark.parametrize(
    "places",
    [
        {"include": [{"kind": "country", "code": "QQ"}]},  # unknown country
        {
            "include": [{"kind": "airport", "code": "BCN"}],
            "exclude": [{"kind": "region", "code": "mars"}],
        },
        {"include": [{"kind": "airport", "code": "bcn"}]},  # malformed code
        {"include": [{"kind": "planet", "code": "EARTH"}]},  # unknown kind
        {  # include − exclude leaves nothing
            "include": [{"kind": "country", "code": "SE"}],
            "exclude": [{"kind": "region", "code": "nordics"}],
        },
    ],
)
def test_watch_with_unknown_or_empty_places_is_rejected(api, places):
    for side in ("origins", "destinations"):
        r = api.post("/watches", json={**HEL_BCN, side: places})
        assert r.status_code == 422, r.text
    assert api.get("/watches").json() == []


# --- Watch settings ----------------------------------------------------------------------------


def test_sensitivity_defaults_to_30_percent(api):
    w = api.post("/watches", json=HEL_BCN).json()
    assert w["sensitivity_pct"] == 30
    w2 = api.post("/watches", json={**HEL_BCN, "sensitivity_pct": 45}).json()
    assert w2["sensitivity_pct"] == 45


@pytest.mark.parametrize("bad", [0, 95, 12.5])
def test_sensitivity_out_of_range_is_rejected(api, bad):
    assert api.post("/watches", json={**HEL_BCN, "sensitivity_pct": bad}).status_code == 422


def test_threshold_is_optional(api):
    w = api.post("/watches", json={**HEL_BCN, "price_threshold": None}).json()
    assert w["price_threshold"] is None


def test_edit_a_watch(api):
    w = api.post("/watches", json=HEL_BCN).json()

    r = api.put(
        f"/watches/{w['id']}",
        json={**SUN, "adults": 2, "price_threshold": {"amount_eur": 90, "basis": "per_adult"}},
    )
    assert r.status_code == 200, r.text
    got = api.get(f"/watches/{w['id']}").json()
    assert got["name"] == "Sun, not Sweden"
    assert got["adults"] == 2
    assert got["price_threshold"] == {"amount_eur": 90.0, "basis": "per_adult"}
    assert got["destinations"]["exclude"] == [{"kind": "country", "code": "SE"}]
    assert got["status"] == "active"
    assert got["created_at"] == w["created_at"]


def test_invalid_edit_is_rejected_and_changes_nothing(api):
    w = api.post("/watches", json=HEL_BCN).json()
    bad = {**HEL_BCN, "name": "x", "destinations": {"include": [{"kind": "country", "code": "QQ"}]}}
    assert api.put(f"/watches/{w['id']}", json=bad).status_code == 422
    assert api.get(f"/watches/{w['id']}").json()["name"] == "Barcelona weekend"


def test_pause_and_resume(api):
    w = api.post("/watches", json=HEL_BCN).json()

    paused = api.post(f"/watches/{w['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert api.get(f"/watches/{w['id']}").json()["status"] == "paused"

    resumed = api.post(f"/watches/{w['id']}/resume")
    assert resumed.json()["status"] == "active"


def test_delete_a_watch(api):
    w = api.post("/watches", json=HEL_BCN).json()
    keep = api.post("/watches", json={**HEL_BCN, "name": "Keep"}).json()

    assert api.delete(f"/watches/{w['id']}").status_code == 204
    assert api.get(f"/watches/{w['id']}").status_code == 404
    assert [x["id"] for x in api.get("/watches").json()] == [keep["id"]]


@pytest.mark.parametrize(
    "method, path",
    [
        ("put", "/watches/999999"),
        ("post", "/watches/999999/pause"),
        ("post", "/watches/999999/resume"),
        ("delete", "/watches/999999"),
    ],
)
def test_changing_an_unknown_watch_is_404(api, method, path):
    kwargs = {"json": HEL_BCN} if method == "put" else {}
    assert getattr(api, method)(path, **kwargs).status_code == 404
