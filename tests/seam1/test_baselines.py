"""Seam 1: Baselines and Deal detection, fake sources in -> Alerts out.

History is built with `pipeline.collect()` (a scan that only collects prices; detection and
Alerts run in `pipeline.run()`). The clock starts at 2026-10-21 09:00Z.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from flight_scanner.api import create_app

START = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def leg(origin: str, destination: str, day: str, price: float) -> dict:
    return {"origin": origin, "destination": destination, "depart_date": day, "price": price}


def payload(legs: list[dict]) -> dict:
    return {"currency": "EUR", "prices": legs}


def watch(
    trip_pattern: dict,
    dest: str = "BCN",
    threshold_eur: float | None = None,
    match: str = "both",
    **kw,
) -> dict:
    spec = {
        "name": "Trip",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": dest}]},
        "trip_pattern": trip_pattern,
        **kw,
    }
    if threshold_eur is not None:
        spec["price_threshold"] = {"amount_eur": threshold_eur, "basis": "total", "match": match}
    return spec


ONE_WAY_20_NOV = {"preset": "one_way_fixed", "departure": "2026-11-20"}
NOV_DATES = ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]


def collect_daily(pipeline, days: int, make_payload) -> None:
    """One collecting scan per day for `days` days, each replaying make_payload(day_index)."""
    for i in range(days):
        pipeline.clock.set(START + timedelta(days=i))
        pipeline.fake.replay(make_payload(i))
        pipeline.collect()


def normal_hel_bcn(i: int) -> dict:
    # around 100 EUR, a little noise from day to day
    return payload([leg("HEL", "BCN", d, 95 + (i + j) % 3 * 5) for j, d in enumerate(NOV_DATES)])


def test_three_weeks_of_normal_prices_then_a_fare_half_below_yields_a_deal(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    collect_daily(pipeline, 21, normal_hel_bcn)

    pipeline.clock.set(START + timedelta(days=21))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.outbound_date, alert.return_date) == (date(2026, 11, 20), None)
    assert alert.price_per_adult_eur == 50
    assert alert.baseline_tier == "route"
    assert alert.baseline_per_adult_eur == 100
    assert alert.verification == "unverified"


def test_twenty_observations_on_only_two_days_do_not_make_a_route_baseline(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    many_dates = [f"2026-11-{d:02d}" for d in range(1, 13)]  # 12 trips a day, 24 in all
    collect_daily(pipeline, 2, lambda i: payload([leg("HEL", "BCN", d, 100) for d in many_dates]))

    pipeline.clock.set(START + timedelta(days=2))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    pipeline.run()

    # Only the low-confidence cross-section of the month's current prices is left to judge by.
    assert [a.baseline_tier for a in pipeline.notifier.alerts] == ["provisional"]


def test_a_sparse_route_falls_back_to_the_destination_country_baseline(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV, dest="BCN"))
    # Barcelona is new, but Helsinki -> Madrid (also Spain) has a week of history
    collect_daily(
        pipeline,
        8,
        lambda i: payload([leg("HEL", "MAD", d, 120) for d in NOV_DATES[:3]]),
    )

    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 70)]))
    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.baseline_tier == "country"
    assert alert.baseline_per_adult_eur == 120
    assert alert.price_per_adult_eur == 70


def test_with_no_history_a_provisional_baseline_from_the_months_prices_is_used(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    month = [leg("HEL", "BCN", f"2026-11-{d:02d}", 100) for d in range(10, 16)]
    pipeline.fake.replay(payload([*month, leg("HEL", "BCN", "2026-11-20", 60)]))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.baseline_tier == "provisional"
    assert alert.baseline_per_adult_eur == 100
    assert alert.verification == "unverified"


def test_with_no_baseline_and_no_threshold_nothing_is_a_deal(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 1)]))

    pipeline.run()

    assert pipeline.notifier.alerts == []


def test_both_the_baseline_test_and_the_price_threshold_must_pass(pipeline):
    below_both = pipeline.create_watch(watch(ONE_WAY_20_NOV, threshold_eur=60))
    pipeline.create_watch(watch(ONE_WAY_20_NOV, threshold_eur=40))  # Baseline only
    one_way_18_nov = {"preset": "one_way_fixed", "departure": "2026-11-18"}
    pipeline.create_watch(watch(one_way_18_nov, threshold_eur=200))  # threshold only
    collect_daily(pipeline, 8, normal_hel_bcn)

    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(
        payload([leg("HEL", "BCN", "2026-11-20", 50), leg("HEL", "BCN", "2026-11-18", 90)])
    )
    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.watch_id == below_both.id
    assert alert.baseline_tier == "route"


def test_either_the_baseline_test_or_the_price_threshold_is_enough_when_the_watch_says_so(
    pipeline,
):
    baseline_only = pipeline.create_watch(watch(ONE_WAY_20_NOV, threshold_eur=40, match="either"))
    one_way_18_nov = {"preset": "one_way_fixed", "departure": "2026-11-18"}
    threshold_only = pipeline.create_watch(watch(one_way_18_nov, threshold_eur=200, match="either"))
    one_way_19_nov = {"preset": "one_way_fixed", "departure": "2026-11-19"}
    pipeline.create_watch(watch(one_way_19_nov, threshold_eur=80, match="either"))  # neither
    collect_daily(pipeline, 8, normal_hel_bcn)

    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(
        payload(
            [
                leg("HEL", "BCN", "2026-11-20", 50),
                leg("HEL", "BCN", "2026-11-18", 90),
                leg("HEL", "BCN", "2026-11-19", 95),
            ]
        )
    )
    pipeline.run()

    assert sorted(a.watch_id for a in pipeline.notifier.alerts) == sorted(
        [baseline_only.id, threshold_only.id]
    )


def test_the_watch_sensitivity_sets_how_far_below_the_baseline_a_deal_must_be(pipeline):
    strict = pipeline.create_watch(watch(ONE_WAY_20_NOV, sensitivity_pct=20))
    pipeline.create_watch(watch(ONE_WAY_20_NOV, sensitivity_pct=30))
    collect_daily(pipeline, 8, normal_hel_bcn)

    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 75)]))  # 25% below 100
    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.watch_id == strict.id


def test_round_trips_are_compared_within_their_stay_night_bucket(pipeline):
    pipeline.create_watch(
        watch({"preset": "fixed_dates", "departure": "2026-11-11", "return_date": "2026-11-15"})
    )
    # Every day: 3-4-night trips (out 11/12 Nov, back 15 Nov) cost 100, while 10-11-night
    # trips (back 22 Nov) cost 300; only the former are comparable with a 4-night trip.
    collect_daily(
        pipeline,
        10,
        lambda i: payload(
            [
                leg("HEL", "BCN", "2026-11-11", 50),
                leg("HEL", "BCN", "2026-11-12", 50),
                leg("BCN", "HEL", "2026-11-15", 50),
                leg("BCN", "HEL", "2026-11-22", 250),
            ]
        ),
    )

    pipeline.clock.set(START + timedelta(days=10))
    pipeline.fake.replay(
        payload([leg("HEL", "BCN", "2026-11-11", 25), leg("BCN", "HEL", "2026-11-15", 25)])
    )
    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.outbound_date, alert.return_date) == (date(2026, 11, 11), date(2026, 11, 15))
    assert alert.price_per_adult_eur == 50
    assert (alert.baseline_tier, alert.baseline_per_adult_eur) == ("route", 100)


def test_a_deal_records_the_baseline_version_and_the_route_explorer_shows_its_band(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    collect_daily(pipeline, 8, normal_hel_bcn)
    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    pipeline.run()

    with TestClient(create_app(pipeline.db, pipeline.clock)) as api:
        [deal] = api.get("/deals").json()
        history = api.get("/routes/HEL/BCN/history", params={"departure_date": "2026-11-20"}).json()

    # 8 completed days x 4 departure dates; the version was first computed by this run
    first_computed = START + timedelta(days=8)
    assert datetime.fromisoformat(deal["baseline"].pop("computed_at")) == first_computed
    assert datetime.fromisoformat(history["baseline"].pop("computed_at")) == first_computed
    assert deal["baseline"] == {
        "tier": "route",
        "per_adult_eur": 100.0,
        "method": "daily_min_median_60d",
        "observations": 32,
        "observation_days": 8,
    }
    assert history["baseline"] == {
        "tier": "route",
        "median_per_adult_eur": 100.0,
        "low_per_adult_eur": 95.0,
        "high_per_adult_eur": 105.0,
        "method": "daily_min_median_60d",
        "observations": 32,
        "observation_days": 8,
    }
