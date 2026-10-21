"""Trip patterns: presets the owner picks, normalised to a window, expanded to concrete trips.

Interface (stable for later presets):
  normalise(preset) -> TripPattern
  expand(pattern, today) -> list[Trip]

Walking skeleton supports one preset, a one-way trip on a fixed date. Ticket 04 adds the rest by
widening `TripPreset` into a discriminated union on `preset` and extending `normalise`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, NamedTuple

from pydantic import BaseModel


class OneWayFixed(BaseModel):
    preset: Literal["one_way_fixed"]
    departure: date


TripPreset = OneWayFixed  # becomes Annotated[A | B | ..., Field(discriminator="preset")]


class TripPattern(NamedTuple):
    """Normal form. `stay_nights` is None for one-way trips."""

    departure_start: date
    departure_end: date
    stay_nights: tuple[int, int] | None = None
    return_by: date | None = None


class Trip(NamedTuple):
    outbound: date
    inbound: date | None  # None for one-way


def normalise(preset: TripPreset) -> TripPattern:
    match preset:
        case OneWayFixed(departure=d):
            return TripPattern(departure_start=d, departure_end=d)
    raise TypeError(f"unsupported preset {preset!r}")


def expand(pattern: TripPattern, today: date) -> list[Trip]:
    """Concrete trips for `today`; departures before today are dropped."""
    trips: list[Trip] = []
    day = max(pattern.departure_start, today)
    while day <= pattern.departure_end:
        if pattern.stay_nights is None:
            trips.append(Trip(day, None))
        else:
            lo, hi = pattern.stay_nights
            for n in range(lo, hi + 1):
                ret = day + timedelta(days=n)
                if pattern.return_by is None or ret <= pattern.return_by:
                    trips.append(Trip(day, ret))
        day += timedelta(days=1)
    return trips
