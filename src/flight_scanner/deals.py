"""Deals and Alerts: turn marts.candidates into Deals and hand new Deals to the notifiers.

Walking skeleton rules (ticket 07 adds re-alerts and Digests; ticket 08 adds Verification):
- A Deal is keyed by the dedup key (Watch, origin, destination, outbound, return).
- Every Candidate becomes an Unverified Deal; a key already present is not re-created.
- A Deal with no Alert yet is sent to each notifier whose channel the Watch chose (email/Telegram;
  other channels such as log get every Deal); an Alert row is written per channel sent.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import psycopg

from flight_scanner.notify.base import AlertMessage, Notifier
from flight_scanner.notify.content import booking_link

# Channels a Watch chooses between; notifiers on any other channel receive every Alert.
WATCH_CHANNELS = ("email", "telegram")


def record_deals(conn: psycopg.Connection, now: datetime) -> int:
    """Insert a Deal for each new Candidate; returns how many were new."""
    cur = conn.execute(
        """INSERT INTO app.deals (watch_id, origin, destination, outbound_date, return_date,
               price_per_adult_eur, price_total_eur, adults, source, observed_at,
               verification, baseline_tier, detected_at, airlines, stops, travel_minutes,
               separate_tickets, booking_url, baseline_per_adult_eur)
           SELECT watch_id, origin, destination, outbound_date, return_date,
               price_per_adult_eur, price_total_eur, adults, source, observed_at,
               'unverified', baseline_tier, %s, airlines, stops, travel_minutes,
               separate_tickets, booking_url, baseline_per_adult_eur
           FROM marts.candidates
           ON CONFLICT DO NOTHING""",
        (now,),
    )
    return cur.rowcount


class AlertDeliveryError(Exception):
    """At least one channel failed; its Alerts stay pending and are retried on the next run."""


def _num(v) -> float | None:
    return None if v is None else float(v)


def _message(d: dict, alert_id: int | None = None) -> AlertMessage:
    return AlertMessage(
        deal_id=d["id"],
        watch_id=d["watch_id"],
        watch_name=d["watch_name"],
        origin=d["origin"],
        destination=d["destination"],
        outbound_date=d["outbound_date"],
        return_date=d["return_date"],
        adults=d["adults"],
        price_total_eur=float(d["price_total_eur"]),
        price_per_adult_eur=float(d["price_per_adult_eur"]),
        verification=d["verification"],
        baseline_tier=d["baseline_tier"],
        source=d["source"],
        observed_at=d["observed_at"],
        booking_url=d["booking_url"]
        or booking_link(d["origin"], d["destination"], d["outbound_date"], d["return_date"]),
        airlines=d["airlines"],
        stops=d["stops"],
        travel_minutes=d["travel_minutes"],
        separate_tickets=d["separate_tickets"],
        baseline_per_adult_eur=_num(d["baseline_per_adult_eur"]),
        alert_id=alert_id,
    )


def send_alerts(conn: psycopg.Connection, notifiers: Sequence[Notifier], now: datetime) -> int:
    """Send each Deal once per channel; one failing channel doesn't block the others.

    The Alert row is written in the same transaction as the delivery, so the channel can carry its
    id (Telegram's 👍/👎 buttons) and a failed delivery leaves no row behind.
    """
    sent = 0
    failures: list[str] = []
    for n in notifiers:
        pending = conn.execute(
            """SELECT d.*, w.name AS watch_name
               FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
               WHERE w.status = 'active'
                 AND (%(ch)s <> ALL(%(chosen)s) OR %(ch)s = ANY(w.channels))
                 AND NOT EXISTS (SELECT 1 FROM app.alerts a
                                 WHERE a.deal_id = d.id AND a.channel = %(ch)s)
               ORDER BY d.id""",
            {"ch": n.channel, "chosen": list(WATCH_CHANNELS)},
        ).fetchall()
        for d in pending:
            try:
                with conn.transaction():
                    alert_id = conn.execute(
                        "INSERT INTO app.alerts (deal_id, channel, sent_at, price_total_eur) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (d["id"], n.channel, now, d["price_total_eur"]),
                    ).fetchone()["id"]
                    n.send(_message(d, alert_id))
            except Exception as e:  # noqa: BLE001 - keep other channels going
                failures.append(f"{n.channel}: {type(e).__name__}: {e}")
                break
            sent += 1
    if failures:
        raise AlertDeliveryError("; ".join(failures))
    return sent
