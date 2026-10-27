"""Seam 1: Trip patterns and Round-trip composition, fake sources in -> Alerts out.

The pipeline clock starts at 2026-10-21 09:00Z (Helsinki today is 21 Oct 2026).
"""

from datetime import UTC, date, datetime

from flight_scanner.db import connect


def leg(origin: str, destination: str, day: str, price: float, airline: str = "XX") -> dict:
    return {
        "origin": origin,
        "destination": destination,
        "depart_date": day,
        "price": price,
        "airline": airline,
    }


def round_trip(origin: str, destination: str, out: str, ret: str, price: float) -> dict:
    return {
        "origin": origin,
        "destination": destination,
        "depart_date": out,
        "return_date": ret,
        "price": price,
        "airline": "AY",
    }


def payload(legs: list[dict] = (), round_trips: list[dict] = ()) -> dict:
    return {"currency": "EUR", "prices": list(legs), "round_trips": list(round_trips)}


def watch(trip_pattern: dict, threshold_eur: float = 100, origin: str = "HEL", dest: str = "BCN"):
    return {
        "name": "Trip",
        "origins": {"include": [{"kind": "airport", "code": origin}]},
        "destinations": {"include": [{"kind": "airport", "code": dest}]},
        "trip_pattern": trip_pattern,
        "price_threshold": {"amount_eur": threshold_eur, "basis": "total"},
    }


def deal_trips(pipeline) -> set[tuple[date, date | None]]:
    """Every trip found as a Deal (one route alerts only its cheapest trip, so ask the Deals)."""
    with connect(pipeline.db) as conn:
        rows = conn.execute("SELECT outbound_date, return_date FROM app.deals").fetchall()
    return {(r["outbound_date"], r["return_date"]) for r in rows}


MONTH_NOV_3_6 = {"preset": "month", "month": "2026-11", "stay_nights": {"min": 3, "max": 6}}


def test_month_preset_composes_two_separate_tickets_returning_after_the_window(pipeline):
    """28 Nov -> 2 Dec satisfies "3-6 nights in November": only the departure must be in it."""
    pipeline.create_watch(watch(MONTH_NOV_3_6))
    pipeline.fake.replay(
        payload(legs=[leg("HEL", "BCN", "2026-11-28", 40), leg("BCN", "HEL", "2026-12-02", 45)])
    )

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.outbound_date, alert.return_date) == (date(2026, 11, 28), date(2026, 12, 2))
    assert alert.price_total_eur == 85
    assert alert.ticketing == "separate_tickets"


FIXED_11_15_NOV = {"preset": "fixed_dates", "departure": "2026-11-11", "return_date": "2026-11-15"}


def test_a_cheaper_single_ticket_round_trip_beats_two_leg_prices(pipeline):
    pipeline.create_watch(watch(FIXED_11_15_NOV, threshold_eur=150))
    pipeline.fake.replay(
        payload(
            legs=[leg("HEL", "BCN", "2026-11-11", 60), leg("BCN", "HEL", "2026-11-15", 70)],
            round_trips=[round_trip("HEL", "BCN", "2026-11-11", "2026-11-15", 110)],
        )
    )

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.outbound_date, alert.return_date) == (date(2026, 11, 11), date(2026, 11, 15))
    assert alert.price_total_eur == 110
    assert alert.ticketing == "single_ticket"


def test_two_leg_prices_beat_a_dearer_single_ticket(pipeline):
    pipeline.create_watch(watch(FIXED_11_15_NOV, threshold_eur=150))
    pipeline.fake.replay(
        payload(
            legs=[leg("HEL", "BCN", "2026-11-11", 50), leg("BCN", "HEL", "2026-11-15", 55)],
            round_trips=[round_trip("HEL", "BCN", "2026-11-11", "2026-11-15", 140)],
        )
    )

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.price_total_eur == 105
    assert alert.ticketing == "separate_tickets"


def test_a_composed_round_trip_alert_names_both_airlines_and_two_separate_tickets(pipeline):
    pipeline.create_watch(watch(FIXED_11_15_NOV, threshold_eur=150))
    pipeline.fake.replay(
        payload(
            legs=[
                leg("HEL", "BCN", "2026-11-11", 50, "AY"),
                leg("BCN", "HEL", "2026-11-15", 55, "VY"),
            ]
        )
    )

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.ticketing, alert.separate_tickets) == ("separate_tickets", True)
    assert alert.airlines == "AY, VY"


def test_no_self_transfer_is_composed_within_one_direction(pipeline):
    """HEL->BER plus BER->BCN is not a HEL->BCN outbound; nor is a return via another airport."""
    pipeline.create_watch(watch(FIXED_11_15_NOV, threshold_eur=150))
    pipeline.fake.replay(
        payload(
            legs=[
                leg("HEL", "BER", "2026-11-11", 20),
                leg("BER", "BCN", "2026-11-11", 20),
                leg("BCN", "HEL", "2026-11-15", 30),
                leg("BCN", "BER", "2026-11-15", 10),
                leg("BER", "HEL", "2026-11-15", 10),
            ]
        )
    )

    pipeline.run()

    assert pipeline.notifier.alerts == []


def every_day(origin: str, destination: str, first: str, last: str, price: float) -> list[dict]:
    day, end = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    while day <= end:
        out.append(leg(origin, destination, day.isoformat(), price))
        day = day.fromordinal(day.toordinal() + 1)
    return out


def nights(t: tuple[date, date | None]) -> int:
    return (t[1] - t[0]).days


