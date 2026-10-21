"""The notifier interface and the channel-agnostic Alert content.

`AlertMessage` is everything an Alert says; channels (`notify/email.py`, `notify/telegram.py`)
only format (`notify/content.py`) and deliver it. A `DigestMessage` is one Watch's daily batch of
Alerts; a channel that can send one message for it implements `send_digest` (`DigestNotifier`),
otherwise `deliver_digest` falls back to one `send` per Deal. `send` raises on delivery failure;
the pipeline then leaves the Alert unsent so the next run retries it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertMessage:
    """One Alert. Optional fields are None (or False) when the pipeline doesn't know them yet;
    channels then leave them out rather than guessing."""

    deal_id: int
    watch_id: int
    watch_name: str
    origin: str
    destination: str
    outbound_date: date
    return_date: date | None
    adults: int
    price_total_eur: float
    price_per_adult_eur: float
    verification: str  # "verified" | "unverified"
    baseline_tier: str | None
    source: str
    observed_at: datetime
    booking_url: str
    airlines: str | None = None
    stops: int | None = None  # most stops in any one direction
    travel_minutes: int | None = None  # all legs together
    separate_tickets: bool = False
    baseline_per_adult_eur: float | None = None
    alert_id: int | None = None  # the app.alerts row this delivery is recorded as

    @property
    def pct_below_baseline(self) -> float | None:
        """How far the per-adult price is under the Baseline, in percent (e.g. 45.0)."""
        if self.baseline_per_adult_eur is None:
            return None
        return pct_below_baseline(self.price_per_adult_eur, self.baseline_per_adult_eur)


def pct_below_baseline(price_per_adult_eur: float, baseline_per_adult_eur: float) -> float | None:
    """Percent under the Baseline, one decimal (118 vs 214 -> 44.9); None for a zero Baseline."""
    if baseline_per_adult_eur <= 0:
        return None
    return round((1 - price_per_adult_eur / baseline_per_adult_eur) * 100, 1)


@dataclass(frozen=True)
class DigestMessage:
    """A Watch's Deals since its last Digest, sent as one message."""

    watch_id: int
    watch_name: str
    deals: tuple[AlertMessage, ...]


@runtime_checkable
class Notifier(Protocol):
    channel: str

    def send(self, alert: AlertMessage) -> None: ...


@runtime_checkable
class DigestNotifier(Notifier, Protocol):
    def send_digest(self, digest: DigestMessage) -> None: ...


def deliver_digest(notifier: Notifier, digest: DigestMessage) -> None:
    """One message if the channel supports Digests, else one Alert per Deal. Raises on failure."""
    if isinstance(notifier, DigestNotifier):
        notifier.send_digest(digest)
    else:
        for alert in digest.deals:
            notifier.send(alert)


class RecordingNotifier:
    """Keeps every Alert it is handed. The seam-1 output.

    `channel` defaults to "recording" (gets every Alert); pass "email" or "telegram" to stand in
    for that channel and receive only Watches that chose it.
    """

    def __init__(self, channel: str = "recording") -> None:
        self.channel = channel
        self.alerts: list[AlertMessage] = []
        self.digests: list[DigestMessage] = []

    def send(self, alert: AlertMessage) -> None:
        self.alerts.append(alert)

    def send_digest(self, digest: DigestMessage) -> None:
        self.digests.append(digest)


class LogNotifier:
    """Writes Alerts to the log; the default until real channels are configured."""

    channel = "log"

    def send(self, alert: AlertMessage) -> None:
        log.warning(
            "ALERT %s: %s->%s %s%s EUR %.2f total (%s)",
            alert.watch_name,
            alert.origin,
            alert.destination,
            alert.outbound_date,
            f"/{alert.return_date}" if alert.return_date else "",
            alert.price_total_eur,
            alert.verification,
        )

    def send_digest(self, digest: DigestMessage) -> None:
        log.warning("DIGEST %s: %d Deal(s)", digest.watch_name, len(digest.deals))
        for alert in digest.deals:
            self.send(alert)
