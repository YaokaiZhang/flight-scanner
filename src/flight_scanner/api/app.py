# No `from __future__ import annotations`: FastAPI must resolve the closure-local `Conn` alias.
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

from flight_scanner import watches
from flight_scanner.clock import Clock, SystemClock
from flight_scanner.db import DbSettings
from flight_scanner.places import (
    Place,
    PlaceKind,
    PlaceRef,
    PlaceSet,
    ReferenceData,
    TreeNode,
    default_reference,
)
from flight_scanner.watches import InvalidWatch, Watch, WatchSpec


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
        return found(watches.update(c, watch_id, spec, clock, ref))

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
