"""Watch assistant: a chat agent that suggests Watches, which the owner accepts with one click.

    agent = build_watch_agent(settings)        # None unless FS_WATCH_AGENT is set
    turn = chat(conn, agent, reference, today, "long weekends somewhere warm", chat_id=None)
    turn.reply, turn.proposals                 # what to show; nothing has been created

The agent works through `AgentTools`: it can search Places, read the existing Watches, the fares
observed so far and recent Deals, and propose a Watch. A proposal is a validated `WatchSpec`
(Places exist and resolve to airports, the Trip pattern resolves for today) plus a reason; it is
never saved here. The owner creates it through the ordinary `POST /watches`, so a suggestion uses
no scan budget until it is accepted.

A conversation is kept in `app.agent_chats` as the Messages API history (so tool calls and
thinking stay intact across turns); the browser only holds the chat id.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from flight_scanner import trip_patterns, watches
from flight_scanner.config import Settings
from flight_scanner.places import Place, PlaceRef, PlaceSet, ReferenceData
from flight_scanner.watches import InvalidWatch, WatchSpec

MAX_FARES = 40  # routes per observed_fares answer
MAX_DEALS = 20


class WatchAgentUnavailable(Exception):
    """The agent could not answer (API down, refused, cut short). Nothing was saved."""


class UnknownChat(KeyError):
    """No chat with that id."""


class ResolvedCounts(BaseModel):
    origins: int
    destinations: int


class Proposal(BaseModel):
    """A suggested Watch: valid as it stands, shown with the Places named and the trips it means."""

    id: str
    reason: str
    spec: WatchSpec
    places: list[Place]
    trip: trip_patterns.Resolution
    resolved: ResolvedCounts


class ChatTurn(BaseModel):
    chat_id: int
    reply: str
    proposals: list[Proposal]


@dataclass
class Reply:
    """What one agent turn added to the history, and the text to show the owner."""

    messages: list[dict]
    text: str


class WatchAgent(Protocol):
    def respond(self, history: list[dict], tools: AgentTools) -> Reply:
        """Continue `history` (ending with the owner's message), calling `tools` as needed.
        Returns the messages it added, ending with an assistant message that calls no tool.
        Raises WatchAgentUnavailable when it can't answer."""
        ...


_WATCH = WatchSpec.model_json_schema()
_WATCH_DEFS = _WATCH.pop("$defs")  # "#/$defs/..." refs resolve from the root of input_schema

_PLACE_REF = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["airport", "city", "country", "region"]},
        "code": {"type": "string"},
    },
    "required": ["kind", "code"],
    "additionalProperties": False,
}

TOOLS: list[dict] = [
    {
        "name": "search_places",
        "description": (
            "Find Places (airports, cities, countries, Regions) by name or code. Use it for every "
            "Place you put in a Watch: only codes returned here are valid."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or code, e.g. 'Lisbon'."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_watches",
        "description": "The owner's existing Watches (with status), to avoid duplicates and to "
        "learn where they fly from and how they like to travel.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "observed_fares",
        "description": (
            "Current one-way fares the scanner has observed, per route: cheapest, median and the "
            "cheapest departure date (future departures only). Only routes some Watch already "
            "scans have fares. Optionally narrow by origin and/or destination Place."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": _PLACE_REF,
                "destination": _PLACE_REF,
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_FARES},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "recent_deals",
        "description": "The most recent Deals found (fares well below their Baseline), newest "
        "first.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "propose_watch",
        "description": (
            "Show the owner a Watch they can create with one click. It is validated (Places must "
            "exist, the Trip pattern must resolve); on an error, fix the input and call again. "
            "Proposing never creates anything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "watch": _WATCH,
                "reason": {
                    "type": "string",
                    "description": "One or two sentences on why this Watch suits the owner.",
                },
            },
            "required": ["watch", "reason"],
            "$defs": _WATCH_DEFS,
        },
    },
]


