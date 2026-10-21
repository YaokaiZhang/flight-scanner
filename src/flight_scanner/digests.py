"""Digests: one daily message per Watch in Digest mode, in place of immediate Alerts.

A Digest goes out at DIGEST_TIME (owner's time zone) and lists the Watch's Deals whose Alert round
(see `deals`) became due before that time and has not been sent on that channel yet, i.e. all
Deals since the last Digest. Rounds that become due later wait for the next day's Digest. A quiet
day sends nothing. Delivery failures leave the rounds pending, so the next run retries them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from itertools import groupby

import psycopg

from flight_scanner.clock import OWNER_TZ
from flight_scanner.deals import CHANNEL_FILTER, WATCH_CHANNELS, AlertDeliveryError, _message
from flight_scanner.notify.base import DigestMessage, Notifier, deliver_digest

DIGEST_TIME = time(8, 0)


def latest_digest_time(now: datetime) -> datetime:
    """The most recent DIGEST_TIME (owner's time zone) at or before `now`."""
    local = now.astimezone(OWNER_TZ)
    cutoff = datetime.combine(local.date(), DIGEST_TIME, tzinfo=OWNER_TZ)
    if cutoff > local:
        cutoff = datetime.combine(local.date() - timedelta(days=1), DIGEST_TIME, tzinfo=OWNER_TZ)
    return cutoff


def send_digests(conn: psycopg.Connection, notifiers: Sequence[Notifier], now: datetime) -> int:
    """Send every due Digest on every channel the Watch chose; returns how many were sent.

    As for immediate Alerts, the Digest and its Alert rows are written in the same transaction as
    the delivery, so each Deal in it carries its Alert id (Telegram's 👍/👎 buttons) and a failed
    delivery leaves nothing behind.
    """
    cutoff = latest_digest_time(now)
    sent = 0
    failures: list[str] = []
    for n in notifiers:
        pending = conn.execute(
            f"""SELECT d.*, w.name AS watch_name
               FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
               WHERE w.status = 'active' AND w.delivery = 'digest'
                 AND d.verification <> 'failed'
                 AND {CHANNEL_FILTER}
                 AND d.alert_due_at < %(cutoff)s
                 AND NOT EXISTS (SELECT 1 FROM app.alerts a
                                 WHERE a.deal_id = d.id AND a.channel = %(ch)s
                                   AND a.alert_round = d.alert_round)
               ORDER BY d.watch_id, d.id""",
            {"ch": n.channel, "chosen": list(WATCH_CHANNELS), "cutoff": cutoff},
        ).fetchall()
        for (watch_id, watch_name), group in groupby(
            pending, key=lambda d: (d["watch_id"], d["watch_name"])
        ):
            rows = list(group)
            try:
                with conn.transaction():
                    digest_id = conn.execute(
                        "INSERT INTO app.digests (watch_id, channel, sent_at, deal_count) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (watch_id, n.channel, now, len(rows)),
                    ).fetchone()["id"]
                    alerts = []
                    for d in rows:
                        alert_id = conn.execute(
                            "INSERT INTO app.alerts (deal_id, channel, sent_at, price_total_eur, "
                            "alert_round, digest_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                            (
                                d["id"],
                                n.channel,
                                now,
                                d["price_total_eur"],
                                d["alert_round"],
                                digest_id,
                            ),
                        ).fetchone()["id"]
                        alerts.append(_message(d, alert_id))
                    deliver_digest(n, DigestMessage(watch_id, watch_name, tuple(alerts)))
            except Exception as e:  # noqa: BLE001 - keep other channels going
                failures.append(f"{n.channel} digest: {type(e).__name__}: {e}")
                break
            sent += 1
    if failures:
        raise AlertDeliveryError("; ".join(failures))
    return sent
