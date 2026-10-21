"""Seam 1: Verification and Price insights, fake sources and fake Google Flights in -> Alerts out.

Candidates are checked live through the real SerpApi adapter, answered by `FakeGoogleFlights`
(prices for the whole party, like SerpApi). The clock starts at 2026-10-21 09:00Z.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from flight_scanner.api import create_app
from flight_scanner.notify.content import text

START = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
NOV18, NOV20, NOV27 = date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 27)


def leg(origin: str, destination: str, day: str, price: float) -> dict:
    return {"origin": origin, "destination": destination, "depart_date": day, "price": price}


def payload(legs: list[dict]) -> dict:
    return {"currency": "EUR", "prices": legs}


def watch(trip_pattern: dict, threshold_eur: float | None = None, **kw) -> dict:
    spec = {
        "name": "Trip",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": trip_pattern,
        **kw,
    }
    if threshold_eur is not None:
        spec["price_threshold"] = {"amount_eur": threshold_eur, "basis": "total"}
    return spec


ROUND_TRIP_20_27_NOV = {
    "preset": "fixed_dates",
    "departure": "2026-11-20",
    "return_date": "2026-11-27",
}
ONE_WAY_20_NOV = {"preset": "one_way_fixed", "departure": "2026-11-20"}
ONE_WAY_18_NOV = {"preset": "one_way_fixed", "departure": "2026-11-18"}
# The month's other departures at 100 make a provisional Baseline of 100; 20 Nov at 60 is a
# Candidate against it (40% below).
MONTH_AT_100_AND_20_NOV_AT_60 = payload(
    [
        *(leg("HEL", "BCN", f"2026-11-{d:02d}", 100) for d in range(10, 16)),
        leg("HEL", "BCN", "2026-11-20", 60),
    ]
)


def deals(pipeline, **params) -> list[dict]:
    with TestClient(create_app(pipeline.db, pipeline.clock)) as api:
        return api.get("/deals", params=params).json()


def test_a_candidate_is_verified_live_as_a_round_trip_for_the_watchs_adults(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ROUND_TRIP_20_27_NOV, threshold_eur=300, adults=2))
    pipeline.fake.replay(
        payload([leg("HEL", "BCN", "2026-11-20", 50), leg("BCN", "HEL", "2026-11-27", 50)])
    )
    google.offer("HEL", "BCN", NOV20, NOV27, total=240, typical=(500, 700))

    pipeline.run()

    assert google.asked == [("HEL", "BCN", NOV20, NOV27, 2, "1")]
    [alert] = pipeline.notifier.alerts
    assert alert.verification == "verified"
    # the live price for both adults replaces the cached per-adult estimate
    assert (alert.price_total_eur, alert.price_per_adult_eur) == (240, 120)
    assert "Verified: checked live." in text(alert)


def test_a_candidate_that_fails_verification_is_recorded_but_not_alerted(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ROUND_TRIP_20_27_NOV, threshold_eur=300, adults=2))
    pipeline.fake.replay(
        payload([leg("HEL", "BCN", "2026-11-20", 50), leg("BCN", "HEL", "2026-11-27", 50)])
    )
    google.offer("HEL", "BCN", NOV20, NOV27, total=320)  # over the 300 threshold for two

    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert pipeline.notifier.alerts == []
    [deal] = deals(pipeline)
    assert deal["verification"] == "failed"
    assert deal["verified_price_total_eur"] == 320
    assert deals(pipeline, status="verified") == []
    assert [d["id"] for d in deals(pipeline, status="failed")] == [deal["id"]]
    assert len(google.asked) == 1  # the same Alert round is not checked twice


def test_when_the_budget_is_spent_the_best_candidate_is_verified_and_the_rest_are_unverified(
    pipeline,
):
    google = pipeline.use_google_flights(daily_quota=1)
    pipeline.create_watch(watch(ONE_WAY_20_NOV, threshold_eur=100))
    pipeline.create_watch(watch(ONE_WAY_18_NOV, threshold_eur=100))
    pipeline.fake.replay(
        payload([leg("HEL", "BCN", "2026-11-20", 50), leg("HEL", "BCN", "2026-11-18", 80)])
    )
    google.offer("HEL", "BCN", NOV20, total=50)
    google.offer("HEL", "BCN", NOV18, total=80)

    pipeline.run()

    # 20 Nov is 50% under its Price threshold, 18 Nov only 20%: 20 Nov gets the one check
    assert google.asked == [("HEL", "BCN", NOV20, None, 1, "2")]
    by_date = {a.outbound_date: a for a in pipeline.notifier.alerts}
    assert by_date[NOV20].verification == "verified"
    assert by_date[NOV18].verification == "unverified"
    assert "Verification budget spent" in text(by_date[NOV18])


def test_a_verifier_outage_still_alerts_the_candidate_as_unverified(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ONE_WAY_20_NOV, threshold_eur=100))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    google.fail_next()

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.verification == "unverified"


def test_a_provisional_candidate_is_rejudged_against_the_price_insight_and_can_fail(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    pipeline.fake.replay(MONTH_AT_100_AND_20_NOV_AT_60)
    # Google says 55-75 is typical for this very trip: 60 is not 30% below it
    google.offer("HEL", "BCN", NOV20, total=60, typical=(55, 75))

    pipeline.run()

    assert pipeline.notifier.alerts == []
    [deal] = deals(pipeline)
    assert deal["verification"] == "failed"
    assert (deal["baseline"]["tier"], deal["baseline"]["per_adult_eur"]) == ("price_insight", 65)


def test_a_provisional_candidate_confirmed_by_the_price_insight_is_a_verified_deal(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    pipeline.fake.replay(MONTH_AT_100_AND_20_NOV_AT_60)
    google.offer("HEL", "BCN", NOV20, total=60, typical=(180, 220))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.verification == "verified"
    assert (alert.baseline_tier, alert.baseline_per_adult_eur) == ("price_insight", 200)
    # once the next run has rebuilt the Baselines, the route explorer shows the trip's Price
    # insight as its Baseline band: the typical range
    pipeline.clock.advance(minutes=30)
    pipeline.run()
    with TestClient(create_app(pipeline.db, pipeline.clock)) as api:
        band = api.get("/routes/HEL/BCN/history", params={"departure_date": "2026-11-20"}).json()[
            "baseline"
        ]
    assert (band["tier"], band["low_per_adult_eur"], band["high_per_adult_eur"]) == (
        "price_insight",
        180,
        220,
    )
    assert band["median_per_adult_eur"] == 200


def test_without_price_history_the_typical_range_alone_is_the_price_insight(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    pipeline.fake.replay(MONTH_AT_100_AND_20_NOV_AT_60)
    google.offer("HEL", "BCN", NOV20, total=60, typical=(180, 220), history=[])

    pipeline.run()
    # the stored Price insight is the trip's Baseline tier in later runs too (no new check)
    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    pipeline.run()

    assert len(google.asked) == 2  # the 10%-further drop is a new Alert round, checked again
    assert [(a.baseline_tier, a.baseline_per_adult_eur) for a in pipeline.notifier.alerts] == [
        ("price_insight", 200),
        ("price_insight", 200),
    ]


def test_price_insight_history_backfills_the_route_baseline_past_the_seven_day_rule(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    pipeline.fake.replay(MONTH_AT_100_AND_20_NOV_AT_60)
    # Google's price history of this trip: about 100 every day for the last 30 days
    history = [(START - timedelta(days=d), 100 + d % 2 * 4) for d in range(1, 31)]
    google.offer("HEL", "BCN", NOV20, total=60, typical=(90, 110), history=history)
    pipeline.run()

    # The next day: our own history is one day old, yet the route Baseline exists
    pipeline.clock.set(START + timedelta(days=1))
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    google.offer("HEL", "BCN", NOV20, total=50, typical=(90, 110))
    pipeline.run()

    first, second = pipeline.notifier.alerts
    assert (first.baseline_tier, first.verification) == ("price_insight", "verified")
    assert (second.baseline_tier, second.verification) == ("route", "verified")
    [deal] = deals(pipeline)
    assert deal["baseline"]["observation_days"] >= 7
    assert deal["baseline"]["observations"] >= 20
