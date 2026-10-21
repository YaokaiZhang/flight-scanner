"""The daily lakehouse job: export -> the engine rebuilds Baselines and the backtest -> publish.

Publishing writes the engine's Baselines back to Postgres as new versions
(analytics.baseline_versions, change-only, method prefixed with the engine) and replaces the
lakehouse backtest (analytics.backtest_deals). marts.effective_baselines then prefers those
versions for detection while they are fresh. The job is never on the alerting path: an
unavailable or over-quota engine is recorded and nothing else changes.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from flight_scanner.clock import OWNER_TZ
from flight_scanner.lakehouse.base import Lakehouse, LakehouseResult, LakehouseUnavailable
from flight_scanner.lakehouse.export import export_parquet

KEY = ("tier", "origin_city", "destination", "departure_month", "stay_bucket")
VALUES = ("method", "median_per_adult_eur", "mad_eur", "observations", "observation_days")
BACKTEST_COLUMNS = (
    "deal_id",
    "watch_id",
    "outcome",
    "price_per_adult_eur",
    "baseline_per_adult_eur",
    "pct_below_baseline",
    "later_observation_days",
    "highest_later_price_per_adult_eur",
    "computed_at",
)


@dataclass(frozen=True)
class LakehouseRun:
    id: int
    engine: str
    as_of: datetime
    status: str  # published | unavailable | over_quota | failed
    detail: str | None
    exported_rows: int
    baselines_published: int
    backtest_deals: int


def run_daily(
    conn: psycopg.Connection, lakehouse: Lakehouse, work_dir: Path, now: datetime
) -> LakehouseRun:
    """Export, run the engine, publish; records the run whatever happens. Re-raises only
    unexpected failures (after recording them): unavailability is expected."""
    export_date = now.astimezone(OWNER_TZ).date()
    directory = work_dir / "lakehouse-export" / uuid.uuid4().hex[:12]
    run = {"exported_rows": 0, "baselines_published": 0, "backtest_deals": 0}
    status, detail, remote_run_id, result = "failed", None, None, None
    failure: BaseException | None = None
    try:
        export = export_parquet(conn, directory, now, export_date)
        run["exported_rows"] = export.rows
        result = lakehouse.run(export)
        remote_run_id, status = result.remote_run_id, "published"
    except LakehouseUnavailable as e:
        status, detail = e.reason, e.detail
    except Exception as e:  # recorded, then re-raised below
        detail, failure = f"{type(e).__name__}: {e}", e
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    with conn.transaction():
        run_id = conn.execute(
            """INSERT INTO analytics.lakehouse_runs
                   (engine, as_of, export_date, status, detail, remote_run_id, exported_rows)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (lakehouse.name, now, export_date, status, detail, remote_run_id, run["exported_rows"]),
        ).fetchone()["id"]
        if result is not None:
            run["baselines_published"] = _publish_baselines(conn, run_id, lakehouse.name, result)
            run["backtest_deals"] = _publish_backtest(conn, run_id, result)
            conn.execute(
                """UPDATE analytics.lakehouse_runs
                   SET baselines_published = %s, backtest_deals = %s WHERE id = %s""",
                (run["baselines_published"], run["backtest_deals"], run_id),
            )
    if failure is not None:
        raise failure
    return latest_run(conn)  # type: ignore[return-value]


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return Decimal(str(a)).quantize(Decimal("0.01")) == Decimal(str(b)).quantize(
            Decimal("0.01")
        )
    return a == b


def _publish_baselines(
    conn: psycopg.Connection, run_id: int, engine: str, result: LakehouseResult
) -> int:
    stored = {
        tuple(r[k] for k in KEY): r
        for r in conn.execute(
            f"""SELECT DISTINCT ON ({", ".join(KEY)}) *
                FROM analytics.baseline_versions
                ORDER BY {", ".join(KEY)}, computed_at DESC"""
        )
    }
    new = []
    for row in result.gold["baselines"]:
        row = {**row, "method": f"{engine}/{row['method']}"}
        before = stored.get(tuple(row[k] for k in KEY))
        if before is None or not all(_same(before[v], row[v]) for v in VALUES):
            new.append(row)
    columns = (*KEY, *VALUES, "computed_at")
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO analytics.baseline_versions ({", ".join(columns)}, run_id)
                VALUES ({", ".join(["%s"] * len(columns))}, %s)
                ON CONFLICT ({", ".join(KEY)}, computed_at) DO UPDATE SET
                {", ".join(f"{v} = excluded.{v}" for v in VALUES)}, run_id = excluded.run_id""",
            [(*(r[c] for c in columns), run_id) for r in new],
        )
    return len(new)


def _publish_backtest(conn: psycopg.Connection, run_id: int, result: LakehouseResult) -> int:
    rows = result.gold["backtest_deals"]
    conn.execute("DELETE FROM analytics.backtest_deals")
    with conn.cursor() as cur:
        cur.executemany(
            f"""INSERT INTO analytics.backtest_deals (run_id, {", ".join(BACKTEST_COLUMNS)})
                VALUES (%s, {", ".join(["%s"] * len(BACKTEST_COLUMNS))})""",
            [(run_id, *(r[c] for c in BACKTEST_COLUMNS)) for r in rows],
        )
    return len(rows)


def latest_run(conn: psycopg.Connection) -> LakehouseRun | None:
    row = conn.execute(
        """SELECT id, engine, as_of, status, detail, exported_rows, baselines_published,
                  backtest_deals
           FROM analytics.lakehouse_runs ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    return LakehouseRun(**row) if row else None