@dataclass
class AgentTools:
    """The agent's view of the system: read-only, except that proposals are collected."""

    conn: psycopg.Connection
    reference: ReferenceData
    today: date
    proposals: list[Proposal] = field(default_factory=list)

    def run(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """(JSON result, is_error) for one tool call."""
        handler = getattr(self, f"_{name}", None) if name in {t["name"] for t in TOOLS} else None
        if handler is None:
            return json.dumps({"error": f"unknown tool {name!r}"}), True
        try:
            return json.dumps(handler(**args), default=str), False
        except (ValidationError, InvalidWatch, ValueError, TypeError) as e:
            return json.dumps({"error": str(e)}), True

    def _search_places(self, query: str, limit: int = 8) -> list[dict]:
        return [p.model_dump() for p in self.reference.search(query, min(limit, 20))]

    def _list_watches(self) -> list[dict]:
        out = []
        for w in watches.list_all(self.conn):
            out.append(
                {
                    "name": w.name,
                    "status": w.status,
                    "origins": self._named(w.origins),
                    "destinations": self._named(w.destinations),
                    "trip_pattern": w.trip_pattern.model_dump(mode="json"),
                    "adults": w.adults,
                    "channels": w.channels,
                    "price_threshold": w.price_threshold and w.price_threshold.model_dump(),
                    "sensitivity_pct": w.sensitivity_pct,
                }
            )
        return out

    def _named(self, places: PlaceSet) -> dict:
        def name(r: PlaceRef) -> str:
            p = self.reference.describe(r)
            return f"{r.kind} {r.code}" + (f" ({p.name})" if p else "")

        return {
            "include": [name(r) for r in places.include],
            "exclude": [name(r) for r in places.exclude],
        }

    def _airports(self, ref: dict | None) -> list[str] | None:
        if ref is None:
            return None
        place = PlaceRef(**ref)
        if not self.reference.known(place):
            raise ValueError(f"unknown {place.kind} {place.code!r}: use search_places")
        return sorted(self.reference.airports_of(place))

    def _observed_fares(
        self, origin: dict | None = None, destination: dict | None = None, limit: int = 25
    ) -> list[dict]:
        if (
            self.conn.execute("SELECT to_regclass('history.leg_price_history') AS t").fetchone()[
                "t"
            ]
            is None
        ):
            return []
        rows = self.conn.execute(
            """SELECT origin, destination, count(DISTINCT departure_date) AS departure_dates,
                      min(price_per_adult_eur) AS cheapest_eur,
                      round(percentile_cont(0.5) WITHIN GROUP (ORDER BY price_per_adult_eur)
                            ::numeric, 2) AS median_eur,
                      (array_agg(departure_date ORDER BY price_per_adult_eur, departure_date))[1]
                          AS cheapest_date
               FROM history.leg_price_history
               WHERE valid_to IS NULL AND departure_date >= %(today)s
                 AND (%(o)s::text[] IS NULL OR origin = ANY(%(o)s))
                 AND (%(d)s::text[] IS NULL OR destination = ANY(%(d)s))
               GROUP BY origin, destination
               ORDER BY cheapest_eur, origin, destination
               LIMIT %(limit)s""",
            {
                "today": self.today,
                "o": self._airports(origin),
                "d": self._airports(destination),
                "limit": min(limit, MAX_FARES),
            },
        ).fetchall()
        return [
            {
                **r,
                "cheapest_eur": float(r["cheapest_eur"]),
                "median_eur": float(r["median_eur"]),
                "origin_name": self._airport_name(r["origin"]),
                "destination_name": self._airport_name(r["destination"]),
            }
            for r in rows
        ]

    def _airport_name(self, code: str) -> str | None:
        p = self.reference.describe(PlaceRef(kind="airport", code=code))
        return None if p is None else f"{p.name} ({p.context})" if p.context else p.name

    def _recent_deals(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT d.origin, d.destination, d.outbound_date, d.return_date, d.adults,
                      d.price_per_adult_eur, d.baseline_per_adult_eur, d.verification,
                      d.detected_at, w.name AS watch
               FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
               WHERE d.verification <> 'failed'
               ORDER BY d.detected_at DESC, d.id DESC LIMIT %s""",
            (MAX_DEALS,),
        ).fetchall()
        return [
            {
                **r,
                "price_per_adult_eur": float(r["price_per_adult_eur"]),
                "baseline_per_adult_eur": None
                if r["baseline_per_adult_eur"] is None
                else float(r["baseline_per_adult_eur"]),
            }
            for r in rows
        ]

    def _propose_watch(self, watch: dict | str, reason: str) -> dict:
        if isinstance(watch, str):  # a Watch sent as a JSON string instead of an object
            watch = json.loads(watch)
        spec = WatchSpec.model_validate(watch)
        watches.validate(spec, self.reference)
        trip = trip_patterns.resolve(spec.trip_pattern, self.today)
        if trip.expired or trip.trip_count == 0:
            raise ValueError("the Trip pattern has no trips from today on: pick future dates")
        refs = dict.fromkeys(
            [*spec.origins.include, *spec.origins.exclude]
            + [*spec.destinations.include, *spec.destinations.exclude]
        )
        proposal = Proposal(
            id=uuid.uuid4().hex[:12],
            reason=reason.strip(),
            spec=spec,
            places=[p for r in refs if (p := self.reference.describe(r)) is not None],
            trip=trip,
            resolved=ResolvedCounts(
                origins=len(self.reference.resolve(spec.origins)),
                destinations=len(self.reference.resolve(spec.destinations)),
            ),
        )
        self.proposals.append(proposal)
        return {
            "proposed": proposal.id,
            "departures": f"{trip.departure_start} to {trip.departure_end}",
            "trips": trip.trip_count,
            "airports": proposal.resolved.model_dump(),
        }


def chat(
    conn: psycopg.Connection,
    agent: WatchAgent,
    reference: ReferenceData,
    today: date,
    text: str,
    chat_id: int | None = None,
) -> ChatTurn:
    """One owner message and the agent's answer. A new chat when `chat_id` is None; UnknownChat (a
    KeyError) when it does not exist. The turn is saved only once the agent has answered."""
    history: list[dict] = []
    if chat_id is not None:
        row = conn.execute(
            "SELECT messages FROM app.agent_chats WHERE id = %s", (chat_id,)
        ).fetchone()
        if row is None:
            raise UnknownChat(chat_id)
        history = row["messages"]
    content = text.strip()
    if not history:  # the date anchors "next month", "this winter", rolling windows
        content = f"(Today is {today:%A %d %B %Y}.)\n\n{content}"
    question = {"role": "user", "content": content}
    tools = AgentTools(conn, reference, today)
    reply = agent.respond([*history, question], tools)
    messages = [*history, question, *reply.messages]
    if chat_id is None:
        chat_id = conn.execute(
            "INSERT INTO app.agent_chats (messages) VALUES (%s) RETURNING id", (Jsonb(messages),)
        ).fetchone()["id"]
    else:
        conn.execute(
            "UPDATE app.agent_chats SET messages = %s, updated_at = now() WHERE id = %s",
            (Jsonb(messages), chat_id),
        )
    return ChatTurn(chat_id=chat_id, reply=reply.text, proposals=tools.proposals)


def build_watch_agent(settings: Settings) -> WatchAgent | None:
    """FS_WATCH_AGENT=claude turns on the Claude Watch assistant (needs ANTHROPIC_API_KEY);
    unset/empty turns it off."""
    kind = settings.env.get("FS_WATCH_AGENT", "").strip().lower()
    if not kind:
        return None
    if kind != "claude":
        raise ValueError(f"unknown FS_WATCH_AGENT {kind!r} (expected 'claude' or empty)")
    from flight_scanner.watch_agent.claude import ClaudeWatchAgent, WatchAgentSettings

    return ClaudeWatchAgent(WatchAgentSettings.from_env(settings.env))
