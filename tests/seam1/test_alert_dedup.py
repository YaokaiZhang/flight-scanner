"""Seam 1: an Alert goes out once per dedup key, again only on a further drop or a reappearance."""

from datetime import timedelta

ROUTE = ("HEL", "BCN")


def watch(threshold_eur: float = 120, delivery: str | None = None) -> dict:
    spec = {
        "name": "Barcelona weekend",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "price_threshold": {"amount_eur": threshold_eur, "basis": "total"},
    }
    if delivery is not None:
        spec["delivery"] = delivery
    return spec


def fare(price: float) -> dict:
    """The fake source quoting HEL->BCN on 14 Nov at `price` EUR."""
    return {
        "currency": "EUR",
        "prices": [
            {"origin": "HEL", "destination": "BCN", "depart_date": "2026-11-14", "price": price}
        ],
    }


def scan_at(pipeline, price: float, after: timedelta = timedelta(0)) -> None:
    pipeline.clock.advance(after)
    pipeline.fake.replay(fare(price), route=ROUTE)
    pipeline.run()


def alerted_prices(pipeline) -> list[float]:
    return [a.price_total_eur for a in pipeline.notifier.alerts]


def test_a_deal_still_present_on_later_scans_is_not_alerted_again(pipeline):
    pipeline.create_watch(watch())
    scan_at(pipeline, 100)
    scan_at(pipeline, 100, after=timedelta(hours=6))
    scan_at(pipeline, 95, after=timedelta(hours=6))  # a 5% drop is not enough

    assert alerted_prices(pipeline) == [100]


def test_a_further_drop_of_ten_percent_from_the_last_alerted_price_alerts_again(pipeline):
    pipeline.create_watch(watch())
    scan_at(pipeline, 100)
    scan_at(pipeline, 91, after=timedelta(minutes=30))  # 9% below 100: no
    scan_at(pipeline, 90, after=timedelta(minutes=30))  # 10% below 100: yes
    scan_at(pipeline, 82, after=timedelta(minutes=30))  # 8.9% below 90: no

    assert alerted_prices(pipeline) == [100, 90]


def test_a_fare_absent_for_24_hours_that_reappears_as_a_deal_alerts_again(pipeline):
    pipeline.create_watch(watch(threshold_eur=120))
    scan_at(pipeline, 100)
    scan_at(pipeline, 150, after=timedelta(minutes=30))  # over the threshold: no longer a Deal
    scan_at(pipeline, 100, after=timedelta(hours=24))

    assert alerted_prices(pipeline) == [100, 100]


def test_a_fare_back_within_24_hours_is_not_alerted_again(pipeline):
    pipeline.create_watch(watch(threshold_eur=120))
    scan_at(pipeline, 100)
    scan_at(pipeline, 150, after=timedelta(minutes=30))
    scan_at(pipeline, 100, after=timedelta(hours=23))
    scan_at(pipeline, 100, after=timedelta(hours=2))  # present again, so the absence ended

    assert alerted_prices(pipeline) == [100]


NOVEMBER_3_6_NIGHTS = {"preset": "month", "month": "2026-11", "stay_nights": {"min": 3, "max": 6}}


def month_watch() -> dict:
    return {
        "name": "Barcelona in November",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": NOVEMBER_3_6_NIGHTS,
        "price_threshold": {"amount_eur": 100, "basis": "total"},
    }


def returns_on_4_nov(*returns: tuple[str, float]) -> dict:
    """HEL->BCN on 4 Nov at 40 EUR and BCN->HEL on each (day, price): one trip per return day."""
    legs = [{"origin": "HEL", "destination": "BCN", "depart_date": "2026-11-04", "price": 40}]
    legs += [
        {"origin": "BCN", "destination": "HEL", "depart_date": day, "price": price}
        for day, price in returns
    ]
    return {"currency": "EUR", "prices": legs}


def scan_dates(pipeline, *returns: tuple[str, float], after: timedelta = timedelta(0)) -> None:
    pipeline.clock.advance(after)
    pipeline.fake.replay(returns_on_4_nov(*returns))
    pipeline.run()


def test_a_route_alerts_once_for_its_cheapest_dates_not_once_per_date(pipeline):
    pipeline.create_watch(month_watch())
    scan_dates(pipeline, ("2026-11-07", 50), ("2026-11-08", 37), ("2026-11-09", 34))

    assert alerted_prices(pipeline) == [74]


def test_other_dates_on_an_alerted_route_alert_only_when_ten_percent_cheaper(pipeline):
    pipeline.create_watch(month_watch())
    scan_dates(pipeline, ("2026-11-09", 34))  # 74
    scan_dates(pipeline, ("2026-11-09", 34), ("2026-11-07", 28), after=timedelta(hours=6))  # 68
    scan_dates(pipeline, ("2026-11-09", 34), ("2026-11-08", 26), after=timedelta(hours=6))  # 66

    assert alerted_prices(pipeline) == [74, 66]


def test_a_route_quiet_for_a_week_alerts_new_dates_again(pipeline):
    pipeline.create_watch(month_watch())
    scan_dates(pipeline, ("2026-11-09", 34))  # 74
    scan_dates(pipeline, ("2026-11-09", 34), ("2026-11-07", 34), after=timedelta(days=7))

    assert alerted_prices(pipeline) == [74, 74]
