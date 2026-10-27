"""Seam 2: the Watch assistant chat endpoints, with a scripted agent against real Postgres."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app
from flight_scanner.clock import FakeClock
from flight_scanner.testing.fake_watch_agent import FakeWatchAgent

CLOCK = FakeClock(datetime(2026, 10, 21, 9, tzinfo=UTC))
SUN = {
    "name": "Canaries this winter",
    "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
    "destinations": {"include": [{"kind": "country", "code": "ES"}]},
    "trip_pattern": {"preset": "month", "month": "2026-12", "stay_nights": {"min": 3, "max": 7}},
}
PROPOSE = [("propose_watch", {"watch": SUN, "reason": "December sun at off-season fares."})]


def client(db, agent):
    return TestClient(create_app(db, CLOCK, watch_agent=agent))


@pytest.fixture
def agent() -> FakeWatchAgent:
    return FakeWatchAgent(PROPOSE, "Spain is cheap in December.")


@pytest.fixture
def api(db, agent):
    with client(db, agent) as c:
        yield c


def test_the_assistant_is_enabled_when_configured(api, db):
    assert api.get("/agent").json() == {"enabled": True}
    with client(db, None) as off:
        assert off.get("/agent").json() == {"enabled": False}


def test_a_new_chat_returns_the_reply_and_proposals(api, agent):
    r = api.post("/agent/chats", json={"text": "Somewhere warm in December"})

    assert r.status_code == 200, r.text
    turn = r.json()
    assert isinstance(turn["chat_id"], int)
    assert turn["reply"] == "Spain is cheap in December."
    [p] = turn["proposals"]
    assert set(p) == {"id", "reason", "spec", "places", "trip", "resolved"}
    assert p["reason"] == "December sun at off-season fares."
    assert p["spec"]["name"] == "Canaries this winter"
    assert [(pl["kind"], pl["code"], pl["name"]) for pl in p["places"]] == [
        ("airport", "HEL", "Helsinki Vantaa Airport"),
        ("country", "ES", "Spain"),
    ]
    assert p["trip"]["departure_start"] == "2026-12-01"
    assert p["trip"]["departure_end"] == "2026-12-31"
    assert p["trip"]["kind"] == "round_trip"
    assert p["resolved"]["origins"] == 1
    assert p["resolved"]["destinations"] > 10
    assert "21 October 2026" in agent.histories[0][0]["content"]


def test_a_proposal_spec_can_be_created_unchanged(api):
    [p] = api.post("/agent/chats", json={"text": "Sun"}).json()["proposals"]

    created = api.post("/watches", json=p["spec"])

    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Canaries this winter"
    assert created.json()["places"] == p["places"]


def test_a_chat_can_be_continued(api, agent):
    chat_id = api.post("/agent/chats", json={"text": "Sun"}).json()["chat_id"]

    r = api.post(f"/agent/chats/{chat_id}", json={"text": "And Portugal?"})

    assert r.status_code == 200, r.text
    assert r.json()["chat_id"] == chat_id
    second = agent.histories[1]
    assert second[0]["role"] == "user"
    assert second[-1] == {"role": "user", "content": "And Portugal?"}
    assert len(second) == 5  # question, tool call, tool result, answer, new question


def test_an_unknown_chat_is_404(api):
    assert api.post("/agent/chats/999999", json={"text": "hi"}).status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_empty_or_long_messages_are_rejected(api, text):
    assert api.post("/agent/chats", json={"text": text}).status_code == 422


def test_503_when_the_assistant_is_off_or_fails(db):
    with client(db, None) as off:
        r = off.post("/agent/chats", json={"text": "hi"})
        assert r.status_code == 503
        assert r.json()["detail"]

    with client(db, FakeWatchAgent(fail=True)) as failing:
        r = failing.post("/agent/chats", json={"text": "hi"})
        assert r.status_code == 503
        assert r.json()["detail"]
