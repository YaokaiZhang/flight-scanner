"""Seam 1: the backtest classifies past Deals from the prices observed after them.

A week of normal HEL-BCN prices (~100) makes a route Baseline; a fare of 50 on day 8 becomes a
Deal. What the same trip costs on the following days decides whether it was a real dip (the price
went back toward the Baseline) or not (it stayed low). Read through GET /backtest.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from flight_scanner.api import create_app

START = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
NOV_DATES = ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]


def leg(origin: str, destination: str, day: str, price: float) -> dict:
    return {"origin": origin, "destination": destination, "depart_date": day, "price": price}


def payload(legs: list[dict]) -> dict:
    return {"currency": "EUR", "prices": legs}


def watch(trip_pattern: dict) -> dict:
    return {
        "name": "Barcelona",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": trip_pattern,
    }


ONE_WAY_20_NOV = {"preset": "one_way_fixed", "departure": "2026-11-20"}


def normal_hel_bcn(i: int) -> dict:
    return payload([leg("HEL", "BCN", d, 95 + (i + j) % 3 * 5) for j, d in enumerate(NOV_DATES)])


def deal_on_day_8(pipeline, fare: dict | None = None, history=normal_hel_bcn) -> None:
    """A week of normal prices, then the Deal fare on day 8 (a full run alerts it)."""
    for i in range(8):
        pipeline.clock.set(START + timedelta(days=i))
        pipeline.fake.replay(history(i))
        pipeline.collect()
    pipeline.clock.set(START + timedelta(days=8))
    pipeline.fake.replay(fare or payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    pipeline.run()
    assert len(pipeline.notifier.alerts) == 1


def later_days(pipeline, prices: list[dict], first_day: int = 9) -> None:
    """One collecting scan per day replaying each payload, then a full run (builds the backtest)."""
    for i, p in enumerate(prices):
        pipeline.clock.set(START + timedelta(days=first_day + i))
        pipeline.fake.replay(p)
        pipeline.collect()
    pipeline.clock.advance(hours=1)
    pipeline.run()


def backtest(pipeline) -> dict:
    with TestClient(create_app(pipeline.db, pipeline.clock)) as api:
        response = api.get("/backtest")
    assert response.status_code == 200
    [watch_backtest] = response.json()["watches"]
    return watch_backtest


def test_a_deal_whose_price_later_returns_to_the_baseline_was_a_real_dip(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    deal_on_day_8(pipeline)

    later_days(pipeline, [payload([leg("HEL", "BCN", "2026-11-20", p)]) for p in (60, 95, 100)])

    result = backtest(pipeline)
    [deal] = result["past_deals"]
    assert deal["outcome"] == "real_dip"
    assert deal["price_per_adult_eur"] == 50
    assert deal["baseline_per_adult_eur"] == 100
    assert deal["pct_below_baseline"] == 50
    assert deal["later_observation_days"] == 3
    assert deal["highest_later_price_per_adult_eur"] == 100
    assert result["outcomes"]["real_dip"] == 1
    assert result["precision"] == 1.0


def test_a_deal_whose_price_stays_low_was_not_a_real_dip(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    deal_on_day_8(pipeline)

    # 60 is a fifth of the way back to 100: not enough to call the dip over
    later_days(pipeline, [payload([leg("HEL", "BCN", "2026-11-20", p)]) for p in (50, 60, 55)])

    result = backtest(pipeline)
    [deal] = result["past_deals"]
    assert deal["outcome"] == "stayed_low"
    assert deal["highest_later_price_per_adult_eur"] == 60
    assert result["outcomes"]["stayed_low"] == 1
    assert result["precision"] == 0.0


def test_a_deal_with_too_few_later_observations_is_still_pending(pipeline):
    pipeline.create_watch(watch(ONE_WAY_20_NOV))
    deal_on_day_8(pipeline)

    later_days(pipeline, [payload([leg("HEL", "BCN", "2026-11-20", 50)])])

    result = backtest(pipeline)
    [deal] = result["past_deals"]
    assert (deal["outcome"], deal["later_observation_days"]) == ("pending", 1)
    assert result["precision"] is None


def test_a_round_trip_deal_is_judged_by_its_later_outbound_plus_return_prices(pipeline):
    pipeline.create_watch(
        watch({"preset": "fixed_dates", "departure": "2026-11-18", "return_date": "2026-11-21"})
    )

    def normal_round_trips(i: int) -> dict:
        # 3-4-night trips cost 100: 17->21, 18->21, 18->22 (17->22 is 5 nights, another bucket)
        return payload(
            [
                *(leg("HEL", "BCN", d, 50) for d in ("2026-11-17", "2026-11-18")),
                *(leg("BCN", "HEL", d, 50) for d in ("2026-11-21", "2026-11-22")),
            ]
        )

    fare = payload([leg("HEL", "BCN", "2026-11-18", 25), leg("BCN", "HEL", "2026-11-21", 25)])
    deal_on_day_8(pipeline, fare, history=normal_round_trips)

    # the outbound alone climbs back; together with the return the trip is 75, then 100
    later_days(
        pipeline,
        [
            payload([leg("HEL", "BCN", "2026-11-18", 50)]),  # no return price that day
            payload([leg("HEL", "BCN", "2026-11-18", 50), leg("BCN", "HEL", "2026-11-21", 25)]),
            payload([leg("HEL", "BCN", "2026-11-18", 50), leg("BCN", "HEL", "2026-11-21", 50)]),
        ],
    )

    [deal] = backtest(pipeline)["past_deals"]
    assert (deal["price_per_adult_eur"], deal["baseline_per_adult_eur"]) == (50, 100)
    assert deal["later_observation_days"] == 2
    assert deal["highest_later_price_per_adult_eur"] == 100
    assert deal["outcome"] == "real_dip"


def test_a_candidate_that_failed_verification_was_never_a_deal_and_is_not_backtested(pipeline):
    google = pipeline.use_google_flights()
    pipeline.create_watch(
        watch(ONE_WAY_20_NOV) | {"price_threshold": {"amount_eur": 80, "basis": "total"}}
    )
    pipeline.fake.replay(payload([leg("HEL", "BCN", "2026-11-20", 50)]))
    google.offer("HEL", "BCN", date(2026, 11, 20), None, total=120)  # live: over the threshold

    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()

    assert pipeline.notifier.alerts == []
    result = backtest(pipeline)
    assert (result["deals"], result["past_deals"]) == (0, [])
