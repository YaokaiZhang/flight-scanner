"""Seam 3: the Wizz Air timetable adapter's contract.

`parse` turns recorded `Api/search/timetable` payloads into Leg prices (in the departure
country's currency); `plan`/`fetch` run against a scripted transport: API version discovery,
the POSTed search, low request rate and block detection.

The recorded payload is representative, built from the endpoint's publicly known answer shape;
it was not captured from the live site (see ticket-13 notes).
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from flight_scanner.clock import FakeClock
from flight_scanner.sources.base import (
    RawPayload,
    ScanRequest,
    SourceBlocked,
    SourceUnavailable,
)
from flight_scanner.sources.polite_http import HttpResponse
from flight_scanner.sources.wizz import WizzAdapter
from flight_scanner.testing.scripted_http import FakeTimer, ScriptedTransport
from flight_scanner.watches import Demand

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "wizz"
T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
NOV = date(2026, 11, 1)
OCT = date(2026, 10, 1)
BODY = (PAYLOADS / "bud-bcn-2026-11.json").read_bytes()
BUILD = HttpResponse(200, {"Content-Type": "text/plain"}, b"SSR https://be.wizzair.com/27.6.0")
TIMETABLE = "https://be.wizzair.com/27.6.0/Api/search/timetable"


def ok(body: bytes = BODY) -> HttpResponse:
    return HttpResponse(200, {"Content-Type": "application/json"}, body)


def adapter(transport: ScriptedTransport, **kwargs) -> tuple[WizzAdapter, FakeTimer]:
    timer = FakeTimer()
    transport.timer = timer
    a = WizzAdapter(
        FakeClock(T0), transport=transport, sleep=timer.sleep, monotonic=timer.monotonic, **kwargs
    )
    return a, timer


def raw(body: bytes = BODY) -> RawPayload:
    return RawPayload("wizz", ScanRequest("wizz", {}), T0, body)


# --- parse ---------------------------------------------------------------------------------


def test_timetable_parses_into_one_leg_price_per_priced_day_in_local_currency():
    a, _ = adapter(ScriptedTransport())
    parsed = a.parse(raw())

    assert parsed.round_trip_prices == []
    legs = {p.departure_date: p for p in parsed.leg_prices}
    # "checkPrice" (no price known) and "soldOut" days are left out
    assert sorted(legs) == [date(2026, 11, 12), date(2026, 11, 14), date(2026, 11, 19)]
    leg = legs[date(2026, 11, 14)]
    assert leg.source == "wizz"
    assert leg.observed_at == T0
    assert (leg.origin, leg.destination) == ("BUD", "BCN")
    assert leg.price == Decimal("12990")
    assert leg.currency == "HUF"  # staging converts with the FX seed
    assert leg.adults == 1
    assert (leg.airline, leg.stops) == ("W6", 0)


def test_an_answer_without_flights_parses_into_no_prices():
    a, _ = adapter(ScriptedTransport())
    body = b'{"validationCodes": ["InvalidMarket"]}'
    assert a.parse(raw(body)).leg_prices == []
    assert a.parse(raw(b'{"outboundFlights": [], "returnFlights": null}')).leg_prices == []


# --- plan ----------------------------------------------------------------------------------


def test_plan_asks_for_one_month_timetable_per_route_for_one_adult():
    a, _ = adapter(ScriptedTransport())

    reqs = a.plan([Demand("BUD", "BCN", NOV, round_trip=True), Demand("BUD", None, NOV)])

    assert getattr(a, "wildcard_destinations", False) is False
    assert [dict(r.params) for r in reqs] == [
        {
            "flightList": [
                {
                    "departureStation": "BUD",
                    "arrivalStation": "BCN",
                    "from": "2026-11-01",
                    "to": "2026-11-30",
                }
            ],
            "priceType": "regular",
            "adultCount": 1,
            "childCount": 0,
            "infantCount": 0,
        }
    ]


def test_the_current_month_starts_today():
    a, _ = adapter(ScriptedTransport())
    [req] = a.plan([Demand("BUD", "BCN", OCT)])
    assert req.params["flightList"][0]["from"] == "2026-10-21"
    assert req.params["flightList"][0]["to"] == "2026-10-31"


def test_plan_never_exceeds_the_budget():
    a, _ = adapter(ScriptedTransport())
    demands = [Demand("BUD", d, NOV) for d in ("BCN", "LTN", "FCO")]
    assert len(a.plan(demands, budget=2)) == 2


# --- fetch ---------------------------------------------------------------------------------


def test_fetch_discovers_the_api_version_once_and_posts_the_search():
    transport = ScriptedTransport(BUILD, ok(), ok())
    a, _ = adapter(transport)
    [req] = a.plan([Demand("BUD", "BCN", NOV)])

    got = a.fetch(req)
    a.fetch(req)

    assert got.body == BODY and got.request == req and got.fetched_at == T0
    (m0, u0, *_), (m1, u1, _, body, _), (m2, u2, *_) = transport.calls
    assert (m0, u0) == ("GET", "https://wizzair.com/buildnumber")
    assert (m1, u1) == ("POST", TIMETABLE)
    assert json.loads(body) == dict(req.params)
    assert (m2, u2) == ("POST", TIMETABLE)  # version cached


def test_a_configured_api_url_skips_discovery():
    transport = ScriptedTransport(ok())
    a, _ = adapter(transport, api_url="https://be.wizzair.com/28.0.0")
    a.fetch(a.plan([Demand("BUD", "BCN", NOV)])[0])
    assert transport.calls[0][1] == "https://be.wizzair.com/28.0.0/Api/search/timetable"


def test_a_stale_api_version_is_rediscovered_once():
    newer = HttpResponse(200, {}, b"SSR https://be.wizzair.com/27.7.0")
    transport = ScriptedTransport(BUILD, HttpResponse(404, {}, b""), newer, ok())
    a, _ = adapter(transport)

    assert a.fetch(a.plan([Demand("BUD", "BCN", NOV)])[0]).body == BODY
    assert transport.calls[-1][1] == "https://be.wizzair.com/27.7.0/Api/search/timetable"


def test_a_route_wizz_does_not_fly_is_stored_as_an_empty_timetable():
    body = b'{"validationCodes": ["InvalidMarket"]}'
    transport = ScriptedTransport(BUILD, HttpResponse(400, {}, body))
    a, _ = adapter(transport)
    got = a.fetch(a.plan([Demand("BUD", "HEL", NOV)])[0])
    assert a.parse(got).leg_prices == []


def test_requests_are_spaced_at_a_low_rate_by_default():
    transport = ScriptedTransport(BUILD, ok(), ok())
    a, _ = adapter(transport)
    req = a.plan([Demand("BUD", "BCN", NOV)])[0]
    a.fetch(req)
    a.fetch(req)
    times = [c[-1] for c in transport.calls]
    assert [b - a for a, b in zip(times, times[1:], strict=False)] == [10.0, 10.0]


def test_outages_are_retried_then_make_the_source_unavailable():
    transport = ScriptedTransport(BUILD, *[HttpResponse(502, {}, b"")] * 3)
    a, timer = adapter(transport, max_retries=2)
    with pytest.raises(SourceUnavailable) as e:
        a.fetch(a.plan([Demand("BUD", "BCN", NOV)])[0])
    assert not isinstance(e.value, SourceBlocked)
    assert len(timer.slept) >= 2


def test_bot_protection_blocks_the_source_without_any_workaround():
    challenge = HttpResponse(429, {"x-kpsdk-ct": "abc"}, b"")
    transport = ScriptedTransport(BUILD, challenge)
    a, _ = adapter(transport)
    with pytest.raises(SourceBlocked):
        a.fetch(a.plan([Demand("BUD", "BCN", NOV)])[0])
    assert len(transport.calls) == 2  # no retry
