"""Seam 1: Travelpayouts payloads in -> change-only price history out (read through the API).

The real Travelpayouts adapter runs inside the pipeline; only its HTTP transport is scripted,
replaying recorded payloads per scan time.
"""

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app
from flight_scanner.sources.travelpayouts import HttpResponse, TravelpayoutsAdapter

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "travelpayouts"
EMPTY = b'{"success": true, "data": [], "currency": "eur"}'


class RecordedTravelpayouts:
    """HTTP transport answering from recorded payloads keyed by (origin, one_way)."""

    def __init__(self):
        self.answers: dict[tuple[str, str], bytes] = {}

    def answer(self, origin: str, one_way: bool, payload: str) -> None:
        self.answers[(origin, "true" if one_way else "false")] = (PAYLOADS / payload).read_bytes()

    def __call__(self, url: str, headers: dict, timeout: float) -> HttpResponse:
        q = parse_qs(urlsplit(url).query)
        body = self.answers.get((q["origin"][0], q["one_way"][0]), EMPTY)
        return HttpResponse(200, {}, body)


@pytest.fixture
def travelpayouts(pipeline) -> RecordedTravelpayouts:
    transport = RecordedTravelpayouts()
    pipeline.add_source(
        TravelpayoutsAdapter(
            token="test-token", clock=pipeline.clock, transport=transport, sleep=lambda s: None
        )
    )
    return transport


@pytest.fixture
def api(pipeline):
    with TestClient(create_app(pipeline.db, pipeline.clock)) as client:
        yield client


def one_way(origin: str, destination: str, departure: str = "2026-11-14") -> dict:
    return {
        "name": f"{origin} to {destination}",
        "origins": {"include": [{"kind": "airport", "code": origin}]},
        "destinations": {"include": [{"kind": "airport", "code": destination}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": departure},
        "adults": 2,
    }


def history(api, origin, destination, departure, return_date=None) -> list[dict]:
    params = {"departure_date": departure}
    if return_date:
        params["return_date"] = return_date
    r = api.get(f"/routes/{origin}/{destination}/history", params=params)
    assert r.status_code == 200, r.text
    return r.json()["points"]


def test_unchanged_then_changed_price_yields_two_history_rows(pipeline, travelpayouts, api):
    pipeline.create_watch(one_way("HEL", "BCN"))
    t0 = pipeline.clock.now()
    travelpayouts.answer("HEL", one_way=True, payload="hel-bcn-2026-11-one-way.json")
    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()  # the same 89 again: no new row
    pipeline.clock.advance(minutes=30)
    travelpayouts.answer("HEL", one_way=True, payload="hel-bcn-2026-11-one-way-cheaper.json")
    pipeline.run()

    points = history(api, "HEL", "BCN", "2026-11-14")

    assert [(p["source"], p["kind"], p["price_per_adult_eur"]) for p in points] == [
        ("travelpayouts", "leg", 89.0),
        ("travelpayouts", "leg", 79.0),
    ]
    first, second = points
    assert _t(first["valid_from"]) == t0
    assert _t(first["valid_to"]) == t0 + timedelta(hours=1)
    assert _t(first["last_observed_at"]) == t0 + timedelta(minutes=30)
    assert first["observations"] == 2
    assert _t(second["valid_from"]) == t0 + timedelta(hours=1)
    assert second["valid_to"] is None


def test_round_trip_prices_get_their_own_history(pipeline, travelpayouts, api):
    pipeline.create_watch(
        {
            **one_way("HEL", "BCN"),
            "trip_pattern": {
                "preset": "fixed_dates",
                "departure": "2026-11-14",
                "return_date": "2026-11-18",
            },
        }
    )
    travelpayouts.answer("HEL", one_way=False, payload="hel-bcn-2026-11-round-trip.json")

    pipeline.run()

    points = history(api, "HEL", "BCN", "2026-11-14", return_date="2026-11-18")
    assert [(p["kind"], p["price_per_adult_eur"]) for p in points] == [("round_trip", 151.0)]
    assert history(api, "HEL", "BCN", "2026-11-14", return_date="2026-11-20") == []


def test_routes_with_history_can_be_listed(pipeline, travelpayouts, api):
    pipeline.create_watch(one_way("HEL", "BCN"))
    travelpayouts.answer("HEL", one_way=True, payload="hel-bcn-2026-11-one-way.json")
    pipeline.run()

    routes = api.get("/routes").json()

    [route] = routes
    assert (route["origin"], route["destination"]) == ("HEL", "BCN")
    assert route["departure_dates"] == ["2026-11-13", "2026-11-14", "2026-11-15"]
    assert (route["origin_city"], route["destination_city"]) == ("Helsinki", "Barcelona")
    assert (route["origin_country"], route["destination_country"]) == ("Finland", "Spain")
    assert route["origin_airport"] and route["destination_airport"]


def test_history_is_rebuilt_from_raw_payloads_alone(pipeline, travelpayouts, api):
    pipeline.create_watch(one_way("HEL", "BCN"))
    travelpayouts.answer("HEL", one_way=True, payload="hel-bcn-2026-11-one-way.json")
    pipeline.run()
    pipeline.clock.advance(minutes=30)
    travelpayouts.answer("HEL", one_way=True, payload="hel-bcn-2026-11-one-way-cheaper.json")
    pipeline.run()
    before = history(api, "HEL", "BCN", "2026-11-14")

    report = pipeline.rebuild()  # wipes parsed rows, re-parses the raw store, rebuilds dbt

    assert report.payloads == 2 * 2  # two scans x (travelpayouts + the idle fake source)
    assert history(api, "HEL", "BCN", "2026-11-14") == before


def test_non_eur_prices_are_converted_to_eur_per_adult(pipeline, api):
    pipeline.create_watch(one_way("HEL", "BCN"))
    pipeline.fake.replay(
        {
            "currency": "SEK",
            "prices": [
                {"origin": "HEL", "destination": "BCN", "depart_date": "2026-11-14", "price": 1000}
            ],
        },
        route=("HEL", "BCN"),
    )
    pipeline.run()

    [point] = history(api, "HEL", "BCN", "2026-11-14")
    assert point["source"] == "fake"
    assert point["price_per_adult_eur"] == 87.0  # dbt seed fx_rates: 1 SEK = 0.087 EUR


def _t(value: str) -> datetime:
    return datetime.fromisoformat(value)
