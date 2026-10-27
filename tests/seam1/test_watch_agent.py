"""Seam 1: the Watch assistant's tools and chat storage against real Postgres (scripted agent)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from flight_scanner import watches
from flight_scanner.clock import FakeClock
from flight_scanner.db import connect
from flight_scanner.places import default_reference
from flight_scanner.testing.fake_watch_agent import FakeWatchAgent
from flight_scanner.watch_agent import AgentTools, UnknownChat, WatchAgentUnavailable, chat

TODAY = date(2026, 10, 21)
HEL_BCN_PAYLOAD = (
    Path(__file__).parents[1] / "fixtures" / "payloads" / "fake" / "hel-bcn-2026-11.json"
)

LISBON_WEEKENDS = {
    "name": "Lisbon long weekends",
    "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
    "destinations": {"include": [{"kind": "city", "code": "PT-lisbon"}]},
    "trip_pattern": {"preset": "rolling", "within_days": 60, "stay_nights": {"min": 2, "max": 4}},
}


@pytest.fixture
def conn(db):
    with connect(db) as c:
        yield c


@pytest.fixture
def tools(conn) -> AgentTools:
    return AgentTools(conn, default_reference(), TODAY)


def run(tools: AgentTools, name: str, **args):
    output, is_error = tools.run(name, args)
    return json.loads(output), is_error


def test_search_places_returns_codes_to_use(tools):
    places, is_error = run(tools, "search_places", query="Lisbon")

    assert not is_error
    assert {"kind": "airport", "code": "LIS"} in [
        {"kind": p["kind"], "code": p["code"]} for p in places
    ]
    assert {"kind": "city", "code": "PT-lisbon"} in [
        {"kind": p["kind"], "code": p["code"]} for p in places
    ]


def test_list_watches_names_the_places(conn, tools):
    clock = FakeClock(datetime(2026, 10, 21, 9, tzinfo=UTC))
    watches.create(conn, watches.WatchSpec.model_validate(LISBON_WEEKENDS), clock)

    [w], is_error = run(tools, "list_watches")

    assert not is_error
    assert w["name"] == "Lisbon long weekends"
    assert w["origins"]["include"] == ["airport HEL (Helsinki Vantaa Airport)"]
    assert w["destinations"]["include"][0].startswith("city PT-lisbon (Lisbon")


def test_a_valid_proposal_is_collected_with_places_and_trips(tools):
    result, is_error = run(
        tools, "propose_watch", watch=LISBON_WEEKENDS, reason="Cheap autumn fares to Lisbon."
    )

    assert not is_error, result
    [proposal] = tools.proposals
    assert result["proposed"] == proposal.id
    assert proposal.reason == "Cheap autumn fares to Lisbon."
    assert proposal.spec.name == "Lisbon long weekends"
    assert [(p.kind, p.code) for p in proposal.places] == [
        ("airport", "HEL"),
        ("city", "PT-lisbon"),
    ]
    assert proposal.trip.rolling
    assert (proposal.trip.departure_start, proposal.trip.departure_end) == (
        TODAY,
        date(2026, 12, 20),
    )
    assert proposal.trip.trip_count == result["trips"] > 0
    assert proposal.resolved.origins == 1
    assert proposal.resolved.destinations >= 1


def test_a_watch_sent_as_a_json_string_is_accepted(tools):
    _, is_error = run(tools, "propose_watch", watch=json.dumps(LISBON_WEEKENDS), reason="Sun.")

    assert not is_error
    assert len(tools.proposals) == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"destinations": {"include": [{"kind": "airport", "code": "XYZ"}]}}, "unknown airport"),
        ({"destinations": {"include": [{"kind": "airport", "code": "lis"}]}}, "valid airport"),
        (
            {"trip_pattern": {"preset": "one_way_fixed", "departure": "2026-09-01"}},
            "no trips from today",
        ),
        ({"adults": 0}, "adults"),
    ],
)
def test_an_invalid_proposal_is_an_error_and_not_collected(tools, change, message):
    result, is_error = run(tools, "propose_watch", watch={**LISBON_WEEKENDS, **change}, reason="x")

    assert is_error
    assert message in result["error"]
    assert tools.proposals == []


def test_unknown_tools_and_bad_arguments_are_errors(tools):
    assert run(tools, "drop_tables")[1]
    assert run(tools, "search_places", q="Lisbon")[1]  # wrong argument name


def _history_table(conn, rows):
    conn.execute("CREATE SCHEMA IF NOT EXISTS history")
    conn.execute(
        """CREATE TABLE history.leg_price_history (
               source text, origin text, destination text, departure_date date,
               price_per_adult_eur numeric, valid_from timestamptz, valid_to timestamptz)"""
    )
    for o, d, dep, price, current in rows:
        conn.execute(
            "INSERT INTO history.leg_price_history VALUES "
            "('fake', %s, %s, %s, %s, '2026-10-01', %s)",
            (o, d, dep, price, None if current else "2026-10-10"),
        )


def test_observed_fares_without_history_is_empty(tools):
    assert run(tools, "observed_fares") == ([], False)


def test_observed_fares_are_current_future_fares_per_route_and_can_be_narrowed(conn, tools):
    _history_table(
        conn,
        [
            ("HEL", "BCN", "2026-11-14", 89, True),
            ("HEL", "BCN", "2026-11-21", 120, True),
            ("HEL", "BCN", "2026-11-28", 40, False),  # superseded price
            ("HEL", "BCN", "2026-10-01", 30, True),  # departed already
            ("HEL", "LIS", "2026-12-05", 150, True),
            ("TLL", "BCN", "2026-11-14", 60, True),
        ],
    )

    fares, _ = run(tools, "observed_fares")
    assert [(f["origin"], f["destination"]) for f in fares] == [
        ("TLL", "BCN"),
        ("HEL", "BCN"),
        ("HEL", "LIS"),
    ]
    hel_bcn = fares[1]
    assert hel_bcn["cheapest_eur"] == 89
    assert hel_bcn["median_eur"] == 104.5
    assert hel_bcn["cheapest_date"] == "2026-11-14"
    assert hel_bcn["departure_dates"] == 2
    assert hel_bcn["origin_name"].startswith("Helsinki Vantaa Airport")

    from_helsinki, _ = run(tools, "observed_fares", origin={"kind": "city", "code": "FI-helsinki"})
    assert [f["destination"] for f in from_helsinki] == ["BCN", "LIS"]
    to_spain, _ = run(
        tools,
        "observed_fares",
        origin={"kind": "airport", "code": "HEL"},
        destination={"kind": "country", "code": "ES"},
    )
    assert [f["destination"] for f in to_spain] == ["BCN"]
    assert run(tools, "observed_fares", limit=1)[0][0]["origin"] == "TLL"

    unknown, is_error = run(tools, "observed_fares", origin={"kind": "airport", "code": "XYZ"})
    assert is_error
    assert "search_places" in unknown["error"]


def test_fares_and_deals_from_a_real_scan(pipeline):
    pipeline.create_watch(
        {
            "name": "Barcelona weekend",
            "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
            "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
            "trip_pattern": {"preset": "one_way_fixed", "departure": "2026-11-14"},
            "price_threshold": {"amount_eur": 100, "basis": "per_adult"},
        }
    )
    pipeline.fake.replay(HEL_BCN_PAYLOAD, route=("HEL", "BCN"))
    pipeline.run()

    with connect(pipeline.db) as c:
        tools = AgentTools(c, default_reference(), TODAY)
        [fare], _ = run(tools, "observed_fares")
        [deal], _ = run(tools, "recent_deals")

    assert (fare["origin"], fare["destination"], fare["cheapest_eur"]) == ("HEL", "BCN", 89)
    assert (deal["origin"], deal["destination"], deal["watch"]) == (
        "HEL",
        "BCN",
        "Barcelona weekend",
    )
    assert deal["price_per_adult_eur"] == 89


# --- chat() --------------------------------------------------------------------------------------


def stored(conn, chat_id) -> list[dict]:
    return conn.execute(
        "SELECT messages FROM app.agent_chats WHERE id = %s", (chat_id,)
    ).fetchone()["messages"]


def test_a_chat_is_created_then_continued_with_its_history(conn):
    agent = FakeWatchAgent(
        turns=[
            (
                [
                    ("search_places", {"query": "Lisbon"}),
                    ("propose_watch", {"watch": LISBON_WEEKENDS, "reason": "Sunny."}),
                ],
                "Lisbon looks good.",
            ),
            ([], "Anything else?"),
        ]
    )
    ref = default_reference()

    first = chat(conn, agent, ref, TODAY, "  Somewhere warm  ")

    assert first.reply == "Lisbon looks good."
    [proposal] = first.proposals
    assert proposal.spec.name == "Lisbon long weekends"
    [question] = agent.histories[0]
    assert question["role"] == "user"
    assert question["content"].startswith("(Today is Wednesday 21 October 2026.)")
    assert question["content"].endswith("Somewhere warm")
    messages = stored(conn, first.chat_id)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[2]["content"][1]["type"] == "tool_result"

    second = chat(conn, agent, ref, TODAY, "Thanks", chat_id=first.chat_id)

    assert second.chat_id == first.chat_id
    assert second.reply == "Anything else?"
    assert second.proposals == []  # proposals belong to the turn that made them
    assert agent.histories[1] == [*messages, {"role": "user", "content": "Thanks"}]
    assert stored(conn, first.chat_id) == [
        *messages,
        {"role": "user", "content": "Thanks"},
        {"role": "assistant", "content": [{"type": "text", "text": "Anything else?"}]},
    ]


def test_an_unknown_chat_is_a_key_error(conn):
    with pytest.raises(UnknownChat):
        chat(conn, FakeWatchAgent(), default_reference(), TODAY, "hi", chat_id=999)
    assert issubclass(UnknownChat, KeyError)


def test_a_failing_agent_saves_nothing(conn):
    first = chat(conn, FakeWatchAgent(), default_reference(), TODAY, "hi")
    before = stored(conn, first.chat_id)

    with pytest.raises(WatchAgentUnavailable):
        chat(conn, FakeWatchAgent(fail=True), default_reference(), TODAY, "more", first.chat_id)
    with pytest.raises(WatchAgentUnavailable):
        chat(conn, FakeWatchAgent(fail=True), default_reference(), TODAY, "new chat")

    assert stored(conn, first.chat_id) == before
    assert conn.execute("SELECT count(*) AS n FROM app.agent_chats").fetchone()["n"] == 1
