"""Seam 1: the scan planner. Watches in -> source requests (what the fake source is asked) and
scan tasks (read through the API) out, with Alerts still flowing for what was scanned."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app


@pytest.fixture
def api(pipeline):
    with TestClient(create_app(pipeline.db, pipeline.clock)) as client:
        yield client


def airports(*codes: str) -> dict:
    return {"include": [{"kind": "airport", "code": c} for c in codes]}


def one_way(destinations: dict, departure: str = "2026-11-14", threshold: float = 100) -> dict:
    return {
        "name": "Watch",
        "origins": airports("HEL"),
        "destinations": destinations,
        "trip_pattern": {"preset": "one_way_fixed", "departure": departure},
        "price_threshold": {"amount_eur": threshold, "basis": "total"},
    }


def fare(origin: str, destination: str, price: float, day: str = "2026-11-14") -> dict:
    return {
        "currency": "EUR",
        "prices": [
            {"origin": origin, "destination": destination, "depart_date": day, "price": price}
        ],
    }


def asked(pipeline) -> list[tuple]:
    """(origin, destination, month) of every request the fake source got."""
    return [
        (r.params["origin"], r.params["destination"], r.params["month"])
        for r in pipeline.fake.requests
    ]


def tasks(api, **params) -> list[dict]:
    r = api.get("/scan-tasks", params=params)
    assert r.status_code == 200, r.text
    return r.json()["tasks"]


def test_overlapping_watches_share_one_scan_task(pipeline, api):
    a = pipeline.create_watch(one_way(airports("BCN")))
    b = pipeline.create_watch(one_way(airports("BCN", "MAD")))
    pipeline.fake.replay(fare("HEL", "BCN", 59), route=("HEL", "BCN"))

    pipeline.run()

    assert sorted(asked(pipeline)) == [("HEL", "BCN", "2026-11"), ("HEL", "MAD", "2026-11")]
    shared = [t for t in tasks(api) if t["destination"] == "BCN"]
    assert len(shared) == 1
    assert shared[0]["source"] == "fake"
    assert shared[0]["month"] == "2026-11"
    assert shared[0]["status"] == "scanned"
    assert sorted(shared[0]["watch_ids"]) == sorted([a.id, b.id])
    assert {al.watch_id for al in pipeline.notifier.alerts} == {a.id, b.id}


def test_a_tight_budget_scans_the_nearest_departure_and_records_the_rest_as_skipped(pipeline, api):
    pipeline.set_budget("fake", per_run=1)
    later = pipeline.create_watch(one_way(airports("BCN"), departure="2027-02-14"))
    soon = pipeline.create_watch(one_way(airports("MAD"), departure="2026-10-26"))
    pipeline.fake.replay(fare("HEL", "BCN", 59, day="2027-02-14"), route=("HEL", "BCN"))
    pipeline.fake.replay(fare("HEL", "MAD", 59, day="2026-10-26"), route=("HEL", "MAD"))

    pipeline.run()

    assert asked(pipeline) == [("HEL", "MAD", "2026-10")]
    assert {a.watch_id for a in pipeline.notifier.alerts} == {soon.id}
    [skipped] = tasks(api, status="skipped")
    assert (skipped["destination"], skipped["month"]) == ("BCN", "2027-02")
    assert skipped["watch_ids"] == [later.id]
    assert skipped["reason"]
    assert skipped["priority"] < tasks(api, status="scanned")[0]["priority"]


def test_time_since_last_scan_rotates_a_tight_budget(pipeline):
    pipeline.set_budget("fake", per_run=1)
    pipeline.create_watch(one_way(airports("BCN", "MAD")))

    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert sorted(asked(pipeline)) == [("HEL", "BCN", "2026-11"), ("HEL", "MAD", "2026-11")]


def test_a_price_close_to_a_deal_is_rescanned_first(pipeline):
    pipeline.create_watch(one_way(airports("BCN", "MAD")))
    pipeline.fake.replay(fare("HEL", "BCN", 300), route=("HEL", "BCN"))
    pipeline.fake.replay(fare("HEL", "MAD", 110), route=("HEL", "MAD"))
    pipeline.run()

    pipeline.set_budget("fake", per_run=1)
    pipeline.fake.requests.clear()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert asked(pipeline) == [("HEL", "MAD", "2026-11")]


def test_a_volatile_route_is_rescanned_first(pipeline):
    pipeline.create_watch(one_way(airports("BCN", "MAD")))
    pipeline.fake.replay(fare("HEL", "BCN", 200), route=("HEL", "BCN"))
    pipeline.fake.replay(fare("HEL", "MAD", 200), route=("HEL", "MAD"))
    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(fare("HEL", "MAD", 260), route=("HEL", "MAD"))
    pipeline.run()

    pipeline.set_budget("fake", per_run=1)
    pipeline.fake.requests.clear()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert asked(pipeline) == [("HEL", "MAD", "2026-11")]


def test_paused_and_expired_watches_generate_no_tasks(pipeline, api):
    paused = pipeline.create_watch(one_way(airports("BCN")))
    api.post(f"/watches/{paused.id}/pause").raise_for_status()
    pipeline.create_watch(one_way(airports("MAD"), departure="2026-11-01"))
    pipeline.clock.set(pipeline.clock.now() + timedelta(days=12))  # past 2026-11-01

    pipeline.run()

    assert asked(pipeline) == []
    assert tasks(api) == []


def test_a_wide_watch_is_one_wildcard_task(pipeline, api):
    w = pipeline.create_watch(one_way({"include": [{"kind": "region", "code": "europe"}]}))
    pipeline.fake.replay(fare("HEL", "BCN", 59), route=("HEL", "BCN"))

    pipeline.run()

    assert asked(pipeline) == [("HEL", None, "2026-11")]
    [task] = tasks(api)
    assert task["destination"] is None and task["destinations"] > 100
    assert {(a.watch_id, a.destination) for a in pipeline.notifier.alerts} == {(w.id, "BCN")}


def test_a_daily_quota_carries_over_between_runs(pipeline, api):
    pipeline.set_budget("fake", per_day=3)
    pipeline.create_watch(one_way(airports("BCN", "MAD")))

    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert len(asked(pipeline)) == 3
    assert [t["status"] for t in tasks(api)] == ["scanned", "skipped"]


def test_tasks_of_a_failing_source_are_recorded_as_failed(pipeline, api):
    pipeline.create_watch(one_way(airports("BCN")))
    pipeline.fake.fail()

    pipeline.run()

    assert [t["status"] for t in tasks(api)] == ["failed"]


def test_a_round_trip_asks_for_round_trip_prices_and_the_return_leg(pipeline, api):
    pipeline.create_watch(
        {
            **one_way(airports("BCN")),
            "trip_pattern": {
                "preset": "fixed_dates",
                "departure": "2026-11-28",
                "return_date": "2026-12-03",
            },
        }
    )

    pipeline.run()

    got = {(t["origin"], t["destination"], t["month"], t["round_trip"]) for t in tasks(api)}
    assert got == {("HEL", "BCN", "2026-11", True), ("BCN", "HEL", "2026-12", False)}


def month_of_fares(origin: str, destination: str, price_14_nov: float) -> dict:
    """Six November departures at 100, the 14th at `price_14_nov`."""
    days = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    prices = [
        {"origin": origin, "destination": destination, "depart_date": d, "price": 100} for d in days
    ]
    prices.append(
        {
            "origin": origin,
            "destination": destination,
            "depart_date": "2026-11-14",
            "price": price_14_nov,
        }
    )
    return {"currency": "EUR", "prices": prices}


def test_a_price_close_to_its_baseline_deal_is_rescanned_first(pipeline):
    # No Price threshold: only the Baselines say how close each route is to a Deal.
    watch = one_way(airports("BCN", "MAD"))
    del watch["price_threshold"]
    pipeline.create_watch(watch)
    pipeline.fake.replay(month_of_fares("HEL", "BCN", 100), route=("HEL", "BCN"))
    pipeline.fake.replay(month_of_fares("HEL", "MAD", 75), route=("HEL", "MAD"))  # near -30%
    pipeline.run()

    pipeline.set_budget("fake", per_run=1)
    pipeline.fake.requests.clear()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert asked(pipeline) == [("HEL", "MAD", "2026-11")]
