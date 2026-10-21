"""Wizz Air: live Leg prices per route per day from the public timetable search.

OFF BY DEFAULT. This is an unofficial endpoint used by wizzair.com itself; Wizz Air's terms
forbid automated access to its website, and the site sits behind bot protection. The adapter
only runs when the owner lists it in FS_SOURCES *and* sets FS_ENABLE_WIZZ=true, accepting that
choice (see `.env.example` and ADR-0002). It sends few requests, slowly, and when the bot
protection answers it stops (SourceBlocked) instead of trying to get past it.

API base: https://be.wizzair.com/<version>; the version changes with every site release and is
  read from https://wizzair.com/buildnumber ("SSR https://be.wizzair.com/27.6.0"), unless
  FS_WIZZ_API_URL pins it. A 404 re-reads the version once.
Search:   POST <base>/Api/search/timetable  (JSON body = the stored request params)
  {"flightList": [{"departureStation", "arrivalStation", "from": YYYY-MM-DD, "to": ...}],
   "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0}
  One request per route and month (from today in the current month); no "anywhere" queries.
Answer:   {"outboundFlights": [{"departureStation", "arrivalStation", "departureDate":
  "2026-11-14T00:00:00", "price": {"amount": 12990, "currencyCode": "HUF"}, "priceType":
  "price" | "checkPrice" | "soldOut", "departureDates": [...]}], "returnFlights": null}
  the cheapest direct fare per day for one adult, in the departure country's currency
  (staging converts it). A route Wizz does not fly answers 400 ("InvalidMarket"): stored,
  parsed as no prices.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from flight_scanner.clock import Clock, today
from flight_scanner.scan_planner import Budget
from flight_scanner.sources.base import (
    LegPrice,
    ParsedPrices,
    RawPayload,
    ScanRequest,
    SourceUnavailable,
)
from flight_scanner.sources.polite_http import HttpResponse, PoliteHttp
from flight_scanner.watches import Demand

log = logging.getLogger(__name__)

BUILD_NUMBER_URL = "https://wizzair.com/buildnumber"
AIRLINE = "W6"
NOT_SERVED = {400}
_API_BASE = re.compile(rb"https://be\.wizzair\.com/[0-9][0-9.]*[0-9]")


class WizzAdapter:
    name = "wizz"
    wildcard_destinations = False
    # Planner hooks (see RyanairAdapter): every 2 h per route-month, 20 a run, 300 a day.
    rescan_after = timedelta(hours=2)
    default_budget = Budget(per_run=20, per_day=300)

    def __init__(self, clock: Clock, *, api_url: str | None = None, **http_options):
        self._clock = clock
        self._pinned = bool(api_url)
        self._api_url = api_url.rstrip("/") if api_url else None
        self._http = PoliteHttp(self.name, **http_options)

    # --- plan ------------------------------------------------------------------------------
    def plan(self, demands: Sequence[Demand], budget: int | None = None) -> list[ScanRequest]:
        now = today(self._clock)
        out = []
        for d in demands:
            if d.destination is None:
                continue
            first = d.month.replace(day=1)
            last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            start = max(first, now)
            if start > last:
                continue
            out.append(
                ScanRequest(
                    self.name,
                    {
                        "flightList": [
                            {
                                "departureStation": d.origin,
                                "arrivalStation": d.destination,
                                "from": start.isoformat(),
                                "to": last.isoformat(),
                            }
                        ],
                        "priceType": "regular",
                        "adultCount": 1,
                        "childCount": 0,
                        "infantCount": 0,
                    },
                )
            )
        return out if budget is None else out[:budget]

    # --- fetch -----------------------------------------------------------------------------
    def fetch(self, request: ScanRequest) -> RawPayload:
        body = json.dumps(dict(request.params)).encode()
        resp = self._search(body)
        if resp.status == 404 and not self._pinned:  # a new site release moved the API
            self._api_url = None
            resp = self._search(body)
        if resp.status in NOT_SERVED:
            log.info("wizz: no timetable for %s (HTTP %s)", request.params, resp.status)
        elif resp.status != 200:
            raise SourceUnavailable(f"wizz: unexpected HTTP {resp.status}")
        return RawPayload(self.name, request, self._clock.now(), resp.body)

    def _search(self, body: bytes) -> HttpResponse:
        url = f"{self._base()}/Api/search/timetable"
        return self._http.request("POST", url, {"Content-Type": "application/json"}, body)

    def _base(self) -> str:
        if self._api_url is None:
            resp = self._http.request("GET", BUILD_NUMBER_URL, {"Accept": "text/plain"})
            match = _API_BASE.search(resp.body) if resp.status == 200 else None
            if match is None:
                raise SourceUnavailable(f"wizz: API version not found (HTTP {resp.status})")
            self._api_url = match.group().decode()
        return self._api_url

    # --- parse (pure on the raw bytes) -----------------------------------------------------
    def parse(self, raw: RawPayload) -> ParsedPrices:
        doc = json.loads(raw.body)
        flights = doc.get("outboundFlights") if isinstance(doc, dict) else None
        legs: dict[tuple, LegPrice] = {}
        for f in flights or []:
            price = f.get("price") or {}
            amount = price.get("amount")
            if f.get("priceType") != "price" or not amount:
                continue
            leg = LegPrice(
                source=raw.source,
                observed_at=raw.fetched_at,
                origin=f["departureStation"],
                destination=f["arrivalStation"],
                departure_date=date.fromisoformat(f["departureDate"][:10]),
                price=Decimal(str(amount)),
                currency=str(price["currencyCode"]).upper(),
                airline=AIRLINE,
                stops=0,
            )
            key = (leg.origin, leg.destination, leg.departure_date)
            if key not in legs or leg.price < legs[key].price:
                legs[key] = leg
        return ParsedPrices(leg_prices=list(legs.values()))
