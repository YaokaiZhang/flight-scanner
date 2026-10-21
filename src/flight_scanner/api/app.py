# No `from __future__ import annotations`: FastAPI must resolve the closure-local `Conn` alias.
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from flight_scanner import feedback, trip_patterns, watches
from flight_scanner.api import backtest, routes, scan_tasks, sources
from flight_scanner.clock import Clock, SystemClock, today
from flight_scanner.db import DbSettings
from flight_scanner.notify.base import pct_below_baseline
from flight_scanner.notify.content import booking_link
from flight_scanner.places import (
    Place,
    PlaceKind,
    PlaceRef,
    PlaceSet,
    ReferenceData,
    TreeNode,
    default_reference,
)
from flight_scanner.trip_patterns import TripPreset
from flight_scanner.watches import InvalidWatch, Watch, WatchSpec


class Feedback(BaseModel):
    rating: feedback.Rating
    via: feedback.Via


class FeedbackIn(BaseModel):
    rating: feedback.Rating | None  # null clears the rating


class TripPatternQuery(BaseModel):
    trip_pattern: TripPreset


class DealBaseline(BaseModel):
    """The Baseline version a Deal was judged against: (tier, key, computed_at) plus support."""

    tier: str
    per_adult_eur: float
    method: str | None
    computed_at: datetime | None
    observations: int | None
    observation_days: int | None


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
    ticketing: str
    # verified | unverified | failed (checked live and not a Deal: recorded, never alerted)
    verification: Literal["verified", "unverified", "failed"]
    # why: live_deal | live_not_a_deal | not_found | budget_exhausted | no_verifier |
    # verifier_error (null: not judged yet)
    verification_reason: str | None = None
    verified_at: datetime | None = None  # when it was checked live
    verified_price_total_eur: float | None = None  # the live price for the Watch's adults
    verified_price_per_adult_eur: float | None = None
    baseline_tier: str | None
    detected_at: datetime
    airlines: str | None
    stops: int | None
    travel_minutes: int | None
    separate_tickets: bool
    booking_url: str
    baseline_per_adult_eur: float | None
    pct_below_baseline: float | None
    baseline: DealBaseline | None
    deal_context: str | None = None  # why it might be cheap, when researched in time
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
    version = None
    if row["baseline_tier"] is not None and baseline is not None:
        version = DealBaseline(
            tier=row["baseline_tier"],
            per_adult_eur=float(baseline),
            method=row["baseline_method"],
            computed_at=row["baseline_computed_at"],
            observations=row["baseline_observations"],
            observation_days=row["baseline_observation_days"],
        )
    live = row["verified_price_total_eur"]
    return Deal(
        **{**row, "booking_url": booking_url},
        verified_price_per_adult_eur=None
        if live is None
        else round(float(live) / row["adults"], 2),
        pct_below_baseline=pct,
        baseline=version,
        feedback=Feedback(rating=rating, via=row["feedback_via"]) if rating else None,
    )


class ResolvedCounts(BaseModel):
    origins: int
    destinations: int


class WatchOut(Watch):
    """A Watch as the API returns it: plus the Places it names and its resolved airport counts."""

    places: list[Place]
    resolved: ResolvedCounts


class Resolution(BaseModel):
    airport_count: int
    airports: list[str]
    reference_version: str


def _unknown_places(refs: list[PlaceRef]) -> HTTPException:
    return HTTPException(
        422,
        [
            {
                "type": "unknown_place",
                "msg": f"unknown {p.kind} {p.code!r}",
                "input": p.model_dump(),
            }
            for p in refs
        ],
    )


