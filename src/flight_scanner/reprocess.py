"""Rebuild the parsed landing rows from the raw store alone.

Every staging and history model is a pure function of `landing.leg_prices` /
`landing.round_trip_prices` / `landing.price_insights`, and those are a pure function (each
adapter's `parse`) of the raw payloads. `reprocess` re-derives the landing rows from the raw
files listed in the manifest (`landing.raw_payloads`), e.g. after fixing a parser; running dbt
afterwards rebuilds staging and history. Only sources with a parser are touched, so rows of a
source that is not configured now are kept as they are.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import psycopg

from flight_scanner.ingestion import load_parsed
from flight_scanner.raw_store import RawStore
from flight_scanner.sources.base import ParsedPrices, RawPayload, ScanRequest

Parser = Callable[[RawPayload], ParsedPrices]


@dataclass
class ReprocessReport:
    payloads: int = 0
    leg_prices: int = 0
    round_trip_prices: int = 0
    skipped_sources: dict[str, int] = field(default_factory=dict)


def reprocess(
    conn: psycopg.Connection, raw_store: RawStore, parsers: Mapping[str, Parser]
) -> ReprocessReport:
    """Replace the landing rows of every source in `parsers`, in one transaction."""
    report = ReprocessReport()
    sources = sorted(parsers)
    with conn.transaction():
        conn.execute("DELETE FROM landing.leg_prices WHERE source = ANY(%s)", (sources,))
        conn.execute("DELETE FROM landing.round_trip_prices WHERE source = ANY(%s)", (sources,))
        conn.execute("DELETE FROM landing.price_insights WHERE source = ANY(%s)", (sources,))
        manifest = conn.execute(
            "SELECT id, source, fetched_at, request, path, sha256 FROM landing.raw_payloads "
            "ORDER BY id"
        ).fetchall()
        for row in manifest:
            parse = parsers.get(row["source"])
            if parse is None:
                n = report.skipped_sources.get(row["source"], 0)
                report.skipped_sources[row["source"]] = n + 1
                continue
            stored = raw_store.open(row["path"])
            if stored.sha256 != row["sha256"]:
                raise ValueError(f"raw payload {row['path']} does not match its manifest sha256")
            raw = RawPayload(
                row["source"],
                ScanRequest(row["source"], row["request"]),
                row["fetched_at"],
                stored.read(),
            )
            parsed = parse(raw)
            load_parsed(conn, row["id"], parsed)
            report.payloads += 1
            report.leg_prices += len(parsed.leg_prices)
            report.round_trip_prices += len(parsed.round_trip_prices)
    return report
