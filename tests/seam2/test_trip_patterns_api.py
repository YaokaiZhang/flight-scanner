"""Seam 2: the resolved departure window and Stay-night range the Watch editor shows."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app
from flight_scanner.clock import FakeClock

NIGHTS_3_6 = {"min": 3, "max": 6}


@pytest.fixture
def api(db):
    clock = FakeClock(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
    with TestClient(create_app(db, clock)) as client:
        yield client


def resolve(api, preset: dict):
    return api.post("/trip-patterns/resolve", json={"trip_pattern": preset})


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        (
            {"preset": "one_way_fixed", "departure": "2026-11-14"},
            {
                "kind": "one_way",
                "departure_start": "2026-11-14",
                "departure_end": "2026-11-14",
                "stay_nights": None,
                "latest_return": None,
                "trip_count": 1,
            },
        ),
        (
            {"preset": "fixed_dates", "departure": "2026-11-11", "return_date": "2026-11-15"},
            {
                "kind": "round_trip",
                "departure_start": "2026-11-11",
                "departure_end": "2026-11-11",
                "stay_nights": {"min": 4, "max": 4},
                "latest_return": "2026-11-15",
                "trip_count": 1,
            },
        ),
        (
            {"preset": "month", "month": "2026-11", "stay_nights": NIGHTS_3_6},
            {
                "kind": "round_trip",
                "departure_start": "2026-11-01",
                "departure_end": "2026-11-30",
                "stay_nights": NIGHTS_3_6,
                "latest_return": "2026-12-06",
                "trip_count": 120,
            },
        ),
        (
            {"preset": "rolling", "within_days": 60, "stay_nights": {"min": 2, "max": 4}},
            {
                "kind": "round_trip",
                "rolling": True,
                "departure_start": "2026-10-21",
                "departure_end": "2026-12-20",
                "latest_return": "2026-12-24",
                "trip_count": 61 * 3,
            },
        ),
        (
            {
                "preset": "fixed_departure",
                "departure": "2026-11-22",
                "stay_nights": {"min": 3, "max": 5},
            },
            {
                "departure_start": "2026-11-22",
                "departure_end": "2026-11-22",
                "latest_return": "2026-11-27",
                "trip_count": 3,
            },
        ),
        (
            {
                "preset": "around_date",
                "target": "2026-11-22",
                "flex_days": 2,
                "stay_nights": {"min": 3, "max": 5},
            },
            {
                "departure_start": "2026-11-20",
                "departure_end": "2026-11-24",
                "latest_return": "2026-11-29",
                "trip_count": 15,
            },
        ),
        (
            {
                "preset": "month",
                "month": "2026-11",
                "stay_nights": NIGHTS_3_6,
                "return_by": "2026-11-30",
            },
            {
                "departure_start": "2026-11-01",
                "departure_end": "2026-11-30",
                "return_by": "2026-11-30",
                "latest_return": "2026-11-30",
            },
        ),
    ],
)
def test_every_preset_resolves_to_a_departure_window_and_stay_nights(api, preset, expected):
    r = resolve(api, preset)
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in expected} == expected
    assert body["expired"] is False


def test_a_window_that_has_fully_passed_resolves_as_expired(api):
    body = resolve(api, {"preset": "month", "month": "2026-09", "stay_nights": NIGHTS_3_6}).json()
    assert body["expired"] is True
    assert body["trip_count"] == 0


@pytest.mark.parametrize(
    "preset",
    [
        {"preset": "month", "month": "2026-13", "stay_nights": NIGHTS_3_6},
        {"preset": "month", "month": "2026-11", "stay_nights": {"min": 6, "max": 3}},
        {"preset": "month", "month": "2026-11"},
        {"preset": "fixed_dates", "departure": "2026-11-15", "return_date": "2026-11-11"},
        {
            "preset": "around_date",
            "target": "2026-11-22",
            "flex_days": -1,
            "stay_nights": NIGHTS_3_6,
        },
        {"preset": "rolling", "within_days": 60},
        {"preset": "somewhen"},
    ],
)
def test_invalid_presets_are_rejected(api, preset):
    assert resolve(api, preset).status_code == 422


def test_a_watch_stores_any_preset_as_given(api):
    preset = {
        "preset": "around_date",
        "target": "2026-11-22",
        "flex_days": 2,
        "stay_nights": {"min": 3, "max": 5},
        "return_by": None,
    }
    spec = {
        "name": "Around 22 Nov",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": preset,
    }
    created = api.post("/watches", json=spec)
    assert created.status_code == 201
    assert api.get(f"/watches/{created.json()['id']}").json()["trip_pattern"] == preset


def test_editing_the_trip_pattern_expires_or_revives_the_watch_immediately(api):
    spec = {
        "name": "Barcelona",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
    }
    w = api.post("/watches", json=spec).json()
    past = {**spec, "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-10-01"}}
    assert api.put(f"/watches/{w['id']}", json=past).json()["status"] == "expired"
    assert api.put(f"/watches/{w['id']}", json=spec).json()["status"] == "active"
