"""Seam 3: the Claude Deal-context researcher against a recorded-shape Messages API (no network).

The real SDK client runs over an in-process transport, so request serialisation and response
parsing are the SDK's own; only the HTTP exchange is canned.
"""

import json
from datetime import date

import anthropic
import httpx2
import pytest

from flight_scanner.config import Settings
from flight_scanner.deal_context import DealFacts, build_researcher
from flight_scanner.deal_context.claude import ClaudeResearcher, ClaudeSettings

DEAL = DealFacts(
    deal_id=1,
    origin="HEL",
    destination="BCN",
    outbound_date=date(2026, 11, 14),
    return_date=date(2026, 11, 17),
    adults=2,
    price_per_adult_eur=89,
    baseline_per_adult_eur=180,
    airlines="VY",
)
SEARCH = [
    {"type": "text", "text": "I'll look for Vueling promotions."},
    {
        "type": "server_tool_use",
        "id": "srvtoolu_1",
        "name": "web_search",
        "input": {"query": "Vueling Helsinki Barcelona sale November 2026"},
    },
    {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": [
            {
                "type": "web_search_result",
                "url": "https://news.example/vueling-autumn-sale",
                "title": "Vueling autumn sale",
                "encrypted_content": "abc",
                "page_age": "2 days ago",
            }
        ],
    },
]
ANSWER = "Vueling's autumn sale on Helsinki routes runs until 31 October."


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


class FakeMessagesApi:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self.responses.pop(0))

    def body(self, i: int = 0) -> dict:
        return json.loads(self.requests[i].content)

    def researcher(self, **settings) -> ClaudeResearcher:
        client = anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handler)),
        )
        return ClaudeResearcher(ClaudeSettings(api_key="test-key", **settings), client=client)


def test_asks_claude_with_web_search_and_returns_the_answer_after_the_search():
    api = FakeMessagesApi(message([*SEARCH, {"type": "text", "text": ANSWER}]))

    assert api.researcher().research(DEAL) == ANSWER

    [request] = api.requests
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == "test-key"
    assert "anthropic-beta" not in request.headers
    body = api.body()
    assert body["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in body
    assert "thinking" not in body
    assert body["output_config"] == {"effort": "medium"}
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    question = body["messages"][0]["content"]
    assert "HEL to BCN" in question
    assert "2026-11-14 to 2026-11-17" in question
    assert "EUR 89 per adult" in question
    assert "EUR 180" in question
    assert "VY" in question


def test_model_and_effort_are_configurable():
    api = FakeMessagesApi(message([{"type": "text", "text": ANSWER}]))

    api.researcher(model="claude-sonnet-5-5", effort="low").research(DEAL)

    assert api.body()["model"] == "claude-sonnet-5-5"
    assert api.body()["output_config"] == {"effort": "low"}


def test_nothing_found_means_no_context():
    api = FakeMessagesApi(message([*SEARCH, {"type": "text", "text": "NONE"}]))

    assert api.researcher().research(DEAL) is None


def test_a_paused_search_turn_is_resumed():
    api = FakeMessagesApi(
        message(SEARCH, stop_reason="pause_turn"),
        message([{"type": "text", "text": ANSWER}]),
    )

    assert api.researcher().research(DEAL) == ANSWER

    second = api.body(1)["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]
    assert second[1]["content"][1]["type"] == "server_tool_use"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_a_refused_or_truncated_answer_gives_no_context(stop_reason):
    api = FakeMessagesApi(message([{"type": "text", "text": "Vueling's autumn"}], stop_reason))

    assert api.researcher().research(DEAL) is None


def test_deal_context_is_off_unless_configured():
    assert build_researcher(Settings.from_env({})) is None
    assert build_researcher(Settings.from_env({"ANTHROPIC_API_KEY": "k"})) is None


def test_claude_deal_context_needs_an_api_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_researcher(Settings.from_env({"FS_DEAL_CONTEXT": "claude"}))
    with pytest.raises(ValueError, match="FS_DEAL_CONTEXT"):
        build_researcher(Settings.from_env({"FS_DEAL_CONTEXT": "gpt"}))

    researcher = build_researcher(
        Settings.from_env({"FS_DEAL_CONTEXT": "claude", "ANTHROPIC_API_KEY": "k"})
    )
    assert isinstance(researcher, ClaudeResearcher)
    assert researcher.settings.model == "claude-haiku-5-5"
    assert researcher.settings.effort == "medium"
