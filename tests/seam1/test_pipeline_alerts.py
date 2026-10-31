"""Seam 1: the owner hears when the pipeline itself is in trouble, through the real sensors."""

from datetime import UTC, datetime, timedelta

import dagster as dg
import pytest

from flight_scanner.db import connect
from flight_scanner.notify.base import RecordingNotifier
from flight_scanner.notify.telegram import TelegramNotifier, TelegramSettings
from flight_scanner.pipeline.definitions import _pipeline_alert_sensors, build_definitions
from flight_scanner.pipeline_alerts import run_failed
from flight_scanner.testing.fake_telegram import FakeTelegram
from flight_scanner.testing.harness import PipelineHarness

START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
PAYLOAD = {
    "currency": "EUR",
    "prices": [
        {"origin": "HEL", "destination": "BCN", "depart_date": "2026-12-05", "price": 60},
        {"origin": "BCN", "destination": "HEL", "depart_date": "2026-12-08", "price": 60},
    ],
}
WATCH = {
    "name": "Barcelona",
    "origins": {"include": [{"kind": "airport", "code": "HEL"}]},
    "destinations": {"include": [{"kind": "airport", "code": "BCN"}]},
    "trip_pattern": {
        "preset": "fixed_departure",
        "departure": "2026-12-05",
        "stay_nights": {"min": 3, "max": 3},
    },
    "adults": 1,
    "price_threshold": None,
}


@pytest.fixture
def pipeline(db, tmp_path, dbt_parse_dir) -> PipelineHarness:
    return PipelineHarness(db, tmp_path, start=START, dbt_parse_dir=dbt_parse_dir)


def scan(pipeline: PipelineHarness) -> None:
    pipeline.fake.replay(PAYLOAD)
    pipeline.collect()


def sensor(pipeline: PipelineHarness, name: str):
    return next(s for s in _pipeline_alert_sensors(pipeline.runtime) if s.name == name)


def tick(pipeline: PipelineHarness, cursor: str | None = None) -> str | None:
    with dg.DagsterInstance.ephemeral() as instance:
        context = dg.build_sensor_context(instance=instance, cursor=cursor)
        return sensor(pipeline, "pipeline_stall_alert").evaluate_tick(context).cursor


def test_a_source_silent_for_two_hours_alerts_once_then_recovery_alerts_once(pipeline):
    pipeline.create_watch(WATCH)
    scan(pipeline)
    ops = pipeline.notifier.ops

    cursor = tick(pipeline)
    assert ops == []

    pipeline.clock.advance(hours=2, minutes=1)
    cursor = tick(pipeline, cursor)
    assert len(ops) == 1 and "no prices from fake" in ops[0]

    pipeline.clock.advance(hours=3)
    cursor = tick(pipeline, cursor)
    assert len(ops) == 1

    scan(pipeline)
    tick(pipeline, cursor)
    assert len(ops) == 2 and "landing again from fake" in ops[1]


def test_nobody_is_alerted_when_no_watch_wants_prices(pipeline):
    pipeline.create_watch(WATCH)
    scan(pipeline)
    with connect(pipeline.db, autocommit=True) as conn:
        conn.execute("DELETE FROM app.watch_slots")
    pipeline.clock.advance(hours=5)
    tick(pipeline)
    assert pipeline.notifier.ops == []


def test_a_source_no_longer_configured_does_not_alert(pipeline):
    pipeline.create_watch(WATCH)
    scan(pipeline)
    pipeline.runtime.sources = []
    pipeline.clock.advance(hours=5)
    tick(pipeline)
    assert pipeline.notifier.ops == []


def test_a_failed_run_alerts_through_the_real_failure_sensor(pipeline):
    @dg.op
    def boom():
        raise RuntimeError("boom")

    @dg.job(name="scan")
    def failing():
        boom()

    with dg.DagsterInstance.ephemeral() as instance:
        result = failing.execute_in_process(instance=instance, raise_on_error=False)
        context = dg.build_run_status_sensor_context(
            sensor_name="pipeline_failure_alert",
            dagster_event=result.get_run_failure_event(),
            dagster_instance=instance,
            dagster_run=result.dagster_run,
        ).for_run_failure()
        sensor(pipeline, "pipeline_failure_alert")(context)

    assert len(pipeline.notifier.ops) == 1
    assert pipeline.notifier.ops[0].startswith("Flight Scanner: the scan run ")


def test_repeated_failures_of_a_job_alert_once_every_six_hours(db):
    notifier = RecordingNotifier()
    with connect(db, autocommit=True) as conn:
        sent = [
            run_failed(conn, [notifier], "scan", "r", "", START + timedelta(hours=h))
            for h in (0, 1, 5, 6)
        ] + [run_failed(conn, [notifier], "lakehouse", "r", "", START)]
    assert sent == [True, False, False, True, True]


def test_an_unreachable_channel_does_not_stop_the_other_channels(db):
    class Broken:
        channel = "broken"

        def send(self, alert):
            raise AssertionError

        def send_ops(self, text):
            raise OSError("down")

    notifier = RecordingNotifier()
    with connect(db, autocommit=True) as conn:
        run_failed(conn, [Broken(), notifier], "scan", "r", "", START)
    assert len(notifier.ops) == 1


def test_telegram_receives_the_message_escaped():
    with FakeTelegram() as tg:
        settings = TelegramSettings(tg.token, str(tg.chat_id), tg.url)
        TelegramNotifier(settings).send_ops("a <run> failed")
        assert tg.calls_to("sendMessage")[0]["text"] == "a &lt;run&gt; failed"


def test_the_alert_sensors_run_by_default(pipeline):
    defs = build_definitions(pipeline.runtime)
    for name in ("pipeline_failure_alert", "pipeline_stall_alert"):
        assert defs.resolve_sensor_def(name).default_status == dg.DefaultSensorStatus.RUNNING


def freshness_check(result: dg.ExecuteInProcessResult) -> dg.AssetCheckEvaluation:
    evaluations = result.get_asset_check_evaluations()
    return next(e for e in evaluations if e.check_name == "landing_is_fresh")


def statuses(check: dg.AssetCheckEvaluation) -> dict:
    return {t["table"]: t["status"] for t in check.metadata["tables"].value}


def test_a_scan_reports_landing_freshness_and_stale_data_does_not_stop_it(pipeline):
    pipeline.run_dbt_data_tests()
    pipeline.create_watch(WATCH)
    pipeline.fake.replay(PAYLOAD)

    check = freshness_check(pipeline.run())  # raises if the run failed

    assert check.severity == dg.AssetCheckSeverity.WARN
    assert not check.passed
    assert statuses(check)["round_trip_prices"] == "error"  # nothing ever landed


def test_prices_that_just_landed_are_fresh(db, tmp_path, dbt_parse_dir):
    pipeline = PipelineHarness(db, tmp_path, datetime.now(UTC), dbt_parse_dir)
    pipeline.run_dbt_data_tests()
    pipeline.create_watch(WATCH)
    pipeline.fake.replay(PAYLOAD)

    assert statuses(freshness_check(pipeline.run()))["leg_prices"] == "pass"
