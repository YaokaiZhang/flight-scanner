"""Seam 1: what an Alert says, and which channels it goes to."""

from datetime import date
from pathlib import Path

from flight_scanner.notify.base import RecordingNotifier

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "fake"
HEL_BCN = PAYLOADS / "hel-bcn-2026-11.json"  # HEL->BCN 14 Nov: EUR 89, VY, direct, 250 min


def hel_bcn_watch(**overrides) -> dict:
    return {
        "name": "Barcelona weekend",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "adults": 2,
        "price_threshold": {"amount_eur": 100, "basis": "per_adult"},
        **overrides,
    }


def test_alert_carries_the_full_deal_details_and_a_booking_link(pipeline):
    pipeline.create_watch(hel_bcn_watch())
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.watch_name == "Barcelona weekend"
    assert (alert.origin, alert.destination) == ("HEL", "BCN")
    assert (alert.outbound_date, alert.return_date) == (date(2026, 11, 14), None)
    assert alert.airlines == "VY"
    assert alert.stops == 0
    assert alert.travel_minutes == 250
    assert (alert.price_per_adult_eur, alert.price_total_eur, alert.adults) == (89, 178, 2)
    assert alert.verification == "unverified"
    assert alert.separate_tickets is False
    # No Baseline exists yet for this route: the Alert says nothing about one.
    assert alert.baseline_per_adult_eur is None
    assert alert.pct_below_baseline is None
    assert alert.booking_url == (
        "https://www.google.com/travel/flights?q=Flights%20from%20HEL%20to%20BCN%20on%20"
        "2026-11-14%20one%20way&curr=EUR"
    )


def test_alerts_reach_only_the_channels_the_watch_chose(pipeline):
    email = pipeline.add_notifier(RecordingNotifier("email"))
    telegram = pipeline.add_notifier(RecordingNotifier("telegram"))
    pipeline.create_watch(hel_bcn_watch(name="Telegram only", channels=["telegram"]))
    pipeline.create_watch(hel_bcn_watch(name="Both"))  # default: email and Telegram
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))

    pipeline.run()

    assert [a.watch_name for a in telegram.alerts] == ["Telegram only", "Both"]
    assert [a.watch_name for a in email.alerts] == ["Both"]
    # Channels outside the Watch's choice (log, the recording notifier) see every Alert.
    assert len(pipeline.notifier.alerts) == 2
    # Each delivery is its own Alert, so feedback can be tied to the message that carried it.
    alert_ids = [a.alert_id for a in [*email.alerts, *telegram.alerts]]
    assert None not in alert_ids and len(set(alert_ids)) == 3
