"""Seam 2: GET /data-health — per-source freshness and last success, coverage gaps, planner backlog
and skipped tasks, Verification budget used and data-quality check failures. The data comes from
real pipeline runs over fake sources."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from flight_scanner import source_health
from flight_scanner.api import create_app
from flight_scanner.data_health import VerificationBudget
from flight_scanner.db import connect
from flight_scanner.sources.replay import ReplayAdapter
from flight_scanner.testing.harness import PipelineHarness

START = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
DAY = "2026-11-14"


def watch(destinations: list[str], threshold_eur: float | None = None) -> dict:
    return {
        "name": "Health",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": d} for d in destinations]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": DAY},
        "adults": 1,
        "price_threshold": None
        if threshold_eur is None
        else {"amount_eur": threshold_eur, "basis": "total"},
    }


def payload(*legs: tuple[str, float]) -> dict:
    return {
        "currency": "EUR",
        "prices": [
            {"origin": "HEL", "destination": d, "depart_date": DAY, "price": p} for d, p in legs
        ],
    }


@pytest.fixture
def pipeline(db, tmp_path) -> PipelineHarness:
    return PipelineHarness(db, tmp_path, start=START)


def health(db, pipeline, budget: VerificationBudget | None = None) -> dict:
    with TestClient(create_app(db, pipeline.clock, verification_budget=budget)) as api:
        response = api.get("/data-health")
    assert response.status_code == 200
    return response.json()


def at(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def test_before_any_scan_everything_is_empty(db, pipeline):
    body = health(db, pipeline)

    assert at(body["checked_at"]) == START
    assert body["sources"] == []
    assert body["coverage"] == {"route_months": 0, "covered": 0, "gaps": []}
    assert body["backlog"] == {"planned_at": None, "sources": [], "skipped": []}
    assert body["verification"] == []
    assert body["checks"] == {"active": [], "recent": []}


def test_sources_show_freshness_last_success_failures_and_blocks(db, pipeline):
    pipeline.create_watch(watch(["BCN"]))
    pipeline.fake.replay(payload(("BCN", 150)), route=("HEL", "BCN"))
    broken = pipeline.add_source(ReplayAdapter("broken", pipeline.clock))
    broken.fail()
    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()
    with connect(db) as conn:
        source_health.block(conn, "wizz", "wizz: turned away (HTTP 403)", pipeline.clock.now())

    sources = {s["source"]: s for s in health(db, pipeline)["sources"]}

    assert sorted(sources) == ["broken", "fake", "wizz"]
    fake = sources["fake"]
    assert fake["status"] == "ok"
    assert at(fake["last_success_at"]) == START + timedelta(minutes=30)
    assert at(fake["last_observation_at"]) == START + timedelta(minutes=30)
    assert fake["observation_age_minutes"] == 0
    assert (fake["last_failure_at"], fake["last_error"], fake["blocked"]) == (None, None, None)
    broken = sources["broken"]
    assert broken["status"] == "failing"
    assert broken["last_success_at"] is None and broken["last_observation_at"] is None
    assert at(broken["last_failure_at"]) == START + timedelta(minutes=30)
    assert "scripted outage" in broken["last_error"]
    wizz = sources["wizz"]
    assert wizz["status"] == "blocked"
    assert wizz["blocked"]["reason"] == "wizz: turned away (HTTP 403)"


def test_a_rejected_request_fails_only_its_task_and_the_source_stays_ok(db, pipeline):
    pipeline.create_watch(watch(["MAD", "BCN"]))
    pipeline.fake.reject(route=("HEL", "MAD"), reason="airport MAD: not flightable")
    pipeline.fake.replay(payload(("BCN", 150)), route=("HEL", "BCN"))
    pipeline.run()

    with connect(db) as conn:
        tasks = {
            r["destination"]: r
            for r in conn.execute("SELECT destination, status, error FROM app.scan_tasks")
        }
    assert tasks["BCN"]["status"] == "scanned"
    assert tasks["MAD"]["status"] == "failed"
    assert "not flightable" in tasks["MAD"]["error"]
    [fake] = health(db, pipeline)["sources"]
    assert fake["status"] == "ok"
    assert (fake["last_failure_at"], fake["last_error"]) == (None, None)


def test_coverage_gaps_are_demanded_route_months_without_recent_prices(db, pipeline):
    pipeline.create_watch(watch(["BCN", "LIS"]))
    pipeline.create_watch(
        {
            **watch(["MAD"]),
            "name": "Madrid return",
            "trip_pattern": {
                "preset": "fixed_dates",
                "departure": "2026-11-28",
                "return_date": "2026-12-02",
            },
        }
    )
    pipeline.fake.replay(payload(("BCN", 150)), route=("HEL", "BCN"))
    pipeline.fake.replay(
        {
            "currency": "EUR",
            "prices": [
                {"origin": "HEL", "destination": "MAD", "depart_date": "2026-11-28", "price": 90}
            ],
        },
        route=("HEL", "MAD"),
    )
    pipeline.run()

    coverage = health(db, pipeline)["coverage"]

    # HEL->BCN, HEL->LIS and HEL->MAD in November, MAD->HEL in December (the return leg)
    assert (coverage["route_months"], coverage["covered"]) == (4, 2)
    gaps = [(g["origin"], g["destination"], g["month"]) for g in coverage["gaps"]]
    assert gaps == [("HEL", "LIS", "2026-11"), ("MAD", "HEL", "2026-12")]
    assert all(len(g["watch_ids"]) == 1 for g in coverage["gaps"])

    pipeline.clock.advance(days=8)  # prices older than a week no longer count as coverage
    assert health(db, pipeline)["coverage"]["covered"] == 0


def test_backlog_counts_budget_skips_and_lists_every_skipped_task_with_its_reason(db, pipeline):
    pipeline.create_watch(watch(["BCN", "LIS"]))
    blocked = pipeline.add_source(ReplayAdapter("blocked", pipeline.clock))
    with connect(db) as conn:
        source_health.block(conn, blocked.name, "turned away", pipeline.clock.now())
    pipeline.set_budget("fake", per_run=1)
    pipeline.run()

    backlog = health(db, pipeline)["backlog"]

    assert at(backlog["planned_at"]) == START
    per_source = {s["source"]: s for s in backlog["sources"]}
    assert per_source["fake"] == {
        "source": "fake",
        "scheduled": 0,
        "scanned": 1,
        "failed": 0,
        "skipped": 1,
        "backlog": 1,
    }
    assert per_source["blocked"]["skipped"] == 2 and per_source["blocked"]["backlog"] == 0
    reasons = sorted((t["source"], t["reason"]) for t in backlog["skipped"])
    assert reasons == [
        ("blocked", "source blocked: turned away"),
        ("blocked", "source blocked: turned away"),
        ("fake", "over the per-run budget"),
    ]
    assert all(t["month"] == "2026-11" and t["origin"] == "HEL" for t in backlog["skipped"])


def test_verification_budget_used_today_and_this_month_with_outcomes(db, pipeline):
    pipeline.use_google_flights(daily_quota=1, monthly_quota=250)
    pipeline.create_watch(watch(["BCN", "LIS"], threshold_eur=120))
    pipeline.fake.replay(payload(("BCN", 89)), route=("HEL", "BCN"))
    pipeline.fake.replay(payload(("LIS", 95)), route=("HEL", "LIS"))
    pipeline.run()  # two Candidates, one live call: one checked (not found), one budget-capped

    [serpapi] = health(db, pipeline, VerificationBudget("serpapi", 1, 250))["verification"]

    assert serpapi == {
        "source": "serpapi",
        "used_today": 1,
        "daily_quota": 1,
        "used_month": 1,
        "monthly_quota": 250,
        "outcomes": {"verified": 0, "failed": 1, "unverified": 1},
        "reasons": {"budget_exhausted": 1, "not_found": 1},
    }

    pipeline.clock.advance(days=1)
    [later] = health(db, pipeline, VerificationBudget("serpapi", 1, 250))["verification"]
    assert (later["used_today"], later["used_month"]) == (0, 1)


def test_check_failures_are_listed_while_active_and_kept_as_recent(db, pipeline):
    pipeline.create_watch(watch(["BCN"]))
    pipeline.fake.replay(payload(("BCN", 150)), route=("HEL", "BCN"))
    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(payload(), route=("HEL", "BCN"))
    pipeline.run()  # HEL is suddenly empty: gated

    checks = health(db, pipeline)["checks"]
    [gate] = checks["active"]
    assert (gate["check_name"], gate["source"], gate["origin"]) == ("zero_rows", "fake", "HEL")
    assert at(gate["since"]) == START + timedelta(minutes=30)
    assert "HEL" in gate["detail"]
    [fake] = health(db, pipeline)["sources"]
    assert (fake["status"], fake["gated_by"]) == ("gated", ["zero_rows"])

    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(payload(("BCN", 150)), route=("HEL", "BCN"))
    pipeline.run()

    checks = health(db, pipeline)["checks"]
    assert checks["active"] == []
    [recent] = checks["recent"]
    assert (recent["check_name"], recent["origin"]) == ("zero_rows", "HEL")
    assert at(recent["checked_at"]) == START + timedelta(minutes=30)
