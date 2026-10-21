"""Seam 1: fake sources in -> Alerts out, through real Postgres, dbt and Dagster."""

from datetime import date
from pathlib import Path

from flight_scanner.sources.replay import ReplayAdapter

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "fake"


def hel_bcn_watch(threshold_eur: float, adults: int = 1) -> dict:
    return {
        "name": "Barcelona weekend",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "adults": adults,
        "price_threshold": {"amount_eur": threshold_eur, "basis": "total"},
    }


def test_leg_price_under_threshold_yields_exactly_one_alert(pipeline):
    watch = pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    pipeline.fake.replay(PAYLOADS / "hel-bcn-2026-11.json", route=("HEL", "BCN"))

    pipeline.run()
    pipeline.clock.advance(minutes=30)
    pipeline.run()  # the same fare seen again must not alert twice

    [alert] = pipeline.notifier.alerts
    assert alert.watch_id == watch.id
    assert (alert.origin, alert.destination) == ("HEL", "BCN")
    assert alert.outbound_date == date(2026, 11, 14)
    assert alert.return_date is None
    assert alert.price_total_eur == 89
    assert alert.verification == "unverified"


def test_leg_price_above_threshold_yields_no_alert(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=80))
    pipeline.fake.replay(PAYLOADS / "hel-bcn-2026-11.json", route=("HEL", "BCN"))

    pipeline.run()

    assert pipeline.notifier.alerts == []


def test_threshold_is_compared_with_the_total_for_all_adults(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=150, adults=2))  # 2 x 89 = 178
    pipeline.fake.replay(PAYLOADS / "hel-bcn-2026-11.json", route=("HEL", "BCN"))

    pipeline.run()

    assert pipeline.notifier.alerts == []


def test_only_fares_seen_by_the_scan_time_count(pipeline):
    """Payloads are scripted per scan time: a fare recorded for later is not seen yet."""
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    later = pipeline.clock.now().replace(hour=12)
    pipeline.fake.replay(PAYLOADS / "hel-bcn-2026-11.json", route=("HEL", "BCN"), at=later)

    pipeline.run()
    assert pipeline.notifier.alerts == []

    pipeline.clock.set(later)
    pipeline.run()
    assert len(pipeline.notifier.alerts) == 1


def test_raw_payloads_are_kept_immutably_by_source_and_date(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    recorded = (PAYLOADS / "hel-bcn-2026-11.json").read_bytes()
    pipeline.fake.replay(PAYLOADS / "hel-bcn-2026-11.json", route=("HEL", "BCN"))

    pipeline.run()

    [stored] = pipeline.raw_store.list("fake", date(2026, 10, 21))
    assert stored.read() == recorded
    assert "source=fake" in stored.path.parts and "date=2026-10-21" in stored.path.parts
    assert not stored.path.stat().st_mode & 0o222  # read-only on disk


def test_a_source_outage_does_not_stop_other_sources(pipeline):
    pipeline.create_watch(hel_bcn_watch(threshold_eur=120))
    pipeline.fake.fail()
    other = pipeline.add_source(ReplayAdapter("other", pipeline.clock))
    other.replay(PAYLOADS / "hel-bcn-2026-11.json", route=("HEL", "BCN"))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.source == "other"
