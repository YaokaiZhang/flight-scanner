"""Sources that disabled themselves after being turned away (bot protection, access denied).

A source adapter raises `SourceBlocked` instead of working around a block; the pipeline records
it here and the scan planner skips every task of a blocked source (reason "source blocked ...")
until the owner re-enables it with `python -m flight_scanner unblock <source>`.

  block(conn, source, reason, now)   record a block (the first one wins until unblocked)
  blocks(conn) -> {source: Block}     the sources currently disabled
  unblock(conn, source) -> bool       re-enable; False if it was not blocked
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class Block:
    source: str
    blocked_at: datetime
    reason: str


def block(conn: psycopg.Connection, source: str, reason: str, now: datetime) -> None:
    conn.execute(
        """INSERT INTO app.source_blocks (source, blocked_at, reason) VALUES (%s, %s, %s)
           ON CONFLICT (source) DO NOTHING""",
        (source, now, reason),
    )


def blocks(conn: psycopg.Connection) -> dict[str, Block]:
    rows = conn.execute(
        "SELECT source, blocked_at, reason FROM app.source_blocks ORDER BY source"
    ).fetchall()
    return {r["source"]: Block(**r) for r in rows}


def unblock(conn: psycopg.Connection, source: str) -> bool:
    cur = conn.execute("DELETE FROM app.source_blocks WHERE source = %s", (source,))
    return cur.rowcount > 0