def test_fixed_departure_with_a_range_of_stay_nights(pipeline):
    pipeline.create_watch(
        watch(
            {
                "preset": "fixed_departure",
                "departure": "2026-11-22",
                "stay_nights": {"min": 3, "max": 5},
            }
        )
    )
    pipeline.fake.replay(
        payload(
            legs=every_day("HEL", "BCN", "2026-11-21", "2026-11-23", 40)
            + every_day("BCN", "HEL", "2026-11-23", "2026-11-30", 40)
        )
    )

    pipeline.run()

    assert deal_trips(pipeline) == {
        (date(2026, 11, 22), date(2026, 11, 25)),
        (date(2026, 11, 22), date(2026, 11, 26)),
        (date(2026, 11, 22), date(2026, 11, 27)),
    }


def test_target_date_plus_minus_k_days(pipeline):
    pipeline.create_watch(
        watch(
            {
                "preset": "around_date",
                "target": "2026-11-22",
                "flex_days": 2,
                "stay_nights": {"min": 3, "max": 3},
            }
        )
    )
    pipeline.fake.replay(
        payload(
            legs=every_day("HEL", "BCN", "2026-11-17", "2026-11-27", 40)
            + every_day("BCN", "HEL", "2026-11-17", "2026-12-03", 40)
        )
    )

    pipeline.run()

    assert deal_trips(pipeline) == {
        (date(2026, 11, d), date(2026, 11, d + 3)) for d in range(20, 25)
    }


def test_month_preset_covers_every_departure_day_and_stay_length(pipeline):
    pipeline.create_watch(watch(MONTH_NOV_3_6))
    pipeline.fake.replay(
        payload(
            legs=every_day("HEL", "BCN", "2026-10-25", "2026-12-05", 40)
            + every_day("BCN", "HEL", "2026-10-25", "2026-12-12", 40)
        )
    )

    pipeline.run()

    found = deal_trips(pipeline)
    assert {t[0] for t in found} == {date(2026, 11, d) for d in range(1, 31)}
    assert {nights(t) for t in found} == {3, 4, 5, 6}
    assert len(found) == 30 * 4
    assert max(t[1] for t in found) == date(2026, 12, 6)


def test_latest_return_date_cuts_trips_that_end_too_late(pipeline):
    pipeline.create_watch(watch({**MONTH_NOV_3_6, "return_by": "2026-11-30"}))
    pipeline.fake.replay(
        payload(
            legs=every_day("HEL", "BCN", "2026-11-24", "2026-11-28", 40)
            + every_day("BCN", "HEL", "2026-11-27", "2026-12-04", 40)
        )
    )

    pipeline.run()

    found = deal_trips(pipeline)
    assert max(t[1] for t in found) == date(2026, 11, 30)
    assert found == {
        (date(2026, 11, 24), date(2026, 11, 27)),
        (date(2026, 11, 24), date(2026, 11, 28)),
        (date(2026, 11, 24), date(2026, 11, 29)),
        (date(2026, 11, 24), date(2026, 11, 30)),
        (date(2026, 11, 25), date(2026, 11, 28)),
        (date(2026, 11, 25), date(2026, 11, 29)),
        (date(2026, 11, 25), date(2026, 11, 30)),
        (date(2026, 11, 26), date(2026, 11, 29)),
        (date(2026, 11, 26), date(2026, 11, 30)),
        (date(2026, 11, 27), date(2026, 11, 30)),
    }


def test_rolling_window_slides_daily_with_the_clock(pipeline):
    """2-4 nights departing within the next 60 days: 21 Oct -> 20 Dec, then 22 Oct -> 21 Dec."""
    pipeline.create_watch(
        watch({"preset": "rolling", "within_days": 60, "stay_nights": {"min": 2, "max": 4}})
    )
    pipeline.fake.replay(
        payload(
            legs=[
                leg("HEL", "BCN", "2026-12-20", 40),
                leg("HEL", "BCN", "2026-12-21", 40),
                leg("BCN", "HEL", "2026-12-24", 40),
            ]
        )
    )

    pipeline.run()
    assert deal_trips(pipeline) == {(date(2026, 12, 20), date(2026, 12, 24))}

    pipeline.clock.advance(days=1)
    pipeline.run()
    assert deal_trips(pipeline) == {
        (date(2026, 12, 20), date(2026, 12, 24)),
        (date(2026, 12, 21), date(2026, 12, 24)),
    }


def test_a_watch_whose_departure_window_has_passed_expires_and_stops_scanning(pipeline):
    """Departures in November: still active on 30 Nov, expired from 1 Dec (Helsinki dates)."""
    w = pipeline.create_watch(watch(MONTH_NOV_3_6))
    pipeline.fake.replay(
        payload(legs=[leg("HEL", "BCN", "2026-11-30", 40), leg("BCN", "HEL", "2026-12-04", 40)])
    )

    pipeline.clock.set(datetime(2026, 11, 30, 21, 0, tzinfo=UTC))  # 23:00 in Helsinki
    pipeline.run()
    assert pipeline.get_watch(w.id).status == "active"
    assert len(pipeline.notifier.alerts) == 1

    pipeline.clock.set(datetime(2026, 11, 30, 22, 30, tzinfo=UTC))  # 00:30 on 1 Dec in Helsinki
    fetches = pipeline.fake.fetch_count
    pipeline.run()
    assert pipeline.get_watch(w.id).status == "expired"
    assert pipeline.fake.fetch_count == fetches  # no demand, so no source was asked
