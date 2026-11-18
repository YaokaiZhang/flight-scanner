"""Seam 1: the owner hears when the lakehouse has published nothing for a day and a half, whatever
the reason (quota, outage, network), once, and again when it publishes. A day the engine turns
away is recorded as a successful Dagster run, so the failure alert never sees it."""

from datetime import UTC, datetime, timedelta

import dagster as dg
import pytest

from flight_scanner.db import connect
from flight_scanner.pipeline.definitions import build_definitions
from flight_scanner.testing.harness import PipelineHarness

MORNING = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


@pytest.fixture
def pipeline(db, tmp_path, dbt_parse_dir) -> PipelineHarness:
    harness = PipelineHarness(db, tmp_path, start=MORNING, dbt_parse_dir=dbt_parse_dir)
    harness.use_databricks()
    return harness


def record(pipeline: PipelineHarness, status: str, ago: timedelta, detail: str = "") -> None:
    as_of = pipeline.clock.now() - ago
    with connect(pipeline.db, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO analytics.lakehouse_runs (engine, as_of, export_date, status, detail)
               VALUES (%s, %s, %s, %s, %s)""",
            ("databricks", as_of, as_of.date(), status, detail or None),
        )


def tick(pipeline: PipelineHarness, cursor: str | None = None) -> str | None:
    sensor = build_definitions(pipeline.runtime).resolve_sensor_def("lakehouse_stale_alert")
    with dg.DagsterInstance.ephemeral() as instance:
        context = dg.build_sensor_context(instance=instance, cursor=cursor)
        return sensor.evaluate_tick(context).cursor


def test_a_day_and_a_half_without_a_publish_alerts_once_then_recovery_alerts_once(pipeline):
    ops = pipeline.notifier.ops
    record(pipeline, "published", timedelta(hours=30))
    record(pipeline, "unavailable", timedelta(hours=1), "404 FEATURE_DISABLED: runs disabled")
    cursor = tick(pipeline)
    assert ops == []

    pipeline.clock.advance(hours=7)
    cursor = tick(pipeline, cursor)
    assert len(ops) == 1
    assert "published nothing since" in ops[0] and "FEATURE_DISABLED" in ops[0]

    pipeline.clock.advance(hours=12)
    cursor = tick(pipeline, cursor)
    assert len(ops) == 1

    record(pipeline, "published", timedelta(0))
    tick(pipeline, cursor)
    assert len(ops) == 2 and "published again" in ops[1]


def test_a_lakehouse_that_never_published_alerts_a_day_and_a_half_after_its_first_try(pipeline):
    record(pipeline, "failed", timedelta(hours=35), "LakehouseError: boom")
    tick(pipeline)
    assert pipeline.notifier.ops == []

    pipeline.clock.advance(hours=2)
    tick(pipeline)
    assert len(pipeline.notifier.ops) == 1 and "boom" in pipeline.notifier.ops[0]


def test_a_new_lakehouse_with_no_runs_yet_does_not_alert(pipeline):
    tick(pipeline)
    assert pipeline.notifier.ops == []


def test_the_alert_runs_by_default_and_only_with_a_lakehouse(db, tmp_path, dbt_parse_dir, pipeline):
    defs = build_definitions(pipeline.runtime)
    assert defs.resolve_sensor_def("lakehouse_stale_alert").default_status == (
        dg.DefaultSensorStatus.RUNNING
    )

    off = PipelineHarness(db, tmp_path / "off", start=MORNING, dbt_parse_dir=dbt_parse_dir)
    assert "lakehouse_stale_alert" not in [s.name for s in build_definitions(off.runtime).sensors]
