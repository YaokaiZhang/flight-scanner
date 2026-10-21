"""Seam 1: data-quality gates. Suspicious data (an empty scan of a normally populated origin, a
source-wide price-level jump, stale data) blocks Deal detection for the affected slice only, and
one source failing never stops the others from alerting."""

from datetime import timedelta

from flight_scanner.sources.replay import ReplayAdapter

DAY = "2026-11-14"
SOUTH = ["BCN", "MAD", "LIS", "FCO", "ATH"]


def one_way(name: str, origin: str, destinations: list[str], threshold_eur: float = 120) -> dict:
    return {
        "name": name,
        "origins": {"include": [{"kind": "airport", "code": origin}]},
        "destinations": {"include": [{"kind": "airport", "code": d} for d in destinations]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": DAY},
        "adults": 1,
        "price_threshold": {"amount_eur": threshold_eur, "basis": "total"},
    }


def payload(*legs: tuple[str, str, float]) -> dict:
    return {
        "currency": "EUR",
        "prices": [
            {"origin": o, "destination": d, "depart_date": DAY, "price": p} for o, d, p in legs
        ],
    }


def check(result, name: str):
    [evaluation] = [c for c in result.get_asset_check_evaluations() if c.check_name == name]
    return evaluation


def test_a_zero_row_scan_blocks_detection_for_that_origin_only(pipeline):
    pipeline.create_watch(one_way("From Helsinki", "HEL", ["BCN"]))
    pipeline.create_watch(one_way("From Tallinn", "TLL", ["BCN"]))
    pipeline.fake.replay(payload(("HEL", "BCN", 89)), route=("HEL", "BCN"))
    pipeline.fake.replay(payload(("TLL", "BCN", 150)), route=("TLL", "BCN"))
    pipeline.collect()  # prices only: HEL -> BCN at 89 is known but not judged yet

    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(payload(), route=("HEL", "BCN"))  # HEL suddenly returns nothing
    pipeline.fake.replay(payload(("TLL", "BCN", 95)), route=("TLL", "BCN"))
    result = pipeline.run()

    assert [a.origin for a in pipeline.notifier.alerts] == ["TLL"]  # HEL's cached 89 is held
    zero_rows = check(result, "zero_rows")
    assert not zero_rows.passed
    [gate] = zero_rows.metadata["failing_slices"].value
    assert (gate["source"], gate["origin"]) == ("fake", "HEL")
    assert check(result, "price_jump").passed and check(result, "stale_data").passed

    pipeline.clock.advance(minutes=30)
    pipeline.fake.replay(payload(("HEL", "BCN", 89)), route=("HEL", "BCN"))
    result = pipeline.run()  # HEL answers again: the gate lifts

    assert check(result, "zero_rows").passed
    assert sorted(a.origin for a in pipeline.notifier.alerts) == ["HEL", "TLL"]


def test_a_source_wide_price_jump_blocks_that_source_only(pipeline):
    pipeline.create_watch(one_way("Southern Europe", "HEL", SOUTH))
    other = pipeline.add_source(ReplayAdapter("other", pipeline.clock))
    for d in SOUTH:
        pipeline.fake.replay(payload(("HEL", d, 150)), route=("HEL", d))
    other.replay(payload(("HEL", "BCN", 160)), route=("HEL", "BCN"))
    pipeline.collect()

    pipeline.clock.advance(minutes=30)
    for d in SOUTH:  # every fake price falls to a third: a parsing or currency bug, not Deals
        pipeline.fake.replay(payload(("HEL", d, 50)), route=("HEL", d))
    other.replay(payload(("HEL", "BCN", 110)), route=("HEL", "BCN"))
    result = pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.destination, alert.source, alert.price_total_eur) == ("BCN", "other", 110)
    jump = check(result, "price_jump")
    assert not jump.passed
    [gate] = jump.metadata["failing_slices"].value
    assert (gate["source"], gate["origin"]) == ("fake", None)


def test_a_failing_source_goes_stale_and_the_others_keep_alerting(pipeline):
    pipeline.create_watch(one_way("Barcelona", "HEL", ["BCN"]))
    other = pipeline.add_source(ReplayAdapter("other", pipeline.clock))
    pipeline.fake.replay(payload(("HEL", "BCN", 89)), route=("HEL", "BCN"))
    other.replay(payload(("HEL", "BCN", 150)), route=("HEL", "BCN"))
    pipeline.collect()

    pipeline.fake.fail(at=pipeline.clock.now() + timedelta(minutes=1))  # outage from now on
    pipeline.clock.advance(hours=7)
    other.replay(payload(("HEL", "BCN", 100)), route=("HEL", "BCN"))
    result = pipeline.run()

    [alert] = pipeline.notifier.alerts  # the other source's fresh 100, not fake's stale 89
    assert (alert.source, alert.price_total_eur) == ("other", 100)
    stale = check(result, "stale_data")
    assert not stale.passed
    [gate] = stale.metadata["failing_slices"].value
    assert (gate["source"], gate["origin"]) == ("fake", None)
