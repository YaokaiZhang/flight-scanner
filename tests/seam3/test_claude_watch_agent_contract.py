"""Seam 3: the Claude Watch assistant against a recorded-shape Messages API (no network).

The real SDK client runs over an in-process transport, so request serialisation and response
parsing are the SDK's own; only the HTTP exchange is canned.
"""

import json

import anthropic
import httpx2
import pytest

from flight_scanner.config import Settings
from flight_scanner.watch_agent import TOOLS, WatchAgentUnavailable, build_watch_agent
from flight_scanner.watch_agent.claude import (
    MAX_ROUNDS,
    ClaudeWatchAgent,
    WatchAgentSettings,
)

QUESTION = {"role": "user", "content": "(Today is Wednesday 21 October 2026.)\n\nSun in December"}
THINKING = {"type": "thinking", "thinking": "", "signature": "sig-1"}


def message(content, stop_reason="end_turn"):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


def tool_use(i: int, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": args}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


class FakeMessagesApi:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        return httpx2.Response(status, json=body)

    def body(self, i: int = 0) -> dict:
        return json.loads(self.requests[i].content)

    def agent(self, **settings) -> ClaudeWatchAgent:
        client = anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handler)),
        )
        return ClaudeWatchAgent(WatchAgentSettings(api_key="test-key", **settings), client=client)


def ok(*responses):
    return FakeMessagesApi(*[(200, r) for r in responses])


class RecordingTools:
    """Answers every tool call with a canned result; `search_places` with is_error for 'XYZ'."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        self.calls.append((name, args))
        if args.get("query") == "XYZ":
            return json.dumps({"error": "nothing found"}), True
        return json.dumps([{"name": name}]), False


def test_request_shape_and_a_direct_answer():
    api = ok(message([THINKING, text("Try Lisbon.")]))

    reply = api.agent().respond([QUESTION], RecordingTools())

    assert reply.text == "Try Lisbon."
    assert reply.messages == [{"role": "assistant", "content": [THINKING, text("Try Lisbon.")]}]
    [request] = api.requests
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == "test-key"
    assert "anthropic-beta" not in request.headers
    body = api.body()
    assert body["model"] == "claude-haiku-5-5"
    assert body["output_config"] == {"effort": "medium"}
    assert body["max_tokens"] == 16000
    assert body["tools"] == TOOLS
    assert body["messages"] == [QUESTION]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert "Never invent" in body["system"]
    for absent in ("fallbacks", "thinking", "tool_choice", "temperature"):
        assert absent not in body


def test_the_tool_schemas_are_plain_json_schema():
    propose = next(t for t in TOOLS if t["name"] == "propose_watch")
    assert "$defs" in propose["input_schema"]
    assert "$defs" not in propose["input_schema"]["properties"]["watch"]
    refs = json.dumps(propose["input_schema"]).count('"$ref": "#/$defs/')
    assert refs > 0


def test_tool_calls_are_answered_in_one_message_then_the_answer_ends_the_turn():
    calls = [
        THINKING,
        tool_use(1, "search_places", {"query": "Lisbon"}),
        tool_use(2, "search_places", {"query": "XYZ"}),
    ]
    api = ok(message(calls, "tool_use"), message([text("Lisbon it is.")]))
    tools = RecordingTools()

    reply = api.agent().respond([QUESTION], tools)

    assert tools.calls == [
        ("search_places", {"query": "Lisbon"}),
        ("search_places", {"query": "XYZ"}),
    ]
    assert reply.text == "Lisbon it is."
    assistant, results, answer = reply.messages
    assert assistant == {"role": "assistant", "content": calls}  # thinking passed back as-is
    assert results == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": json.dumps([{"name": "search_places"}]),
                "is_error": False,
            },
            {
                "type": "tool_result",
                "tool_use_id": "toolu_2",
                "content": json.dumps({"error": "nothing found"}),
                "is_error": True,
            },
        ],
    }
    assert answer == {"role": "assistant", "content": [text("Lisbon it is.")]}
    assert api.body(1)["messages"] == [QUESTION, assistant, results]


def test_after_the_round_limit_a_last_call_without_tools_forces_an_answer():
    looping = message([tool_use(1, "list_watches", {})], "tool_use")
    api = ok(*[looping] * MAX_ROUNDS, message([text("Here is what I found.")]))

    reply = api.agent().respond([QUESTION], RecordingTools())

    assert len(api.requests) == MAX_ROUNDS + 1
    assert all("tool_choice" not in api.body(i) for i in range(MAX_ROUNDS))
    last = api.body(MAX_ROUNDS)
    assert last["tool_choice"] == {"type": "none"}
    assert last["tools"] == TOOLS
    assert reply.text == "Here is what I found."
    assert reply.messages[-1]["role"] == "assistant"
    assert len(reply.messages) == 2 * MAX_ROUNDS + 1


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_a_refused_or_cut_off_answer_is_unavailable(stop_reason):
    api = ok(message([text("I can")], stop_reason))

    with pytest.raises(WatchAgentUnavailable):
        api.agent().respond([QUESTION], RecordingTools())


def test_an_api_error_is_unavailable():
    api = FakeMessagesApi(
        (529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    )

    with pytest.raises(WatchAgentUnavailable):
        api.agent().respond([QUESTION], RecordingTools())


def test_model_and_effort_are_configurable():
    api = ok(message([text("ok")]))

    api.agent(model="claude-sonnet-5-5", effort="low").respond([QUESTION], RecordingTools())

    assert api.body()["model"] == "claude-sonnet-5-5"
    assert api.body()["output_config"] == {"effort": "low"}


def test_settings_from_the_environment():
    assert build_watch_agent(Settings.from_env({"ANTHROPIC_API_KEY": "k"})) is None
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_watch_agent(Settings.from_env({"FS_WATCH_AGENT": "claude"}))
    with pytest.raises(ValueError, match="FS_WATCH_AGENT"):
        build_watch_agent(Settings.from_env({"FS_WATCH_AGENT": "gpt"}))

    agent = build_watch_agent(
        Settings.from_env({"FS_WATCH_AGENT": "claude", "ANTHROPIC_API_KEY": "k"})
    )
    assert isinstance(agent, ClaudeWatchAgent)
    assert agent.settings == WatchAgentSettings(
        api_key="k", model="claude-haiku-5-5", effort="medium"
    )
    custom = WatchAgentSettings.from_env(
        {
            "ANTHROPIC_API_KEY": "k",
            "FS_WATCH_AGENT_MODEL": "claude-sonnet-5-5",
            "FS_WATCH_AGENT_EFFORT": "high",
        }
    )
    assert (custom.model, custom.effort) == ("claude-sonnet-5-5", "high")
