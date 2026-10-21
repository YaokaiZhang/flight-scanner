"""Seam 1: optional Deal context ("why is this cheap?") from a researcher, capped at 60 s."""

import time
from pathlib import Path

from flight_scanner.notify.content import text
from flight_scanner.testing.fake_researcher import FakeResearcher

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads" / "fake"
HEL_BCN = PAYLOADS / "hel-bcn-2026-11.json"  # HEL->BCN 14 Nov: EUR 89, VY, direct

SALE = "Vueling is running an autumn sale on Helsinki routes until 31 Oct."


def hel_bcn_watch(**overrides) -> dict:
    return {
        "name": "Barcelona weekend",
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "adults": 1,
        "price_threshold": {"amount_eur": 100, "basis": "per_adult"},
        **overrides,
    }


def test_deal_context_found_in_time_is_added_to_the_alert(pipeline):
    researcher = FakeResearcher({("HEL", "BCN"): SALE})
    pipeline.use_researcher(researcher)
    pipeline.create_watch(hel_bcn_watch())
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.deal_context == SALE
    assert f"Why cheap? {SALE}" in text(alert)
    # The researcher was told which Deal to explain.
    [asked] = researcher.asked
    assert (asked.origin, asked.destination, str(asked.outbound_date)) == (
        "HEL",
        "BCN",
        "2026-11-14",
    )
    assert asked.price_per_adult_eur == 89


def test_late_deal_context_does_not_hold_the_alert_back(pipeline):
    researcher = FakeResearcher({("HEL", "BCN"): SALE}, hold=True)  # answers only when released
    pipeline.use_researcher(researcher, timeout_seconds=0.5)
    pipeline.create_watch(hel_bcn_watch())
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))

    try:
        pipeline.run()
    finally:
        researcher.release()

    [alert] = pipeline.notifier.alerts
    assert alert.deal_context is None
    assert "Why cheap?" not in text(alert)


def test_deals_are_researched_once_even_when_late(pipeline):
    researcher = FakeResearcher({("HEL", "BCN"): SALE}, hold=True)
    pipeline.use_researcher(researcher, timeout_seconds=0.2)
    pipeline.create_watch(hel_bcn_watch())
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))
    started = time.monotonic()
    try:
        pipeline.run()
    finally:
        researcher.release()
    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))
    pipeline.run()

    assert len(researcher.asked) == 1
    assert len(pipeline.notifier.alerts) == 1
    assert time.monotonic() - started < 120


def test_a_failing_researcher_never_blocks_the_alert(pipeline):
    pipeline.use_researcher(FakeResearcher(fail=True))
    pipeline.create_watch(hel_bcn_watch())
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.deal_context is None


def test_without_a_researcher_alerts_carry_no_deal_context(pipeline):
    pipeline.create_watch(hel_bcn_watch())
    pipeline.fake.replay(HEL_BCN, route=("HEL", "BCN"))

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert alert.deal_context is None
