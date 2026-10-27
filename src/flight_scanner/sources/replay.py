"""A fake source that replays recorded payloads, scripted per scan time.

    fake = ReplayAdapter("fake", clock)
    fake.replay(Path("hel-bcn.json"), route=("HEL", "BCN"))          # from now on
    fake.replay(other_bytes, route=("HEL", "BCN"), at=later)          # replaces it from `later`
    fake.fail(at=t0, until=t1)                                        # outage window
    fake.reject(route=("HEL", "XXX"), reason="airport XXX: not flightable")  # invalid request

`fetch` returns the latest scripted payload at or before `clock.now()` for the request's route
(or any route when scripted with `route=None`); with nothing scripted it returns an empty payload.
A wildcard request (destination None) answers with the merged payloads of every scripted route
from that origin. Every fetched request is kept in `requests` (what the source was asked).
The payload format is the "fake" format below; real adapters have their own `parse`.

    {"currency": "EUR", "prices": [{"origin", "destination", "depart_date", "price",
      "airline"?, "transfers"?, "duration"?}], "round_trips": [{... "return_date" ...}]}
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from flight_scanner.clock import Clock
from flight_scanner.sources.base import (
    LegPrice,
    ParsedPrices,
    RawPayload,
    RequestRejected,
    RoundTripPrice,
    ScanRequest,
    SourceUnavailable,
)
from flight_scanner.watches import Demand

EMPTY = b'{"currency": "EUR", "prices": []}'


@dataclass(frozen=True)
class _Entry:
    at: datetime | None  # None: from the beginning of time
    route: tuple[str, str] | None
    body: bytes | None  # None: outage
    until: datetime | None = None
    rejected: str | None = None  # the reason the source rejects requests for this route


class ReplayAdapter:
    wildcard_destinations = True

    def __init__(self, name: str, clock: Clock):
        self.name = name
        self._clock = clock
        self._script: list[_Entry] = []
        self.fetch_count = 0
        self.requests: list[ScanRequest] = []

    # --- scripting -------------------------------------------------------------------------
    def replay(
        self,
        payload: Path | bytes | dict,
        route: tuple[str, str] | None = None,
        at: datetime | None = None,
    ) -> None:
        if isinstance(payload, Path):
            body = payload.read_bytes()
        elif isinstance(payload, dict):
            body = json.dumps(payload).encode()
        else:
            body = payload
        self._script.append(_Entry(at if at is not None else self._clock.now(), route, body))

    def fail(self, at: datetime | None = None, until: datetime | None = None) -> None:
        self._script.append(_Entry(at if at is not None else self._clock.now(), None, None, until))

    def reject(self, route: tuple[str, str], reason: str, at: datetime | None = None) -> None:
        self._script.append(
            _Entry(at if at is not None else self._clock.now(), route, None, rejected=reason)
        )

    @classmethod
    def from_dir(cls, name: str, clock: Clock, directory: Path) -> ReplayAdapter:
        """Replay every `<ORIGIN>-<DESTINATION>*.json` file in `directory` at all times."""
        adapter = cls(name, clock)
        for f in sorted(directory.glob("*.json")):
            o, d = f.stem.upper().split("-")[:2]
            adapter._script.append(_Entry(None, (o, d), f.read_bytes()))
        return adapter

    # --- SourceAdapter -----------------------------------------------------------------------
    def plan(self, demands: Sequence[Demand], budget: int | None = None) -> list[ScanRequest]:
        reqs = [
            ScanRequest(
                self.name,
                {
                    "origin": d.origin,
                    "destination": d.destination,
                    "month": d.month.isoformat()[:7],
                },
            )
            for d in demands
        ]
        return reqs if budget is None else reqs[:budget]

    def fetch(self, request: ScanRequest) -> RawPayload:
        now = self._clock.now()
        self.fetch_count += 1
        self.requests.append(request)
        origin, destination = request.params["origin"], request.params["destination"]
        if destination is not None:
            routes = [(origin, destination)]
        else:
            routes = sorted({e.route for e in self._script if e.route and e.route[0] == origin})
        entries = [self._latest(r, now) for r in routes or [(origin, None)]]
        rejected = [e.rejected for e in entries if e is not None and e.rejected]
        if rejected:
            raise RequestRejected(f"{self.name}: {rejected[0]}")
        if any(e is not None and e.body is None for e in entries):
            raise SourceUnavailable(f"{self.name}: scripted outage")
        bodies = [e.body for e in entries if e is not None]
        if len(bodies) <= 1:
            return RawPayload(self.name, request, now, bodies[0] if bodies else EMPTY)
        docs = [json.loads(b) for b in bodies]
        merged = {
            "currency": docs[0].get("currency", "EUR"),
            "prices": [p for d in docs for p in d.get("prices", [])],
            "round_trips": [p for d in docs for p in d.get("round_trips", [])],
        }
        return RawPayload(self.name, request, now, json.dumps(merged).encode())

    def _latest(self, route: tuple[str, str | None], now: datetime) -> _Entry | None:
        live = [
            e
            for e in self._script
            if (e.at is None or e.at <= now)
            and (e.until is None or now < e.until)
            and (e.route is None or e.route == route)
        ]
        return max(
            live, key=lambda e: e.at or datetime.min.replace(tzinfo=now.tzinfo), default=None
        )

    def parse(self, raw: RawPayload) -> ParsedPrices:
        doc = json.loads(raw.body)
        cur = doc.get("currency", "EUR")
        legs = [
            LegPrice(
                source=raw.source,
                observed_at=raw.fetched_at,
                origin=p["origin"],
                destination=p["destination"],
                departure_date=date.fromisoformat(p["depart_date"]),
                price=Decimal(str(p["price"])),
                currency=cur,
                airline=p.get("airline"),
                stops=p.get("transfers"),
                duration_min=p.get("duration"),
            )
            for p in doc.get("prices", [])
        ]
        rts = [
            RoundTripPrice(
                source=raw.source,
                observed_at=raw.fetched_at,
                origin=p["origin"],
                destination=p["destination"],
                departure_date=date.fromisoformat(p["depart_date"]),
                return_date=date.fromisoformat(p["return_date"]),
                price=Decimal(str(p["price"])),
                currency=cur,
                airline=p.get("airline"),
                stops=p.get("transfers"),
                duration_min=p.get("duration"),
            )
            for p in doc.get("round_trips", [])
        ]
        return ParsedPrices(legs, rts)
