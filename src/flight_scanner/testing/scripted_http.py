"""Test stand-ins for the airline adapters' HTTP: a scripted transport and a fake timer.

    timer = FakeTimer()
    transport = ScriptedTransport(HttpResponse(200, {}, body), TimeoutError(), ..., timer=timer)
    RyanairAdapter(clock, transport=transport, sleep=timer.sleep, monotonic=timer.monotonic)

Each call is answered with the next scripted response (an exception is raised instead);
`calls` records (method, url, headers, body, monotonic time) of every request.
A callable script entry `fn(method, url, headers, body)` computes the answer per request.
"""

from __future__ import annotations

from flight_scanner.sources.polite_http import HttpResponse


class FakeTimer:
    def __init__(self, start: float = 1000.0):
        self.now = start
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class ScriptedTransport:
    def __init__(self, *responses, timer: FakeTimer | None = None, repeat_last: bool = False):
        self.responses = list(responses)
        self.timer = timer
        self.repeat_last = repeat_last
        self.calls: list[tuple[str, str, dict[str, str], bytes | None, float]] = []

    def script(self, *responses) -> None:
        self.responses.extend(responses)

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> HttpResponse:
        self.calls.append((method, url, headers, body, self.timer.now if self.timer else 0.0))
        if not self.responses:
            raise AssertionError(f"unexpected request {method} {url}")
        r = self.responses[0] if self.repeat_last and len(self.responses) == 1 else None
        if r is None:
            r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(method, url, headers, body)
        return r
