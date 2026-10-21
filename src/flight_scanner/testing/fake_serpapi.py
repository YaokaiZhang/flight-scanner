"""An in-process stand-in for SerpApi's Google Flights endpoint (an HTTP `Transport`).

    google = FakeGoogleFlights()
    google.offer("HEL", "BCN", date(2026, 11, 20), date(2026, 11, 27),
                 total=220, typical=(380, 520), history=[(datetime(...), 450), ...])
    adapter = SerpApiAdapter("test-key", clock, transport=google)

Answers in SerpApi's documented `google_flights` shape so the real adapter's `parse` runs.
Prices (`total`, `typical`, `history`) are for the whole party, like the real answer. A trip
without an offer answers "no results"; `fail_next()` makes the next call an error answer.
`asked` lists every trip searched as (origin, destination, outbound, return, adults, type).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from urllib.parse import parse_qs, urlsplit

from flight_scanner.sources.travelpayouts import HttpResponse

_Key = tuple[str, str, date, date | None]


class FakeGoogleFlights:
    def __init__(self):
        self._offers: dict[_Key, dict] = {}
        self._failures = 0
        self.asked: list[tuple] = []

    def offer(
        self,
        origin: str,
        destination: str,
        outbound: date,
        return_date: date | None = None,
        *,
        total: float | None,
        typical: tuple[float, float] | None = None,
        history: Iterable[tuple[datetime, float]] = (),
        airline: str = "Finnair",
    ) -> None:
        self._offers[(origin, destination, outbound, return_date)] = {
            "total": total,
            "typical": typical,
            "history": list(history),
            "airline": airline,
        }

    def fail_next(self, n: int = 1) -> None:
        self._failures += n

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        outbound = date.fromisoformat(q["outbound_date"])
        ret = date.fromisoformat(q["return_date"]) if "return_date" in q else None
        self.asked.append(
            (q["departure_id"], q["arrival_id"], outbound, ret, int(q["adults"]), q["type"])
        )
        if self._failures:
            self._failures -= 1
            return _json(401, {"error": "Your account has run out of searches."})
        offer = self._offers.get((q["departure_id"], q["arrival_id"], outbound, ret))
        doc: dict = {"search_metadata": {"status": "Success"}, "search_parameters": q}
        if offer is None or offer["total"] is None:
            doc["error"] = "Google Flights hasn't returned any results for this query."
            return _json(200, doc)
        doc["best_flights"] = [
            {
                "flights": [
                    {
                        "departure_airport": {"id": q["departure_id"], "time": f"{outbound} 07:05"},
                        "arrival_airport": {"id": q["arrival_id"], "time": f"{outbound} 10:10"},
                        "duration": 245,
                        "airline": offer["airline"],
                        "flight_number": "AY 1661",
                    }
                ],
                "total_duration": 245,
                "price": offer["total"],
                "type": "Round trip" if ret else "One way",
            }
        ]
        insights: dict = {"lowest_price": offer["total"]}
        if offer["typical"] is not None:
            insights["typical_price_range"] = list(offer["typical"])
        if offer["history"]:
            insights["price_history"] = [[int(t.timestamp()), p] for t, p in offer["history"]]
        doc["price_insights"] = insights
        return _json(200, doc)


def _json(status: int, doc: dict) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(doc).encode())
