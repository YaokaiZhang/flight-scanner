"""Verification: check the best Candidates live, within the live source's free budget.

Runs after `deals.record_deals` and before Deal context and Alerts. A Deal is due when its current
Alert round has no Verification outcome yet (a new Deal, a further price drop, a reappearance), so
the budget is never spent twice on the same round.

Ranking: immediate-delivery Watches before Digest Watches (Watch priority: Digests are the low-
priority Watches), then % below the Baseline the Candidate was judged against (% below the Price
threshold when it had none), then the earlier departure.

Budget: the verifier declares `daily_quota` and `monthly_quota` (Helsinki days/months); every live
call spent is recorded in `app.verifications` (`called`), which is what is counted.

Each due Deal ends its round as
  verified   - the live price for the Watch's adults still passes the Deal test (Alerts carry it);
  failed     - the live price does not, or the trip was not found: recorded, never alerted;
  unverified - not checked (budget spent, no verifier configured, verifier outage): alerted as
               Unverified with the cached price, labelled.
The live price is judged against the Baseline the Candidate had if that is a route or country
Baseline; otherwise against the Price insight the same call returned (tier 3, so a provisional
Candidate is re-judged), else as the Candidate was (provisional Baseline / Price threshold). The
test is the one in `marts.candidates`. The answer's Fare observations and Price insight are stored
like any scan (raw store + landing), so later dbt runs use them as Baselines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg

from flight_scanner.clock import OWNER_TZ
from flight_scanner.ingestion import load_parsed, store_payload
from flight_scanner.raw_store import RawStore
from flight_scanner.sources.base import VerificationSource, VerificationTrip

log = logging.getLogger(__name__)

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Judgement:
    outcome: str  # verified | failed
    reason: str
    tier: str | None
    baseline_per_adult_eur: Decimal | None


def _pct_below(d: dict) -> Decimal:
    """How far the cached price is under what the Candidate was judged against (0..1)."""
    if d["baseline_per_adult_eur"]:
        return 1 - d["price_per_adult_eur"] / d["baseline_per_adult_eur"]
    if d["price_threshold_eur"]:
        price = (
            d["price_per_adult_eur"]
            if d["price_threshold_basis"] == "per_adult"
            else (d["price_total_eur"])
        )
        return 1 - price / d["price_threshold_eur"]
    return Decimal(0)


def rank(due: list[dict]) -> list[dict]:
    return sorted(
        due,
        key=lambda d: (
            0 if d["delivery"] == "immediate" else 1,
            -_pct_below(d),
            d["outbound_date"],
            d["id"],
        ),
    )


def deal_test(
    tier: str | None,
    baseline_per_adult: Decimal | None,
    price_per_adult: Decimal,
    price_total: Decimal,
    watch: dict,
) -> bool:
    """The Deal test of `marts.candidates`, for one price."""
    threshold = watch["price_threshold_eur"]
    under = (
        threshold is not None
        and (price_per_adult if watch["price_threshold_basis"] == "per_adult" else price_total)
        < threshold
    )
    below = baseline_per_adult is not None and price_per_adult <= baseline_per_adult * (
        100 - watch["sensitivity_pct"]
    ) / Decimal(100)
    if tier in ("route", "country", "price_insight"):
        return below and (threshold is None or under)
    if tier == "provisional" and threshold is None:
        return below
    return under


def remaining_budget(conn: psycopg.Connection, verifier: VerificationSource, now: datetime) -> int:
    used = conn.execute(
        """SELECT
               count(*) FILTER (WHERE (checked_at AT TIME ZONE %(tz)s)::date
                                      = (%(now)s AT TIME ZONE %(tz)s)::date) AS today,
               count(*) FILTER (WHERE date_trunc('month', checked_at AT TIME ZONE %(tz)s)
                                      = date_trunc('month', %(now)s AT TIME ZONE %(tz)s))
                   AS month
           FROM app.verifications
           WHERE called AND source = %(source)s AND checked_at <= %(now)s""",
        {"tz": OWNER_TZ.key, "now": now, "source": verifier.name},
    ).fetchone()
    return max(0, min(verifier.daily_quota - used["today"], verifier.monthly_quota - used["month"]))


_DUE = """SELECT d.*, w.adults AS watch_adults, w.price_threshold_eur, w.price_threshold_basis,
                 w.sensitivity_pct, w.delivery
          FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
          WHERE w.status = 'active' AND d.absent_since IS NULL
            AND d.verification_round IS DISTINCT FROM d.alert_round"""


def verify_deals(
    conn: psycopg.Connection,
    verifier: VerificationSource | None,
    raw_store: RawStore,
    now: datetime,
) -> dict[str, int]:
    """Verify every Deal whose current Alert round is not judged yet; returns counts per
    outcome (verified / failed / unverified) and `calls` spent."""
    due = rank(conn.execute(_DUE).fetchall())
    counts = {"verified": 0, "failed": 0, "unverified": 0, "calls": 0}
    budget = remaining_budget(conn, verifier, now) if verifier is not None else 0
    for d in due:
        if verifier is None:
            _record(conn, d, now, "unverified", "no_verifier", called=False)
        elif budget <= 0:
            _record(conn, d, now, "unverified", "budget_exhausted", called=False, source=verifier)
        else:
            budget -= 1
            counts["calls"] += 1
            _verify(conn, d, verifier, raw_store, now, counts)
            continue
        counts["unverified"] += 1
    return counts


def _verify(
    conn: psycopg.Connection,
    d: dict,
    verifier: VerificationSource,
    raw_store: RawStore,
    now: datetime,
    counts: dict[str, int],
) -> None:
    trip = VerificationTrip(
        d["origin"], d["destination"], d["outbound_date"], d["return_date"], d["watch_adults"]
    )
    try:
        raw = verifier.fetch(verifier.verification_request(trip))
    except Exception as e:  # noqa: BLE001 - an outage leaves the Deal Unverified, never lost
        log.warning("Verification of Deal %s failed: %s: %s", d["id"], type(e).__name__, e)
        _record(conn, d, now, "unverified", "verifier_error", called=True, source=verifier)
        counts["unverified"] += 1
        return
    with conn.transaction():
        payload_id = store_payload(conn, raw_store, raw)
    parsed = verifier.parse(raw)
    with conn.transaction():
        load_parsed(conn, payload_id, parsed)
    live = _live_price_per_adult(conn, payload_id, raw.fetched_at, trip)
    insight = _insight(conn, payload_id, trip)
    if live is None:
        judgement = Judgement("failed", "not_found", d["baseline_tier"], None)
        live_total = None
    else:
        live_total = (live * trip.adults).quantize(CENT)
        judgement = judge(d, live, live_total, insight)
    _record(
        conn,
        d,
        now,
        judgement.outcome,
        judgement.reason,
        called=True,
        source=verifier,
        payload_id=payload_id,
        live_per_adult=live,
        live_total=live_total,
        rejudged=insight if judgement.tier == "price_insight" else None,
    )
    counts[judgement.outcome] += 1


def judge(d: dict, live: Decimal, live_total: Decimal, insight: dict | None) -> Judgement:
    """Judge the live price: the Candidate's route/country Baseline stays; otherwise the Price
    insight (tier 3) replaces a provisional Baseline or the lack of one."""
    tier, baseline = d["baseline_tier"], d["baseline_per_adult_eur"]
    if tier not in ("route", "country") and insight is not None:
        tier, baseline = "price_insight", insight["median_per_adult_eur"]
    ok = deal_test(tier, baseline, live, live_total, d)
    return Judgement(
        "verified" if ok else "failed", "live_deal" if ok else "live_not_a_deal", tier, baseline
    )


def _live_price_per_adult(
    conn: psycopg.Connection, payload_id: int, fetched_at: datetime, trip: VerificationTrip
) -> Decimal | None:
    """The answer's live price (its Fare observation at the fetch instant), EUR per adult, as
    dbt staging normalises it."""
    if trip.return_date is None:
        sql = """SELECT min(price_per_adult_eur) AS p FROM staging.stg_leg_prices
                 WHERE payload_id = %(id)s AND observed_at = %(at)s AND origin = %(o)s
                   AND destination = %(d)s AND departure_date = %(out)s"""
    else:
        sql = """SELECT min(price_per_adult_eur) AS p FROM staging.stg_round_trip_prices
                 WHERE payload_id = %(id)s AND observed_at = %(at)s AND origin = %(o)s
                   AND destination = %(d)s AND departure_date = %(out)s
                   AND return_date = %(ret)s"""
    return conn.execute(
        sql,
        {
            "id": payload_id,
            "at": fetched_at,
            "o": trip.origin,
            "d": trip.destination,
            "out": trip.outbound_date,
            "ret": trip.return_date,
        },
    ).fetchone()["p"]


def _insight(conn: psycopg.Connection, payload_id: int, trip: VerificationTrip) -> dict | None:
    """The answer's Price insight as a Baseline (as marts.price_insights computes it)."""
    row = conn.execute(
        """SELECT observed_at, history_points, typical_low_per_adult_eur AS low,
                  typical_high_per_adult_eur AS high
           FROM staging.stg_price_insights
           WHERE payload_id = %s AND origin = %s AND destination = %s AND departure_date = %s
             AND return_date IS NOT DISTINCT FROM %s""",
        (payload_id, trip.origin, trip.destination, trip.outbound_date, trip.return_date),
    ).fetchone()
    if row is None:
        return None
    return {
        "median_per_adult_eur": ((row["low"] + row["high"]) / 2).quantize(CENT, ROUND_HALF_UP),
        "method": "typical_price_range",
        "computed_at": row["observed_at"],
        "observations": row["history_points"],
    }


