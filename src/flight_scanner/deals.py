"""Deals and Alerts: turn marts.candidates into Deals and hand new Deals to the notifiers.

Rules (ticket 08 adds Verification):
- A Deal is keyed by the Alert dedup key (Watch, origin, destination, outbound, return). Every
  Candidate becomes (or refreshes) an Unverified Deal; its price and details are the latest
  Candidate's.
- Alert rounds: a new Deal is due round 1. A Deal still present is not alerted again, except a
  new round is due when its price drops >= REALERT_DROP below the last alerted price, or when it
  reappears after being absent (not a Candidate) for >= REAPPEARANCE_GAP.
- A due round is sent once per channel to each notifier whose channel the Watch chose
  (email/Telegram; other channels such as log get every Deal); an Alert row (deal, channel,
  round) records it. Watches in Digest mode get their rounds batched by `digests.send_digests`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg

from flight_scanner.notify.base import AlertMessage, Notifier
from flight_scanner.notify.content import booking_link

# Channels a Watch chooses between; notifiers on any other channel receive every Alert.
WATCH_CHANNELS = ("email", "telegram")
# SQL (Watch `w`, params ch, chosen): the notifier on channel %(ch)s gets this Watch's Alerts.
CHANNEL_FILTER = "(%(ch)s <> ALL(%(chosen)s) OR %(ch)s = ANY(w.channels))"

REALERT_DROP = Decimal("0.10")  # a further drop of 10% from the last alerted price alerts again
REAPPEARANCE_GAP = timedelta(hours=24)  # a fare gone this long alerts again when it returns

_DEDUP_KEY = "(watch_id, origin, destination, outbound_date, coalesce(return_date, '0001-01-01'))"
# A further Alert round is due for an existing Deal (old row `d`) seen again as `excluded`.
_ROUND_DUE = """(excluded.price_total_eur <= d.alert_price_total_eur * (1 - %(drop)s)
    OR (d.absent_since IS NOT NULL AND %(now)s - d.absent_since >= %(gap)s))"""


def record_deals(conn: psycopg.Connection, now: datetime) -> int:
    """Refresh Deals from marts.candidates and decide which are due an Alert round.

    Returns how many Deals were new."""
    with conn.transaction():
        # Deals of active Watches whose key is no longer a Candidate start (or stay) absent.
        conn.execute(
            """UPDATE app.deals d SET absent_since = %s
               FROM app.watches w
               WHERE w.id = d.watch_id AND w.status = 'active' AND d.absent_since IS NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM marts.candidates c
                     WHERE c.watch_id = d.watch_id AND c.origin = d.origin
                       AND c.destination = d.destination AND c.outbound_date = d.outbound_date
                       AND c.return_date IS NOT DISTINCT FROM d.return_date)""",
            (now,),
        )
        rows = conn.execute(
            f"""INSERT INTO app.deals AS d (watch_id, origin, destination, outbound_date,
                   return_date, price_per_adult_eur, price_total_eur, adults, source, observed_at,
                   ticketing, verification, baseline_tier, detected_at, last_seen_at,
                   alert_round, alert_price_total_eur, alert_due_at, airlines, stops,
                   travel_minutes, separate_tickets, booking_url, baseline_per_adult_eur)
               SELECT watch_id, origin, destination, outbound_date, return_date,
                   price_per_adult_eur, price_total_eur, adults, source, observed_at,
                   ticketing, 'unverified', baseline_tier, %(now)s, %(now)s, 1,
                   price_total_eur, %(now)s, airlines, stops, travel_minutes, separate_tickets,
                   booking_url, baseline_per_adult_eur
               FROM marts.candidates
               ON CONFLICT {_DEDUP_KEY} DO UPDATE SET
                   price_per_adult_eur = excluded.price_per_adult_eur,
                   price_total_eur = excluded.price_total_eur,
                   adults = excluded.adults,
                   source = excluded.source,
                   observed_at = excluded.observed_at,
                   ticketing = excluded.ticketing,
                   baseline_tier = excluded.baseline_tier,
                   airlines = excluded.airlines,
                   stops = excluded.stops,
                   travel_minutes = excluded.travel_minutes,
                   separate_tickets = excluded.separate_tickets,
                   booking_url = excluded.booking_url,
                   baseline_per_adult_eur = excluded.baseline_per_adult_eur,
                   last_seen_at = %(now)s,
                   absent_since = NULL,
                   alert_round = d.alert_round + CASE WHEN {_ROUND_DUE} THEN 1 ELSE 0 END,
                   alert_price_total_eur = CASE WHEN {_ROUND_DUE}
                       THEN excluded.price_total_eur ELSE d.alert_price_total_eur END,
                   alert_due_at = CASE WHEN {_ROUND_DUE} THEN %(now)s ELSE d.alert_due_at END
               RETURNING (xmax = 0) AS inserted""",
            {"now": now, "drop": REALERT_DROP, "gap": REAPPEARANCE_GAP},
        ).fetchall()
    return sum(1 for r in rows if r["inserted"])


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
        ticketing=d["ticketing"],
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
        deal_context=d["deal_context"],
    )


def send_alerts(conn: psycopg.Connection, notifiers: Sequence[Notifier], now: datetime) -> int:
    """Send each due Alert round once per channel; one failing channel doesn't block the others.

    The Alert row is written in the same transaction as the delivery, so the channel can carry its
    id (Telegram's 👍/👎 buttons) and a failed delivery leaves no row behind.
    """
    sent = 0
    failures: list[str] = []
    for n in notifiers:
        pending = conn.execute(
            f"""SELECT d.*, w.name AS watch_name
               FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
               WHERE w.status = 'active' AND w.delivery = 'immediate'
                 AND {CHANNEL_FILTER}
                 AND NOT EXISTS (SELECT 1 FROM app.alerts a
                                 WHERE a.deal_id = d.id AND a.channel = %(ch)s
                                   AND a.alert_round = d.alert_round)
               ORDER BY d.id""",
            {"ch": n.channel, "chosen": list(WATCH_CHANNELS)},
        ).fetchall()
        for d in pending:
            try:
                with conn.transaction():
                    alert_id = conn.execute(
                        "INSERT INTO app.alerts (deal_id, channel, sent_at, price_total_eur, "
                        "alert_round) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (d["id"], n.channel, now, d["price_total_eur"], d["alert_round"]),
                    ).fetchone()["id"]
                    n.send(_message(d, alert_id))
            except Exception as e:  # noqa: BLE001 - keep other channels going
                failures.append(f"{n.channel}: {type(e).__name__}: {e}")
                break
            sent += 1
    if failures:
        raise AlertDeliveryError("; ".join(failures))
    return sent
