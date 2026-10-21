"""Seam 1: Watches in Digest mode get one daily summary instead of immediate Alerts."""

from datetime import UTC, datetime, timedelta

# The harness starts at 2026-10-21 09:00Z (12:00 in Helsinki). Digests go out at 08:00 Helsinki,
# which is 05:00Z while summer time lasts (until 25 Oct 2026).
NEXT_MORNING = datetime(2026, 10, 22, 5, 0, tzinfo=UTC)


def digest_watch(delivery: str = "digest") -> dict:
    return {
        "name": "Barcelona, low priority",
        "origins": {
            "include": [{"kind": "airport", "code": "HEL"}, {"kind": "airport", "code": "TKU"}]
        },
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "price_threshold": {"amount_eur": 120, "basis": "total"},
        "delivery": delivery,
    }


def fares(hel: float, tku: float) -> dict:
    return {
        "currency": "EUR",
        "prices": [
            {"origin": o, "destination": "BCN", "depart_date": "2026-11-14", "price": p}
            for o, p in (("HEL", hel), ("TKU", tku))
        ],
    }


def scan(pipeline, at: datetime, hel: float, tku: float) -> None:
    pipeline.clock.set(at)
    pipeline.fake.replay(fares(hel, tku))  # any route
    pipeline.run()


def digest_lines(digest) -> list[tuple[str, float]]:
    return sorted((d.origin, d.price_total_eur) for d in digest.deals)


def test_a_digest_watch_sends_no_immediate_alerts_and_one_digest_the_next_morning(pipeline):
    watch = pipeline.create_watch(digest_watch())
    start = pipeline.clock.now()

    scan(pipeline, start, hel=100, tku=110)
    scan(pipeline, start + timedelta(hours=3), hel=100, tku=110)
    assert pipeline.notifier.alerts == []
    assert pipeline.notifier.digests == []

    scan(pipeline, NEXT_MORNING, hel=100, tku=110)
    scan(pipeline, NEXT_MORNING + timedelta(minutes=30), hel=100, tku=110)

    assert pipeline.notifier.alerts == []
    [digest] = pipeline.notifier.digests
    assert digest.watch_id == watch.id
    assert digest.watch_name == "Barcelona, low priority"
    assert digest_lines(digest) == [("HEL", 100), ("TKU", 110)]


def test_a_digest_lists_only_the_deals_since_the_last_digest(pipeline):
    pipeline.create_watch(digest_watch())
    scan(pipeline, pipeline.clock.now(), hel=100, tku=110)
    scan(pipeline, NEXT_MORNING, hel=100, tku=110)

    # Next day: HEL drops a further 10% (a new Alert round); TKU is unchanged (no new round).
    scan(pipeline, NEXT_MORNING + timedelta(hours=6), hel=90, tku=110)
    scan(pipeline, NEXT_MORNING + timedelta(days=1), hel=90, tku=110)

    first, second = pipeline.notifier.digests
    assert digest_lines(first) == [("HEL", 100), ("TKU", 110)]
    assert digest_lines(second) == [("HEL", 90)]


def test_a_quiet_day_sends_no_digest(pipeline):
    pipeline.create_watch(digest_watch())
    scan(pipeline, pipeline.clock.now(), hel=150, tku=150)  # nothing under the threshold
    scan(pipeline, NEXT_MORNING, hel=150, tku=150)

    assert pipeline.notifier.digests == []


def test_switching_a_watch_to_digest_mode_is_per_watch(pipeline):
    immediate = pipeline.create_watch(digest_watch(delivery="immediate"))
    pipeline.create_watch(digest_watch())
    scan(pipeline, pipeline.clock.now(), hel=100, tku=110)

    assert {a.watch_id for a in pipeline.notifier.alerts} == {immediate.id}
    assert len(pipeline.notifier.alerts) == 2
    assert pipeline.notifier.digests == []
