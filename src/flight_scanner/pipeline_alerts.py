"""Messages to the owner about the pipeline itself, not about fares.

  run_failed(conn, notifiers, job, run_id, error, now)    at most once per REPEAT_AFTER per job
  stall_changed(notifiers, previous, stalled)             when the set of stalled sources changes

A channel that cannot be reached is logged and never raises: these run in Dagster sensors, and
the next failure or change tries again.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from flight_scanner.notify.base import Notifier, OpsNotifier

log = logging.getLogger(__name__)

REPEAT_AFTER = timedelta(hours=6)  # a job failing every 30 minutes should not send 48 a day


def _send(notifiers: Sequence[Notifier], text: str) -> None:
    for notifier in notifiers:
        if isinstance(notifier, OpsNotifier):
            try:
                notifier.send_ops(text)
            except Exception as e:
                log.warning("pipeline alert not delivered on %s: %s", notifier.channel, e)


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
    _send(notifiers, f"Flight Scanner: the {job} run {run_id[:8]} failed. {error}".strip())
    conn.execute(
        "INSERT INTO app.notifier_state (name, value) VALUES (%s, %s) "
        "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
        (key, Jsonb(now.isoformat())),
    )
    return True


def stall_changed(
    notifiers: Sequence[Notifier], previous: Sequence[str], stalled: Sequence[str]
) -> None:
    new, recovered = sorted(set(stalled) - set(previous)), sorted(set(previous) - set(stalled))
    if new:
        _send(
            notifiers,
            f"Flight Scanner: no prices from {', '.join(new)} for over 2 hours. "
            "Scans may be stuck; check the Dagster run queue.",
        )
    if recovered:
        _send(notifiers, f"Flight Scanner: prices are landing again from {', '.join(recovered)}.")
