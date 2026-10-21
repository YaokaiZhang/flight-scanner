# No `from __future__ import annotations`: FastAPI resolves these type hints at runtime.
"""Source state for the data-health page.

GET /sources/blocked
    sources that disabled themselves after being turned away (bot protection, access denied),
    with when and why; re-enable with `python -m flight_scanner unblock <source>`
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from flight_scanner import source_health

router = APIRouter()


def _conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(_conn)]


class BlockedSource(BaseModel):
    source: str
    blocked_at: datetime
    reason: str


@router.get("/sources/blocked")
def list_blocked_sources(conn: Conn) -> list[BlockedSource]:
    return [BlockedSource(**vars(b)) for b in source_health.blocks(conn).values()]
