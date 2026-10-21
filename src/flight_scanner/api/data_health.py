# No `from __future__ import annotations`: FastAPI resolves these type hints at runtime.
"""The data-health page's data: freshness, coverage, backlog, Verification budget, checks.

GET /data-health    see flight_scanner.data_health
"""

from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Request

from flight_scanner import data_health

router = APIRouter()


def _conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(_conn)]


@router.get("/data-health")
def get_data_health(conn: Conn, request: Request) -> data_health.DataHealth:
    return data_health.summary(
        conn, request.app.state.clock.now(), request.app.state.verification_budget
    )
