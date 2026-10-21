"""Data-quality gates: suspicious data blocks Deal detection for the affected slice only.

After every scan's ingestion the checks below run over what the scan sources landed. A failing
slice is a *gate*: dbt's `marts.trip_prices` leaves out its prices, so they cannot become a trip's
current price or a Candidate, while other sources (and other origins of the same source) carry
on. A gate lifts at the first evaluation in which its check passes again.

  zero_rows    slice (source, origin): the source's latest scan of an origin landed no prices,
               although a scan of it within NORMAL_WINDOW landed some (an empty answer from a
               normally populated origin is a broken source or parser, not "no fares")
  price_jump   slice (source, every origin): the median ratio of the prices of the source's
               latest scan to the same trips' median over the JUMP_WINDOW before it is beyond
               PRICE_JUMP either way, over at least JUMP_MIN_TRIPS trips (a currency or parsing
               change, not a sale)
  stale_data   slice (source, every origin): the source has prices but none observed within
               STALE_AFTER (an outage, a block or a starved budget: its cached prices are old)

Prices are compared in the source's own currency and per adult, so the checks need no FX rates.

  CHECKS                                  check name -> description (Dagster asset checks)
  evaluate(conn, sources, now) -> [Gate]   run the checks, replace the gates, append the history
  gates(conn) -> [Gate]                   the slices currently gated
  recent_failures(conn, since) -> [Gate]  every failing slice per evaluation since `since`
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import psycopg

NORMAL_WINDOW = timedelta(days=7)
PRICE_JUMP = 0.4  # median ratio below 0.6 or above 1 / 0.6
JUMP_WINDOW = timedelta(days=7)
JUMP_MIN_TRIPS = 5
STALE_AFTER = timedelta(hours=6)
KEEP_FAILURES_FOR = timedelta(days=30)

CHECKS = {
    "zero_rows": "An origin that normally has prices: the source's latest scan of it landed none",
    "price_jump": f"Source-wide price level moved more than {PRICE_JUMP:.0%} against the last "
    f"{JUMP_WINDOW.days} days",
    "stale_data": f"The source has no Fare observation newer than "
    f"{STALE_AFTER / timedelta(hours=1):g} h",
}


@dataclass(frozen=True)
class Gate:
    check_name: str
    source: str
    origin: str | None  # None: every origin of the source
    detail: str
    checked_at: datetime
    since: datetime | None = None  # first consecutive evaluation failing (current gates only)

    def as_metadata(self) -> dict:
        d = asdict(self)
        return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in d.items()}


def _fmt(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _zero_rows(conn: psycopg.Connection, sources: list[str], now: datetime) -> list[Gate]:
    rows = conn.execute(
        """WITH scans AS (
               SELECT t.source, t.origin, p.planned_at, sum(t.rows) AS landed
               FROM app.scan_tasks t JOIN app.scan_plans p ON p.id = t.plan_id
               WHERE t.status = 'scanned' AND t.rows IS NOT NULL AND t.source = ANY(%(sources)s)
                 AND p.planned_at <= %(now)s
               GROUP BY t.source, t.origin, p.planned_at),
           latest AS (
               SELECT DISTINCT ON (source, origin) source, origin, planned_at, landed
               FROM scans ORDER BY source, origin, planned_at DESC)
           SELECT l.source, l.origin, l.planned_at,
                  max(s.planned_at) AS populated_at,
                  (array_agg(s.landed ORDER BY s.planned_at DESC))[1] AS populated_rows
           FROM latest l
           JOIN scans s ON s.source = l.source AND s.origin = l.origin
                AND s.planned_at < l.planned_at AND s.planned_at >= l.planned_at - %(window)s
                AND s.landed > 0
           WHERE l.landed = 0
           GROUP BY l.source, l.origin, l.planned_at
           ORDER BY l.source, l.origin""",
        {"sources": sources, "now": now, "window": NORMAL_WINDOW},
    ).fetchall()
    return [
        Gate(
            "zero_rows",
            r["source"],
            r["origin"],
            f"{r['source']} returned no prices for {r['origin']} at {_fmt(r['planned_at'])}; "
            f"it had {r['populated_rows']} at {_fmt(r['populated_at'])}",
            now,
        )
        for r in rows
    ]


def _price_jump(conn: psycopg.Connection, sources: list[str], now: datetime) -> list[Gate]:
    rows = conn.execute(
        """WITH last_scan AS (
               SELECT t.source, max(p.planned_at) AS since
               FROM app.scan_tasks t JOIN app.scan_plans p ON p.id = t.plan_id
               WHERE t.status = 'scanned' AND t.source = ANY(%(sources)s)
                 AND p.planned_at <= %(now)s
               GROUP BY t.source),
           obs AS (
               SELECT o.source, o.origin, o.destination, o.departure_date,
                      CAST(NULL AS date) AS return_date, o.currency,
                      o.price / o.adults AS price, o.observed_at, l.since
               FROM landing.leg_prices o JOIN last_scan l ON l.source = o.source
               WHERE o.observed_at >= l.since - %(window)s AND o.observed_at <= %(now)s
               UNION ALL
               SELECT o.source, o.origin, o.destination, o.departure_date, o.return_date,
                      o.currency, o.price / o.adults, o.observed_at, l.since
               FROM landing.round_trip_prices o JOIN last_scan l ON l.source = o.source
               WHERE o.observed_at >= l.since - %(window)s AND o.observed_at <= %(now)s),
           cur AS (
               SELECT source, origin, destination, departure_date, return_date, currency,
                      min(price) AS price
               FROM obs WHERE observed_at >= since
               GROUP BY source, origin, destination, departure_date, return_date, currency),
           ref AS (
               SELECT source, origin, destination, departure_date, return_date, currency,
                      percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS price
               FROM obs WHERE observed_at < since
               GROUP BY source, origin, destination, departure_date, return_date, currency)
           SELECT c.source, count(*) AS trips,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY c.price / r.price) AS ratio
           FROM cur c JOIN ref r
             ON r.source = c.source AND r.origin = c.origin AND r.destination = c.destination
            AND r.departure_date = c.departure_date AND r.currency = c.currency
            AND r.return_date IS NOT DISTINCT FROM c.return_date
           WHERE r.price > 0
           GROUP BY c.source
           HAVING count(*) >= %(min_trips)s
           ORDER BY c.source""",
        {"sources": sources, "now": now, "window": JUMP_WINDOW, "min_trips": JUMP_MIN_TRIPS},
    ).fetchall()
    low, high = 1 - PRICE_JUMP, 1 / (1 - PRICE_JUMP)
    return [
        Gate(
            "price_jump",
            r["source"],
            None,
            f"{r['source']} prices moved to {r['ratio']:.0%} of their {JUMP_WINDOW.days}-day "
            f"median (median over {r['trips']} trips)",
            now,
        )
        for r in rows
        if not low <= r["ratio"] <= high
    ]


def _stale_data(conn: psycopg.Connection, sources: list[str], now: datetime) -> list[Gate]:
    rows = conn.execute(
        """SELECT source, max(observed_at) AS newest FROM (
               SELECT source, observed_at FROM landing.leg_prices
               WHERE source = ANY(%(sources)s) AND observed_at <= %(now)s
               UNION ALL
               SELECT source, observed_at FROM landing.round_trip_prices
               WHERE source = ANY(%(sources)s) AND observed_at <= %(now)s) o
           GROUP BY source ORDER BY source""",
        {"sources": sources, "now": now},
    ).fetchall()
    return [
        Gate(
            "stale_data",
            r["source"],
            None,
            f"{r['source']}'s newest price was observed at {_fmt(r['newest'])}",
            now,
        )
        for r in rows
        if now - r["newest"] > STALE_AFTER
    ]


def evaluate(conn: psycopg.Connection, sources: Sequence[str], now: datetime) -> list[Gate]:
    """Run every check over the scan sources' data; the failing slices become the gates."""
    names = list(sources)
    failing = [*_zero_rows(conn, names, now), *_price_jump(conn, names, now)]
    failing += _stale_data(conn, names, now)
    previous = {(g.check_name, g.source, g.origin): g.since for g in gates(conn)}
    current = [
        Gate(**{**asdict(g), "since": previous.get((g.check_name, g.source, g.origin)) or now})
        for g in failing
    ]
    conn.execute("DELETE FROM app.quality_gates")
    conn.execute(
        "DELETE FROM app.quality_failures WHERE checked_at < %s", (now - KEEP_FAILURES_FOR,)
    )
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app.quality_gates (check_name, source, origin, detail, since, checked_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            [(g.check_name, g.source, g.origin, g.detail, g.since, now) for g in current],
        )
        cur.executemany(
            """INSERT INTO app.quality_failures (checked_at, check_name, source, origin, detail)
               VALUES (%s, %s, %s, %s, %s)""",
            [(now, g.check_name, g.source, g.origin, g.detail) for g in current],
        )
    return current


def gates(conn: psycopg.Connection) -> list[Gate]:
    rows = conn.execute(
        """SELECT check_name, source, origin, detail, checked_at, since FROM app.quality_gates
           ORDER BY source, check_name, origin NULLS FIRST"""
    ).fetchall()
    return [Gate(**r) for r in rows]


def recent_failures(conn: psycopg.Connection, since: datetime, limit: int = 100) -> list[Gate]:
    rows = conn.execute(
        """SELECT check_name, source, origin, detail, checked_at FROM app.quality_failures
           WHERE checked_at >= %s ORDER BY checked_at DESC, id DESC LIMIT %s""",
        (since, limit),
    ).fetchall()
    return [Gate(**r) for r in rows]
