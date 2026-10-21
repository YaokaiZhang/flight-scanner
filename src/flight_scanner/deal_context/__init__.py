"""Deal context: a short line on why a Deal might be cheap (sale, new route, off-season).

Optional: the pipeline runs without a researcher (`Runtime.researcher` is None unless
FS_DEAL_CONTEXT is set). A researcher only explains a Deal; it is never a price source and never
changes a Deal's price, status or whether it alerts.

Each new Deal is researched once, before its first Alert. Deals are researched in parallel and
the Alert step waits at most `timeout` seconds (wall time, DEAL_CONTEXT_TIMEOUT = 60 s) for all of
them. A Deal whose context is not ready by then is marked `late` and alerted without it; an answer
that arrives afterwards is dropped. A failing researcher is logged and marked `failed`.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import psycopg

from flight_scanner.config import Settings

log = logging.getLogger(__name__)

DEAL_CONTEXT_TIMEOUT = 60.0  # seconds an Alert may wait for its Deal context
MAX_LENGTH = 280  # characters; longer answers are cut at a word boundary
MAX_PARALLEL = 8  # Deals researched at once


@dataclass(frozen=True)
class DealFacts:
    """What the researcher is told about a Deal."""

    deal_id: int
    origin: str
    destination: str
    outbound_date: date
    return_date: date | None
    adults: int
    price_per_adult_eur: float
    baseline_per_adult_eur: float | None = None
    airlines: str | None = None


class Researcher(Protocol):
    def research(self, deal: DealFacts) -> str | None:
        """One short sentence on why this fare might be cheap, or None if nothing was found.
        May block (web research); may raise."""
        ...


def clean(answer: str | None) -> str | None:
    """Single-line, trimmed to MAX_LENGTH; None for empty answers or an explicit NONE."""
    if answer is None:
        return None
    one_line = re.sub(r"\s+", " ", answer).strip().strip('"').strip()
    if not one_line or one_line.upper().rstrip(".") == "NONE":
        return None
    if len(one_line) > MAX_LENGTH:
        one_line = one_line[: MAX_LENGTH - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return one_line


def _facts(d: dict) -> DealFacts:
    return DealFacts(
        deal_id=d["id"],
        origin=d["origin"],
        destination=d["destination"],
        outbound_date=d["outbound_date"],
        return_date=d["return_date"],
        adults=d["adults"],
        price_per_adult_eur=float(d["price_per_adult_eur"]),
        baseline_per_adult_eur=None
        if d["baseline_per_adult_eur"] is None
        else float(d["baseline_per_adult_eur"]),
        airlines=d["airlines"],
    )


def add_deal_context(
    conn: psycopg.Connection,
    researcher: Researcher | None,
    now: datetime,
    timeout: float = DEAL_CONTEXT_TIMEOUT,
) -> dict[str, int]:
    """Research every not-yet-alerted Deal once, waiting at most `timeout` seconds in total.

    Returns counts per outcome (found / none / late / failed)."""
    if researcher is None:
        return {}
    deals = conn.execute(
        """SELECT d.* FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
           WHERE w.status = 'active' AND d.deal_context_status IS NULL
             AND d.verification <> 'failed'
             AND NOT EXISTS (SELECT 1 FROM app.alerts a WHERE a.deal_id = d.id)
           ORDER BY d.id"""
    ).fetchall()
    if not deals:
        return {}
    pool = ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(deals)), thread_name_prefix="ctx")
    futures: dict[Future, dict] = {pool.submit(researcher.research, _facts(d)): d for d in deals}
    done, _ = wait(futures, timeout=timeout)
    # Never wait for stragglers: they finish (or time out in their client) in the background.
    pool.shutdown(wait=False, cancel_futures=True)

    counts: dict[str, int] = {}
    results = []
    for f, d in futures.items():
        context = None
        if f not in done:
            status = "late"
        elif f.exception() is not None:
            status = "failed"
            e = f.exception()
            log.warning("Deal context for Deal %s failed: %s: %s", d["id"], type(e).__name__, e)
        else:
            context = clean(f.result())
            status = "found" if context else "none"
        counts[status] = counts.get(status, 0) + 1
        results.append((context, status, now, d["id"]))
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "UPDATE app.deals SET deal_context = %s, deal_context_status = %s, "
            "deal_context_at = %s WHERE id = %s",
            results,
        )
    return counts


def build_researcher(settings: Settings) -> Researcher | None:
    """FS_DEAL_CONTEXT=claude enables the Claude web-research agent (needs ANTHROPIC_API_KEY);
    unset/empty disables Deal context."""
    kind = settings.env.get("FS_DEAL_CONTEXT", "").strip().lower()
    if not kind:
        return None
    if kind != "claude":
        raise ValueError(f"unknown FS_DEAL_CONTEXT {kind!r} (expected 'claude' or empty)")
    from flight_scanner.deal_context.claude import ClaudeResearcher, ClaudeSettings

    return ClaudeResearcher(ClaudeSettings.from_env(settings.env))
