"""The scan planner: spend each source's limited budget where Deals are most likely.

Every pipeline run turns the active Watches' slots into scan tasks, one per (source, origin,
destination or wildcard, departure month), shared by every Watch that wants that route-month.
Tasks are ranked, scheduled in priority order while they fit the source's budget, and the rest
are recorded as skipped. Ingestion then executes the scheduled tasks and reports back.

Public interface:
  Budget(per_run, per_day)       request limits of one source (None: unlimited)
  plan(conn, slots, sources, budgets, now, today) -> plan id
                                 build, rank, schedule and record this run's tasks
  scheduled(conn, plan_id)       the plan's scheduled tasks (what ingestion fetches)
  finish(conn, statuses, now)    record which scheduled tasks were scanned or failed
  latest(conn, status, source)   the most recent plan, as the API shows it
  DEAL_GAP_ESTIMATORS            pluggable "how far is the best price from a Deal" signals

Demand per slot: the outbound leg (origin -> destination in the outbound month, also asking for
Round-trip prices when the slot has a return) and, for round trips, the return leg (destination
-> origin in the return month). A source that can price "anywhere" (`wildcard_destinations`) gets
one wildcard task instead of per-airport tasks when an origin-month demands at least
WILDCARD_MIN_DESTINATIONS destinations. Paused and expired Watches have no slots, so no tasks.

Ranking (each factor 0..1, weighted sum = priority; ties go to the earlier departure):
  proximity   1 / (1 + days until the earliest departure / 30)
  volatility  largest relative price spread (max - min) / min of one departure date over the
              last 7 days of price history (0 without history)
  deal        1 - gap, clipped to 0..1, where gap = best current price / Deal price - 1 for the
              closest slot; NEUTRAL_DEAL when no estimator knows the route-month
  staleness   hours since this task was last scanned / 24, clipped; 1 when never scanned
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import psycopg
from psycopg.types.json import Jsonb

from flight_scanner.clock import OWNER_TZ
from flight_scanner.sources.base import ScanRequest, SourceAdapter
from flight_scanner.watches import Demand, WatchSlot

WILDCARD_MIN_DESTINATIONS = 6
WEIGHTS = {"proximity": 0.3, "volatility": 0.2, "deal": 0.3, "staleness": 0.2}
NEUTRAL_DEAL = 0.5
VOLATILITY_WINDOW = timedelta(days=7)
STALE_AFTER = timedelta(hours=24)
KEEP_PLANS_FOR = timedelta(days=30)

RouteMonth = tuple[str, str, date]  # (origin, destination airport, first day of month)


@dataclass(frozen=True)
class Budget:
    per_run: int | None = None  # requests in one pipeline run
    per_day: int | None = None  # requests per owner (Helsinki) calendar day


@dataclass
class Task:
    origin: str
    destination: str | None  # None: wildcard
    month: date
    round_trip: bool = False
    earliest_departure: date = date.max
    watch_ids: set[int] = field(default_factory=set)
    destinations: set[str] = field(default_factory=set)  # airports it prices

    @property
    def demand(self) -> Demand:
        return Demand(self.origin, self.destination, self.month, self.round_trip)

    def route_months(self) -> list[RouteMonth]:
        return [(self.origin, d, self.month) for d in sorted(self.destinations)]

    def add(self, round_trip: bool, departure: date, watch_id: int, destination: str) -> None:
        self.round_trip = self.round_trip or round_trip
        self.earliest_departure = min(self.earliest_departure, departure)
        self.watch_ids.add(watch_id)
        self.destinations.add(destination)


@dataclass(frozen=True)
class ScheduledTask:
    id: int
    source: str
    requests: list[ScanRequest]


# --- demand ------------------------------------------------------------------------------------


def _airport_tasks(slots: Iterable[WatchSlot]) -> dict[RouteMonth, Task]:
    tasks: dict[RouteMonth, Task] = {}

    def add(o: str, d: str, day: date, round_trip: bool, watch_id: int) -> None:
        key = (o, d, day.replace(day=1))
        task = tasks.setdefault(key, Task(o, d, key[2]))
        task.add(round_trip, day, watch_id, d)

    for s in slots:
        add(s.origin, s.destination, s.outbound_date, s.return_date is not None, s.watch_id)
        if s.return_date is not None:
            add(s.destination, s.origin, s.return_date, False, s.watch_id)
    return tasks


def _collapse(tasks: Iterable[Task]) -> list[Task]:
    """One wildcard task per origin-month that demands many destinations."""
    groups: dict[tuple[str, date], list[Task]] = {}
    for t in tasks:
        groups.setdefault((t.origin, t.month), []).append(t)
    out: list[Task] = []
    for (origin, month), group in groups.items():
        if len(group) < WILDCARD_MIN_DESTINATIONS:
            out.extend(group)
            continue
        wildcard = Task(origin, None, month)
        for t in group:
            wildcard.round_trip = wildcard.round_trip or t.round_trip
            wildcard.earliest_departure = min(wildcard.earliest_departure, t.earliest_departure)
            wildcard.watch_ids |= t.watch_ids
            wildcard.destinations |= t.destinations
        out.append(wildcard)
    return out


def tasks_for(source: SourceAdapter, slots: Sequence[WatchSlot]) -> list[Task]:
    tasks = list(_airport_tasks(slots).values())
    if getattr(source, "wildcard_destinations", False):
        tasks = _collapse(tasks)
    return tasks


# --- signals -----------------------------------------------------------------------------------

DealGapEstimator = Callable[[psycopg.Connection, datetime], Mapping[RouteMonth, float]]


def _exists(conn: psycopg.Connection, relation: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) AS r", (relation,)).fetchone()["r"] is not None


def threshold_gap(conn: psycopg.Connection, now: datetime) -> dict[RouteMonth, float]:
    """Gap of each Watch slot's current price (marts.trip_prices, last run) to its Price
    threshold, per adult; attributed to the slot's outbound and return route-months."""
    if not _exists(conn, "marts.trip_prices"):
        return {}
    rows = conn.execute(
        """SELECT p.origin, p.destination, p.outbound_date, p.return_date,
                  p.price_per_adult_eur / (CASE WHEN w.price_threshold_basis = 'per_adult'
                       THEN w.price_threshold_eur
                       ELSE w.price_threshold_eur / w.adults END) - 1 AS gap
           FROM marts.trip_prices p JOIN app.watches w ON w.id = p.watch_id
           WHERE w.status = 'active' AND w.price_threshold_eur IS NOT NULL"""
    )
    return _gaps_by_route_month(rows)


