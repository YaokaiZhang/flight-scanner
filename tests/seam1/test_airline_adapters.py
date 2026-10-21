"""Seam 1: the optional Ryanair and Wizz adapters inside the real pipeline.

The adapters run unchanged; only their HTTP transport is scripted (recorded calendar payloads,
or a bot-protection answer) and their sleeps are fake, so nothing touches the network.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flight_scanner import source_health
from flight_scanner.api import create_app
from flight_scanner.db import connect
from flight_scanner.sources.polite_http import HttpResponse
from flight_scanner.sources.ryanair import RyanairAdapter
from flight_scanner.sources.wizz import WizzAdapter
from flight_scanner.testing.scripted_http import FakeTimer, ScriptedTransport

PAYLOADS = Path(__file__).parents[1] / "fixtures" / "payloads"
RYANAIR_STN_BCN = (PAYLOADS / "ryanair" / "stn-bcn-2026-11.json").read_bytes()
WIZZ_BUD_BCN = (PAYLOADS / "wizz" / "bud-bcn-2026-11.json").read_bytes()


@pytest.fixture
def api(pipeline):
    with TestClient(create_app(pipeline.db, pipeline.clock)) as client:
        yield client


def airports(*codes: str) -> dict:
    return {"include": [{"kind": "airport", "code": c} for c in codes]}


def one_way(origin: str, destinations: dict, threshold: float = 50) -> dict:
    return {
        "name": "Cheap hop",
        "origins": airports(origin),
        "destinations": destinations,
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "price_threshold": {"amount_eur": threshold, "basis": "total"},
    }


def ryanair_calendar(method, url, headers, body):
    """Ryanair flies STN-BCN (recorded calendar); any other route is not flown (404)."""
    if "/STN/BCN/" in url:
        return HttpResponse(200, {"Content-Type": "application/json"}, RYANAIR_STN_BCN)
    return HttpResponse(404, {}, b'{"message": "Availability.RouteNotFound"}')


def add_ryanair(pipeline, *responses) -> ScriptedTransport:
    timer = FakeTimer()
    transport = ScriptedTransport(*responses, timer=timer, repeat_last=True)
    pipeline.add_source(
        RyanairAdapter(
            pipeline.clock, transport=transport, sleep=timer.sleep, monotonic=timer.monotonic
        )
    )
    return transport


def tasks(api, **params) -> list[dict]:
    r = api.get("/scan-tasks", params=params)
    assert r.status_code == 200, r.text
    return r.json()["tasks"]


def test_ryanair_calendar_prices_alert_and_each_route_is_rescanned_at_most_every_two_hours(
    pipeline, api
):
    watch = pipeline.create_watch(one_way("STN", airports("BCN")))
    transport = add_ryanair(pipeline, ryanair_calendar)

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.watch_id, alert.source) == (watch.id, "ryanair")
    assert (alert.origin, alert.destination, alert.airlines) == ("STN", "BCN", "FR")
    assert alert.price_total_eur == pytest.approx(19.99)
    assert len(transport.calls) == 1

    pipeline.clock.advance(minutes=30)
    pipeline.run()
    assert len(transport.calls) == 1  # 30 min later: not asked again
    [later] = tasks(api, source="ryanair")
    assert later["status"] == "skipped" and "2 h" in later["reason"]
    assert [t["status"] for t in tasks(api, source="fake")] == ["scanned"]  # cadence per source

    pipeline.clock.advance(minutes=90)
    pipeline.run()
    assert len(transport.calls) == 2


def test_airline_sources_have_a_small_default_budget(pipeline, api):
    many = [
        "BCN", "DUB", "AGP", "ALC", "BGY", "CIA", "MAD", "PMI", "FAO", "OPO", "LIS", "VLC",
        "SVQ", "BVA", "CRL", "NAP", "PSA", "BLQ", "KRK", "WMI", "BUD", "VIE", "ATH", "MLA",
    ]  # fmt: skip
    pipeline.create_watch(one_way("STN", airports(*many)))
    transport = add_ryanair(pipeline, ryanair_calendar)

    pipeline.run()

    statuses = [t["status"] for t in tasks(api, source="ryanair")]
    assert statuses.count("scanned") == 20 and statuses.count("skipped") == 4
    assert len(transport.calls) == 20


def test_a_blocked_airline_source_disables_itself_and_the_others_keep_alerting(pipeline, api):
    hel = pipeline.create_watch(one_way("HEL", airports("BCN"), threshold=100))
    pipeline.create_watch(one_way("STN", airports("BCN")))
    pipeline.fake.replay(
        {
            "currency": "EUR",
            "prices": [
                {"origin": "HEL", "destination": "BCN", "depart_date": "2026-11-14", "price": 59}
            ],
        },
        route=("HEL", "BCN"),
    )
    blocked = HttpResponse(403, {"Content-Type": "text/html"}, b"<html>Access denied</html>")
    transport = add_ryanair(pipeline, blocked)

    pipeline.run()

    assert {a.watch_id for a in pipeline.notifier.alerts} == {hel.id}
    assert {t["status"] for t in tasks(api, source="ryanair")} == {"failed"}
    [block] = api.get("/sources/blocked").json()
    assert block["source"] == "ryanair" and "403" in block["reason"]
    assert datetime.fromisoformat(block["blocked_at"]) == datetime(2026, 10, 21, 9, tzinfo=UTC)

    pipeline.clock.advance(hours=3)
    pipeline.run()
    assert len(transport.calls) == 1  # disabled: never asked again, nothing worked around
    skipped = tasks(api, source="ryanair")
    assert {t["status"] for t in skipped} == {"skipped"}
    assert all("blocked" in t["reason"] for t in skipped)

    with connect(pipeline.db) as conn:  # the owner re-enables it (python -m flight_scanner unblock)
        assert source_health.unblock(conn, "ryanair")
    transport.responses = [ryanair_calendar]
    pipeline.clock.advance(minutes=30)
    pipeline.run()
    assert len(transport.calls) == 3  # HEL-BCN and STN-BCN
    assert api.get("/sources/blocked").json() == []
    assert {t["status"] for t in tasks(api, source="ryanair")} == {"scanned"}


def test_wizz_prices_in_local_currency_alert_in_euro(pipeline):
    watch = pipeline.create_watch(one_way("BUD", airports("BCN")))
    timer = FakeTimer()
    transport = ScriptedTransport(
        HttpResponse(200, {}, b"SSR https://be.wizzair.com/27.6.0"),
        HttpResponse(200, {"Content-Type": "application/json"}, WIZZ_BUD_BCN),
        timer=timer,
    )
    pipeline.add_source(
        WizzAdapter(
            pipeline.clock, transport=transport, sleep=timer.sleep, monotonic=timer.monotonic
        )
    )

    pipeline.run()

    [alert] = pipeline.notifier.alerts
    assert (alert.watch_id, alert.source, alert.airlines) == (watch.id, "wizz", "W6")
    assert 25 < alert.price_total_eur < 40  # 12 990 HUF
