"""Watches: persistence of what the owner wants, and the demand it generates.

Public interface:
  WatchSpec / Watch            - input and stored shapes (pydantic; reused by the HTTP API)
  create / get / list_all      - persistence
  refresh_expiry(conn, today)  - mark Watches whose departure window has fully passed as expired
  slots(conn, today)           - concrete (watch, origin, destination, outbound, return) trips
  demands(slots)               - de-duplicated (origin, destination, month) for source planning
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, NamedTuple

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from flight_scanner import places, trip_patterns
from flight_scanner.clock import Clock
from flight_scanner.places import PlaceSet
from flight_scanner.trip_patterns import TripPreset


class PriceThreshold(BaseModel):
    amount_eur: float = Field(gt=0)
    basis: Literal["total", "per_adult"] = "total"


class WatchSpec(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    origins: PlaceSet
    destinations: PlaceSet
    trip_pattern: TripPreset
    adults: int = Field(default=1, ge=1, le=9)
    price_threshold: PriceThreshold | None = None
    # "immediate": an Alert per Deal as found; "digest": one daily Digest (see `digests`).
    delivery: Literal["immediate", "digest"] = "immediate"


class Watch(WatchSpec):
    id: int
    status: Literal["active", "paused", "expired"]
    created_at: datetime
    updated_at: datetime


class WatchSlot(NamedTuple):
    watch_id: int
    origin: str
    destination: str
    outbound_date: date
    return_date: date | None


class Demand(NamedTuple):
    """What a source adapter is asked to price. `destination` None means anywhere."""

    origin: str
    destination: str | None
    month: date  # first day of the departure month


_COLUMNS = (
    "id, name, origins, destinations, trip_pattern, adults, price_threshold_eur, "
    "price_threshold_basis, status, delivery, created_at, updated_at"
)


def _from_row(row: dict) -> Watch:
    threshold = None
    if row["price_threshold_eur"] is not None:
        threshold = PriceThreshold(
            amount_eur=float(row["price_threshold_eur"]), basis=row["price_threshold_basis"]
        )
    return Watch(**{**row, "price_threshold": threshold})


def create(conn: psycopg.Connection, spec: WatchSpec, clock: Clock) -> Watch:
    now = clock.now()
    t = spec.price_threshold
    row = conn.execute(
        f"""INSERT INTO app.watches (name, origins, destinations, trip_pattern, adults,
                price_threshold_eur, price_threshold_basis, delivery, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}""",
        (
            spec.name,
            Jsonb(spec.origins.model_dump(mode="json")),
            Jsonb(spec.destinations.model_dump(mode="json")),
            Jsonb(spec.trip_pattern.model_dump(mode="json")),
            spec.adults,
            t.amount_eur if t else None,
            t.basis if t else None,
            spec.delivery,
            now,
            now,
        ),
    ).fetchone()
    return _from_row(row)


def get(conn: psycopg.Connection, watch_id: int) -> Watch | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM app.watches WHERE id = %s", (watch_id,)).fetchone()
    return _from_row(row) if row else None


def list_all(conn: psycopg.Connection) -> list[Watch]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM app.watches ORDER BY created_at DESC, id DESC")
    return [_from_row(r) for r in rows]


def refresh_expiry(conn: psycopg.Connection, today: date) -> None:
    """Mark Watches whose departure window has fully passed as expired (paused ones too); an
    expired Watch whose window is open again (its Trip pattern was edited) becomes active."""
    for w in list_all(conn):
        expired = trip_patterns.is_expired(trip_patterns.normalise(w.trip_pattern), today)
        status = "expired" if expired else ("active" if w.status == "expired" else w.status)
        if status != w.status:
            conn.execute("UPDATE app.watches SET status = %s WHERE id = %s", (status, w.id))


def slots(conn: psycopg.Connection, today: date) -> list[WatchSlot]:
    out: list[WatchSlot] = []
    for w in list_all(conn):
        if w.status != "active":
            continue
        pattern = trip_patterns.normalise(w.trip_pattern)
        trips = trip_patterns.expand(pattern, today)
        for o in sorted(places.resolve(w.origins)):
            for d in sorted(places.resolve(w.destinations)):
                if o == d:
                    continue
                out.extend(WatchSlot(w.id, o, d, t.outbound, t.inbound) for t in trips)
    return out


def demands(watch_slots: list[WatchSlot]) -> list[Demand]:
    """Leg demand for every slot: the outbound leg and, for round trips, the return leg."""
    seen: set[Demand] = set()
    for s in watch_slots:
        seen.add(Demand(s.origin, s.destination, s.outbound_date.replace(day=1)))
        if s.return_date is not None:
            seen.add(Demand(s.destination, s.origin, s.return_date.replace(day=1)))
    return sorted(seen)
