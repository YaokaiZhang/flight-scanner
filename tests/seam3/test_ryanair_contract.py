"""Seam 3: the Ryanair calendar adapter's contract.

`parse` turns recorded `farfnd/v4 ... cheapestPerDay` payloads into Leg prices; `plan`/`fetch`
are driven through a scripted HTTP transport and a fake monotonic clock, so the low request
rate, backoff and block detection are observable without the network.

The recorded payload is representative, built from the endpoint's publicly known answer shape;
it was not captured from the live site (see ticket-13 notes).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from flight_scanner.clock import FakeClock
from flight_scanner.sources.base import (
    RawPayload,
    ScanRequest,
    SourceBlocked,
    SourceUnavailable,
)
from flight_scanner.sources.polite_http import HttpResponse
from flight_scanner.sources.ryanair import RyanairAdapter
from flight_scanner.testing.scripted_http import FakeTimer, ScriptedTransport
from flight_scanner.watches import Demand

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "ryanair"
T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
NOV = date(2026, 11, 1)
BODY = (PAYLOADS / "stn-bcn-2026-11.json").read_bytes()


def ok(body: bytes = BODY) -> HttpResponse:
    return HttpResponse(200, {"Content-Type": "application/json"}, body)


def adapter(transport: ScriptedTransport, **kwargs) -> tuple[RyanairAdapter, FakeTimer]:
    timer = FakeTimer()
    transport.timer = timer
    a = RyanairAdapter(
        FakeClock(T0), transport=transport, sleep=timer.sleep, monotonic=timer.monotonic, **kwargs
    )
    return a, timer


def raw(body: bytes = BODY) -> RawPayload:
    """A stored payload; its request names the route (the calendar's fares do not)."""
    params = {"origin": "STN", "destination": "BCN", "month": "2026-11-01", "currency": "EUR"}
    return RawPayload("ryanair", ScanRequest("ryanair", params), T0, body)


# --- parse ---------------------------------------------------------------------------------


def test_calendar_parses_into_one_leg_price_per_day_with_a_fare():
    a, _ = adapter(ScriptedTransport())
    parsed = a.parse(raw())

    assert parsed.round_trip_prices == []
    legs = {p.departure_date: p for p in parsed.leg_prices}
    # sold-out and unavailable days carry no price and are left out
    assert sorted(legs) == [date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)]
    leg = legs[date(2026, 11, 14)]
    assert leg.source == "ryanair"
    assert leg.observed_at == T0
    assert (leg.origin, leg.destination) == ("STN", "BCN")
    assert leg.price == Decimal("19.99")
    assert leg.currency == "EUR"
    assert leg.adults == 1
    assert (leg.airline, leg.stops) == ("FR", 0)


def test_a_route_ryanair_does_not_fly_parses_into_no_prices():
    a, _ = adapter(ScriptedTransport())
    body = b'{"message": "Availability.RouteNotFound", "code": "Availability.RouteNotFound"}'
    assert a.parse(raw(body)).leg_prices == []


# --- plan ----------------------------------------------------------------------------------


def test_plan_asks_for_one_month_calendar_per_route():
    a, _ = adapter(ScriptedTransport())
    demands = [Demand("STN", "BCN", NOV, round_trip=True), Demand("STN", "DUB", NOV)]

    reqs = a.plan(demands)

    assert [r.source for r in reqs] == ["ryanair", "ryanair"]
    assert [dict(r.params) for r in reqs] == [
        {"origin": "STN", "destination": "BCN", "month": "2026-11-01", "currency": "EUR"},
        {"origin": "STN", "destination": "DUB", "month": "2026-11-01", "currency": "EUR"},
    ]


def test_plan_never_exceeds_the_budget_and_cannot_price_anywhere():
    a, _ = adapter(ScriptedTransport())
    assert getattr(a, "wildcard_destinations", False) is False
    demands = [Demand("STN", d, NOV) for d in ("BCN", "DUB", "AGP")]
    assert len(a.plan(demands, budget=2)) == 2
    assert a.plan([Demand("STN", None, NOV)]) == []


# --- fetch: low request rate, backoff, blocks ----------------------------------------------


def test_fetch_returns_the_raw_calendar_from_the_public_endpoint():
    transport = ScriptedTransport(ok())
    a, _ = adapter(transport)
    [req] = a.plan([Demand("STN", "BCN", NOV)])

    got = a.fetch(req)

    assert got.body == BODY and got.request == req and got.fetched_at == T0
    method, url, _, _ = transport.calls[0][:4]
    assert method == "GET"
    parts = urlsplit(url)
    assert parts.netloc == "www.ryanair.com"
    assert parts.path == "/api/farfnd/v4/oneWayFares/STN/BCN/cheapestPerDay"
    assert parse_qs(parts.query) == {"outboundMonthOfDate": ["2026-11-01"], "currency": ["EUR"]}


def test_requests_are_spaced_at_a_low_rate_by_default():
    transport = ScriptedTransport(ok(), ok(), ok())
    a, _ = adapter(transport)
    req = a.plan([Demand("STN", "BCN", NOV)])[0]

    for _ in range(3):
        a.fetch(req)

    times = [c[-1] for c in transport.calls]
    assert [b - a for a, b in zip(times, times[1:], strict=False)] == [10.0, 10.0]  # 6 a minute


def test_rate_limited_and_server_errors_are_retried_with_backoff():
    transport = ScriptedTransport(
        HttpResponse(429, {"Retry-After": "30"}, b""), HttpResponse(503, {}, b""), ok()
    )
    a, timer = adapter(transport, backoff_base_s=5.0)
    req = a.plan([Demand("STN", "BCN", NOV)])[0]

    assert a.fetch(req).body == BODY
    assert timer.slept[:2] == [30.0, 10.0]  # Retry-After honoured, then 5 * 2**1


def test_persistent_failure_makes_the_source_unavailable_but_not_blocked():
    transport = ScriptedTransport(*[HttpResponse(503, {}, b"")] * 3)
    a, _ = adapter(transport, max_retries=2)
    req = a.plan([Demand("STN", "BCN", NOV)])[0]

    with pytest.raises(SourceUnavailable) as e:
        a.fetch(req)
    assert not isinstance(e.value, SourceBlocked)
    assert len(transport.calls) == 3


def test_a_route_that_is_not_flown_is_stored_as_an_empty_calendar():
    body = b'{"message": "Availability.RouteNotFound"}'
    transport = ScriptedTransport(HttpResponse(404, {}, body))
    a, _ = adapter(transport)
    req = a.plan([Demand("STN", "HEL", NOV)])[0]

    got = a.fetch(req)

    assert got.body == body
    assert a.parse(got).leg_prices == []


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(403, {"Content-Type": "text/html"}, b"<html>Access denied</html>"),
        HttpResponse(200, {"Content-Type": "text/html"}, b"<html>Please verify you are human"),
        HttpResponse(409, {}, b'{"message": "Declined", "code": "Declined"}'),
    ],
    ids=["forbidden", "challenge-page", "declined"],
)
def test_bot_protection_blocks_the_source_at_once_without_retrying(response):
    transport = ScriptedTransport(response)
    a, _ = adapter(transport)
    req = a.plan([Demand("STN", "BCN", NOV)])[0]

    with pytest.raises(SourceBlocked):
        a.fetch(req)
    assert len(transport.calls) == 1  # no retry, no workaround