def _record(
    conn: psycopg.Connection,
    d: dict,
    now: datetime,
    outcome: str,
    reason: str,
    *,
    called: bool,
    source: VerificationSource | None = None,
    payload_id: int | None = None,
    live_per_adult: Decimal | None = None,
    live_total: Decimal | None = None,
    rejudged: dict | None = None,
) -> None:
    tier, baseline = d["baseline_tier"], d["baseline_per_adult_eur"]
    if rejudged is not None:
        tier, baseline = "price_insight", rejudged["median_per_adult_eur"]
    with conn.transaction():
        conn.execute(
            """UPDATE app.deals SET verification = %(outcome)s, verification_round = alert_round,
                   verification_reason = %(reason)s,
                   verified_at = CASE WHEN %(called)s THEN %(now)s ELSE verified_at END,
                   verified_price_total_eur = %(live_total)s
               WHERE id = %(id)s""",
            {
                "outcome": outcome,
                "reason": reason,
                "called": called and live_total is not None,
                "now": now,
                "live_total": live_total,
                "id": d["id"],
            },
        )
        if rejudged is not None:
            conn.execute(
                """UPDATE app.deals SET baseline_tier = 'price_insight',
                       baseline_per_adult_eur = %(median_per_adult_eur)s,
                       baseline_method = %(method)s, baseline_computed_at = %(computed_at)s,
                       baseline_observations = %(observations)s,
                       baseline_observation_days = %(observations)s
                   WHERE id = %(id)s""",
                {**rejudged, "id": d["id"]},
            )
        conn.execute(
            """INSERT INTO app.verifications (deal_id, alert_round, checked_at, source, called,
                   outcome, reason, payload_id, cached_price_per_adult_eur,
                   live_price_per_adult_eur, baseline_tier, baseline_per_adult_eur)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                d["id"],
                d["alert_round"],
                now,
                source.name if source is not None else None,
                called,
                outcome,
                reason,
                payload_id,
                d["price_per_adult_eur"],
                live_per_adult,
                tier,
                baseline,
            ),
        )