def _gaps_by_route_month(rows: Iterable[Mapping]) -> dict[RouteMonth, float]:
    """Smallest gap per route-month; a slot counts for its outbound and return route-months."""
    gaps: dict[RouteMonth, float] = {}
    for r in rows:
        keys = [(r["origin"], r["destination"], r["outbound_date"].replace(day=1))]
        if r["return_date"] is not None:
            keys.append((r["destination"], r["origin"], r["return_date"].replace(day=1)))
        for k in keys:
            gaps[k] = min(gaps.get(k, float("inf")), float(r["gap"]))
    return gaps


def baseline_gap(conn: psycopg.Connection, now: datetime) -> dict[RouteMonth, float]:
    """Gap of each Watch slot's current price (marts.trip_prices, last run) to its Deal price:
    the Baseline it would be judged against (route, else country, else provisional tier, from
    marts.baselines) less the Watch's sensitivity. Slots without any Baseline are unknown."""
    if not all(_exists(conn, t) for t in ("marts.trip_prices", "marts.baselines", "ref.airports")):
        return {}
    rows = conn.execute(
        """WITH slots AS (
               SELECT p.origin, p.destination, p.outbound_date, p.return_date,
                      p.price_per_adult_eur, w.sensitivity_pct,
                      coalesce(oa.city, p.origin) AS origin_city, da.country,
                      CAST(date_trunc('month', p.outbound_date) AS date) AS month,
                      CASE WHEN p.return_date IS NULL THEN 'one_way'
                           WHEN p.return_date - p.outbound_date <= 2 THEN '1-2'
                           WHEN p.return_date - p.outbound_date <= 4 THEN '3-4'
                           WHEN p.return_date - p.outbound_date <= 7 THEN '5-7'
                           WHEN p.return_date - p.outbound_date <= 14 THEN '8-14'
                           ELSE '15+' END AS bucket
               FROM marts.trip_prices p
               JOIN app.watches w ON w.id = p.watch_id
               LEFT JOIN ref.airports oa ON oa.code = p.origin
               LEFT JOIN ref.airports da ON da.code = p.destination
               WHERE w.status = 'active')
           SELECT s.origin, s.destination, s.outbound_date, s.return_date,
                  s.price_per_adult_eur / (b.median_per_adult_eur * (100 - s.sensitivity_pct)
                      / 100.0) - 1 AS gap
           FROM slots s
           JOIN LATERAL (
               SELECT median_per_adult_eur FROM marts.baselines b
               WHERE b.origin_city = s.origin_city AND b.departure_month = s.month
                 AND b.stay_bucket = s.bucket AND b.median_per_adult_eur > 0
                 AND ((b.tier IN ('route', 'provisional') AND b.destination = s.destination)
                      OR (b.tier = 'country' AND b.destination = s.country))
               ORDER BY CASE b.tier WHEN 'route' THEN 1 WHEN 'country' THEN 2 ELSE 3 END
               LIMIT 1) b ON true"""
    )
    return _gaps_by_route_month(rows)


