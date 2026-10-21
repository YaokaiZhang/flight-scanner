"""Seam 2: the Deals feed and 👍/👎 feedback (from the UI and from Telegram) over HTTP.

Deals are produced the real way: Watches created through the API, one pipeline run with a fake
source replaying a recorded payload.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app
from flight_scanner.config import Settings
from flight_scanner.db import connect
from flight_scanner.notify.registry import build_notifiers
from flight_scanner.testing.fake_researcher import FakeResearcher
from flight_scanner.testing.fake_telegram import FakeTelegram
from flight_scanner.testing.harness import PipelineHarness

HEL_BCN = Path(__file__).parents[1] / "fixtures" / "payloads" / "fake" / "hel-bcn-2026-11.json"


def watch(name: str, **overrides) -> dict:
    return {
        "name": name,
        "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
        "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
        "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
        "adults": 1,
        "price_threshold": {"amount_eur": 120, "basis": "total"},
        **overrides,
    }


@pytest.fixture
def pipeline(db, tmp_path) -> PipelineHarness:
    h = PipelineHarness(db, tmp_path, start=datetime(2026, 10, 21, 9, 0, tzinfo=UTC))
    h.fake.replay(HEL_BCN, route=("HEL", "BCN"))
    return h


@pytest.fixture
def api(db, pipeline):
    with TestClient(create_app(db, pipeline.clock)) as client:
        yield client


def test_deals_carry_alert_details_and_no_rating_yet(api, pipeline):
    api.post("/watches", json=watch("Barcelona weekend"))
    pipeline.run()

    [deal] = api.get("/deals").json()
    assert deal["airlines"] == "VY"
    assert deal["stops"] == 0
    assert deal["travel_minutes"] == 250
    assert deal["separate_tickets"] is False
    assert deal["baseline_per_adult_eur"] is None
    assert deal["pct_below_baseline"] is None
    assert deal["booking_url"].startswith("https://www.google.com/travel/flights?q=")
    assert deal["feedback"] is None
    assert deal["deal_context"] is None  # no researcher configured


def test_deal_context_is_shown_in_the_feed_when_researched_in_time(api, pipeline):
    sale = "Vueling is running an autumn sale on Helsinki routes."
    pipeline.use_researcher(FakeResearcher({("HEL", "BCN"): sale}))
    api.post("/watches", json=watch("Barcelona weekend"))
    pipeline.run()

    [deal] = api.get("/deals").json()
    assert deal["deal_context"] == sale
    assert api.get(f"/deals/{deal['id']}").json()["deal_context"] == sale


def test_rate_a_deal_from_the_feed_then_change_and_clear_it(api, pipeline):
    api.post("/watches", json=watch("Barcelona weekend"))
    pipeline.run()
    [deal] = api.get("/deals").json()

    rated = api.post(f"/deals/{deal['id']}/feedback", json={"rating": "up"})
    assert rated.status_code == 200
    assert rated.json()["feedback"] == {"rating": "up", "via": "web"}
    assert api.get("/deals").json()[0]["feedback"] == {"rating": "up", "via": "web"}

    api.post(f"/deals/{deal['id']}/feedback", json={"rating": "down"})
    assert api.get("/deals").json()[0]["feedback"]["rating"] == "down"

    api.post(f"/deals/{deal['id']}/feedback", json={"rating": None})
    assert api.get("/deals").json()[0]["feedback"] is None


def test_feedback_is_validated(api, pipeline):
    api.post("/watches", json=watch("Barcelona weekend"))
    pipeline.run()
    [deal] = api.get("/deals").json()

    assert api.post("/deals/999999/feedback", json={"rating": "up"}).status_code == 404
    assert api.post(f"/deals/{deal['id']}/feedback", json={"rating": "meh"}).status_code == 422
    assert api.get("/deals").json()[0]["feedback"] is None


def test_deals_feed_filters_by_watch_and_status(api, pipeline):
    first = api.post("/watches", json=watch("First")).json()
    second = api.post("/watches", json=watch("Second")).json()
    pipeline.run()

    assert {d["watch_name"] for d in api.get("/deals").json()} == {"First", "Second"}
    only_first = api.get("/deals", params={"watch_id": first["id"]}).json()
    assert [d["watch_id"] for d in only_first] == [first["id"]]
    # Every Deal is Unverified until Verification exists.
    unverified = api.get("/deals", params={"status": "unverified"}).json()
    assert {d["watch_id"] for d in unverified} == {first["id"], second["id"]}
    assert api.get("/deals", params={"status": "verified"}).json() == []
    assert (
        api.get("/deals", params={"status": "unverified", "watch_id": second["id"]}).json()[0][
            "watch_name"
        ]
        == "Second"
    )
    assert api.get("/deals", params={"status": "maybe"}).status_code == 422


def test_watch_channels_default_to_both_and_can_be_chosen(api):
    default = api.post("/watches", json=watch("Both")).json()
    assert default["channels"] == ["email", "telegram"]

    chosen = api.post("/watches", json=watch("Telegram", channels=["telegram"])).json()
    assert api.get(f"/watches/{chosen['id']}").json()["channels"] == ["telegram"]

    assert api.post("/watches", json=watch("None", channels=[])).status_code == 422
    assert api.post("/watches", json=watch("SMS", channels=["sms"])).status_code == 422


def collect(telegram, pipeline) -> int:
    """What the `telegram_feedback` sensor does on each tick."""
    with connect(pipeline.db, autocommit=True) as conn:
        return telegram.collect_feedback(conn, pipeline.clock.now())


def test_telegram_button_press_rates_the_deal_its_alert_was_about(api, pipeline):
    with FakeTelegram() as tg:
        env = {
            "FS_NOTIFIERS": "telegram",
            "TELEGRAM_BOT_TOKEN": tg.token,
            "TELEGRAM_CHAT_ID": str(tg.chat_id),
            "TELEGRAM_API_URL": tg.url,
        }
        [telegram] = build_notifiers(Settings.from_env(env))
        pipeline.add_notifier(telegram)
        api.post("/watches", json=watch("Barcelona weekend"))
        pipeline.run()
        [message] = tg.calls_to("sendMessage")
        up, down, _book = message["reply_markup"]["inline_keyboard"][0]

        tg.press_raw(down["callback_data"])
        tg.press_raw(up["callback_data"], chat_id=666)  # someone else's chat: ignored
        tg.press_raw("rate:999999:up")  # an Alert that doesn't exist: ignored
        assert collect(telegram, pipeline) == 1

        assert api.get("/deals").json()[0]["feedback"] == {"rating": "down", "via": "telegram"}
        # Every tap is acknowledged so the button stops spinning; none is processed twice.
        assert len(tg.calls_to("answerCallbackQuery")) == 3
        assert collect(telegram, pipeline) == 0
