"""Travelpayouts (Aviasales Data API): cached Leg prices and Round-trip prices.

Endpoint: GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates
  origin, destination   IATA city or airport codes (destination omitted: anywhere)
  departure_at          YYYY-MM (a whole month of departures per call)
  one_way               "true" -> one-way tickets (Leg prices); "false" -> return tickets
                        (Round-trip prices, any return date)
  currency=eur, sorting=price, direct=false, limit, page
  auth                  X-Access-Token header (the token never enters the stored request)
Answer: {"success": true, "data": [{origin, destination, origin_airport, destination_airport,
  price, airline, flight_number, departure_at, return_at, transfers, return_transfers,
  duration, duration_to, duration_back, link}], "currency": "eur"}
Prices are per adult, from a cache of Aviasales searches made in the last ~48 h.

Rate limiting: at most `requests_per_minute` calls (spaced evenly). Backoff: 429, 5xx and network
errors are retried with exponential backoff (honouring Retry-After) up to `max_retries` times;
401/403 and other 4xx fail at once. Exhausted retries or `success: false` raise
`SourceUnavailable`, which ingestion isolates.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from flight_scanner.clock import Clock
from flight_scanner.sources.base import (
    LegPrice,
    ParsedPrices,
    RawPayload,
    RoundTripPrice,
    ScanRequest,
    SourceUnavailable,
)
from flight_scanner.watches import Demand

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
PAGE_LIMIT = 1000


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, dict[str, str], float], HttpResponse]


def urllib_transport(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
    """The real HTTP call (stdlib only), gunzipping the body. Network failures raise OSError."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, resp_headers, body = resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        status, resp_headers, body = e.code, dict(e.headers or {}), e.read() or b""
    if {k.lower(): v for k, v in resp_headers.items()}.get("content-encoding") == "gzip":
        body = gzip.decompress(body)
    return HttpResponse(status, resp_headers, body)


