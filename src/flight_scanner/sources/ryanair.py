"""Ryanair: live Leg prices per route per day from the public fare-finder calendar.

OFF BY DEFAULT. This is an unofficial endpoint used by ryanair.com itself; Ryanair's terms
forbid automated access to its website, and it has sued scrapers. The adapter only runs when the
owner lists it in FS_SOURCES *and* sets FS_ENABLE_RYANAIR=true, accepting that choice (see
`.env.example` and ADR-0002). It sends few requests, slowly, and never works around a block.

Endpoint: GET https://www.ryanair.com/api/farfnd/v4/oneWayFares/{origin}/{destination}/
          cheapestPerDay?outboundMonthOfDate=YYYY-MM-01&currency=EUR
Answer:   {"outbound": {"fares": [{"day": "2026-11-14", "departureDate": "...", "arrivalDate":
          "...", "price": {"value": 19.99, "currencyCode": "EUR", ...} | null, "soldOut": bool,
          "unavailable": bool}, ...], "minFare": ..., "maxFare": ...}}
          one entry per day of the month, the cheapest direct one-way fare per adult.
A route Ryanair does not fly answers 404 (or 400) with a JSON error: stored, parsed as no prices.
No "anywhere" queries: one request per route and month.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from flight_scanner.clock import Clock
from flight_scanner.scan_planner import Budget
from flight_scanner.sources.base import (
    LegPrice,
    ParsedPrices,
    RawPayload,
    ScanRequest,
    SourceUnavailable,
)
from flight_scanner.sources.polite_http import PoliteHttp
from flight_scanner.watches import Demand

log = logging.getLogger(__name__)

BASE_URL = "https://www.ryanair.com/api/farfnd/v4/oneWayFares"
AIRLINE = "FR"
NOT_SERVED = {400, 404}  # route not flown: an empty calendar, not a failure


class RyanairAdapter:
    name = "ryanair"
    wildcard_destinations = False
    # Planner hooks: scan each route-month at most every 2 h (spec: airline cadence 1-2 h) and,
    # unless FS_SCAN_BUDGETS says otherwise, at most 20 requests a run and 300 a day.
    rescan_after = timedelta(hours=2)
    default_budget = Budget(per_run=20, per_day=300)

    def __init__(self, clock: Clock, *, currency: str = "EUR", **http_options):
        self._clock = clock
        self._currency = currency
        self._http = PoliteHttp(self.name, **http_options)

    def plan(self, demands: Sequence[Demand], budget: int | None = None) -> list[ScanRequest]:
        out = [
            ScanRequest(
                self.name,
                {
                    "origin": d.origin,
                    "destination": d.destination,
                    "month": d.month.replace(day=1).isoformat(),
                    "currency": self._currency,
                },
            )
            for d in demands
            if d.destination is not None
        ]
        return out if budget is None else out[:budget]

    def fetch(self, request: ScanRequest) -> RawPayload:
        p = request.params
        query = urlencode({"outboundMonthOfDate": p["month"], "currency": p["currency"]})
        url = f"{BASE_URL}/{p['origin']}/{p['destination']}/cheapestPerDay?{query}"
        resp = self._http.request("GET", url)
        if resp.status in NOT_SERVED:
            log.info(
                "ryanair: no calendar for %s-%s (HTTP %s)",
                p["origin"],
                p["destination"],
                resp.status,
            )
        elif resp.status != 200:
            raise SourceUnavailable(f"ryanair: unexpected HTTP {resp.status}")
        return RawPayload(self.name, request, self._clock.now(), resp.body)

    def parse(self, raw: RawPayload) -> ParsedPrices:
        doc = json.loads(raw.body)
        outbound = doc.get("outbound") if isinstance(doc, dict) else None
        if not outbound:
            return ParsedPrices()
        params = raw.request.params
        legs: list[LegPrice] = []
        for fare in outbound.get("fares") or []:
            price = fare.get("price")
            if not price or fare.get("soldOut") or fare.get("unavailable"):
                continue
            if price.get("value") is None:
                continue
            legs.append(
                LegPrice(
                    source=raw.source,
                    observed_at=raw.fetched_at,
                    origin=_airport(fare, "departureAirport") or params.get("origin"),
                    destination=_airport(fare, "arrivalAirport") or params.get("destination"),
                    departure_date=date.fromisoformat(fare["day"]),
                    price=Decimal(str(price["value"])),
                    currency=str(price.get("currencyCode") or self._currency).upper(),
                    airline=AIRLINE,
                    stops=0,
                )
            )
        return ParsedPrices(leg_prices=legs)


def _airport(fare: dict, key: str) -> str | None:
    value = fare.get(key)
    return value.get("iataCode") if isinstance(value, dict) else None
