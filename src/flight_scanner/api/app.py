# No `from __future__ import annotations`: FastAPI must resolve the closure-local `Conn` alias.
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from flight_scanner import watches
from flight_scanner.clock import Clock, SystemClock
from flight_scanner.db import DbSettings
from flight_scanner.watches import Watch, WatchSpec


class Deal(BaseModel):
    id: int
    watch_id: int
    watch_name: str
    origin: str
    destination: str
    outbound_date: date
    return_date: date | None
    adults: int
    price_per_adult_eur: float
    price_total_eur: float
    source: str
    observed_at: datetime
    verification: str
    baseline_tier: str | None
    detected_at: datetime


def create_app(db: DbSettings, clock: Clock | None = None) -> FastAPI:
    clock = clock or SystemClock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from psycopg.rows import dict_row

        pool = ConnectionPool(
            db.conninfo, min_size=1, max_size=5, kwargs={"row_factory": dict_row}, open=True
        )
        app.state.pool = pool
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(title="Flight Scanner API", lifespan=lifespan)

    def conn(request: Request) -> Iterator[psycopg.Connection]:
        with request.app.state.pool.connection() as c:
            yield c

    Conn = Annotated[psycopg.Connection, Depends(conn)]

    @app.get("/health")
    def health(c: Conn) -> dict:
        c.execute("SELECT 1")
        return {"ok": True}

    @app.post("/watches", status_code=201)
    def create_watch(spec: WatchSpec, c: Conn) -> Watch:
        return watches.create(c, spec, clock)

    @app.get("/watches")
    def list_watches(c: Conn) -> list[Watch]:
        return watches.list_all(c)

    @app.get("/watches/{watch_id}")
    def get_watch(watch_id: int, c: Conn) -> Watch:
        w = watches.get(c, watch_id)
        if w is None:
            raise HTTPException(404, "watch not found")
        return w

    @app.get("/deals")
    def list_deals(c: Conn, watch_id: int | None = None) -> list[Deal]:
        rows = c.execute(
            """SELECT d.*, w.name AS watch_name
               FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
               WHERE %(w)s::bigint IS NULL OR d.watch_id = %(w)s
               ORDER BY d.detected_at DESC, d.id DESC LIMIT 200""",
            {"w": watch_id},
        )
        return [Deal(**r) for r in rows]

    return app
