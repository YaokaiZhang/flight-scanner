"""Messages to the owner about the pipeline itself, not about fares.

  run_failed(conn, notifiers, job, run_id, error, now)    at most once per REPEAT_AFTER per job
  stall_changed(conn, notifiers, previous, stalled, now)  when the set of stalled sources changes
  retry_undelivered(conn, notifiers, now)                 resend what a channel could not take

A channel that cannot be reached is logged and never raises: these run in Dagster sensors, which
will not evaluate the same failure or change again. The message waits in `app.notifier_state`
for that channel until it arrives or GIVE_UP_AFTER passes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from flight_scanner.notify.base import Notifier, OpsNotifier

log = logging.getLogger(__name__)

REPEAT_AFTER = timedelta(hours=6)  # a job failing every 30 minutes should not send 48 a day
GIVE_UP_AFTER = timedelta(hours=24)  # past this, the message describes a situation long gone
_UNDELIVERED_PREFIX = "pipeline_alerts.undelivered."


def _send(
    conn: psycopg.Connection, notifiers: Sequence[Notifier], text: str, now: datetime
) -> None:
    for notifier in notifiers:
        if isinstance(notifier, OpsNotifier):
            try:
                notifier.send_ops(text)
            except Exception as e:
                log.warning("pipeline alert not delivered on %s: %s", notifier.channel, e)
                conn.execute(
                    "INSERT INTO app.notifier_state (name, value) VALUES (%s, %s)",
                    (
                        f"{_UNDELIVERED_PREFIX}{uuid.uuid4()}",
                        Jsonb(
                            {
                                "channel": notifier.channel,
                                "text": text,
                                "first_tried": now.isoformat(),
                            }
                        ),
                    ),
                )


def retry_undelivered(
    conn: psycopg.Connection, notifiers: Sequence[Notifier], now: datetime
) -> None:
    """Resend waiting messages, oldest first; a channel still down is left until the next call."""
    rows = conn.execute(
        "SELECT name, value FROM app.notifier_state WHERE starts_with(name, %s) "
        "ORDER BY value->>'first_tried', name",
        (_UNDELIVERED_PREFIX,),
    ).fetchall()
    channels = {n.channel: n for n in notifiers if isinstance(n, OpsNotifier)}
    down: set[str] = set()
    for row in rows:
        channel, first_tried = (
            row["value"]["channel"],
            datetime.fromisoformat(row["value"]["first_tried"]),
        )
        if channel in down:
            continue
        if channel in channels and now - first_tried < GIVE_UP_AFTER:
            try:
                channels[channel].send_ops(
                    f"{row['value']['text']} [delayed, first tried {first_tried:%Y-%m-%d %H:%M %Z}]"
                )
            except Exception as e:
                log.warning("pipeline alert still not delivered on %s: %s", channel, e)
                down.add(channel)
                continue
        else:
            log.warning(
                "pipeline alert dropped undelivered on %s: %s", channel, row["value"]["text"]
            )
        conn.execute("DELETE FROM app.notifier_state WHERE name = %s", (row["name"],))


def run_failed(
    conn: psycopg.Connection,
    notifiers: Sequence[Notifier],
    job: str,
    run_id: str,
    error: str,
    now: datetime,
) -> bool:
    """Report a failed run unless this job's failure was reported recently; True if reported."""
    key = f"pipeline_alerts.run_failed.{job}"
    row = conn.execute("SELECT value FROM app.notifier_state WHERE name = %s", (key,)).fetchone()
    if row and now - datetime.fromisoformat(row["value"]) < REPEAT_AFTER:
        return False
    _send(
        conn, notifiers, f"Flight Scanner: the {job} run {run_id[:8]} failed. {error}".strip(), now
    )
    conn.execute(
        "INSERT INTO app.notifier_state (name, value) VALUES (%s, %s) "
        "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
        (key, Jsonb(now.isoformat())),
    )
    return True


def stall_changed(
    conn: psycopg.Connection,
    notifiers: Sequence[Notifier],
    previous: Sequence[str],
    stalled: Sequence[str],
    now: datetime,
) -> None:
    new, recovered = sorted(set(stalled) - set(previous)), sorted(set(previous) - set(stalled))
    if new:
        _send(
            conn,
            notifiers,
            f"Flight Scanner: no prices from {', '.join(new)} for over 2 hours. "
            "Scans may be stuck; check the Dagster run queue.",
            now,
        )
    if recovered:
        _send(
            conn,
            notifiers,
            f"Flight Scanner: prices are landing again from {', '.join(recovered)}.",
            now,
        )
