# No `from __future__ import annotations`: FastAPI resolves these type hints at runtime.
"""The backtest page's data: per Watch, were its Deals real dips, Alert rate, and feedback.

GET /backtest    every Watch's backtest summary and past Deals (see flight_scanner.backtest)
"""

from collections.abc import Iterator
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, Request

from flight_scanner import backtest

router = APIRouter()


def _conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(_conn)]


@router.get("/backtest")
def get_backtest(conn: Conn, request: Request) -> backtest.Backtest:
    return backtest.summary(conn, request.app.state.clock.now())
