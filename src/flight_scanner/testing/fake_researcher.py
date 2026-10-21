"""A scripted stand-in for the Deal-context researcher (no network, no API key).

FakeResearcher({("HEL", "BCN"): "Autumn sale"})   # answers per (origin, destination)
FakeResearcher(..., hold=True)                       # blocks until .release(): the late path
FakeResearcher(fail=True)                            # raises on every call
FakeResearcher(default="Autumn sale")                # same answer for every route
"""

from __future__ import annotations

import threading

from flight_scanner.deal_context import DealFacts

MAX_HOLD = 30.0  # seconds; a held call never outlives a forgotten release() by more than this


class FakeResearcher:
    def __init__(
        self,
        contexts: dict[tuple[str, str], str] | None = None,
        hold: bool = False,
        fail: bool = False,
        default: str | None = None,
    ) -> None:
        self.default = default
        self.contexts = dict(contexts or {})
        self.fail = fail
        self.asked: list[DealFacts] = []
        self._released = threading.Event()
        if not hold:
            self._released.set()
        self._lock = threading.Lock()

    def release(self) -> None:
        self._released.set()

    def research(self, deal: DealFacts) -> str | None:
        with self._lock:
            self.asked.append(deal)
        self._released.wait(MAX_HOLD)
        if self.fail:
            raise RuntimeError("research failed")
        return self.contexts.get((deal.origin, deal.destination), self.default)