# Tried in order; the first estimator that knows a route-month wins: the Baseline the Deal test
# uses (ticket 05), then the Price threshold.
DEAL_GAP_ESTIMATORS: list[DealGapEstimator] = [baseline_gap, threshold_gap]


def _deal_gaps(conn: psycopg.Connection, now: datetime) -> dict[RouteMonth, float]:
    merged: dict[RouteMonth, float] = {}
    for estimate in DEAL_GAP_ESTIMATORS:
        for key, gap in estimate(conn, now).items():
            merged.setdefault(key, gap)
    return merged


def _volatility(conn: psycopg.Connection, now: datetime) -> dict[RouteMonth, float]:
    if not _exists(conn, "history.leg_price_history"):
        return {}
    rows = conn.execute(
        """SELECT origin, destination, month, max(spread) AS spread FROM (
               SELECT origin, destination,
                      CAST(date_trunc('month', departure_date) AS date) AS month,
                      (max(price_per_adult_eur) - min(price_per_adult_eur))
                          / nullif(min(price_per_adult_eur), 0) AS spread
               FROM history.leg_price_history
               WHERE valid_from <= %(now)s AND (valid_to IS NULL OR valid_to >= %(since)s)
               GROUP BY source, origin, destination, departure_date) d
           GROUP BY origin, destination, month""",
        {"now": now, "since": now - VOLATILITY_WINDOW},
    )
    return {(r["origin"], r["destination"], r["month"]): float(r["spread"] or 0) for r in rows}


def _last_scans(conn: psycopg.Connection) -> dict[tuple, datetime]:
    rows = conn.execute(
        """SELECT t.source, t.origin, t.destination, t.month, max(p.planned_at) AS at
           FROM app.scan_tasks t JOIN app.scan_plans p ON p.id = t.plan_id
           WHERE t.status = 'scanned' GROUP BY t.source, t.origin, t.destination, t.month"""
    )
    return {(r["source"], r["origin"], r["destination"], r["month"]): r["at"] for r in rows}


def _used_today(conn: psycopg.Connection, now: datetime) -> dict[str, int]:
    day_start = datetime.combine(now.astimezone(OWNER_TZ).date(), time(), OWNER_TZ)
    rows = conn.execute(
        """SELECT t.source, sum(jsonb_array_length(t.requests)) AS n
           FROM app.scan_tasks t JOIN app.scan_plans p ON p.id = t.plan_id
           WHERE t.status <> 'skipped' AND p.planned_at >= %s GROUP BY t.source""",
        (day_start,),
    )
    return {r["source"]: int(r["n"]) for r in rows}


@dataclass
class Signals:
    volatility: dict[RouteMonth, float]
    deal_gaps: dict[RouteMonth, float]
    last_scans: dict[tuple, datetime]

    @classmethod
    def load(cls, conn: psycopg.Connection, now: datetime) -> Signals:
        return cls(_volatility(conn, now), _deal_gaps(conn, now), _last_scans(conn))


# --- ranking and scheduling ----------------------------------------------------------------------


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def factors(task: Task, source: str, signals: Signals, now: datetime, today: date) -> dict:
    days = max((task.earliest_departure - today).days, 0)
    keys = task.route_months()
    volatility = max((signals.volatility.get(k, 0.0) for k in keys), default=0.0)
    gaps = [signals.deal_gaps[k] for k in keys if k in signals.deal_gaps]
    last = signals.last_scans.get((source, task.origin, task.destination, task.month))
    return {
        "proximity": 1 / (1 + days / 30),
        "volatility": _clip(volatility),
        "deal": _clip(1 - min(gaps)) if gaps else NEUTRAL_DEAL,
        "staleness": 1.0 if last is None else _clip((now - last) / STALE_AFTER),
    }


