"""Seam 1: a day without a published lakehouse run is retried, whether the engine turned the job
away or the stack was down at 04:15. The retries are capped: they cost Free Edition quota.
Helsinki is UTC+2 on these dates."""

from datetime import UTC, datetime, timedelta

import dagster as dg
import pytest
from dagster._core.storage.dagster_run import NOT_FINISHED_STATUSES

from flight_scanner.db import connect
from flight_scanner.pipeline.definitions import build_definitions
from flight_scanner.testing.harness import PipelineHarness

MORNING = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # 10:00 in Helsinki
EXPORT_DATE = "2026-11-02"


@pytest.fixture
def pipeline(db, tmp_path, dbt_parse_dir) -> PipelineHarness:
    harness = PipelineHarness(db, tmp_path, start=MORNING, dbt_parse_dir=dbt_parse_dir)
    harness.use_databricks()
    return harness


def record(pipeline: PipelineHarness, status: str, as_of: datetime) -> None:
    with connect(pipeline.db, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO analytics.lakehouse_runs (engine, as_of, export_date, status)
               VALUES (%s, %s, %s, %s)""",
            ("databricks", as_of, as_of.astimezone(UTC).date(), status),
        )


def tick(pipeline: PipelineHarness, in_progress: bool = False) -> list[dg.RunRequest]:
    sensor = build_definitions(pipeline.runtime).resolve_sensor_def("lakehouse_retry")
    with dg.DagsterInstance.ephemeral() as instance:
        if in_progress:
            instance.add_run(
                dg.DagsterRun(job_name="lakehouse", run_id="r", status=dg.DagsterRunStatus.STARTED)
            )
        context = dg.build_sensor_context(instance=instance)
        return sensor.evaluate_tick(context).run_requests or []


def test_a_day_the_stack_missed_is_run_once_it_is_back(pipeline):
    [request] = tick(pipeline)
    assert request.run_key == f"lakehouse-{EXPORT_DATE}-attempt-1"


def test_nothing_happens_before_the_scheduled_run_has_had_its_chance(pipeline):
    pipeline.clock.set(datetime(2026, 11, 2, 2, 20, tzinfo=UTC))  # 04:20 in Helsinki
    assert tick(pipeline) == []


def test_a_run_in_progress_is_not_doubled(pipeline):
    assert tick(pipeline, in_progress=True) == []


def test_a_day_already_published_is_left_alone(pipeline):
    record(pipeline, "unavailable", MORNING - timedelta(hours=5))
    record(pipeline, "published", MORNING - timedelta(hours=3))
    assert tick(pipeline) == []


@pytest.mark.parametrize("status", ["unavailable", "failed"])
def test_a_turned_away_run_is_retried_after_two_hours(pipeline, status):
    record(pipeline, status, MORNING - timedelta(hours=1))
    assert tick(pipeline) == []

    pipeline.clock.advance(hours=1)
    [request] = tick(pipeline)
    assert request.run_key == f"lakehouse-{EXPORT_DATE}-attempt-2"


def test_a_spent_quota_waits_for_tomorrow(pipeline):
    record(pipeline, "over_quota", MORNING - timedelta(hours=5))
    assert tick(pipeline) == []


def test_it_stops_after_three_attempts_and_starts_afresh_the_next_day(pipeline):
    for hours in (5, 3, 2):
        record(pipeline, "unavailable", MORNING - timedelta(hours=hours))
    assert tick(pipeline) == []

    pipeline.clock.advance(hours=24)
    [request] = tick(pipeline)
    assert request.run_key == "lakehouse-2026-11-03-attempt-1"


def test_the_retry_runs_by_default_and_only_with_a_lakehouse(db, tmp_path, dbt_parse_dir, pipeline):
    defs = build_definitions(pipeline.runtime)
    assert defs.resolve_sensor_def("lakehouse_retry").default_status == (
        dg.DefaultSensorStatus.RUNNING
    )

    off = PipelineHarness(db, tmp_path / "off", start=MORNING, dbt_parse_dir=dbt_parse_dir)
    names = [s.name for s in build_definitions(off.runtime).sensors]
    assert "lakehouse_retry" not in names


def test_the_sensor_treats_a_run_queued_for_the_slot_as_unfinished():
    assert dg.DagsterRunStatus.QUEUED in NOT_FINISHED_STATUSES
