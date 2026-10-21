# No `from __future__ import annotations`: FastAPI resolves these type hints at runtime.
"""The scan planner's latest plan: what each source was asked, and what was skipped.

GET /scan-tasks?status=scheduled|scanned|failed|skipped&source=NAME
    tasks of the most recent plan, highest priority first per source
"""

from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from flight_scanner import scan_planner

router = APIRouter()


def _conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(_conn)]
Status = Literal["scheduled", "scanned", "failed", "skipped"]


class Factors(BaseModel):
    proximity: float
    volatility: float
    deal: float
    staleness: float


class ScanTask(BaseModel):
    id: int
    source: str
    origin: str
    destination: str | None  # null: wildcard (anywhere from origin)
    month: str  # YYYY-MM
    round_trip: bool
    earliest_departure: date
    destinations: int  # demanded destination airports this task prices
    watch_ids: list[int]
    priority: float
    factors: Factors
    requests: int  # source requests it costs
    status: Status
    reason: str | None  # why it was skipped


class ScanPlan(BaseModel):
    planned_at: datetime | None
    tasks: list[ScanTask]


@router.get("/scan-tasks")
def list_scan_tasks(
    conn: Conn, status: Status | None = None, source: str | None = None
) -> ScanPlan:
    planned_at, rows = scan_planner.latest(conn, status, source)
    return ScanPlan(
        planned_at=planned_at,
        tasks=[
            ScanTask(
                **{
                    **r,
                    "month": r["month"].isoformat()[:7],
                    "priority": float(r["priority"]),
                    "requests": len(r["requests"]),
                }
            )
            for r in rows
        ],
    )
