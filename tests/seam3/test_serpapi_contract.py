"""Seam 3: the SerpApi Google Flights adapter's contract (Verification only).

`verification_request` builds one round-trip (or one-way) search for a trip and the Watch's
adults; `fetch` is driven through a scripted HTTP transport (the API key goes only into the URL,
never into the stored request); `parse` turns recorded answers into the live price, the Price
insight and its price-history points (as Fare observations).

The recorded payloads follow SerpApi's documented `google_flights` answer (search_metadata,
search_parameters, best_flights/other_flights, price_insights, airports); they were not captured
from the live API (no key here).
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from flight_scanner.clock import FakeClock
from flight_scanner.config import Settings
from flight_scanner.sources.base import (
    PriceInsight,
    RawPayload,
    ScanRequest,
    SourceUnavailable,
    VerificationTrip,
)
from flight_scanner.sources.registry import build_verifier
from flight_scanner.sources.serpapi import SerpApiAdapter
from flight_scanner.sources.travelpayouts import HttpResponse

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "serpapi"
T0 = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
NOV20, NOV27 = date(2026, 11, 20), date(2026, 11, 27)
ROUND_TRIP = VerificationTrip("HEL", "BCN", NOV20, NOV27, adults=2)
ONE_WAY = VerificationTrip("HEL", "BCN", NOV20, None, adults=1)


class ScriptedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def answer(name: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, (PAYLOADS / name).read_bytes())


def adapter(transport=None, **kw) -> SerpApiAdapter:
    return SerpApiAdapter(
        api_key="test-key", clock=FakeClock(T0), transport=transport, sleep=lambda s: None, **kw
    )


def raw(name: str, trip: VerificationTrip = ROUND_TRIP) -> RawPayload:
    request = adapter().verification_request(trip)
    return RawPayload("serpapi", request, T0, (PAYLOADS / name).read_bytes())


def test_a_round_trip_request_asks_google_flights_for_the_trip_and_adults_without_the_key():
    request = adapter().verification_request(ROUND_TRIP)

    assert request == ScanRequest(
        "serpapi",
        {
            "engine": "google_flights",
            "type": "1",
            "departure_id": "HEL",
            "arrival_id": "BCN",
            "outbound_date": "2026-11-20",
            "return_date": "2026-11-27",
            "adults": 2,
            "currency": "EUR",
            "hl": "en",
            "gl": "fi",
        },
    )


def test_a_one_way_trip_is_searched_one_way():
    params = adapter().verification_request(ONE_WAY).params
    assert params["type"] == "2"
    assert "return_date" not in params


def test_fetch_puts_the_key_in_the_url_only():
    transport = ScriptedTransport(answer("hel-bcn-2026-11-20-round-trip.json"))
    a = adapter(transport)

    raw_payload = a.fetch(a.verification_request(ROUND_TRIP))

    query = parse_qs(urlsplit(transport.urls[0]).query)
    assert transport.urls[0].startswith("https://serpapi.com/search.json?")
    assert query["api_key"] == ["test-key"]
    assert query["engine"] == ["google_flights"]
    assert "api_key" not in raw_payload.request.params
    assert raw_payload.fetched_at == T0
    assert json.loads(raw_payload.body)["price_insights"]["lowest_price"] == 290


def test_parse_gives_the_cheapest_live_round_trip_price_for_all_adults():
    parsed = adapter().parse(raw("hel-bcn-2026-11-20-round-trip.json"))

    [live] = [p for p in parsed.round_trip_prices if p.observed_at == T0]
    assert (live.origin, live.destination, live.departure_date, live.return_date) == (
        "HEL",
        "BCN",
        NOV20,
        NOV27,
    )
    assert (live.price, live.currency, live.adults) == (Decimal("290"), "EUR", 2)
    assert (live.airline, live.stops, live.duration_min) == ("SAS", 1, 380)
    assert parsed.leg_prices == []


def test_parse_gives_the_price_insight_typical_range():
    parsed = adapter().parse(raw("hel-bcn-2026-11-20-round-trip.json"))

    assert parsed.price_insights == [
        PriceInsight(
            source="serpapi",
            observed_at=T0,
            origin="HEL",
            destination="BCN",
            departure_date=NOV20,
            return_date=NOV27,
            adults=2,
            currency="EUR",
            typical_low=Decimal("380"),
            typical_high=Decimal("520"),
            lowest_price=Decimal("290"),
            price_level="low",
            history_points=8,
        )
    ]


def test_price_history_points_become_fare_observations_of_the_trip_at_their_own_time():
    parsed = adapter().parse(raw("hel-bcn-2026-11-20-round-trip.json"))

    history = sorted(
        (p.observed_at, p.price) for p in parsed.round_trip_prices if p.observed_at < T0
    )
    assert len(history) == 8  # the point at the request instant is the live price, not history
    assert history[0] == (datetime(2026, 10, 13, tzinfo=UTC), Decimal("460"))
    assert history[-1] == (datetime(2026, 10, 20, tzinfo=UTC), Decimal("410"))
    assert {(p.adults, p.currency, p.return_date) for p in parsed.round_trip_prices} == {
        (2, "EUR", NOV27)
    }


def test_an_answer_without_price_history_still_gives_the_typical_range():
    parsed = adapter().parse(raw("hel-bcn-2026-11-20-round-trip-no-history.json"))

    [insight] = parsed.price_insights
    assert (insight.typical_low, insight.typical_high, insight.history_points) == (
        Decimal("380"),
        Decimal("520"),
        0,
    )
    assert [p.observed_at for p in parsed.round_trip_prices] == [T0]


def test_a_one_way_answer_gives_a_live_leg_price():
    parsed = adapter().parse(raw("hel-bcn-2026-11-20-one-way.json", ONE_WAY))

    [leg] = parsed.leg_prices
    assert (leg.origin, leg.destination, leg.departure_date, leg.price, leg.adults) == (
        "HEL",
        "BCN",
        NOV20,
        Decimal("129"),
        1,
    )
    assert parsed.round_trip_prices == []
    [insight] = parsed.price_insights
    assert (insight.return_date, insight.typical_low, insight.typical_high) == (
        None,
        Decimal("110"),
        Decimal("170"),
    )


def test_no_results_is_an_answer_with_no_price():
    transport = ScriptedTransport(answer("hel-bcn-no-results.json"))
    a = adapter(transport)

    parsed = a.parse(a.fetch(a.verification_request(ROUND_TRIP)))

    assert (parsed.leg_prices, parsed.round_trip_prices, parsed.price_insights) == ([], [], [])


def test_an_error_answer_makes_the_source_unavailable():
    a = adapter(ScriptedTransport(answer("invalid-key.json", status=401)))
    with pytest.raises(SourceUnavailable, match="Invalid API key"):
        a.fetch(a.verification_request(ROUND_TRIP))


def test_rate_limits_and_server_errors_are_retried():
    transport = ScriptedTransport(
        HttpResponse(429, {}, b'{"error": "rate"}'),
        OSError("reset"),
        answer("hel-bcn-2026-11-20-round-trip.json"),
    )
    a = adapter(transport, max_retries=2)

    a.fetch(a.verification_request(ROUND_TRIP))

    assert len(transport.urls) == 3


def test_the_free_tier_quota_is_250_a_month_and_8_a_day_by_default():
    a = adapter()
    assert (a.monthly_quota, a.daily_quota) == (250, 8)


def test_the_verifier_is_off_unless_configured_and_its_budget_can_be_lowered():
    clock = FakeClock(T0)
    assert build_verifier(Settings.from_env({}), clock) is None
    verifier = build_verifier(
        Settings.from_env(
            {"FS_VERIFIER": "serpapi", "SERPAPI_API_KEY": "k", "FS_SERPAPI_DAILY_BUDGET": "5"}
        ),
        clock,
    )
    assert (verifier.name, verifier.daily_quota, verifier.monthly_quota) == ("serpapi", 5, 250)
    with pytest.raises(ValueError, match="SERPAPI_API_KEY"):
        build_verifier(Settings.from_env({"FS_VERIFIER": "serpapi"}), clock)
