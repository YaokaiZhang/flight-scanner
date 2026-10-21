"""Ingestion: the scan plan's scheduled tasks -> each source adapter -> raw store + landing.

One source failing (SourceUnavailable or any error) never stops the others; the outcome per
source, and per scan task ("scanned" or "failed"), is returned so the pipeline can record it.
A source that was turned away (`SourceBlocked`) is flagged `blocked`; the pipeline then disables
it (`source_health`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from flight_scanner.raw_store import RawStore
from flight_scanner.scan_planner import ScheduledTask
from flight_scanner.sources.base import ParsedPrices, RawPayload, SourceAdapter, SourceBlocked

log = logging.getLogger(__name__)

_LEG_COLS = (
    "source, observed_at, origin, destination, departure_date, price, currency, adults, "
    "airline, stops, duration_min"
)
_INSIGHT_COLS = (
    "source, observed_at, origin, destination, departure_date, return_date, adults, currency, "
    "typical_low, typical_high, lowest_price, price_level, history_points"
)
_RT_COLS = (
    "source, observed_at, origin, destination, departure_date, return_date, price, currency, "
    "adults, airline, stops, duration_min"
)


@dataclass
class SourceOutcome:
    source: str
    requests: int = 0
    payloads: int = 0
    leg_prices: int = 0
    round_trip_prices: int = 0
    error: str | None = None
    blocked: bool = False  # turned away by the source (bot protection, access denied)


@dataclass
class IngestReport:
    outcomes: list[SourceOutcome] = field(default_factory=list)
    task_status: dict[int, str] = field(default_factory=dict)  # scan task id -> scanned|failed

    def as_metadata(self) -> dict:
        return {o.source: asdict(o) for o in self.outcomes}


def store_payload(conn: psycopg.Connection, raw_store: RawStore, raw: RawPayload) -> int:
    stored = raw_store.put(raw)
    row = conn.execute(
        """INSERT INTO landing.raw_payloads (source, fetched_at, request, path, sha256)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (path) DO UPDATE SET path = EXCLUDED.path RETURNING id""",
        (
            raw.source,
            raw.fetched_at,
            Jsonb(json.loads(json.dumps(dict(raw.request.params)))),
            str(stored.path),
            stored.sha256,
        ),
    ).fetchone()
    return row["id"]


def load_parsed(conn: psycopg.Connection, payload_id: int, parsed: ParsedPrices) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO landing.leg_prices (payload_id, {_LEG_COLS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    payload_id,
                    p.source,
                    p.observed_at,
                    p.origin,
                    p.destination,
                    p.departure_date,
                    p.price,
                    p.currency,
                    p.adults,
                    p.airline,
                    p.stops,
                    p.duration_min,
                )
                for p in parsed.leg_prices
            ],
        )
        cur.executemany(
            f"INSERT INTO landing.round_trip_prices (payload_id, {_RT_COLS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    payload_id,
                    p.source,
                    p.observed_at,
                    p.origin,
                    p.destination,
                    p.departure_date,
                    p.return_date,
                    p.price,
                    p.currency,
                    p.adults,
                    p.airline,
                    p.stops,
                    p.duration_min,
                )
                for p in parsed.round_trip_prices
            ],
        )
        cur.executemany(
            f"INSERT INTO landing.price_insights (payload_id, {_INSIGHT_COLS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    payload_id,
                    i.source,
                    i.observed_at,
                    i.origin,
                    i.destination,
                    i.departure_date,
                    i.return_date,
                    i.adults,
                    i.currency,
                    i.typical_low,
                    i.typical_high,
                    i.lowest_price,
                    i.price_level,
                    i.history_points,
                )
                for i in parsed.price_insights
            ],
        )


def ingest(
    conn: psycopg.Connection,
    adapters: Sequence[SourceAdapter],
    tasks: Sequence[ScheduledTask],
    raw_store: RawStore,
) -> IngestReport:
    """Fetch every scheduled task's requests, in order, per source. When a source fails, its
    current and remaining tasks are failed and the other sources carry on."""
    report = IngestReport()
    for adapter in adapters:
        outcome = SourceOutcome(adapter.name)
        report.outcomes.append(outcome)
        mine = [t for t in tasks if t.source == adapter.name]
        outcome.requests = sum(len(t.requests) for t in mine)
        try:
            for task in mine:
                report.task_status[task.id] = "failed"
                for req in task.requests:
                    raw = adapter.fetch(req)
                    # the raw bytes are committed before parsing, so a parse bug never loses data
                    with conn.transaction():
                        payload_id = store_payload(conn, raw_store, raw)
                    outcome.payloads += 1
                    parsed = adapter.parse(raw)
                    with conn.transaction():
                        load_parsed(conn, payload_id, parsed)
                    outcome.leg_prices += len(parsed.leg_prices)
                    outcome.round_trip_prices += len(parsed.round_trip_prices)
                report.task_status[task.id] = "scanned"
        except Exception as e:  # noqa: BLE001 - isolate every source failure
            log.warning("source %s failed: %s", adapter.name, e)
            outcome.error = f"{type(e).__name__}: {e}"
            outcome.blocked = isinstance(e, SourceBlocked)
        for task in mine:
            report.task_status.setdefault(task.id, "failed")
    return report
