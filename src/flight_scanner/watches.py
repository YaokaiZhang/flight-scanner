"""Watches: persistence of what the owner wants, and the demand it generates.

Public interface:
  WatchSpec / Watch            - input and stored shapes (pydantic; reused by the HTTP API)
  validate(spec, reference)    - Place checks needing reference data; raises InvalidWatch
  create / update / get / list_all / set_status / delete - persistence (create/update validate)
  refresh_expiry(conn, today)  - mark Watches whose departure window has fully passed as expired
  slots(conn, today, reference) - concrete (watch, origin, destination, outbound, return) trips;
                                 Places are resolved here, on every call, so reference-data
                                 changes reach existing Watches without editing them
  Demand                       - what a source is asked to price (built by `scan_planner`)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, NamedTuple

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from flight_scanner import trip_patterns
from flight_scanner.clock import Clock
from flight_scanner.places import PlaceSet, ReferenceData, default_reference
from flight_scanner.trip_patterns import TripPreset


class PriceThreshold(BaseModel):
    amount_eur: float = Field(gt=0)
    basis: Literal["total", "per_adult"] = "total"


Channel = Literal["email", "telegram"]


class WatchSpec(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    origins: PlaceSet
    destinations: PlaceSet
    trip_pattern: TripPreset
    adults: int = Field(default=1, ge=1, le=9)
    price_threshold: PriceThreshold | None = None
    sensitivity_pct: int = Field(default=30, ge=1, le=90)  # % below Baseline for a Deal
    # "immediate": an Alert per Deal as found; "digest": one daily Digest (see `digests`).
    delivery: Literal["immediate", "digest"] = "immediate"
    # Where Alerts go: email, Telegram or both.
    channels: list[Channel] = Field(default_factory=lambda: ["email", "telegram"], min_length=1)

    @field_validator("channels")
    @classmethod
    def _distinct_channels(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class InvalidWatch(ValueError):
    """A WatchSpec that is well-formed but not acceptable (e.g. names unknown Places)."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["msg"] for e in errors))
        self.errors = errors


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
    """What a source adapter is asked to price (one scan task). `destination` None means
    anywhere. `round_trip`: a slot returns from destination to origin, so single-ticket
    Round-trip prices are wanted too (the return leg is its own Demand)."""

    origin: str
    destination: str | None
    month: date  # first day of the departure month
    round_trip: bool = False


_COLUMNS = (
    "id, name, origins, destinations, trip_pattern, adults, price_threshold_eur, "
    "price_threshold_basis, sensitivity_pct, channels, status, delivery, created_at, updated_at"
)


def _from_row(row: dict) -> Watch:
    threshold = None
    if row["price_threshold_eur"] is not None:
        threshold = PriceThreshold(
            amount_eur=float(row["price_threshold_eur"]), basis=row["price_threshold_basis"]
        )
    return Watch(**{**row, "price_threshold": threshold})


def validate(spec: WatchSpec, reference: ReferenceData | None = None) -> None:
    """Every Place must exist, and each side must resolve to at least one airport."""
    ref = reference or default_reference()
    errors: list[dict] = []
    for side in ("origins", "destinations"):
        place_set: PlaceSet = getattr(spec, side)
        unknown = ref.unknown(place_set)
        for p in unknown:
            errors.append(
                {
                    "type": "unknown_place",
                    "loc": ["body", side],
                    "msg": f"{side}: unknown {p.kind} {p.code!r}",
                    "input": p.model_dump(),
                }
            )
        if not unknown and not ref.resolve(place_set):
            errors.append(
                {
                    "type": "no_airports",
                    "loc": ["body", side],
                    "msg": f"{side}: resolves to no airports",
                    "input": place_set.model_dump(),
                }
            )
    if errors:
        raise InvalidWatch(errors)


def _values(spec: WatchSpec) -> dict:
    t = spec.price_threshold
    return {
        "name": spec.name,
        "origins": Jsonb(spec.origins.model_dump(mode="json")),
        "destinations": Jsonb(spec.destinations.model_dump(mode="json")),
        "trip_pattern": Jsonb(spec.trip_pattern.model_dump(mode="json")),
        "adults": spec.adults,
        "price_threshold_eur": t.amount_eur if t else None,
        "price_threshold_basis": t.basis if t else None,
        "sensitivity_pct": spec.sensitivity_pct,
        "channels": spec.channels,
        "delivery": spec.delivery,
    }


def create(
    conn: psycopg.Connection,
    spec: WatchSpec,
    clock: Clock,
    reference: ReferenceData | None = None,
) -> Watch:
    validate(spec, reference)
    now = clock.now()
    values = {**_values(spec), "created_at": now, "updated_at": now}
    cols = ", ".join(values)
    params = ", ".join(f"%({k})s" for k in values)
    row = conn.execute(
        f"INSERT INTO app.watches ({cols}) VALUES ({params}) RETURNING {_COLUMNS}", values
    ).fetchone()
    return _from_row(row)


def update(
    conn: psycopg.Connection,
    watch_id: int,
    spec: WatchSpec,
    clock: Clock,
    reference: ReferenceData | None = None,
) -> Watch | None:
    """Replace a Watch's settings (status and creation time are kept). None if it does not exist."""
    validate(spec, reference)
    values = {**_values(spec), "updated_at": clock.now()}
    assignments = ", ".join(f"{k} = %({k})s" for k in values)
    row = conn.execute(
        f"UPDATE app.watches SET {assignments} WHERE id = %(id)s RETURNING {_COLUMNS}",
        {**values, "id": watch_id},
    ).fetchone()
    return _from_row(row) if row else None


def set_status(
    conn: psycopg.Connection, watch_id: int, status: Literal["active", "paused"], clock: Clock
) -> Watch | None:
    """Pause or resume a Watch. None if it does not exist."""
    row = conn.execute(
        f"UPDATE app.watches SET status = %s, updated_at = %s WHERE id = %s RETURNING {_COLUMNS}",
        (status, clock.now(), watch_id),
    ).fetchone()
    return _from_row(row) if row else None


def delete(conn: psycopg.Connection, watch_id: int) -> bool:
    """Delete a Watch with its slots, Deals and Alerts. False if it did not exist."""
    return conn.execute("DELETE FROM app.watches WHERE id = %s", (watch_id,)).rowcount > 0


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


def slots(
    conn: psycopg.Connection, today: date, reference: ReferenceData | None = None
) -> list[WatchSlot]:
    ref = reference or default_reference()
    out: list[WatchSlot] = []
    for w in list_all(conn):
        if w.status != "active":
            continue
        pattern = trip_patterns.normalise(w.trip_pattern)
        trips = trip_patterns.expand(pattern, today)
        destinations = sorted(ref.resolve(w.destinations))
        for o in sorted(ref.resolve(w.origins)):
            for d in destinations:
                if o == d:
                    continue
                out.extend(WatchSlot(w.id, o, d, t.outbound, t.inbound) for t in trips)
    return out
