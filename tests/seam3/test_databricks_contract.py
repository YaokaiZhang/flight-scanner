"""Seam 3: the Databricks lakehouse adapter's contract, through a scripted HTTP transport.

The request and answer shapes follow Databricks' documented REST APIs (Files API, Jobs API 2.2
run-now / runs/get, SQL Statement Execution API 2.0 with JSON_ARRAY results); they were not
captured from a live workspace (no account here). How Free Edition reports a spent fair-use
quota is not documented: any 429, or any error or failed run mentioning a quota, counts.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from flight_scanner.config import Settings
from flight_scanner.lakehouse import (
    DatabricksLakehouse,
    Export,
    ExportedTable,
    LakehouseError,
    LakehouseUnavailable,
    build_lakehouse,
)
from flight_scanner.sources.polite_http import HttpResponse
from flight_scanner.testing.scripted_http import FakeTimer, ScriptedTransport

AS_OF = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
HOST = "https://adb-123.cloud.databricks.com"


def ok(payload: dict | None = None, status: int = 200) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(payload or {}).encode())


def no_content() -> HttpResponse:
    return HttpResponse(204, {}, b"")


def terminated(result_state: str = "SUCCESS", message: str = "") -> HttpResponse:
    state = {"life_cycle_state": "TERMINATED", "result_state": result_state}
    return ok({"run_id": 77, "state": {**state, "state_message": message}})


def running() -> HttpResponse:
    return ok({"run_id": 77, "state": {"life_cycle_state": "RUNNING"}})


BASELINE_COLUMNS = [
    ("tier", "STRING"),
    ("departure_month", "DATE"),
    ("median_per_adult_eur", "DECIMAL"),
    ("observations", "LONG"),
    ("computed_at", "TIMESTAMP"),
]


def statement(rows: list[list], columns=BASELINE_COLUMNS, next_link: str | None = None):
    result: dict = {"chunk_index": 0, "data_array": rows}
    if next_link:
        result["next_chunk_internal_link"] = next_link
    return ok(
        {
            "statement_id": "s-1",
            "status": {"state": "SUCCEEDED"},
            "manifest": {
                "format": "JSON_ARRAY",
                "schema": {
                    "columns": [
                        {"name": n, "type_name": t, "position": i}
                        for i, (n, t) in enumerate(columns)
                    ]
                },
            },
            "result": result,
        }
    )


ROW = ["route", "2026-11-01", "100.00", "84", "2026-11-11T03:00:00.000Z"]


@pytest.fixture
def export(tmp_path: Path) -> Export:
    tables = []
    for relation in ("staging.stg_leg_prices", "history.leg_price_history"):
        path = tmp_path / f"{relation}.parquet"
        path.write_bytes(b"PAR1" + relation.encode())
        tables.append(ExportedTable(relation, path, rows=3))
    return Export(as_of=AS_OF, export_date=date(2026, 11, 11), tables=tuple(tables))


def lakehouse(transport, timer=None, **kw) -> DatabricksLakehouse:
    timer = timer or FakeTimer()
    return DatabricksLakehouse(
        HOST,
        "dapi-secret",
        job_id=42,
        warehouse_id="wh-1",
        transport=transport,
        sleep=timer.sleep,
        monotonic=timer.monotonic,
        **kw,
    )


def happy_script():
    return [
        no_content(),  # directory
        no_content(),  # file 1
        no_content(),  # file 2
        ok({"run_id": 77, "number_in_job": 77}),
        running(),
        terminated(),
        statement([ROW]),  # gold.baselines
        statement([], columns=[("deal_id", "LONG")]),  # gold.backtest_deals
    ]


def test_a_run_uploads_the_export_runs_the_job_and_reads_gold_back(export):
    transport = ScriptedTransport(*happy_script())

    result = lakehouse(transport).run(export)

    calls = [(m, u.removeprefix(HOST)) for m, u, *_ in transport.calls]
    folder = "/Volumes/flight_scanner/bronze/exports/2026-11-11"
    assert calls[:3] == [
        ("PUT", f"/api/2.0/fs/directories{folder}"),
        ("PUT", f"/api/2.0/fs/files{folder}/staging.stg_leg_prices.parquet?overwrite=true"),
        ("PUT", f"/api/2.0/fs/files{folder}/history.leg_price_history.parquet?overwrite=true"),
    ]
    assert transport.calls[1][3] == b"PAR1staging.stg_leg_prices"
    assert calls[3] == ("POST", "/api/2.2/jobs/run-now")
    assert json.loads(transport.calls[3][3]) == {
        "job_id": 42,
        "job_parameters": {"as_of": "2026-11-11T03:00:00+00:00", "export_date": "2026-11-11"},
    }
    assert calls[4:6] == [("GET", "/api/2.2/jobs/runs/get?run_id=77")] * 2
    selects = [json.loads(c[3]) for c in transport.calls[6:]]
    assert [s["statement"] for s in selects] == [
        "SELECT * FROM flight_scanner.gold.baselines",
        "SELECT * FROM flight_scanner.gold.backtest_deals",
    ]
    assert {(s["warehouse_id"], s["format"], s["disposition"]) for s in selects} == {
        ("wh-1", "JSON_ARRAY", "INLINE")
    }
    assert result.remote_run_id == "77"
    assert result.gold == {
        "baselines": [
            {
                "tier": "route",
                "departure_month": date(2026, 11, 1),
                "median_per_adult_eur": Decimal("100.00"),
                "observations": 84,
                "computed_at": AS_OF,
            }
        ],
        "backtest_deals": [],
    }


def test_the_token_goes_only_into_the_authorization_header(export):
    transport = ScriptedTransport(*happy_script())

    lakehouse(transport).run(export)

    for _, url, headers, body, _ in transport.calls:
        assert headers["Authorization"] == "Bearer dapi-secret"
        assert "dapi-secret" not in url
        assert b"dapi-secret" not in (body or b"")


def test_result_chunks_are_followed_and_pending_statements_polled(export):
    link = "/api/2.0/sql/statements/s-1/result/chunks/1"
    script = happy_script()[:6]
    script += [
        ok({"statement_id": "s-1", "status": {"state": "PENDING"}}),
        statement([ROW], next_link=link),
        ok({"chunk_index": 1, "data_array": [[*ROW[:2], "120.50", "3", None]]}),
        statement([], columns=[("deal_id", "LONG")]),
    ]
    transport = ScriptedTransport(*script)

    result = lakehouse(transport).run(export)

    assert transport.calls[7][1] == f"{HOST}/api/2.0/sql/statements/s-1"
    assert transport.calls[8][1] == HOST + link
    assert [r["median_per_adult_eur"] for r in result.gold["baselines"]] == [
        Decimal("100.00"),
        Decimal("120.50"),
    ]
    assert result.gold["baselines"][1]["computed_at"] is None


def test_http_429_means_over_quota(export):
    transport = ScriptedTransport(
        no_content(),
        ok({"error_code": "RESOURCE_EXHAUSTED", "message": "slow down"}, status=429),
    )

    with pytest.raises(LakehouseUnavailable) as e:
        lakehouse(transport).run(export)
    assert e.value.reason == "over_quota"


def test_a_run_that_failed_on_the_quota_means_over_quota(export):
    script = happy_script()[:4] + [
        terminated("FAILED", "Workspace exceeded its fair-use quota for today")
    ]

    with pytest.raises(LakehouseUnavailable) as e:
        lakehouse(ScriptedTransport(*script)).run(export)
    assert e.value.reason == "over_quota"


def test_a_job_that_fails_otherwise_is_an_error_not_an_outage(export):
    script = happy_script()[:4] + [terminated("FAILED", "dbt build: 1 error")]

    with pytest.raises(LakehouseError, match="dbt build: 1 error"):
        lakehouse(ScriptedTransport(*script)).run(export)


def test_server_errors_and_network_failures_are_retried_then_mean_unavailable(export):
    timer = FakeTimer()
    transport = ScriptedTransport(
        ok({}, status=503), OSError("connection reset"), ok({}, status=502), timer=timer
    )

    with pytest.raises(LakehouseUnavailable) as e:
        lakehouse(transport, timer=timer, max_retries=2).run(export)
    assert e.value.reason == "unavailable"
    assert len(transport.calls) == 3
    assert timer.slept == [2.0, 4.0]


def test_a_run_that_never_finishes_means_unavailable(export):
    timer = FakeTimer()
    script = happy_script()[:4] + [running()]
    transport = ScriptedTransport(*script, timer=timer, repeat_last=True)

    with pytest.raises(LakehouseUnavailable) as e:
        lakehouse(transport, timer=timer, poll_seconds=60, run_timeout_seconds=600).run(export)
    assert e.value.reason == "unavailable"


def test_bad_credentials_are_an_error(export):
    transport = ScriptedTransport(ok({"error_code": "PERMISSION_DENIED"}, status=403))

    with pytest.raises(LakehouseError):
        lakehouse(transport).run(export)


def test_settings_turn_the_lakehouse_on_only_when_asked():
    assert build_lakehouse(Settings.from_env({})) is None
    with pytest.raises(ValueError, match="DATABRICKS_TOKEN"):
        build_lakehouse(Settings.from_env({"FS_LAKEHOUSE": "databricks"}))
    lh = build_lakehouse(
        Settings.from_env(
            {
                "FS_LAKEHOUSE": "databricks",
                "DATABRICKS_HOST": "adb-123.cloud.databricks.com",
                "DATABRICKS_TOKEN": "dapi-x",
                "FS_DATABRICKS_JOB_ID": "42",
                "FS_DATABRICKS_WAREHOUSE_ID": "wh-1",
                "FS_DATABRICKS_CATALOG": "fs",
            }
        )
    )
    assert isinstance(lh, DatabricksLakehouse)
    assert (lh.host, lh.job_id, lh.catalog, lh.volume) == (
        HOST,
        42,
        "fs",
        "/Volumes/fs/bronze/exports",
    )
