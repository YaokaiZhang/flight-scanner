"""Backtest summary per Watch: were its Deals real dips, how often it alerts, what the owner said.

Reads `marts.backtest_deals` (dbt: each past Deal's outcome from later prices) and joins the
live Alert and 👍/👎 tables, so a rating given a minute ago already counts.

- precision        real dips / (real dips + stayed low); null until one of those exists
- alerts_per_week  Alert rounds sent (a round on several channels counts once) per week since the
                   Watch was created (at least one week)
- pct_below        distribution of the Deals' % below Baseline at Alert time (PCT_BUCKETS)
- feedback         latest rating per Deal, overall and per outcome
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Literal

import psycopg
from pydantic import BaseModel

from flight_scanner import feedback

BACKTEST = "marts.backtest_deals"
Outcome = Literal["real_dip", "stayed_low", "pending", "inconclusive", "unjudged"]
OUTCOMES: tuple[Outcome, ...] = ("real_dip", "stayed_low", "pending", "inconclusive", "unjudged")
# lower bounds (inclusive) of the % below Baseline buckets; the last is open-ended
PCT_BUCKETS = (0, 20, 30, 40, 50)


class PastDeal(BaseModel):
    deal_id: int
    origin: str
    destination: str
    outbound_date: date
    return_date: date | None
    detected_at: datetime
    baseline_tier: str | None
    price_per_adult_eur: float
    baseline_per_adult_eur: float | None
    pct_below_baseline: float | None
    later_observation_days: int
    highest_later_price_per_adult_eur: float | None
    outcome: Outcome
    rating: feedback.Rating | None


class PctBucket(BaseModel):
    from_pct: int
    to_pct: int | None  # exclusive; null = open-ended
    deals: int


class PctBelow(BaseModel):
    median: float | None
    buckets: list[PctBucket]


class FeedbackCounts(BaseModel):
    up: int = 0
    down: int = 0
    unrated: int = 0


class OutcomeFeedback(FeedbackCounts):
    outcome: Outcome


class WatchFeedback(FeedbackCounts):
    by_outcome: list[OutcomeFeedback]


class WatchBacktest(BaseModel):
    watch_id: int
    watch_name: str
    status: str
    sensitivity_pct: int
    deals: int
    outcomes: dict[Outcome, int]
    precision: float | None
    alerts: int
    weeks: float
    alerts_per_week: float
    pct_below_baseline: PctBelow
    feedback: WatchFeedback
    past_deals: list[PastDeal]


class Backtest(BaseModel):
    computed_at: datetime | None  # when the backtest model was built (null: no Deals yet)
    watches: list[WatchBacktest]


def _num(v) -> float | None:
    return None if v is None else float(v)


def _built(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT to_regclass(%s) AS t", (BACKTEST,)).fetchone()["t"] is not None


def _past_deals(conn: psycopg.Connection) -> list[dict]:
    if not _built(conn):
        return []
    return conn.execute(
        f"""SELECT b.*, f.feedback_rating
            FROM {BACKTEST} b JOIN app.deals d ON d.id = b.deal_id
            LEFT JOIN LATERAL ({feedback.LATEST_FOR_DEAL}) f ON true
            ORDER BY b.detected_at DESC, b.deal_id DESC"""
    ).fetchall()


def _pct_below(pcts: list[float]) -> PctBelow:
    buckets = []
    for i, low in enumerate(PCT_BUCKETS):
        high = PCT_BUCKETS[i + 1] if i + 1 < len(PCT_BUCKETS) else None
        n = sum(1 for p in pcts if p >= low and (high is None or p < high))
        buckets.append(PctBucket(from_pct=low, to_pct=high, deals=n))
    return PctBelow(median=median(pcts) if pcts else None, buckets=buckets)


def _feedback(deals: list[PastDeal]) -> WatchFeedback:
    def count(ds: list[PastDeal]) -> dict:
        return {
            "up": sum(1 for d in ds if d.rating == "up"),
            "down": sum(1 for d in ds if d.rating == "down"),
            "unrated": sum(1 for d in ds if d.rating is None),
        }

    return WatchFeedback(
        **count(deals),
        by_outcome=[
            OutcomeFeedback(outcome=o, **count([d for d in deals if d.outcome == o]))
            for o in OUTCOMES
        ],
    )


def summary(conn: psycopg.Connection, now: datetime) -> Backtest:
    """The backtest of every Watch (newest first), with its past Deals (newest first)."""
    computed_at = None
    by_watch: dict[int, list[PastDeal]] = {}
    for r in _past_deals(conn):
        computed_at = r["computed_at"]
        by_watch.setdefault(r["watch_id"], []).append(
            PastDeal(
                **{
                    **r,
                    "price_per_adult_eur": float(r["price_per_adult_eur"]),
                    "baseline_per_adult_eur": _num(r["baseline_per_adult_eur"]),
                    "pct_below_baseline": _num(r["pct_below_baseline"]),
                    "highest_later_price_per_adult_eur": _num(
                        r["highest_later_price_per_adult_eur"]
                    ),
                    "rating": r["feedback_rating"],
                }
            )
        )
    watches = conn.execute(
        """SELECT w.id, w.name, w.status, w.sensitivity_pct, w.created_at,
                  (SELECT count(DISTINCT (a.deal_id, a.alert_round))
                   FROM app.alerts a JOIN app.deals d ON d.id = a.deal_id
                   WHERE d.watch_id = w.id AND a.sent_at <= %s) AS alerts
           FROM app.watches w ORDER BY w.created_at DESC, w.id DESC""",
        (now,),
    ).fetchall()
    out = []
    for w in watches:
        deals = by_watch.get(w["id"], [])
        outcomes = {o: sum(1 for d in deals if d.outcome == o) for o in OUTCOMES}
        judged = outcomes["real_dip"] + outcomes["stayed_low"]
        weeks = max((now - w["created_at"]) / timedelta(weeks=1), 1.0)
        out.append(
            WatchBacktest(
                watch_id=w["id"],
                watch_name=w["name"],
                status=w["status"],
                sensitivity_pct=w["sensitivity_pct"],
                deals=len(deals),
                outcomes=outcomes,
                precision=round(outcomes["real_dip"] / judged, 3) if judged else None,
                alerts=w["alerts"],
                weeks=round(weeks, 1),
                alerts_per_week=round(w["alerts"] / weeks, 2),
                pct_below_baseline=_pct_below(
                    [d.pct_below_baseline for d in deals if d.pct_below_baseline is not None]
                ),
                feedback=_feedback(deals),
                past_deals=deals,
            )
        )
    return Backtest(computed_at=computed_at, watches=out)
