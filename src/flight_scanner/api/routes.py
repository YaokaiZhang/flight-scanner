# No `from __future__ import annotations`: FastAPI resolves these type hints at runtime.
"""Route history for the route explorer: reads the dbt `history` and Baseline layers only.

GET /routes                                   routes with any price history, and their dates
GET /routes/{origin}/{destination}/history    change-only price history for one departure date,
                                              plus the trip's current Baseline band (or null)
    ?departure_date=YYYY-MM-DD                Leg prices for that departure
    &return_date=YYYY-MM-DD                   ... or Round-trip prices for those exact dates
"""

from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

router = APIRouter()

LEG = "history.leg_price_history"
ROUND_TRIP = "history.round_trip_price_history"


def _conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


Conn = Annotated[psycopg.Connection, Depends(_conn)]


class TripDates(BaseModel):
    departure_date: date
    return_date: date


class Route(BaseModel):
    origin: str
    destination: str
    departure_dates: list[date]  # with Leg-price history
    round_trips: list[TripDates]  # with Round-trip-price history


class HistoryPoint(BaseModel):
    source: str
    kind: Literal["leg", "round_trip"]
    price_per_adult_eur: float
    valid_from: datetime
    valid_to: datetime | None  # null while this is the current price
    last_observed_at: datetime
    observations: int
    airline: str | None
    stops: int | None


class BaselineBand(BaseModel):
    """The current Baseline of the trip: median +/- MAD (a Price insight: its typical range), and
    which tier/version it is."""

    tier: Literal["route", "country", "price_insight", "provisional"]
    median_per_adult_eur: float
    low_per_adult_eur: float
    high_per_adult_eur: float
    method: str
    computed_at: datetime
    observations: int
    observation_days: int


class RouteHistory(BaseModel):
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    points: list[HistoryPoint]
    baseline: BaselineBand | None = None


def _built(c: psycopg.Connection, table: str) -> bool:
    """History tables appear after the first dbt build; before that there is no history."""
    return c.execute("SELECT to_regclass(%s) AS t", (table,)).fetchone()["t"] is not None


@router.get("/routes")
def list_routes(c: Conn) -> list[Route]:
    routes: dict[tuple[str, str], Route] = {}

    def route(o: str, d: str) -> Route:
        return routes.setdefault(
            (o, d), Route(origin=o, destination=d, departure_dates=[], round_trips=[])
        )

    if _built(c, LEG):
        for r in c.execute(
            f"SELECT DISTINCT origin, destination, departure_date FROM {LEG} "
            "ORDER BY origin, destination, departure_date"
        ):
            route(r["origin"], r["destination"]).departure_dates.append(r["departure_date"])
    if _built(c, ROUND_TRIP):
        for r in c.execute(
            f"SELECT DISTINCT origin, destination, departure_date, return_date FROM {ROUND_TRIP} "
            "ORDER BY origin, destination, departure_date, return_date"
        ):
            route(r["origin"], r["destination"]).round_trips.append(
                TripDates(departure_date=r["departure_date"], return_date=r["return_date"])
            )
    return [routes[k] for k in sorted(routes)]


@router.get("/routes/{origin}/{destination}/history")
def route_history(
    origin: str,
    destination: str,
    departure_date: date,
    c: Conn,
    return_date: date | None = None,
) -> RouteHistory:
    origin, destination = origin.upper(), destination.upper()
    table, kind = (LEG, "leg") if return_date is None else (ROUND_TRIP, "round_trip")
    points: list[HistoryPoint] = []
    if _built(c, table):
        dates = "departure_date = %(dep)s" + (
            "" if return_date is None else " AND return_date = %(ret)s"
        )
        rows = c.execute(
            f"""SELECT source, price_per_adult_eur, valid_from, valid_to, last_observed_at,
                       observations, airline, stops
                FROM {table}
                WHERE origin = %(o)s AND destination = %(d)s AND {dates}
                ORDER BY valid_from, source""",
            {"o": origin, "d": destination, "dep": departure_date, "ret": return_date},
        )
        points = [HistoryPoint(kind=kind, **r) for r in rows]
    return RouteHistory(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        points=points,
        baseline=_baseline(c, origin, destination, departure_date, return_date),
    )


def stay_bucket(departure_date: date, return_date: date | None) -> str:
    """Stay-night bucket of a trip (as dbt's `stay_bucket` macro)."""
    if return_date is None:
        return "one_way"
    nights = (return_date - departure_date).days
    for top, bucket in ((2, "1-2"), (4, "3-4"), (7, "5-7"), (14, "8-14")):
        if nights <= top:
            return bucket
    return "15+"


BASELINES = "marts.effective_baselines"  # published by the lakehouse, else operational
PRICE_INSIGHTS = "marts.price_insights"


def _baseline(
    c: psycopg.Connection, origin: str, destination: str, dep: date, ret: date | None
) -> BaselineBand | None:
    """The first tier (route, country, the trip's Price insight, provisional) it has right now."""
    if not _built(c, BASELINES) or not _built(c, "ref.airports"):
        return None
    insight = None
    if _built(c, PRICE_INSIGHTS):
        insight = c.execute(
            f"""SELECT * FROM {PRICE_INSIGHTS}
                WHERE origin = %s AND destination = %s AND outbound_date = %s
                  AND return_date IS NOT DISTINCT FROM %s""",
            (origin, destination, dep, ret),
        ).fetchone()
    row = c.execute(
        f"""SELECT b.*
            FROM {BASELINES} b
            LEFT JOIN ref.airports o ON o.code = %(o)s
            LEFT JOIN ref.airports d ON d.code = %(d)s
            WHERE b.origin_city = coalesce(o.city, %(o)s)
              AND b.departure_month = date_trunc('month', %(dep)s::date)::date
              AND b.stay_bucket = %(bucket)s
              AND ((b.tier IN ('route', 'provisional') AND b.destination = %(d)s)
                   OR (b.tier = 'country' AND b.destination = d.country))
            ORDER BY CASE b.tier WHEN 'route' THEN 1 WHEN 'country' THEN 2 ELSE 3 END
            LIMIT 1""",
        {"o": origin, "d": destination, "dep": dep, "bucket": stay_bucket(dep, ret)},
    ).fetchone()
    if insight is not None and (row is None or row["tier"] == "provisional"):
        return BaselineBand(
            tier="price_insight",
            median_per_adult_eur=float(insight["median_per_adult_eur"]),
            low_per_adult_eur=float(insight["typical_low_per_adult_eur"]),
            high_per_adult_eur=float(insight["typical_high_per_adult_eur"]),
            method=insight["method"],
            computed_at=insight["computed_at"],
            observations=insight["observations"],
            observation_days=insight["observation_days"],
        )
    if row is None:
        return None
    median, mad = float(row["median_per_adult_eur"]), float(row["mad_eur"])
    return BaselineBand(
        tier=row["tier"],
        median_per_adult_eur=median,
        low_per_adult_eur=median - mad,
        high_per_adult_eur=median + mad,
        method=row["method"],
        computed_at=row["computed_at"],  # the version
        observations=row["observations"],
        observation_days=row["observation_days"],
    )
