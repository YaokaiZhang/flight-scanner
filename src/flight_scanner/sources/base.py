"""The source-adapter interface.

An adapter turns demand into prices in three steps, each separately replayable:

  plan(demands, budget) -> [ScanRequest]   what to ask for (at most `budget` requests)
  fetch(request)        -> RawPayload      the source's raw bytes, exactly as received
  parse(raw)            -> ParsedPrices    Leg prices and/or Round-trip prices

`parse` must be a pure function of the raw payload so history can be rebuilt from the raw store.
Adapters own their rate limiting, backoff and quota accounting inside `fetch`, and raise
`SourceUnavailable` when the source cannot be reached; ingestion isolates that failure.
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
class ParsedPrices:
    leg_prices: list[LegPrice] = field(default_factory=list)
    round_trip_prices: list[RoundTripPrice] = field(default_factory=list)


@runtime_checkable
class SourceAdapter(Protocol):
    name: str

    def plan(self, demands: Sequence[Demand], budget: int | None = None) -> list[ScanRequest]: ...

    def fetch(self, request: ScanRequest) -> RawPayload: ...

    def parse(self, raw: RawPayload) -> ParsedPrices: ...