def create_app(
    db: DbSettings, clock: Clock | None = None, reference: ReferenceData | None = None
) -> FastAPI:
    clock = clock or SystemClock()
    ref = reference or default_reference()

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
    app.state.clock = clock
    app.include_router(routes.router)
    app.include_router(backtest.router)
    app.include_router(scan_tasks.router)
    app.include_router(sources.router)

    @app.exception_handler(InvalidWatch)
    def invalid_watch(request: Request, exc: InvalidWatch) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors})

    def out(w: Watch) -> WatchOut:
        refs = dict.fromkeys(
            [
                *w.origins.include,
                *w.origins.exclude,
                *w.destinations.include,
                *w.destinations.exclude,
            ]
        )
        described = [d for p in refs if (d := ref.describe(p)) is not None]
        return WatchOut(
            **w.model_dump(),
            places=described,
            resolved=ResolvedCounts(
                origins=len(ref.resolve(w.origins)), destinations=len(ref.resolve(w.destinations))
            ),
        )

    def found(w: Watch | None) -> WatchOut:
        if w is None:
            raise HTTPException(404, "watch not found")
        return out(w)

    def conn(request: Request) -> Iterator[psycopg.Connection]:
        with request.app.state.pool.connection() as c:
            yield c

    Conn = Annotated[psycopg.Connection, Depends(conn)]

    @app.get("/health")
    def health(c: Conn) -> dict:
        c.execute("SELECT 1")
        return {"ok": True}

    # --- Places ----------------------------------------------------------------------------
    @app.get("/places/search")
    def search_places(q: str = "", limit: Annotated[int, Query(ge=1, le=50)] = 10) -> list[Place]:
        return ref.search(q, limit)

    @app.post("/places/resolve")
    def resolve_places(places: PlaceSet) -> Resolution:
        if unknown := ref.unknown(places):
            raise _unknown_places(unknown)
        airports = sorted(ref.resolve(places))
        return Resolution(
            airport_count=len(airports), airports=airports, reference_version=ref.version
        )

    @app.get("/places/regions")
    def list_regions() -> list[Place]:
        return ref.regions_list()

    @app.get("/places/{kind}/{code}/tree")
    def place_tree(
        kind: PlaceKind, code: str, depth: Annotated[int | None, Query(ge=0, le=4)] = None
    ) -> TreeNode:
        node = ref.tree(PlaceRef.model_construct(kind=kind, code=code), depth)
        if node is None:
            raise HTTPException(404, "place not found")
        return node

    # --- Watches ---------------------------------------------------------------------------
    @app.post("/watches", status_code=201)
    def create_watch(spec: WatchSpec, c: Conn) -> WatchOut:
        return out(watches.create(c, spec, clock, ref))

    @app.get("/watches")
    def list_watches(c: Conn) -> list[WatchOut]:
        return [out(w) for w in watches.list_all(c)]

    @app.get("/watches/{watch_id}")
    def get_watch(watch_id: int, c: Conn) -> WatchOut:
        return found(watches.get(c, watch_id))

    @app.put("/watches/{watch_id}")
    def update_watch(watch_id: int, spec: WatchSpec, c: Conn) -> WatchOut:
        found(watches.update(c, watch_id, spec, clock, ref))
        # An edited Trip pattern may expire the Watch or revive an expired one: show it now.
        watches.refresh_expiry(c, today(clock))
        return found(watches.get(c, watch_id))

    @app.post("/watches/{watch_id}/pause")
    def pause_watch(watch_id: int, c: Conn) -> WatchOut:
        return found(watches.set_status(c, watch_id, "paused", clock))

    @app.post("/watches/{watch_id}/resume")
    def resume_watch(watch_id: int, c: Conn) -> WatchOut:
        return found(watches.set_status(c, watch_id, "active", clock))

    @app.delete("/watches/{watch_id}", status_code=204)
    def delete_watch(watch_id: int, c: Conn) -> Response:
        if not watches.delete(c, watch_id):
            raise HTTPException(404, "watch not found")
        return Response(status_code=204)

    @app.post("/trip-patterns/resolve")
    def resolve_trip_pattern(q: TripPatternQuery) -> trip_patterns.Resolution:
        """The resolved departure window and Stay-night range of a preset, for today."""
        return trip_patterns.resolve(q.trip_pattern, today(clock))

    @app.get("/deals")
    def list_deals(
        c: Conn,
        watch_id: int | None = None,
        status: Literal["verified", "unverified", "failed"] | None = None,
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
