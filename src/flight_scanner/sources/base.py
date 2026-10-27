"""The source-adapter interface.

An adapter turns demand into prices in three steps, each separately replayable:

  plan(demands, budget) -> [ScanRequest]   what to ask for (at most `budget` requests);
                                          the scan planner calls it once per scan task
  fetch(request)        -> RawPayload      the source's raw bytes, exactly as received
  parse(raw)            -> ParsedPrices    Leg prices and/or Round-trip prices (and, for a
                                          Verification source, Price insights)

`parse` must be a pure function of the raw payload so history can be rebuilt from the raw store.
Adapters own their rate limiting, backoff and quota accounting inside `fetch`, and raise
`SourceUnavailable` when the source cannot be reached; ingestion isolates that failure.
`RequestRejected` fails only the one request's scan task.
Prices come out in the source's currency and passenger count; dbt staging normalises them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from flight_scanner.watches import Demand


class SourceUnavailable(Exception):
    """The source could not be reached or refused the request (outage, quota, rate limit)."""


class RequestRejected(SourceUnavailable):
    """The source refused this one request as invalid (say, an airport it cannot price) while
    working fine otherwise: only that scan task fails; the source carries on and stays healthy."""


class SourceBlocked(SourceUnavailable):
    """The source turned us away (bot protection, access denied). Never worked around: the
    source is disabled until the owner re-enables it (`python -m flight_scanner unblock`)."""


@dataclass(frozen=True)
class ScanRequest:
    source: str
    params: Mapping[str, Any]  # JSON-serialisable; stored with the raw payload


@dataclass(frozen=True)
class RawPayload:
    source: str
    request: ScanRequest
    fetched_at: datetime
    body: bytes
    content_type: str = "application/json"


@dataclass(frozen=True)
class LegPrice:
    source: str
    observed_at: datetime
    origin: str
    destination: str
    departure_date: date
    price: Decimal
    currency: str
    adults: int = 1
    airline: str | None = None
    stops: int | None = None
    duration_min: int | None = None


@dataclass(frozen=True)
class RoundTripPrice:
    source: str
    observed_at: datetime
    origin: str
    destination: str
    departure_date: date
    return_date: date
    price: Decimal
    currency: str
    adults: int = 1
    airline: str | None = None
    stops: int | None = None
    duration_min: int | None = None


@dataclass(frozen=True)
class PriceInsight:
    """A source's view of one trip's normal price (Google's typical price range), for `adults`
    passengers in `currency`. Its price-history points come out as Fare observations."""

    source: str
    observed_at: datetime
    origin: str
    destination: str
    departure_date: date
    return_date: date | None  # None: one way
    adults: int
    currency: str
    typical_low: Decimal
    typical_high: Decimal
    lowest_price: Decimal | None = None
    price_level: str | None = None
    history_points: int = 0


@dataclass(frozen=True)
class ParsedPrices:
    leg_prices: list[LegPrice] = field(default_factory=list)
    round_trip_prices: list[RoundTripPrice] = field(default_factory=list)
    price_insights: list[PriceInsight] = field(default_factory=list)


@runtime_checkable
class SourceAdapter(Protocol):
    """Optional attribute `wildcard_destinations = True`: the source can answer a Demand with
    destination None (anywhere); the scan planner then collapses wide Watches into one task."""

    name: str

    def plan(self, demands: Sequence[Demand], budget: int | None = None) -> list[ScanRequest]: ...

    def fetch(self, request: ScanRequest) -> RawPayload: ...

    def parse(self, raw: RawPayload) -> ParsedPrices: ...


@dataclass(frozen=True)
class VerificationTrip:
    """One concrete trip to check live, for the Watch's adult count."""

    origin: str
    destination: str
    outbound_date: date
    return_date: date | None
    adults: int = 1


@runtime_checkable
class VerificationSource(Protocol):
    """A live source used only for Verification (not by the scan planner).

    `verification_request` builds the one request that checks a trip; `fetch`/`parse` are as for
    `SourceAdapter`: the live price comes out as the Fare observation at `fetched_at`, plus any
    Price insight. The source declares its free-tier quota; Verification accounts for it."""

    name: str
    monthly_quota: int
    daily_quota: int

    def verification_request(self, trip: VerificationTrip) -> ScanRequest: ...

    def fetch(self, request: ScanRequest) -> RawPayload: ...

    def parse(self, raw: RawPayload) -> ParsedPrices: ...
