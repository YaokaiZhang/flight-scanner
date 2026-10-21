"""Seam 3: the Travelpayouts adapter's contract.

`parse` turns recorded `prices_for_dates` payloads into Leg prices and Round-trip prices;
`plan`/`fetch` are driven through a scripted HTTP transport and a fake monotonic clock, so rate
limiting and backoff are observable without the network or a real token.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from flight_scanner.clock import FakeClock
from flight_scanner.sources.base import RawPayload, ScanRequest, SourceUnavailable
from flight_scanner.sources.travelpayouts import HttpResponse, TravelpayoutsAdapter
from flight_scanner.watches import Demand

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "travelpayouts"
T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


class ScriptedTransport:
    """Answers each HTTP request with the next scripted response; records what was asked."""

    def __init__(self, *responses: HttpResponse):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str], float]] = []
        self.timer: FakeTimer | None = None

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.calls.append((url, headers, self.timer.now if self.timer else 0.0))
        if not self.responses:
            raise AssertionError(f"unexpected request {url}")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeTimer:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def ok(body: bytes | dict) -> HttpResponse:
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    return HttpResponse(200, {}, body)


def adapter(transport: ScriptedTransport, **kwargs) -> tuple[TravelpayoutsAdapter, FakeTimer]:
    timer = FakeTimer()
    transport.timer = timer
    a = TravelpayoutsAdapter(
        token="test-token",
        clock=FakeClock(T0),
        transport=transport,
        sleep=timer.sleep,
        monotonic=timer.monotonic,
        **kwargs,
    )
    return a, timer


def raw(name: str) -> RawPayload:
    request = ScanRequest("travelpayouts", {})
    return RawPayload("travelpayouts", request, T0, (PAYLOADS / name).read_bytes())


# --- parse ---------------------------------------------------------------------------------


def test_one_way_payload_parses_into_the_cheapest_leg_price_per_route_and_date():
    a, _ = adapter(ScriptedTransport())
    parsed = a.parse(raw("hel-bcn-2026-11-one-way.json"))

    assert parsed.round_trip_prices == []
    legs = {p.departure_date: p for p in parsed.leg_prices}
    assert sorted(legs) == [date(2026, 11, 13), date(2026, 11, 14), date(2026, 11, 15)]
    cheapest = legs[date(2026, 11, 14)]  # 89 VY direct beats 112 AY via ARN on the same day
    assert cheapest.source == "travelpayouts"
    assert cheapest.observed_at == T0
    assert (cheapest.origin, cheapest.destination) == ("HEL", "BCN")
    assert cheapest.price == Decimal("89")
    assert cheapest.currency == "EUR"
    assert cheapest.adults == 1
    assert (cheapest.airline, cheapest.stops, cheapest.duration_min) == ("VY", 0, 250)
    assert legs[date(2026, 11, 15)].stops == 1


def test_round_trip_payload_parses_into_round_trip_prices():
    a, _ = adapter(ScriptedTransport())
    parsed = a.parse(raw("hel-bcn-2026-11-round-trip.json"))

    assert parsed.leg_prices == []
    trips = {(p.departure_date, p.return_date): p for p in parsed.round_trip_prices}
    assert sorted(trips) == [
        (date(2026, 11, 13), date(2026, 11, 16)),
        (date(2026, 11, 14), date(2026, 11, 18)),
    ]
    t = trips[(date(2026, 11, 14), date(2026, 11, 18))]  # 151 beats 233 for the same dates
    assert t.price == Decimal("151")
    assert t.currency == "EUR"
    assert (t.origin, t.destination) == ("HEL", "BCN")
    assert t.stops == 1  # the worse direction: 1 stop out, direct back
    assert t.duration_min == 640


def test_airport_codes_are_used_when_the_request_named_a_city():
    body = json.loads((PAYLOADS / "hel-bcn-2026-11-one-way.json").read_text())
    for row in body["data"]:
        row["destination"] = "BCN"
        row["origin"] = "STO"
        row["origin_airport"] = "ARN"
    a, _ = adapter(ScriptedTransport())
    parsed = a.parse(
        RawPayload("travelpayouts", ScanRequest("travelpayouts", {}), T0, json.dumps(body).encode())
    )
    assert {p.origin for p in parsed.leg_prices} == {"ARN"}


def test_an_empty_answer_parses_into_no_prices():
    a, _ = adapter(ScriptedTransport())
    empty = RawPayload(
        "travelpayouts",
        ScanRequest("travelpayouts", {}),
        T0,
        b'{"success": true, "data": [], "currency": "eur"}',
    )
    parsed = a.parse(empty)
    assert parsed.leg_prices == [] and parsed.round_trip_prices == []


# --- plan ----------------------------------------------------------------------------------

NOV = date(2026, 11, 1)


def test_plan_asks_for_a_month_of_one_way_prices_per_demand():
    a, _ = adapter(ScriptedTransport())
    [req] = a.plan([Demand("HEL", "BCN", NOV)])
    assert req.source == "travelpayouts"
    assert req.params["origin"] == "HEL"
    assert req.params["destination"] == "BCN"
    assert req.params["departure_at"] == "2026-11"
    assert req.params["one_way"] == "true"
    assert req.params["currency"] == "eur"
    assert "token" not in json.dumps(dict(req.params))  # stored with the raw payload


def test_plan_adds_round_trip_prices_for_a_round_trip_demand():
    a, _ = adapter(ScriptedTransport())
    demands = [Demand("HEL", "BCN", NOV, round_trip=True), Demand("HEL", "LIS", NOV)]
    reqs = a.plan(demands)
    kinds = [(r.params["origin"], r.params["destination"], r.params["one_way"]) for r in reqs]
    assert kinds == [("HEL", "BCN", "true"), ("HEL", "BCN", "false"), ("HEL", "LIS", "true")]


def test_plan_never_exceeds_the_budget():
    a, _ = adapter(ScriptedTransport())
    demands = [Demand("HEL", d, NOV) for d in ("BCN", "LIS", "ROM", "ATH")]
    assert len(a.plan(demands, budget=2)) == 2


def test_anywhere_demand_omits_the_destination():
    a, _ = adapter(ScriptedTransport())
    [req] = a.plan([Demand("HEL", None, NOV)])
    assert "destination" not in req.params


# --- fetch: auth, rate limit, backoff --------------------------------------------------------

BODY = (PAYLOADS / "hel-bcn-2026-11-one-way.json").read_bytes()


def test_fetch_returns_the_raw_bytes_and_sends_the_token_in_a_header():
    transport = ScriptedTransport(ok(BODY))
    a, _ = adapter(transport)
    [req] = a.plan([Demand("HEL", "BCN", NOV)])

    got = a.fetch(req)

    assert got.body == BODY
    assert got.fetched_at == T0 and got.request == req
    url, headers, _ = transport.calls[0]
    assert urlsplit(url).path == "/aviasales/v3/prices_for_dates"
    query = parse_qs(urlsplit(url).query)
    assert query["origin"] == ["HEL"] and query["departure_at"] == ["2026-11"]
    assert "token" not in query
    assert headers["X-Access-Token"] == "test-token"


def test_requests_are_spaced_to_respect_the_rate_limit():
    transport = ScriptedTransport(ok(BODY), ok(BODY), ok(BODY))
    a, _ = adapter(transport, requests_per_minute=30)  # one every 2 s
    req = a.plan([Demand("HEL", "BCN", NOV)])[0]

    for _ in range(3):
        a.fetch(req)

    times = [t for _, _, t in transport.calls]
    assert [b - a for a, b in zip(times, times[1:], strict=False)] == [2.0, 2.0]


def test_rate_limited_answers_are_retried_with_backoff():
    transport = ScriptedTransport(
        HttpResponse(429, {"Retry-After": "7"}, b"Too Many Requests"),
        HttpResponse(503, {}, b""),
        ok(BODY),
    )
    a, timer = adapter(transport, backoff_base_s=2.0)
    req = a.plan([Demand("HEL", "BCN", NOV)])[0]

    assert a.fetch(req).body == BODY
    assert len(transport.calls) == 3
    assert timer.slept[:2] == [7.0, 4.0]  # Retry-After honoured, then exponential (2 * 2**1)


def test_persistent_failure_makes_the_source_unavailable():
    transport = ScriptedTransport(*[HttpResponse(502, {}, b"")] * 3)
    a, _ = adapter(transport, max_retries=2)
    req = a.plan([Demand("HEL", "BCN", NOV)])[0]

    with pytest.raises(SourceUnavailable):
        a.fetch(req)
    assert len(transport.calls) == 3


def test_network_errors_are_retried():
    transport = ScriptedTransport(TimeoutError("timed out"), ok(BODY))
    a, _ = adapter(transport)
    req = a.plan([Demand("HEL", "BCN", NOV)])[0]
    assert a.fetch(req).body == BODY


def test_a_bad_token_fails_at_once_without_retrying():
    transport = ScriptedTransport(HttpResponse(401, {}, b"Unauthorized"))
    a, _ = adapter(transport)
    req = a.plan([Demand("HEL", "BCN", NOV)])[0]

    with pytest.raises(SourceUnavailable, match="401"):
        a.fetch(req)
    assert len(transport.calls) == 1


def test_an_unsuccessful_answer_makes_the_source_unavailable():
    transport = ScriptedTransport(ok({"success": False, "data": None, "error": "bad params"}))
    a, _ = adapter(transport)
    req = a.plan([Demand("HEL", "BCN", NOV)])[0]
    with pytest.raises(SourceUnavailable, match="bad params"):
        a.fetch(req)


def test_a_token_is_required():
    with pytest.raises(ValueError):
        TravelpayoutsAdapter(token="", clock=FakeClock(T0))
