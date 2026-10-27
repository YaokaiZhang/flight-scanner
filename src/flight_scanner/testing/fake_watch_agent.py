"""A scripted stand-in for the Watch assistant (no network, no API key).

FakeWatchAgent([("search_places", {"query": "Lisbon"})], "Here is one idea.")
    # each turn: runs the calls through the AgentTools, then answers with the text
FakeWatchAgent(turns=[([...], "first"), ([...], "second")])   # a different script per turn
FakeWatchAgent(fail=True)                                     # raises WatchAgentUnavailable

The messages it returns have the Messages API shape (tool_use / tool_result / text blocks), so
stored histories look like the real agent's. `.histories` records what each turn was given and
`.results` the (output, is_error) of every tool call.
"""

from __future__ import annotations

import json

from flight_scanner.watch_agent import AgentTools, Reply, WatchAgentUnavailable

Script = tuple[list[tuple[str, dict]], str]


class FakeWatchAgent:
    def __init__(
        self,
        calls: list[tuple[str, dict]] | None = None,
        text: str = "Here is a suggestion.",
        turns: list[Script] | None = None,
        fail: bool = False,
    ) -> None:
        self.turns = list(turns) if turns is not None else None
        self.script: Script = (list(calls or []), text)
        self.fail = fail
        self.histories: list[list[dict]] = []
        self.results: list[tuple[str, bool]] = []

    def respond(self, history: list[dict], tools: AgentTools) -> Reply:
        self.histories.append(json.loads(json.dumps(history)))
        if self.fail:
            raise WatchAgentUnavailable("scripted failure")
        calls, text = self.turns.pop(0) if self.turns else self.script
        messages: list[dict] = []
        if calls:
            uses = [
                {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": args}
                for i, (name, args) in enumerate(calls)
            ]
            results = []
            for use in uses:
                output, is_error = tools.run(use["name"], use["input"])
                self.results.append((output, is_error))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "content": output,
                        "is_error": is_error,
                    }
                )
            messages += [
                {"role": "assistant", "content": uses},
                {"role": "user", "content": results},
            ]
        messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        return Reply(messages=messages, text=text)