class TravelpayoutsAdapter:
    name = "travelpayouts"

    def __init__(
        self,
        token: str,
        clock: Clock,
        *,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        requests_per_minute: float = 60,
        max_retries: int = 4,
        backoff_base_s: float = 2.0,
        backoff_max_s: float = 60.0,
        timeout_s: float = 30.0,
        currency: str = "eur",
    ):
        if not token:
            raise ValueError("Travelpayouts needs an API token (TRAVELPAYOUTS_TOKEN)")
        self._token = token
        self._clock = clock
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._interval = 60.0 / requests_per_minute
        self._max_retries = max_retries
        self._backoff_base = backoff_base_s
        self._backoff_max = backoff_max_s
        self._timeout = timeout_s
        self._currency = currency
        self._last_request_at: float | None = None

    # --- plan ------------------------------------------------------------------------------
    def plan(self, demands: Sequence[Demand], budget: int | None = None) -> list[ScanRequest]:
        """One one-way request per demand (Leg prices); plus a return-ticket request for each
        demand whose reverse route is also demanded (Round-trip prices). Interleaved per demand
        so a budget cut keeps both kinds for the first demands."""
        reverse = {(d.destination, d.origin) for d in demands}
        out: list[ScanRequest] = []
        for d in demands:
            month = d.month.isoformat()[:7]
            out.append(self._request(d, month, one_way=True))
            if d.destination is not None and (d.origin, d.destination) in reverse:
                out.append(self._request(d, month, one_way=False))
        return out if budget is None else out[:budget]

    def _request(self, d: Demand, month: str, one_way: bool) -> ScanRequest:
        params: dict[str, str | int] = {"origin": d.origin}
        if d.destination is not None:
            params["destination"] = d.destination
        params.update(
            departure_at=month,
            one_way="true" if one_way else "false",
            direct="false",
            currency=self._currency,
            sorting="price",
            limit=PAGE_LIMIT,
            page=1,
        )
        return ScanRequest(self.name, params)

    # --- fetch -----------------------------------------------------------------------------
    def fetch(self, request: ScanRequest) -> RawPayload:
        url = f"{API_URL}?{urlencode(dict(request.params))}"
        headers = {
            "X-Access-Token": self._token,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",  # recommended by the API docs
        }
        attempt = 0
        while True:
            self._wait_for_slot()
            try:
                resp = self._transport(url, headers, self._timeout)
                problem = None if resp.status == 200 else f"HTTP {resp.status}"
                retryable = resp.status == 429 or resp.status >= 500
            except OSError as e:
                resp, problem, retryable = None, f"{type(e).__name__}: {e}", True
            if problem is None:
                break
            if not retryable or attempt >= self._max_retries:
                raise SourceUnavailable(f"travelpayouts: {problem} after {attempt + 1} attempt(s)")
            self._sleep(self._backoff(attempt, resp))
            attempt += 1
        try:
            doc = json.loads(resp.body)
        except ValueError as e:
            raise SourceUnavailable(f"travelpayouts: answer is not JSON ({e})") from e
        if not isinstance(doc, dict) or doc.get("success") is not True:
            error = doc.get("error") if isinstance(doc, dict) else None
            raise SourceUnavailable(f"travelpayouts: request failed ({error or 'success=false'})")
        return RawPayload(self.name, request, self._clock.now(), resp.body)

    def _wait_for_slot(self) -> None:
        now = self._monotonic()
        if self._last_request_at is not None:
            wait = self._last_request_at + self._interval - now
            if wait > 0:
                self._sleep(wait)
                now = self._monotonic()
        self._last_request_at = now

    def _backoff(self, attempt: int, resp: HttpResponse | None) -> float:
        if resp is not None:
            retry_after = {k.lower(): v for k, v in resp.headers.items()}.get("retry-after")
            if retry_after is not None:
                try:
                    return min(float(retry_after), self._backoff_max)
                except ValueError:
                    pass
        return min(self._backoff_base * 2**attempt, self._backoff_max)

    # --- parse (pure on the raw bytes) -----------------------------------------------------
    def parse(self, raw: RawPayload) -> ParsedPrices:
        doc = json.loads(raw.body)
        currency = str(doc.get("currency") or self._currency).upper()
        legs: dict[tuple, LegPrice] = {}
        trips: dict[tuple, RoundTripPrice] = {}
        for row in doc.get("data") or []:
            origin = row.get("origin_airport") or row["origin"]
            destination = row.get("destination_airport") or row["destination"]
            departure = _local_date(row["departure_at"])
            price = Decimal(str(row["price"]))
            airline = row.get("airline") or None
            if row.get("return_at"):
                ret = _local_date(row["return_at"])
                trip = RoundTripPrice(
                    source=raw.source,
                    observed_at=raw.fetched_at,
                    origin=origin,
                    destination=destination,
                    departure_date=departure,
                    return_date=ret,
                    price=price,
                    currency=currency,
                    airline=airline,
                    stops=_max_int(row.get("transfers"), row.get("return_transfers")),
                    duration_min=_int(row.get("duration")),
                )
                key = (origin, destination, departure, ret)
                if key not in trips or price < trips[key].price:
                    trips[key] = trip
            else:
                leg = LegPrice(
                    source=raw.source,
                    observed_at=raw.fetched_at,
                    origin=origin,
                    destination=destination,
                    departure_date=departure,
                    price=price,
                    currency=currency,
                    airline=airline,
                    stops=_int(row.get("transfers")),
                    duration_min=_int(row.get("duration_to") or row.get("duration")),
                )
                key = (origin, destination, departure)
                if key not in legs or price < legs[key].price:
                    legs[key] = leg
        return ParsedPrices(list(legs.values()), list(trips.values()))


def _local_date(value: str) -> date:
    """The calendar date at the departure airport (Travelpayouts gives local time + offset)."""
    return date.fromisoformat(value[:10])


def _int(value) -> int | None:
    return None if value is None or value == "" else int(value)


def _max_int(*values) -> int | None:
    ints = [_int(v) for v in values if _int(v) is not None]
    return max(ints) if ints else None