def priority(f: Mapping[str, float]) -> float:
    return round(sum(WEIGHTS[k] * f[k] for k in WEIGHTS), 6)


def plan(
    conn: psycopg.Connection,
    slots: Sequence[WatchSlot],
    sources: Sequence[SourceAdapter],
    budgets: Mapping[str, Budget],
    now: datetime,
    today: date,
) -> int:
    """Record this run's scan plan; returns its id."""
    conn.execute("DELETE FROM app.scan_plans WHERE planned_at < %s", (now - KEEP_PLANS_FOR,))
    signals = Signals.load(conn, now)
    used_today = _used_today(conn, now)
    plan_id = conn.execute(
        "INSERT INTO app.scan_plans (planned_at) VALUES (%s) RETURNING id", (now,)
    ).fetchone()["id"]
    rows = []
    for source in sources:
        budget = budgets.get(source.name, Budget())
        per_run = budget.per_run
        per_day = (
            None if budget.per_day is None else budget.per_day - used_today.get(source.name, 0)
        )
        ranked = []
        for task in tasks_for(source, slots):
            f = factors(task, source.name, signals, now, today)
            ranked.append((priority(f), task, f))
        ranked.sort(
            key=lambda r: (-r[0], r[1].earliest_departure, r[1].origin, r[1].destination or "")
        )
        for score, task, f in ranked:
            requests = source.plan([task.demand])
            cost = len(requests)
            status, reason = "scheduled", None
            if per_run is not None and cost > per_run:
                status, reason = "skipped", "over the per-run budget"
            elif per_day is not None and cost > per_day:
                status, reason = "skipped", "over the daily quota"
            else:
                per_run = None if per_run is None else per_run - cost
                per_day = None if per_day is None else per_day - cost
            rows.append(
                (
                    plan_id,
                    source.name,
                    task.origin,
                    task.destination,
                    task.month,
                    task.round_trip,
                    task.earliest_departure,
                    len(task.destinations),
                    sorted(task.watch_ids),
                    score,
                    Jsonb({k: round(v, 4) for k, v in f.items()}),
                    Jsonb([json.loads(json.dumps(dict(r.params))) for r in requests]),
                    status,
                    reason,
                )
            )
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app.scan_tasks (plan_id, source, origin, destination, month, round_trip,
                   earliest_departure, destinations, watch_ids, priority, factors, requests,
                   status, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )
    return plan_id


def scheduled(conn: psycopg.Connection, plan_id: int) -> list[ScheduledTask]:
    rows = conn.execute(
        """SELECT id, source, requests FROM app.scan_tasks
           WHERE plan_id = %s AND status = 'scheduled' ORDER BY priority DESC, id""",
        (plan_id,),
    )
    return [
        ScheduledTask(r["id"], r["source"], [ScanRequest(r["source"], p) for p in r["requests"]])
        for r in rows
    ]


def latest_plan_id(conn: psycopg.Connection) -> int | None:
    row = conn.execute("SELECT max(id) AS id FROM app.scan_plans").fetchone()
    return row["id"]


def finish(conn: psycopg.Connection, statuses: Mapping[int, str], now: datetime) -> None:
    """Record the outcome ("scanned" or "failed") of executed scheduled tasks."""
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE app.scan_tasks SET status = %s, finished_at = %s WHERE id = %s",
            [(status, now, task_id) for task_id, status in statuses.items()],
        )


def latest(
    conn: psycopg.Connection, status: str | None = None, source: str | None = None
) -> tuple[datetime | None, list[dict]]:
    """The most recent plan's planned_at and tasks (highest priority first)."""
    row = conn.execute(
        "SELECT id, planned_at FROM app.scan_plans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None, []
    tasks = conn.execute(
        """SELECT id, source, origin, destination, month, round_trip, earliest_departure,
                  destinations, watch_ids, priority, factors, requests, status, reason
           FROM app.scan_tasks
           WHERE plan_id = %(plan)s
             AND (%(status)s::text IS NULL OR status = %(status)s)
             AND (%(source)s::text IS NULL OR source = %(source)s)
           ORDER BY source, priority DESC, id""",
        {"plan": row["id"], "status": status, "source": source},
    ).fetchall()
    return row["planned_at"], tasks
