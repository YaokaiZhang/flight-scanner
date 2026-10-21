"""The data-health page's data: can the owner trust what the scanner sees right now?

  summary(conn, now, verification_budget) -> DataHealth

- sources       per scan source: newest Fare observation (freshness), last scanned / failed task
                and its error, a block (`source_health`) and the data-quality checks gating it.
                status: blocked > failing (the last executed task failed) > gated > no_data > ok
- coverage      the route-months current Watch slots demand (outbound leg, and the return leg of
                round trips) and those with no Fare observation of a departure in that month
                within COVERAGE_WINDOW (the gaps)
- backlog       the latest scan plan per source (tasks scheduled / scanned / failed / skipped);
                `backlog` = skipped over a budget or quota (blocked sources and recently scanned
                route-months are skipped too, but are not waiting for budget), plus every
                skipped task with its reason
- verification  live calls spent per Verification source this Helsinki day and month, against
                the configured quota, and the month's outcomes and reasons
- checks        the data-quality gates in force (`data_quality.gates`) and the failures of the
                last RECENT_CHECKS
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import psycopg
from pydantic import BaseModel

from flight_scanner import data_quality, source_health
from flight_scanner.clock import OWNER_TZ

COVERAGE_WINDOW = timedelta(days=7)
RECENT_CHECKS = timedelta(days=7)
BUDGET_REASONS = ("over the per-run budget", "over the daily quota")
SKIPPED_LIMIT = 200
GAPS_LIMIT = 200

SourceStatus = Literal["ok", "no_data", "gated", "failing", "blocked"]


@dataclass(frozen=True)
class VerificationBudget:
    """The configured live-check quota of a Verification source (Helsinki day and month)."""

    source: str
    daily_quota: int
    monthly_quota: int


class Blocked(BaseModel):
    blocked_at: datetime
    reason: str


class SourceHealth(BaseModel):
    source: str
    status: SourceStatus
    last_observation_at: datetime | None  # newest Fare observation
    observation_age_minutes: int | None
    last_success_at: datetime | None  # last scan task scanned
    last_failure_at: datetime | None
    last_error: str | None
    blocked: Blocked | None
    gated_by: list[str]  # data-quality checks gating (some of) its prices


class CoverageGap(BaseModel):
    origin: str
    destination: str
    month: str  # YYYY-MM
    watch_ids: list[int]


class Coverage(BaseModel):
    route_months: int
    covered: int
    gaps: list[CoverageGap]


class SourceBacklog(BaseModel):
    source: str
    scheduled: int
    scanned: int
    failed: int
    skipped: int
    backlog: int


class SkippedTask(BaseModel):
    source: str
    origin: str
    destination: str | None  # null: wildcard
    month: str
    priority: float
    reason: str | None


class Backlog(BaseModel):
    planned_at: datetime | None
    sources: list[SourceBacklog]
    skipped: list[SkippedTask]


class VerificationUse(BaseModel):
    source: str
    used_today: int
    daily_quota: int | None
    used_month: int
    monthly_quota: int | None
    outcomes: dict[str, int]  # this month: verified / failed / unverified
    reasons: dict[str, int]  # this month


class CheckFailure(BaseModel):
    check_name: str
    source: str
    origin: str | None  # null: the whole source
    detail: str
    checked_at: datetime
    since: datetime | None = None


class Checks(BaseModel):
    active: list[CheckFailure]
    recent: list[CheckFailure]


class DataHealth(BaseModel):
    checked_at: datetime
    sources: list[SourceHealth]
    coverage: Coverage
    backlog: Backlog
    verification: list[VerificationUse]
    checks: Checks


def _verification_sources(conn: psycopg.Connection, budget: VerificationBudget | None) -> set[str]:
    rows = conn.execute("SELECT DISTINCT source FROM app.verifications WHERE source IS NOT NULL")
    return {r["source"] for r in rows} | ({budget.source} if budget else set())


def _sources(
    conn: psycopg.Connection, now: datetime, verifiers: set[str], gates: list
) -> list[SourceHealth]:
    observed = {
        r["source"]: r["at"]
        for r in conn.execute(
            """SELECT source, max(observed_at) AS at FROM (
                   SELECT source, observed_at FROM landing.leg_prices WHERE observed_at <= %(now)s
                   UNION ALL
                   SELECT source, observed_at FROM landing.round_trip_prices
                   WHERE observed_at <= %(now)s) o
               GROUP BY source""",
            {"now": now},
        )
    }
    tasks = {
        r["source"]: r
        for r in conn.execute(
            """SELECT source,
                      max(finished_at) FILTER (WHERE status = 'scanned') AS success_at,
                      max(finished_at) FILTER (WHERE status = 'failed') AS failure_at,
                      (array_agg(error ORDER BY finished_at DESC, id DESC)
                          FILTER (WHERE status = 'failed'))[1] AS error
               FROM app.scan_tasks
               WHERE finished_at <= %(now)s
               GROUP BY source""",
            {"now": now},
        )
    }
    blocks = source_health.blocks(conn)
    names = sorted((set(observed) | set(tasks) | set(blocks)) - verifiers)
    out = []
    for name in names:
        t = tasks.get(name, {})
        success, failure = t.get("success_at"), t.get("failure_at")
        block = blocks.get(name)
        gated_by = sorted({g.check_name for g in gates if g.source == name})
        newest = observed.get(name)
        if block is not None:
            status: SourceStatus = "blocked"
        elif failure is not None and (success is None or failure >= success):
            status = "failing"
        elif gated_by:
            status = "gated"
        elif newest is None:
            status = "no_data"
        else:
            status = "ok"
        out.append(
            SourceHealth(
                source=name,
                status=status,
                last_observation_at=newest,
                observation_age_minutes=None
                if newest is None
                else int((now - newest) / timedelta(minutes=1)),
                last_success_at=success,
                last_failure_at=failure,
                last_error=t.get("error"),
                blocked=None
                if block is None
                else Blocked(blocked_at=block.blocked_at, reason=block.reason),
                gated_by=gated_by,
            )
        )
    return out


def _coverage(conn: psycopg.Connection, now: datetime, verifiers: set[str]) -> Coverage:
    rows = conn.execute(
        """WITH demand AS (
               SELECT origin, destination,
                      CAST(date_trunc('month', outbound_date) AS date) AS month, watch_id
               FROM app.watch_slots
               UNION
               SELECT destination, origin, CAST(date_trunc('month', return_date) AS date), watch_id
               FROM app.watch_slots WHERE return_date IS NOT NULL),
           route_months AS (
               SELECT origin, destination, month, array_agg(DISTINCT watch_id) AS watch_ids
               FROM demand GROUP BY origin, destination, month),
           seen AS (
               SELECT DISTINCT origin, destination,
                      CAST(date_trunc('month', departure_date) AS date) AS month
               FROM (SELECT source, origin, destination, departure_date, observed_at
                     FROM landing.leg_prices
                     UNION ALL
                     SELECT source, origin, destination, departure_date, observed_at
                     FROM landing.round_trip_prices) o
               WHERE observed_at <= %(now)s AND observed_at > %(since)s
                 AND NOT (source = ANY(%(verifiers)s)))
           SELECT r.origin, r.destination, r.month, r.watch_ids, s.origin IS NOT NULL AS covered
           FROM route_months r
           LEFT JOIN seen s
             ON s.origin = r.origin AND s.destination = r.destination AND s.month = r.month
           ORDER BY r.month, r.origin, r.destination""",
        {"now": now, "since": now - COVERAGE_WINDOW, "verifiers": sorted(verifiers)},
    ).fetchall()
    gaps = [
        CoverageGap(
            origin=r["origin"],
            destination=r["destination"],
            month=r["month"].isoformat()[:7],
            watch_ids=sorted(r["watch_ids"]),
        )
        for r in rows
        if not r["covered"]
    ]
    return Coverage(
        route_months=len(rows), covered=sum(r["covered"] for r in rows), gaps=gaps[:GAPS_LIMIT]
    )


def _backlog(conn: psycopg.Connection) -> Backlog:
    plan = conn.execute(
        "SELECT id, planned_at FROM app.scan_plans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if plan is None:
        return Backlog(planned_at=None, sources=[], skipped=[])
    counts = conn.execute(
        """SELECT source,
                  count(*) FILTER (WHERE status = 'scheduled') AS scheduled,
                  count(*) FILTER (WHERE status = 'scanned') AS scanned,
                  count(*) FILTER (WHERE status = 'failed') AS failed,
                  count(*) FILTER (WHERE status = 'skipped') AS skipped,
                  count(*) FILTER (WHERE status = 'skipped' AND reason = ANY(%(budget)s))
                      AS backlog
           FROM app.scan_tasks WHERE plan_id = %(plan)s GROUP BY source ORDER BY source""",
        {"plan": plan["id"], "budget": list(BUDGET_REASONS)},
    ).fetchall()
    skipped = conn.execute(
        """SELECT source, origin, destination, month, priority, reason FROM app.scan_tasks
           WHERE plan_id = %s AND status = 'skipped'
           ORDER BY source, priority DESC, id LIMIT %s""",
        (plan["id"], SKIPPED_LIMIT),
    ).fetchall()
    return Backlog(
        planned_at=plan["planned_at"],
        sources=[SourceBacklog(**r) for r in counts],
        skipped=[
            SkippedTask(
                **{**r, "month": r["month"].isoformat()[:7], "priority": float(r["priority"])}
            )
            for r in skipped
        ],
    )


def _verification(
    conn: psycopg.Connection, now: datetime, budget: VerificationBudget | None
) -> list[VerificationUse]:
    rows = conn.execute(
        """WITH v AS (
               SELECT *, (checked_at AT TIME ZONE %(tz)s)::date AS day,
                      date_trunc('month', checked_at AT TIME ZONE %(tz)s) AS month
               FROM app.verifications
               WHERE source IS NOT NULL AND checked_at <= %(now)s)
           SELECT source, outcome, reason,
                  count(*) FILTER (WHERE called AND day = (%(now)s AT TIME ZONE %(tz)s)::date)
                      AS used_today,
                  count(*) FILTER (WHERE called) AS used_month,
                  count(*) AS decisions
           FROM v WHERE month = date_trunc('month', %(now)s AT TIME ZONE %(tz)s)
           GROUP BY source, outcome, reason""",
        {"tz": OWNER_TZ.key, "now": now},
    ).fetchall()
    names = {r["source"] for r in rows} | ({budget.source} if budget else set())
    out = []
    for name in sorted(names):
        mine = [r for r in rows if r["source"] == name]
        outcomes = {"verified": 0, "failed": 0, "unverified": 0}
        reasons: dict[str, int] = {}
        for r in mine:
            outcomes[r["outcome"]] += r["decisions"]
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + r["decisions"]
        known = budget if budget is not None and budget.source == name else None
        out.append(
            VerificationUse(
                source=name,
                used_today=sum(r["used_today"] for r in mine),
                daily_quota=known.daily_quota if known else None,
                used_month=sum(r["used_month"] for r in mine),
                monthly_quota=known.monthly_quota if known else None,
                outcomes=outcomes,
                reasons=dict(sorted(reasons.items())),
            )
        )
    return out


def _failure(g: data_quality.Gate) -> CheckFailure:
    return CheckFailure(
        check_name=g.check_name,
        source=g.source,
        origin=g.origin,
        detail=g.detail,
        checked_at=g.checked_at,
        since=g.since,
    )


def summary(
    conn: psycopg.Connection, now: datetime, verification_budget: VerificationBudget | None = None
) -> DataHealth:
    verifiers = _verification_sources(conn, verification_budget)
    gates = data_quality.gates(conn)
    return DataHealth(
        checked_at=now,
        sources=_sources(conn, now, verifiers, gates),
        coverage=_coverage(conn, now, verifiers),
        backlog=_backlog(conn),
        verification=_verification(conn, now, verification_budget),
        checks=Checks(
            active=[_failure(g) for g in gates],
            recent=[_failure(g) for g in data_quality.recent_failures(conn, now - RECENT_CHECKS)],
        ),
    )
