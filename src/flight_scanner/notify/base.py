"""The notifier interface and the channel-agnostic Alert content.

`AlertMessage` is everything an Alert says; channels (email, Telegram: ticket 06) only format and
deliver it. `send` raises on delivery failure; the pipeline then leaves the Alert unsent so the
next run retries it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertMessage:
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


@runtime_checkable
class Notifier(Protocol):
    channel: str

    def send(self, alert: AlertMessage) -> None: ...


class RecordingNotifier:
    """Keeps every Alert it is handed. The seam-1 output."""

    channel = "recording"

    def __init__(self) -> None:
        self.alerts: list[AlertMessage] = []

    def send(self, alert: AlertMessage) -> None:
        self.alerts.append(alert)


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
