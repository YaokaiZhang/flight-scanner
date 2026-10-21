# No `from __future__ import annotations`: FastAPI must resolve the closure-local `Conn` alias.
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from flight_scanner import feedback, watches
from flight_scanner.api import routes
from flight_scanner.clock import Clock, SystemClock
from flight_scanner.db import DbSettings
from flight_scanner.notify.base import pct_below_baseline
from flight_scanner.notify.content import booking_link
from flight_scanner.watches import Watch, WatchSpec


class Feedback(BaseModel):
    rating: feedback.Rating
    via: feedback.Via


class FeedbackIn(BaseModel):
    rating: feedback.Rating | None  # null clears the rating


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
    airlines: str | None
    stops: int | None
    travel_minutes: int | None
    separate_tickets: bool
    booking_url: str
    baseline_per_adult_eur: float | None
    pct_below_baseline: float | None
    feedback: Feedback | None


_DEALS_SQL = f"""SELECT d.*, w.name AS watch_name, f.*
                 FROM app.deals d JOIN app.watches w ON w.id = d.watch_id
                 LEFT JOIN LATERAL ({feedback.LATEST_FOR_DEAL}) f ON true"""


def _deal(row: dict) -> Deal:
    """A Deal as its Alerts describe it (same fallback booking link and % below Baseline)."""
    booking_url = row["booking_url"] or booking_link(
        row["origin"], row["destination"], row["outbound_date"], row["return_date"]
    )
    baseline = row["baseline_per_adult_eur"]
    pct = None
    if baseline is not None:
        pct = pct_below_baseline(float(row["price_per_adult_eur"]), float(baseline))
    rating = row["feedback_rating"]
    return Deal(
        **{**row, "booking_url": booking_url},
        pct_below_baseline=pct,
        feedback=Feedback(rating=rating, via=row["feedback_via"]) if rating else None,
    )


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
    app.include_router(routes.router)

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
    def list_deals(
        c: Conn,
        watch_id: int | None = None,
        status: Literal["verified", "unverified"] | None = None,
    ) -> list[Deal]:
        rows = c.execute(
            _DEALS_SQL
            + """ WHERE (%(w)s::bigint IS NULL OR d.watch_id = %(w)s)
                    AND (%(s)s::text IS NULL OR d.verification = %(s)s)
                  ORDER BY d.detected_at DESC, d.id DESC LIMIT 200""",
            {"w": watch_id, "s": status},
        )
        return [_deal(r) for r in rows]

    @app.get("/deals/{deal_id}")
    def get_deal(deal_id: int, c: Conn) -> Deal:
        row = c.execute(_DEALS_SQL + " WHERE d.id = %s", (deal_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "deal not found")
        return _deal(row)

    @app.post("/deals/{deal_id}/feedback")
    def rate_deal(deal_id: int, body: FeedbackIn, c: Conn) -> Deal:
        """👍/👎 from the Deals feed; `{"rating": null}` clears it."""
        if not feedback.rate_deal(c, deal_id, body.rating, "web", clock.now()):
            raise HTTPException(404, "deal not found")
        return get_deal(deal_id, c)

    return app
