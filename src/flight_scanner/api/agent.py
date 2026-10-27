# No `from __future__ import annotations`: FastAPI resolves these type hints at runtime.
"""The Watch assistant chat (see flight_scanner.watch_agent).

GET  /agent                    {"enabled": bool}: whether FS_WATCH_AGENT is configured
POST /agent/chats              {"text": ...} starts a chat -> ChatTurn {chat_id, reply, proposals}
POST /agent/chats/{chat_id}    {"text": ...} continues it -> ChatTurn; 404 for an unknown chat

503 {"detail": ...} when the assistant is off or could not answer (nothing is saved then).
A proposal's `spec` is accepted by POSTing it unchanged to /watches.
"""

import logging
from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from flight_scanner import watch_agent
from flight_scanner.clock import today
from flight_scanner.watch_agent import ChatTurn, UnknownChat, WatchAgentUnavailable

log = logging.getLogger(__name__)
router = APIRouter()


def _conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(_conn)]


class AgentStatus(BaseModel):
    enabled: bool


class ChatMessage(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


@router.get("/agent")
def agent_status(request: Request) -> AgentStatus:
    return AgentStatus(enabled=request.app.state.watch_agent is not None)


def _turn(request: Request, conn: psycopg.Connection, text: str, chat_id: int | None) -> ChatTurn:
    state = request.app.state
    if state.watch_agent is None:
        raise HTTPException(503, "The Watch assistant is not enabled.")
    try:
        return watch_agent.chat(
            conn, state.watch_agent, state.reference, today(state.clock), text, chat_id
        )
    except UnknownChat:
        raise HTTPException(404, "chat not found") from None
    except WatchAgentUnavailable as e:
        log.warning("Watch assistant unavailable: %s", e)
        raise HTTPException(503, "The Watch assistant could not answer. Try again.") from None


@router.post("/agent/chats")
def start_chat(body: ChatMessage, request: Request, conn: Conn) -> ChatTurn:
    return _turn(request, conn, body.text, None)


@router.post("/agent/chats/{chat_id}")
def continue_chat(chat_id: int, body: ChatMessage, request: Request, conn: Conn) -> ChatTurn:
    return _turn(request, conn, body.text, chat_id)
