"""SerpApi Google Flights: the live Verification source (never planned for discovery scans).

Endpoint: GET https://serpapi.com/search.json?engine=google_flights
  departure_id, arrival_id   IATA airport codes
  outbound_date, return_date YYYY-MM-DD (no return_date with type=2)
  type                       "1" round trip (Verification default), "2" one way
  adults                     the Watch's adult count
  currency=EUR, hl=en, gl=fi
  api_key                    added to the URL at fetch time only (never in the stored request)
Answer: {search_metadata{status, ...}, search_parameters, best_flights[], other_flights[]
  (each: flights[{departure_airport{id,time}, arrival_airport, airline, duration, ...}],
  layovers, total_duration, price, type, departure_token|booking_token), price_insights
  {lowest_price, price_level, typical_price_range[low, high], price_history[[unix_ts, price]]},
  airports} or {"error": "..."}.

Assumption (not confirmed against the live API: no key here): prices, the typical range and the
price history are for the whole party (`adults` passengers), in `currency`; staging divides by
`adults`. In round-trip mode an itinerary's `price` is the round-trip total; its `flights` are the
outbound only (returns need a second call, which Verification does not spend).

Free tier: 250 searches a month; `monthly_quota` / `daily_quota` (~8 a day) declare it and
`flight_scanner.verification` accounts for every call made. Retries: 429, 5xx and network errors
up to `max_retries` times with exponential backoff; other errors raise `SourceUnavailable`.
"Google Flights hasn't returned any results" is an answer (no price), not an error.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import urlencode

from flight_scanner.clock import Clock
from flight_scanner.sources.base import (
    LegPrice,
    ParsedPrices,
    PriceInsight,
    RawPayload,
    RoundTripPrice,
    ScanRequest,
    SourceUnavailable,
    VerificationTrip,
)
from flight_scanner.sources.travelpayouts import HttpResponse, Transport, urllib_transport

API_URL = "https://serpapi.com/search.json"
NO_RESULTS = "hasn't returned any results"
MONTHLY_QUOTA = 250  # SerpApi free tier
DAILY_QUOTA = 8  # ~250 / 31


class SerpApiAdapter:
    name = "serpapi"

    def __init__(
        self,
        api_key: str,
        clock: Clock,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monthly_quota: int = MONTHLY_QUOTA,
        daily_quota: int = DAILY_QUOTA,
        max_retries: int = 2,
        backoff_base_s: float = 2.0,
        timeout_s: float = 60.0,
        currency: str = "EUR",
        hl: str = "en",
        gl: str = "fi",
    ):
        if not api_key:
            raise ValueError("SerpApi needs an API key (SERPAPI_API_KEY)")
        self._key = api_key
        self._clock = clock
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self.monthly_quota = monthly_quota
        self.daily_quota = daily_quota
        self._max_retries = max_retries
        self._backoff_base = backoff_base_s
        self._timeout = timeout_s
        self._currency = currency
        self._hl = hl
        self._gl = gl

    # --- plan ------------------------------------------------------------------------------
    def plan(self, demands, budget: int | None = None) -> list[ScanRequest]:
        """Verification only: never asked for discovery scans."""
        return []

    def verification_request(self, trip: VerificationTrip) -> ScanRequest:
        params: dict[str, str | int] = {
            "engine": "google_flights",
            "type": "1" if trip.return_date else "2",
            "departure_id": trip.origin,
            "arrival_id": trip.destination,
            "outbound_date": trip.outbound_date.isoformat(),
        }
        if trip.return_date:
            params["return_date"] = trip.return_date.isoformat()
        params.update(adults=trip.adults, currency=self._currency, hl=self._hl, gl=self._gl)
        return ScanRequest(self.name, params)

    # --- fetch -----------------------------------------------------------------------------
    def fetch(self, request: ScanRequest) -> RawPayload:
        url = f"{API_URL}?{urlencode({**request.params, 'api_key': self._key})}"
        attempt = 0
        while True:
            try:
                resp: HttpResponse | None = self._transport(
                    url, {"Accept": "application/json"}, self._timeout
                )
                retryable = resp.status == 429 or resp.status >= 500
                problem = None if not retryable else f"HTTP {resp.status}"
            except OSError as e:
                resp, retryable, problem = None, True, f"{type(e).__name__}: {e}"
            if problem is None:
                break
            if attempt >= self._max_retries:
                raise SourceUnavailable(f"serpapi: {problem} after {attempt + 1} attempt(s)")
            self._sleep(self._backoff_base * 2**attempt)
            attempt += 1
        try:
            doc = json.loads(resp.body)
        except ValueError as e:
            raise SourceUnavailable(f"serpapi: HTTP {resp.status}, answer is not JSON") from e
        error = doc.get("error") if isinstance(doc, dict) else "answer is not an object"
        if error and NO_RESULTS not in str(error):
            raise SourceUnavailable(f"serpapi: {error}")
        if resp.status != 200:
            raise SourceUnavailable(f"serpapi: HTTP {resp.status}")
        return RawPayload(self.name, request, self._clock.now(), resp.body)

    # --- parse (pure on the raw payload and its request) ----------------------------------
    def parse(self, raw: RawPayload) -> ParsedPrices:
        doc = json.loads(raw.body)
        params = raw.request.params
        origin, destination = str(params["departure_id"]), str(params["arrival_id"])
        outbound = date.fromisoformat(str(params["outbound_date"]))
        ret = date.fromisoformat(str(params["return_date"])) if params.get("return_date") else None
        adults = int(params.get("adults", 1))
        currency = str(params.get("currency") or self._currency).upper()

        def price(observed_at: datetime, amount, itinerary: dict | None = None):
            flights = (itinerary or {}).get("flights") or []
            airlines = ", ".join(dict.fromkeys(f["airline"] for f in flights if f.get("airline")))
            common = dict(
                source=raw.source,
                observed_at=observed_at,
                origin=origin,
                destination=destination,
                departure_date=outbound,
                price=Decimal(str(amount)),
                currency=currency,
                adults=adults,
                airline=airlines or None,
                stops=len(flights) - 1 if flights else None,
                duration_min=(itinerary or {}).get("total_duration"),
            )
            return RoundTripPrice(return_date=ret, **common) if ret else LegPrice(**common)

        observations = []
        itineraries = [
            i
            for i in (doc.get("best_flights") or []) + (doc.get("other_flights") or [])
            if i.get("price") is not None
        ]
        if itineraries:
            cheapest = min(itineraries, key=lambda i: i["price"])  # first of equal prices
            observations.append(price(raw.fetched_at, cheapest["price"], cheapest))

        insights: list[PriceInsight] = []
        found = doc.get("price_insights") or {}
        history = [
            (datetime.fromtimestamp(ts, UTC), amount)
            for ts, amount, *_ in found.get("price_history") or []
            if amount is not None
        ]
        history = [(t, a) for t, a in history if t < raw.fetched_at]
        observations += [price(t, a) for t, a in history]
        typical = [Decimal(str(v)) for v in found.get("typical_price_range") or [] if v is not None]
        if typical:
            lowest = found.get("lowest_price")
            insights.append(
                PriceInsight(
                    source=raw.source,
                    observed_at=raw.fetched_at,
                    origin=origin,
                    destination=destination,
                    departure_date=outbound,
                    return_date=ret,
                    adults=adults,
                    currency=currency,
                    typical_low=min(typical),
                    typical_high=max(typical),
                    lowest_price=None if lowest is None else Decimal(str(lowest)),
                    price_level=found.get("price_level"),
                    history_points=len(history),
                )
            )
        return ParsedPrices(
            leg_prices=[o for o in observations if isinstance(o, LegPrice)],
            round_trip_prices=[o for o in observations if isinstance(o, RoundTripPrice)],
            price_insights=insights,
        )
