"""Seam 2: GET /backtest — per Watch: Deal outcomes, precision, Alert rate, % below Baseline and
👍/👎 joined to the outcomes. Deals come from real pipeline runs over a fake source."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app
from flight_scanner.testing.harness import PipelineHarness

START = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
HEL_BCN = Path(__file__).parents[1] / "fixtures" / "payloads" / "fake" / "hel-bcn-2026-11.json"


def watch(name: str, trip_pattern: dict, **overrides) -> dict:
    return {
        "name": name,
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": trip_pattern,
        "adults": 1,
        "price_threshold": None,
        **overrides,
    }


def leg(origin: str, destination: str, day: str, price: float) -> dict:
    return {"origin": origin, "destination": destination, "depart_date": day, "price": price}


def payload(*legs: dict) -> dict:
    return {"currency": "EUR", "prices": list(legs)}


@pytest.fixture
def pipeline(db, tmp_path) -> PipelineHarness:
    return PipelineHarness(db, tmp_path, start=START)


@pytest.fixture
def api(db, pipeline):
    with TestClient(create_app(db, pipeline.clock)) as client:
        yield client


def by_name(api) -> dict[str, dict]:
    response = api.get("/backtest")
    assert response.status_code == 200
    return {w["watch_name"]: w for w in response.json()["watches"]}


def test_before_any_deal_every_watch_has_an_empty_backtest(api):
    api.post(
        "/watches", json=watch("Quiet", {"preset": "one_way_fixed", "departure": "2026-11-14"})
    )

    response = api.get("/backtest").json()

    assert response["computed_at"] is None
    [quiet] = response["watches"]
    assert quiet["deals"] == 0
    assert quiet["outcomes"] == {
        "real_dip": 0,
        "stayed_low": 0,
        "pending": 0,
        "inconclusive": 0,
        "unjudged": 0,
    }
    assert quiet["precision"] is None
    assert (quiet["alerts"], quiet["alerts_per_week"]) == (0, 0)
    assert quiet["pct_below_baseline"]["median"] is None
    assert [b["deals"] for b in quiet["pct_below_baseline"]["buckets"]] == [0, 0, 0, 0, 0]
    assert quiet["past_deals"] == []


def test_a_threshold_only_deal_is_unjudged_and_counts_toward_the_alert_rate(api, pipeline):
    api.post(
        "/watches",
        json=watch(
            "Barcelona",
            {"preset": "one_way_fixed", "departure": "2026-11-14"},
            price_threshold={"amount_eur": 120, "basis": "total"},
        ),
    )
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))
    pipeline.run()
    [deal] = api.get("/deals").json()
    api.post(f"/deals/{deal['id']}/feedback", json={"rating": "up"})

    pipeline.clock.advance(days=21)  # the Watch is three weeks old, with one Alert
    pipeline.run()
    barcelona = by_name(api)["Barcelona"]

    assert barcelona["outcomes"]["unjudged"] == 1
    assert barcelona["precision"] is None
    assert (barcelona["alerts"], barcelona["weeks"], barcelona["alerts_per_week"]) == (1, 3, 0.33)
    [past] = barcelona["past_deals"]
    assert (past["deal_id"], past["pct_below_baseline"], past["rating"]) == (deal["id"], None, "up")
    assert (barcelona["feedback"]["up"], barcelona["feedback"]["down"]) == (1, 0)
    unjudged = next(f for f in barcelona["feedback"]["by_outcome"] if f["outcome"] == "unjudged")
    assert (unjudged["up"], unjudged["down"], unjudged["unrated"]) == (1, 0, 0)


def test_precision_distribution_and_feedback_by_outcome_for_a_watch(api, pipeline):
    api.post(
        "/watches",
        json=watch(
            "Long weekend",
            {
                "preset": "fixed_departure",
                "departure": "2026-11-18",
                "stay_nights": {"min": 3, "max": 4},
            },
        ),
    )
    # A week of 3-4-night trips at 100 (17->21, 18->21, 18->22): a route Baseline of 100.
    for i in range(8):
        pipeline.clock.set(START + timedelta(days=i))
        pipeline.fake.replay(
            payload(
                leg("HEL", "BCN", "2026-11-17", 50),
                leg("HEL", "BCN", "2026-11-18", 50),
                leg("BCN", "HEL", "2026-11-21", 50),
                leg("BCN", "HEL", "2026-11-22", 50),
            )
        )
        pipeline.collect()
    # Day 8: 18->21 at 50 (50% below) and 18->22 at 65 (35% below) are Deals.
    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(
        payload(
            leg("HEL", "BCN", "2026-11-18", 25),
            leg("BCN", "HEL", "2026-11-21", 25),
            leg("BCN", "HEL", "2026-11-22", 40),
        )
    )
    pipeline.run()
    deals = {d["return_date"]: d["id"] for d in api.get("/deals").json()}
    # Then 18->21 goes back to 100 (a real dip) while 18->22 stays at 65.
    for i in range(9, 12):
        pipeline.clock.set(START + timedelta(days=i))
        pipeline.fake.replay(
            payload(
                leg("HEL", "BCN", "2026-11-18", 25),
                leg("BCN", "HEL", "2026-11-21", 75),
                leg("BCN", "HEL", "2026-11-22", 40),
            )
        )
        pipeline.collect()
    pipeline.clock.advance(hours=1)
    pipeline.run()
    api.post(f"/deals/{deals['2026-11-21']}/feedback", json={"rating": "up"})
    api.post(f"/deals/{deals['2026-11-22']}/feedback", json={"rating": "down"})

    result = by_name(api)["Long weekend"]

    assert result["deals"] == 2
    assert (result["outcomes"]["real_dip"], result["outcomes"]["stayed_low"]) == (1, 1)
    assert result["precision"] == 0.5
    # 2 Alerts over 11 days and an hour
    assert (result["alerts"], result["weeks"], result["alerts_per_week"]) == (2, 1.6, 1.27)
    assert result["pct_below_baseline"]["median"] == 42.5
    assert result["pct_below_baseline"]["buckets"] == [
        {"from_pct": 0, "to_pct": 20, "deals": 0},
        {"from_pct": 20, "to_pct": 30, "deals": 0},
        {"from_pct": 30, "to_pct": 40, "deals": 1},
        {"from_pct": 40, "to_pct": 50, "deals": 0},
        {"from_pct": 50, "to_pct": None, "deals": 1},
    ]
    feedback = {f["outcome"]: f for f in result["feedback"]["by_outcome"]}
    assert (feedback["real_dip"]["up"], feedback["real_dip"]["down"]) == (1, 0)
    assert (feedback["stayed_low"]["up"], feedback["stayed_low"]["down"]) == (0, 1)
    outcomes = {p["return_date"]: p["outcome"] for p in result["past_deals"]}
    assert outcomes == {"2026-11-21": "real_dip", "2026-11-22": "stayed_low"}
