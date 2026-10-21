"""The injectable clock. Anything that depends on "now" or "today" takes a `Clock`.

Never call `datetime.now()` / `date.today()` / SQL `now()` in domain code: take a Clock, and pass
`clock.now()` into SQL and dbt (dbt reads it as the `as_of` var).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

OWNER_TZ = ZoneInfo("Europe/Helsinki")


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, timezone-aware (UTC)."""
        ...


def today(clock: Clock, tz: ZoneInfo = OWNER_TZ) -> date:
    """The owner's calendar date (Helsinki by default) at the clock's current instant."""
    return clock.now().astimezone(tz).date()


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    """A clock that only moves when told to. Used by tests and the e2e stack."""

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start")
        self._now = start.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta | None = None, **kwargs: float) -> datetime:
        self._now += delta if delta is not None else timedelta(**kwargs)
        return self._now

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("naive datetime")
        self._now = instant.astimezone(UTC)
