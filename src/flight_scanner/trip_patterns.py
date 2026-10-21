"""Trip patterns: presets the owner picks, normalised to a window, expanded to concrete trips.

Interface:
  TripPreset                      - the presets a Watch stores (discriminated on `preset`)
  normalise(preset) -> TripPattern
  window(pattern, today) -> (first, last) departure date for `today`
  expand(pattern, today) -> list[Trip]
  is_expired(pattern, today)      - the departure window has fully passed
  resolve(preset, today) -> Resolution   - what the editor shows: window, Stay nights, trips

Normal form: a departure window (absolute dates, or rolling offsets in days from today), Stay
nights `(min, max)` (None for one-way) and an optional latest return date. Only the departure must
fall in the window; the return may land after it. Stay nights are nights between the outbound and
the return date (22 Nov -> 25 Nov = 3).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Annotated, Literal, NamedTuple

from pydantic import BaseModel, Field, model_validator

MAX_STAY_NIGHTS = 60


class StayNights(BaseModel):
    min: int = Field(ge=0, le=MAX_STAY_NIGHTS)
    max: int = Field(ge=0, le=MAX_STAY_NIGHTS)

    @model_validator(mode="after")
    def _ordered(self) -> StayNights:
        if self.min > self.max:
            raise ValueError("stay_nights.min must not exceed stay_nights.max")
        return self


class _RoundTripOptions(BaseModel):
    stay_nights: StayNights
    return_by: date | None = None


class OneWayFixed(BaseModel):
    """One-way on a fixed date."""

    preset: Literal["one_way_fixed"]
    departure: date


class FixedDates(BaseModel):
    """Round trip on fixed dates (zero-width window, min = max Stay nights)."""

    preset: Literal["fixed_dates"]
    departure: date
    return_date: date

    @model_validator(mode="after")
    def _return_after_departure(self) -> FixedDates:
        if self.return_date < self.departure:
            raise ValueError("return_date must not be before departure")
        return self


class Month(_RoundTripOptions):
    """N-M Stay nights departing any day in a calendar month (`"2026-11"`)."""

    preset: Literal["month"]
    month: Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class Rolling(_RoundTripOptions):
    """N-M Stay nights departing between today and today + `within_days`; slides daily."""

    preset: Literal["rolling"]
    within_days: int = Field(ge=0, le=365)


class FixedDeparture(_RoundTripOptions):
    """A fixed departure date with N-M Stay nights."""

    preset: Literal["fixed_departure"]
    departure: date


class AroundDate(_RoundTripOptions):
    """N-M Stay nights departing within `flex_days` either side of a target date."""

    preset: Literal["around_date"]
    target: date
    flex_days: int = Field(ge=0, le=30)


_Presets = OneWayFixed | FixedDates | Month | Rolling | FixedDeparture | AroundDate
TripPreset = Annotated[_Presets, Field(discriminator="preset")]


class AbsoluteWindow(NamedTuple):
    start: date
    end: date


class RollingWindow(NamedTuple):
    """Departures from today + start_days to today + end_days; slides daily."""

    start_days: int
    end_days: int


class TripPattern(NamedTuple):
    """Normal form. `stay_nights` is None for one-way trips."""

    departure_window: AbsoluteWindow | RollingWindow
    stay_nights: tuple[int, int] | None = None
    return_by: date | None = None

    @property
    def kind(self) -> Literal["one_way", "round_trip"]:
        return "one_way" if self.stay_nights is None else "round_trip"


class Trip(NamedTuple):
    outbound: date
    inbound: date | None  # None for one-way


def _nights(o: _RoundTripOptions) -> tuple[int, int]:
    return (o.stay_nights.min, o.stay_nights.max)


def normalise(preset: _Presets) -> TripPattern:
    match preset:
        case OneWayFixed(departure=d):
            return TripPattern(AbsoluteWindow(d, d))
        case FixedDates(departure=d, return_date=r):
            nights = (r - d).days
            return TripPattern(AbsoluteWindow(d, d), (nights, nights))
        case Month(month=m):
            first = date.fromisoformat(f"{m}-01")
            last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            return TripPattern(AbsoluteWindow(first, last), _nights(preset), preset.return_by)
        case Rolling(within_days=n):
            return TripPattern(RollingWindow(0, n), _nights(preset), preset.return_by)
        case FixedDeparture(departure=d):
            return TripPattern(AbsoluteWindow(d, d), _nights(preset), preset.return_by)
        case AroundDate(target=t, flex_days=k):
            k_days = timedelta(days=k)
            return TripPattern(
                AbsoluteWindow(t - k_days, t + k_days), _nights(preset), preset.return_by
            )
    raise TypeError(f"unsupported preset {preset!r}")


def window(pattern: TripPattern, today: date) -> tuple[date, date]:
    """The departure window as absolute dates for `today` (before dropping past days)."""
    w = pattern.departure_window
    if isinstance(w, RollingWindow):
        return today + timedelta(days=w.start_days), today + timedelta(days=w.end_days)
    return w.start, w.end


def is_expired(pattern: TripPattern, today: date) -> bool:
    return window(pattern, today)[1] < today


def expand(pattern: TripPattern, today: date) -> list[Trip]:
    """Concrete trips for `today`; departures before today are dropped."""
    start, end = window(pattern, today)
    trips: list[Trip] = []
    day = max(start, today)
    while day <= end:
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


class Resolution(BaseModel):
    """A preset as the system understood it, for `today` (shown in the Watch editor)."""

    kind: Literal["one_way", "round_trip"]
    rolling: bool
    departure_start: date
    departure_end: date
    stay_nights: StayNights | None
    return_by: date | None
    latest_return: date | None  # the latest return any trip can have
    trip_count: int  # concrete trips for today (past departures dropped)
    expired: bool


def resolve(preset: _Presets, today: date) -> Resolution:
    pattern = normalise(preset)
    start, end = window(pattern, today)
    nights = pattern.stay_nights
    latest = None
    if nights is not None:
        latest = end + timedelta(days=nights[1])
        if pattern.return_by is not None:
            latest = min(latest, pattern.return_by)
    return Resolution(
        kind=pattern.kind,
        rolling=isinstance(pattern.departure_window, RollingWindow),
        departure_start=start,
        departure_end=end,
        stay_nights=StayNights(min=nights[0], max=nights[1]) if nights else None,
        return_by=pattern.return_by,
        latest_return=latest,
        trip_count=len(expand(pattern, today)),
        expired=is_expired(pattern, today),
    )
